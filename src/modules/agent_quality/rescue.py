"""인용 구조(救助) — 대조 실패한 지적 후보에게 근거를 다시 댈 기회를 준다.

LLM 은 복사-붙여넣기를 못 한다. 인용은 추출이 아니라 기억으로 재타이핑이라,
지적은 맞는데 인용만 어긋나는 후보가 매 검토 5~7건씩 폐기됐다(실측,
.docreview/history 2026-08-06~07). 여기서 그 후보에게 검색 도구를 쥐어주고
실재하는 원문을 다시 인용하게 한다. 판정 권한은 그대로 verify_quotes 에
있다 — 모델은 근거를 다시 댈 기회만 얻지, 자기 지적을 검증하지 않는다.

프로토콜은 shared/agent 의 것을 재사용한다(JSON 한 줄, _parse). 환각 방지
파서가 두 벌이 되면 한쪽만 고쳐지고 다른 쪽은 뚫린다.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from modules.llm_client import LLMClient
from modules.shared import (
    Anchor,
    DocTools,
    Document,
    Evidence,
    _norm,
    _parse,
    verify_quotes,
)


@dataclass
class RescueCandidate:
    """대조 실패로 폐기 직전인 지적 하나. one() 이 쌓고 rescue_round 가 받는다."""
    no: str              # 기준 번호 (Finding.rule_id 로 들어갈 값)
    message: str         # issue 본문
    kind: str            # 모순|표기|모호|"" (consistency._KINDS 검증은 이미 끝남)
    quotes: list[str]    # 대조에 실패한 인용들
    anchor: Anchor       # 모델이 보던 청크 위치 (구조 실패 시엔 안 쓰임)


@dataclass
class RescueOutcome:
    """후보 하나의 구조 결과 + 여정.

    evidence 가 판정이다: 리스트면 복원(검증 통과한 근거), None 이면 폐기.
    errored 는 폐기 사유 중 "LLM 오류로 재확인 자체를 못 함"만 가른다 —
    INFO 가 "근거를 못 댐"과 섞지 않기 위해서다(루트 CLAUDE.md).
    searched 는 모델이 실제로 쓴 find_term 검색어들 — 화면이 "재확인 여정"
    (처음 인용 → 검색 → 확정 근거)을 보여주는 데 쓴다. 여정을 버리면
    에이전트가 일한 과정이 결과에서 사라진다.
    """
    evidence: list[Evidence] | None
    errored: bool = False
    searched: list[str] = field(default_factory=list)


# 토큰 겹침으로 볼 낱말의 최소 길이. 한 글자 조사는 아무 줄에나 있다.
_MIN_TOKEN = 2


def closest_lines(doc: Document, quote: str, k: int = 5) -> list[tuple[str, Anchor]]:
    """실패한 인용과 가장 비슷한 실제 문서 줄 최대 k개. (원본 줄, anchor).

    점수 계산만 verify_quotes 와 같은 정규화(_norm)로 하고, **반환은 원본
    줄이다** — 모델에게 "원문을 글자 그대로 인용하라"고 시키면서 가공된
    문자열을 보여주면 앞뒤가 안 맞는다(Evidence.quote 는 원문을 보존한다).
    # ponytail: O(전체 줄 × 토큰) 선형 스캔. 후보 ≤ rescue_max(기본 10)라 충분.
    """
    needle = _norm(quote)
    tokens = [t for t in needle.split(" ") if len(t) >= _MIN_TOKEN]
    if not needle:
        return []
    scored: list[tuple[int, str, Anchor]] = []
    for section in doc.iter_sections():
        for line in (section.text or "").split("\n"):
            norm = _norm(line)
            if not norm:
                continue
            if needle in norm:
                score = len(tokens) + 1   # 통짜 일치가 항상 이긴다
            else:
                score = sum(1 for t in tokens if t in norm)
            if score:
                scored.append((score, line.strip(), section.anchor))
    scored.sort(key=lambda item: -item[0])
    return [(line, anchor) for _score, line, anchor in scored[:k]]


# 후보당 LLM 호출 상한. 1회차(유사 조각 제시)에 도구를 청하면 2회차가 마지막이다.
_MAX_CALLS = 2

_PROMPT = (
    "너는 문서 검토 지적의 근거를 확인한다.\n\n"
    "[지적]\n{message}\n\n"
    "이 지적의 근거로 인용된 문장이 문서에 없다:\n{failed}\n\n"
    "아래는 문서에서 찾은, 그 인용과 비슷한 실제 원문 줄들이다:\n{similar}\n\n"
    "**답은 항상 JSON 하나만 낸다.** 설명을 덧붙이지 마라.\n"
    '- 위 줄(또는 문서의 다른 곳)에 이 지적의 근거가 실재하면, 그 원문을 글자\n'
    '  그대로 옮겨 인용하라: {{"quotes": ["원문 그대로"]}}\n'
    '- 다른 곳을 찾아봐야겠으면: {{"tool": "find_term", "args": {{"term": "찾을 낱말"}}}}\n'
    '- 이 지적의 근거가 문서에 없으면: {{"verdict": "철회"}}\n'
    "quotes 는 문서에서 글자 그대로 복사해야 한다. 요약하거나 고쳐 쓰지 마라 — "
    "원문과 한 글자라도 다르면 그 지적은 버려진다."
)


def _rescue_one(cand: RescueCandidate, doc: Document, tools: DocTools,
                llm: LLMClient) -> RescueOutcome:
    """후보 하나를 구조한다.

    폐기 사유 중 LLM 오류만 errored 로 가른다 — 나머지(철회·형식 붕괴·
    재대조 실패·도구 오남용·호출 상한)는 모두 "근거를 못 댐"으로 묶인다.
    어느 쪽이든 후보는 폐기되지만, INFO 는 "재확인했는데 근거가 없었다"
    와 "재확인 자체를 못 했다"를 섞지 않는다(루트 CLAUDE.md: '0건 통과'와
    '검토를 못 했다'를 절대 섞지 않는다).

    **복원 인용은 이 라운드에서 모델에게 실제로 보여준 텍스트(유사 조각 +
    find_term 결과) 안에 있어야 한다.** verify_quotes 는 존재성만 검증한다 —
    그것만으로는 "통과할 인용을 찾아와라"는 압박을 받은 모델이 문서 아무
    곳의 실문장(지적과 무관한)을 주워 와도 통과한다. 보여준 텍스트로
    제한하면 근거가 유사 검색 또는 모델 자신의 도구 호출로 추적된다.
    """
    failed = "\n".join(f"- {q}" for q in cand.quotes) or "- (인용 없음)"
    similar_lines = closest_lines(doc, cand.quotes[0] if cand.quotes
                                  else cand.message)
    similar = "\n".join(f"- [{a.section or '?'}] {line}"
                        for line, a in similar_lines) or "- (비슷한 줄 없음)"
    # 이 라운드에서 모델에게 보여준 텍스트(정규화). 복원 인용의 허용 범위다.
    shown = [_norm(line) for line, _a in similar_lines]
    searched: list[str] = []
    messages = [{"role": "user", "content": _PROMPT.format(
        message=cand.message, failed=failed, similar=similar)}]

    for _ in range(_MAX_CALLS):
        resp = llm.chat(messages)
        if resp.error or not (resp.text or "").strip():
            return RescueOutcome(None, errored=True, searched=searched)
        obj = _parse(resp.text, keys=("quotes", "tool", "verdict"))
        if obj is None:
            # 형식 붕괴 — 도구 안 쓴 것으로 후퇴
            return RescueOutcome(None, searched=searched)
        if "quotes" in obj:
            raw = obj["quotes"]
            quotes = [raw] if isinstance(raw, str) else (
                [str(q) for q in raw] if isinstance(raw, list) else [])
            # 보여준 텍스트 밖의 인용은 실재하더라도 근거로 세지 않는다.
            quotes = [q for q in quotes
                      if _norm(q) and any(_norm(q) in s for s in shown)]
            found, _missing = verify_quotes(doc, quotes)
            # 판정은 문자열 대조가 내린다
            return RescueOutcome(found or None, searched=searched)
        if "tool" in obj:
            if obj.get("tool") != "find_term":
                # 노출한 도구는 find_term 하나다(스펙 §4). DocTools 의 다른
                # 도구 이름을 대면 실행하지 않고 폐기한다.
                return RescueOutcome(None, searched=searched)
            args = obj.get("args")
            args = args if isinstance(args, dict) else {}
            term = str(args.get("term", "") or "")
            if term:
                searched.append(term)
            result = tools.run("find_term", args)
            shown.append(_norm(result))
            messages.append({"role": "assistant", "content": resp.text})
            messages.append({"role": "user", "content":
                             f"[도구 결과]\n{result}\n\n이제 quotes 로 다시 "
                             f"인용하거나 철회하라. JSON 하나만."})
            continue
        # 철회 포함 — 근거를 대지 못했다
        return RescueOutcome(None, searched=searched)
    return RescueOutcome(None, searched=searched)   # 호출 상한 도달


def rescue_round(cands: list[RescueCandidate], doc: Document, llm: LLMClient, *,
                 max_rescues: int = 10, workers: int = 1,
                 on_progress: Callable[[dict], None] | None = None,
                 label: str = "",
                 ) -> list[RescueOutcome]:
    """구조 라운드. 시도한 후보(cands[:max_rescues])와 같은 길이·순서로 결과.

    상한 초과분은 여기서 다루지 않는다 — 호출부가 len(cands) 와 비교해 센다.

    진행은 **정식 레인**으로 신고한다(plan + step 이벤트). 예전에는 문구 한 줄
    (detail)만 흘렸는데, 재확인은 다른 레인들이 100% 를 찍은 뒤에 도는 일이라
    작은 글줄로는 화면에서 사실상 보이지 않았다 — 1차가 끝나야 작업량을 아는
    작업이므로 레인도 이때 늦게 신고한다(화면이 병합으로 받는다, web/api.js).
    label 은 어느 검사기의 재확인인지다 — 조각·문서 검사기 둘 다 구조를
    돌리므로 없으면 레인 이름이 겹친다.
    """
    attempted = cands[:max_rescues]
    if not attempted:
        return []
    tools = DocTools(doc)
    emit = on_progress or (lambda ev: None)
    lane = f"{label} 근거 재확인" if label else "근거 재확인"
    total = len(attempted)
    emit({"key": "review", "status": "running",
          "detail": f"{lane} 시작 — 대조 실패한 지적 {total}건",
          "active": lane,
          "plan": [{"kind": "rescue", "total": total, "label": lane,
                    "description": "원문에서 인용 근거를 다시 찾는 중",
                    "scope": f"후보 {total}건"}]})
    done = [0]
    lock = threading.Lock()

    def one(cand: RescueCandidate) -> RescueOutcome:
        try:
            return _rescue_one(cand, doc, tools, llm)
        finally:
            # consistency.report() 와 같은 이유의 락 — 동시에 돌면 카운트가 꼬인다.
            with lock:
                done[0] += 1
                i = done[0]
            emit({"key": "review", "status": "running",
                  "detail": f"{lane} ({i}/{total})",
                  "active": lane,
                  "step": {"kind": "rescue", "i": i, "total": total,
                           "label": lane}})

    n = max(1, min(int(workers or 1), total))
    if n == 1:
        return [one(c) for c in attempted]
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="rescue") as pool:
        return list(pool.map(one, attempted))

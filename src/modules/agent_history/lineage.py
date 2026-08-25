"""검토 계보·반영 확인 — 순수 규칙. LLM 없이 파일명·findings 로만 판정한다.

payload 의 UI finding dict({checker, message, section, evidence:[{quote}]})로 동작한다 —
Finding 객체가 아니라 HistoryStore 에 저장된 형태를 그대로 다룬다(이력 재열기 대비).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# **기계가 본 것**과 **사람이 내린 판정**을 갈라 둔다.
#
# 예전에는 `열림`·`닫힘` 하나로 뭉쳐 있었다. 이슈 트래커 말이라 검토자에게 안 통하고,
# 무엇보다 **추정을 단정으로 만든다** — `닫힘` 은 "이번 검토에서 같은 인용을 못 찾았다"
# 일 뿐이다. 문장을 조금만 다듬어도, 절이 옮겨져도 못 찾는다. 안 고쳤는데도 닫힘이 된다.
#
# 그래서 기계는 본 것만 말하고 판정은 사람이 한다.
# `판단 못 함` 은 이번 검토가 불완전했을 때다(LLM 호출 실패 등). 못 본 것을
# "사라졌다"로 내면 안 고친 결함이 "반영됨"으로 읽힌다 — 가장 위험한 오판이다.
OBSERVED = ("그대로 있음", "안 보임", "판단 못 함")  # 기계가 본 것. 근거이자 정렬 기준
STATUSES = ("미반영", "반영됨", "해당없음")          # 사람이 내린 판정

#: 기계가 본 것 → 사람 판정의 초기값. 검토자가 안 건드리면 이 값으로 읽힌다.
#:
#: **셋 다 `미반영` 이다.** 기계는 고쳐졌다고 단정할 수 없기 때문이다.
#:
#: 예전에는 `안 보임` 을 `반영됨` 으로 뒀다. 실측에서 그게 거의 다 틀렸다 —
#: 같은 문서를 다시 올렸는데 `안 보임` 5건 중 5건, 뒤에 매칭을 고치고도 3건 중
#: 3건이 가짜였다(모델이 인용 범위를 다르게 떠서 못 찾은 것뿐이었다).
#:
#: 두 오판의 값이 다르다. 안 고쳤는데 `반영됨` 이면 결함이 **그대로 나간다.**
#: 고쳤는데 `미반영` 이면 검토자가 한 번 더 볼 뿐이다. 기계가 헷갈릴 때는
#: 사람을 부르는 쪽으로 둔다.
DEFAULT_VERDICT = {"그대로 있음": "미반영", "안 보임": "미반영", "판단 못 함": "미반영"}

#: 옛 어휘로 저장된 이력을 읽기 위한 표. 지우면 예전 검토가 빈 값으로 보인다.
LEGACY = {"열림": "그대로 있음", "닫힘": "안 보임", "해당없음": "해당없음"}
# 파일명 개정 접미사. 목록 밖이면 신규 검토로 폴백한다(안전). 데이터라 확장 쉽다.
REVISION_SUFFIXES = ("_수정", "_rev", "_revised", "_v2", "_v3", "_최종", "_회신", "_re")


@dataclass
class LineageItem:
    finding: dict          # 이전 지적(UI dict)
    status: str            # STATUSES 중 하나
    auto: bool = True      # 자동 초안이었나(사람이 안 바꿨으면 True)
    # 이번 검토에서 같은 결함을 짚은 지적의 id. 화면이 이걸로 문서의 그 자리를
    # 연다 — 이전 지적의 좌표는 **이전 문서** 것이라 이번 문서에서 못 쓴다.
    # `안 보임` 이면 빈 값이다. 이번 문서에 가리킬 자리가 없다는 뜻이고,
    # 그 자체가 검토자에게 필요한 정보다.
    match_id: str = ""


@dataclass
class LineageReview:
    parent_id: str = ""
    document_name: str = ""
    items: list[LineageItem] = field(default_factory=list)   # 이전 지적별 상태
    new_findings: list[dict] = field(default_factory=list)   # 새로 나온 지적(신규)


def guess_original_name(filename: str) -> str:
    """파일명에서 확장자·개정 접미사를 떼어 원 검토 대상 이름을 추정한다."""
    stem = re.sub(r"\.[^.]+$", "", filename or "")
    for suf in REVISION_SUFFIXES:
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def find_prior(entries: list[dict], original_name: str) -> dict | None:
    """이력 목록에서 원 이름과 일치/포함하는 가장 최근 검토를 찾는다.

    entries 는 최신순(HistoryStore.list 가 그렇게 준다)을 가정한다 — 첫 매칭이 최신.
    """
    if not original_name:
        return None
    for e in entries:
        title = re.sub(r"\.[^.]+$", "", str(e.get("title") or ""))
        if title == original_name or original_name in title:
            return e
    return None


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _quotes(f: dict) -> set:
    """지적이 든 인용문(공백만 정규화).

    **이것만이 흔들리지 않는다.** 인용은 모델이 지은 말이 아니라 문서에서 문자 그대로
    떠온 글이고, 실재하는지 대조해 통과한 것만 남는다(verify_quotes). 지적 문구는
    모델이 매번 새로 쓰지만 인용은 문서의 글자다.
    """
    return {_norm(e.get("quote")) for e in (f.get("evidence") or [])
            if _norm(e.get("quote"))}


def _no_quote_key(f: dict) -> tuple:
    """인용이 없는 지적(규칙 검사기 등)을 맞출 차선책."""
    return (f.get("checker"), f.get("section"), _norm(f.get("message")))


#: 포함 관계로 같은 지적이라 보려면 짧은 쪽이 이만큼은 돼야 한다.
#:
#: 포함은 **글자가 정확히 같을 때보다 약한 신호**라 문턱이 따로 필요하다. `운영파일`
#: 같은 낱말은 verify 의 `_MIN_QUOTE`(4자)를 넘지만 문서 곳곳에 있어, 이걸로 이으면
#: 서로 다른 지적이 한 덩어리가 된다. 문장 조각쯤은 돼야 한다.
#: 20 은 잠정값이다 — 실측에서 걸린 인용은 70자가 넘었다.
_MIN_CONTAINED = 20


def _contained(a: str, b: str) -> bool:
    """한쪽 인용이 다른 쪽에 통째로 들어 있나(짧은 쪽이 실질적일 때만)."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= _MIN_CONTAINED and short in long_


#: 판정 열쇠의 칸 구분자. 본문에 안 나오는 제어문자라 인용에 섞일 일이 없다.
KEY_SEP = "\u001f"


def verdict_key(f: dict) -> str:
    """이 판정이 **어느 지적에 대한 것인가**를 가리키는 열쇠.

    순번(`"3"`)은 안 된다 — 그 검토 안에서만 뜻이 있어서, 다음 검토의 3번째는
    다른 지적이다. 검토자가 "해당없음"이라 판정한 것을 다음 검토로 이어주려면
    지적의 **신원**이 열쇠여야 한다.

    인용을 그대로 싣는다. 열쇠를 다시 갈라 인용을 꺼낼 수 있어야, 다음 검토에서
    `match_findings` 와 같은 규칙(인용 겹침)으로 맞출 수 있기 때문이다 —
    해시로 뭉개면 겹침을 못 본다.
    """
    checker = f.get("checker") or ""
    quotes = sorted(_quotes(f))
    if quotes:
        return KEY_SEP.join(["q", checker, *quotes])
    return KEY_SEP.join(["m", checker, f.get("section") or "",
                         _norm(f.get("message"))])


#: 다음 검토로 **이어지는** 판정. `해당없음` 하나뿐이다.
#:
#: 이건 "이 지적은 우리 문서엔 해당 안 된다"는 지속되는 판단이라, 검사기가 다음에도
#: 똑같이 낼 것이고 검토자는 매번 같은 것을 다시 눌러야 한다. 도구를 싫어하게
#: 만드는 건 보통 이런 자리다.
#:
#: `반영됨`·`미반영` 은 안 잇는다. 그건 **이번 회차에 고쳐졌나**에 대한 답이라
#: 다음 회차에는 다시 물어야 한다. 특히 `반영됨` 을 이으면 위험하다 — 검토자가
#: 잘못 눌렀거나 작성자가 되돌렸을 때, 안 고쳐진 결함이 두 번째로 조용히 넘어간다.
CARRIED = ("해당없음",)


def carry_verdicts(prior_verdicts: dict, items: list) -> dict:
    """지난 검토의 판정 중 이어질 것을 이번 목록에 옮긴다 → {이번 열쇠: 판정}.

    열쇠끼리 그냥 비교하면 안 된다. 모델이 인용을 하나 더 뜨거나 지적을 쪼개면
    열쇠 글자가 달라지기 때문이다(match_findings 주석의 실측). 그래서 열쇠를 다시
    갈라 인용을 꺼내고, **인용이 하나라도 겹치면** 같은 지적으로 본다.
    """
    if not prior_verdicts:
        return {}
    # (검사기, 인용) → 판정. 인용 없이 저장된 옛 판정은 열쇠 전체로만 맞춘다.
    by_quote: dict = {}
    exact: dict = {}
    for key, verdict in prior_verdicts.items():
        if verdict not in CARRIED:
            continue
        kind, _, rest = str(key).partition(KEY_SEP)
        if kind != "q":
            exact[key] = verdict
            continue
        checker, _, quotes = rest.partition(KEY_SEP)
        for q in quotes.split(KEY_SEP):
            if q:
                by_quote[(checker, q)] = verdict

    carried: dict = {}
    for it in items:
        f = it.finding
        key = verdict_key(f)
        if key in exact:
            carried[key] = exact[key]
            continue
        checker = f.get("checker") or ""
        for q in _quotes(f):
            if (checker, q) in by_quote:
                carried[key] = by_quote[(checker, q)]
                break
    return carried


def is_process_report(f: dict) -> bool:
    """문서 결함이 아니라 **검토 과정 보고**인가(미검토·절단·필터링).

    CLAUDE.md 가 severity 로 그것을 가른다 — "문서 결함이 아니라 검토 과정 보고 →
    info". 이런 것은 반영 확인의 대상이 아니다. 고칠 대상이 아니기 때문이다.

    빼지 않으면 오판이 난다(실측, 같은 문서 재검토):
      · "지적 후보 5건이 원문 대조를 통과하지 못해…"  → 다음엔 4건. 숫자가 바뀌어 안 맞음
      · "…칸 값 검사를 걸지 않았습니다 (Rev05.pdf)"   → 파일명이 박혀 있어 안 맞음
    둘 다 "고쳐졌다"로 읽혔다. 문서는 한 글자도 안 바뀌었는데.
    """
    return f.get("sev") == "info" or bool(f.get("unreviewed"))


def incomplete_checkers(new: list[dict]) -> set:
    """이번 검토에서 **제 몫을 다 못 한** 검사기 이름들.

    미검토 보고를 낸 검사기다(LLM 호출 실패·필수 목록 없음 등). 그 검사기가 낸
    이전 지적은 이번에 안 보여도 "사라졌다"고 말할 수 없다 — 애초에 안 봤으니까.

    검사기별로 가른다. 하나라도 미검토면 전체를 불완전으로 치면, 이 문서들처럼
    필수 절·칸 값이 상시 미검토인 경우 모든 항목이 `판단 못 함` 이 되어 쓸모가 없다.
    """
    return {f.get("checker") for f in new if f.get("unreviewed")}


def match_findings(prior: list[dict], new: list[dict], *,
                   blind: set | None = None) -> LineageReview:
    """이전 지적 ↔ 새 지적 매칭 → 이전 지적별 **관찰**(OBSERVED) + 신규 목록.

    이전 지적의 인용이 새 검토에도 나오면 `그대로 있음`, 안 나오면 `안 보임`.
    새 검토에만 있는 지적은 신규다. 검토 과정 보고(info)는 양쪽에서 뺀다.

    같은 지적인지는 **인용이 하나라도 겹치는가**로 본다. 인용 목록이 통째로 같기를
    요구하면 안 된다 — 모델은 *무엇을* 지적할지는 안 바꾸면서 **몇 건으로 묶어 낼지**를
    바꾼다. 같은 문서를 두 번 검토한 실측:
      · §12  지적 문구까지 한 글자도 안 틀리는데 인용이 2개 → 3개. `안 보임` + `신규`
      · §10.3 인용 4개짜리 지적 1건 → 같은 내용을 3건으로 쪼갬. `안 보임` + `신규` 3
    가짜 `안 보임` 2건, 가짜 `신규` 4건. 진짜 신규는 하나뿐이었다.

    겹침으로 보면 반대 오판(고쳤는데 `그대로 있음`)이 늘 수 있는데 그쪽이 안전하다 —
    검토자가 한 번 더 볼 뿐이다. `안 보임` 은 초기 판정이 `반영됨` 이라 그냥 나간다.

    **판정이 아니라 관찰이다.** `안 보임` 은 "고쳐졌다"가 아니라 "같은 인용을 못
    찾았다"일 뿐이다 — 문장을 다듬거나 절이 옮겨져도 못 찾는다. 고쳤는지는 사람이
    정한다(STATUSES).

    blind 는 **이번에 제 몫을 다 못 한 검사기** 이름들이다(incomplete_checkers).
    그 검사기가 낸 이전 지적은 안 보여도 `판단 못 함` 이다 — 못 본 것을 "사라졌다"로
    내면 안 고친 결함이 "반영됨"으로 읽힌다. 실측: 같은 문서를 재검토했는데 1/142
    호출이 실패해 그 청크의 지적이 통째로 사라졌다.
    """
    blind = blind or set()
    prior = [f for f in prior if not is_process_report(f)]
    new = [f for f in new if not is_process_report(f)]

    # (검사기, 인용문) → 그 인용을 든 새 지적들. 검사기를 함께 묶는다 — 같은 문장을
    # 형식 검사기와 표현 검사기가 각각 인용하면 다른 지적이다.
    by_quote: dict = {}
    by_message: dict = {}
    by_checker: dict = {}
    for i, f in enumerate(new):
        quotes = _quotes(f)
        for q in quotes:
            by_quote.setdefault((f.get("checker"), q), []).append(i)
        if quotes:
            by_checker.setdefault(f.get("checker"), []).append((i, quotes))
        else:
            by_message.setdefault(_no_quote_key(f), []).append(i)

    def hits(f: dict) -> list:
        quotes = _quotes(f)
        if not quotes:
            return by_message.get(_no_quote_key(f), [])
        found = [i for q in quotes for i in by_quote.get((f.get("checker"), q), [])]
        if found:
            return found
        # 글자가 정확히 같은 인용이 하나도 없을 때만 **범위**까지 본다. 모델이
        # 같은 문장을 뜨면서 앞뒤를 더 물거나 덜 무는 일이 있다(실측, 같은 문서):
        #   이전 'Each system and software interface are described correctly …'
        #   이번 '[Rev.00] Satisfied Each system and software interface are described …'
        #   이전 'Satisfied The existing criticality analysis result, which result of …'
        #   이번 'The existing criticality analysis result, which result of …'
        # 셋 다 같은 결함인데 `안 보임` + `신규` 로 갈라졌다.
        return [i for i, qs in by_checker.get(f.get("checker"), ())
                if any(_contained(a, b) for a in quotes for b in qs)]

    seen: set = set()
    items = []
    for f in prior:
        found = hits(f)
        seen.update(found)
        items.append(LineageItem(
            finding=f,
            status=("그대로 있음" if found
                    else "판단 못 함" if f.get("checker") in blind
                    else "안 보임"),
            match_id=str(new[found[0]].get("id") or "") if found else ""))
    new_only = [f for i, f in enumerate(new) if i not in seen]
    return LineageReview(items=items, new_findings=new_only)

"""LLM기반 체커: 청크별 모호성/모순 점검. 근거를 대야 지적이 된다.

옛 구현은 모델이 'ISSUE: …'로 시작하기만 하면 그 문장을 그대로 지적으로
채택했다. 실문서(요구사항명세서)에서 58건이 나왔고 내용은 쓸 만했지만 —
식별자 설명과 형식의 불일치, 같은 기능의 제목이 문서마다 다른 것 — 그중
무엇이 진짜이고 무엇이 모델이 지어낸 것인지 구분할 방법이 없었다. 근거가
하나도 없었기 때문이다.

그래서 agent가 쓰는 관문을 여기에도 세운다: 모델은 지적과 함께 원문을
그대로 인용해야 하고(`quotes`), 그 인용이 실제 문서에 있는지 글자 단위로
대조해(`verify_quotes`) 통과한 것만 리포트에 올린다. 통과 못 한 후보는
버리되, 몇 건을 버렸는지는 INFO로 드러낸다 — 조용히 지우면 "지적이 없다"는
거짓말이 된다.

파서(`_parse`)도 agent의 것을 그대로 쓴다. 환각 방지 코드가 두 벌이 되면
한쪽만 고쳐지고 다른 쪽은 뚫린다.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from modules.shared import (
    Anchor,
    Context,
    Document,
    Finding,
    Severity,
    _is_substantive,
    _norm,
    _parse,
    verify_quotes,
)

from .rescue import RescueCandidate, rescue_round

#: 인용이 **산문**이 아니면 지적으로 내지 않는다.
#:
#: 환각 관문(verify_quotes)은 "이 인용이 문서에 있는가"만 본다. 잔해를 충실히
#: 인용한 지적은 그 관문을 그대로 통과한다 — 지어낸 게 아니기 때문이다.
#: 실측(2026-08-20, SKN56_CDMS_RVVR_Rev05.pdf): 지적 53건 중 20건이 문서가 아니라
#: 추출 결과가 깨진 것이었고, 그중 아래 모양이 절반이다.
#:
#: **좁게 건다.** 표 안의 진짜 오타(`descripted`)까지 죽이면 안 되므로, 문장이라고
#: 볼 수 없는 것만 거른다. 나머지(칸이 공백으로 이어붙은 것)는 여기서 못 가리고
#: 파서가 표를 문장과 안 섞이게 내야 풀린다.
_TOC_DOTS = re.compile(r"\.{6,}")
#: 글자로 된 낱말이 **하나라도** 있는가. 잡으려는 것은 `3.1.1. 3.1.2.` 처럼
#: 글자가 아예 없는 줄이다.
#:
#: 한때 "이런 낱말이 둘 이상"을 요구했는데 한국어를 죽였다 — 한 글자 낱말이
#: 흔해서 `본문 한 줄` 은 `본문` 하나만 잡히고, `표 및 그림` 은 `그림` 하나만
#: 잡힌다. 영어 한 낱말짜리 인용(`descripted`)도 같이 죽었다. 문턱은 "번호뿐인
#: 줄"을 가르는 데 필요한 만큼만 건다 — 이 모듈은 좁게 거는 것이 원칙이다.
_WORD = re.compile(r"[A-Za-z가-힣]{2,}")
#: 표 **여러 행**이 한 인용에 뭉친 모양.
#:
#: 한 행은 칸 수 + 1 이다(`| 항목 | 결과 | 비고 |` = 파이프 넷). 그래서 넷으로
#: 자르면 멀쩡한 세 칸짜리 행이 죽는다 — 표 안의 오타를 봐야 하므로 살려야 한다
#: (CLAUDE.md 공통 C1: "본문뿐 아니라 표·그림 제목·부록·평가표까지 본다").
#: 실측 잔해는 파이프가 일곱 이상이었다.
_MANY_CELLS = 7

#: 빈 칸이 잇달아 나오는 자리(`| |  | |`). 여러 행이 눌려 붙을 때 생긴다 —
#: 사람이 쓴 표 한 행에는 빈 칸이 이렇게 연달아 오지 않는다.
_EMPTY_CELLS = re.compile(r"\|\s*\|")
_MANY_EMPTY = 2


def _is_prose(quote: str) -> bool:
    """이 인용을 문장으로 볼 수 있는가."""
    if _TOC_DOTS.search(quote):
        return False                      # 목차 점선
    if quote.count("|") >= _MANY_CELLS:
        return False                      # 표 여러 행이 뭉침
    if len(_EMPTY_CELLS.findall(quote)) >= _MANY_EMPTY:
        return False                      # 빈 칸이 잇달아 붙음
    if not _WORD.search(quote):
        return False                      # 번호·기호뿐 (`3.1.1. 3.1.2.`)
    return True


@dataclass
class _Unit:
    """검사 단위 하나. 청크와 같은 모양이면 되므로 text·anchor 만 있으면 된다."""
    text: str
    anchor: Anchor


def _criterion_line(c) -> str:
    """기준 한 줄. 본문 아래 세부(note)가 있으면 '확인 방법'으로 함께 싣는다.

    세부를 빼면 "개정바를 **아래 기준으로** 표시했는가?" 처럼 정작 그 기준이
    빠진 문장이 모델에게 간다.
    """
    head = f"No.{getattr(c, 'no', '')}  {getattr(c, 'text', '')}".strip()
    note = (getattr(c, "note", "") or "").strip()
    if not note:
        return head
    body = "\n".join(f"       {ln}" for ln in note.splitlines() if ln.strip())
    return f"{head}\n       확인 방법:\n{body}"

_PROMPT = (
    "아래 [검토 기준]에 비추어 [문서 조각]을 검사하라.\n\n"
    "[검토 기준]\n{criteria}\n\n"
    "기준마다 하나씩, 아래 JSON 하나만 답하라. 설명을 붙이지 마라.\n"
    '{{"results": [\n'
    '  {{"no": "기준 번호", "verdict": "위반", "kind": "모순", '
    '"issue": "무엇이 왜 이 기준에 어긋나는지 한두 문장", '
    '"quotes": ["문제가 되는 원문을 그대로 복사한 문장"]}},\n'
    '  {{"no": "기준 번호", "verdict": "통과"}},\n'
    '  {{"no": "기준 번호", "verdict": "해당없음"}}\n'
    "]}}\n"
    "verdict 는 셋 중 하나다.\n"
    "  위반: 이 조각이 이 기준에 어긋난다.\n"
    "  통과: 이 조각을 이 기준으로 봤고 어긋난 곳이 없다.\n"
    "  해당없음: 이 기준이 **이 조각을 대상으로 하지 않는다.** 기준이 다른 종류의\n"
    "    문서를 말하거나, 이 조각에 그 기준이 볼 것이 애초에 없을 때다.\n"
    "    이때는 위반도 통과도 아니다 — 반드시 해당없음이라고 답하라.\n"
    "    '이 조각에는 …에 대한 내용이 없다' 는 위반이 아니라 해당없음이다.\n"
    "kind 는 셋 중 하나만 쓴다 — 다른 말은 쓰지 마라.\n"
    "  모순: 문서의 두 서술이 서로 어긋나거나, 값·범위·대상이 맞지 않는다.\n"
    "  표기: 오타·문법·띄어쓰기처럼 글자 차원의 잘못이다. 뜻은 알아볼 수 있다.\n"
    "  모호: 뜻이 여러 갈래로 읽히거나 근거가 불분명하다. 어긋난 짝은 없다.\n"
    "quotes 는 조각에서 글자 그대로 복사해야 한다. 요약하거나 고쳐 쓰지 마라 — "
    "원문과 한 글자라도 다르면 그 지적은 버려진다.\n"
    # 실측(2026-08-19): "주어-서술어 수일치 오류" 지적 하나가 같은 표의 18줄을
    # 통째로 인용했다. 정작 오류가 있는 줄은 한둘이고 나머지는 멀쩡한 문장이라,
    # 화면은 멀쩡한 문장 17개에 형광펜을 칠했다. 인용의 **실재**는 코드가
    # 대조하지만(verify_quotes) **해당 여부**는 대조할 방법이 없다 — 여기서 막는다.
    "quotes 에는 그 지적이 실제로 들어맞는 문장만 넣는다. 한 문장이면 하나만 넣어라 — "
    "같은 표·같은 문단에 있다는 이유로 멀쩡한 이웃 문장을 함께 싣지 마라.\n"
    "문장마다 잘못이 다르면 지적을 나눠서 내라(같은 기준 번호로 여러 줄을 내도 된다).\n"
    "고쳐 쓴 문장은 내지 마라. 무엇이 문제인지만 말한다.\n"
    # 실제로 "그러나/하지만/반면" 으로 결론을 네 번 뒤집는 15문장짜리 issue 가
    # 나왔다(2026-08-12). 판단 과정을 issue 칸에 쏟은 것이다. "한두 문장" 이라는
    # 부탁만으로는 안 막혔으므로 무엇을 쓰지 말아야 하는지를 못박는다.
    # **이것은 보장이 아니다** — 모델에게 부탁하는 것은 코드가 아니다. 길이가
    # 실제로 길게 나왔을 때는 화면이 접어서 받는다(index.html .fmsg).
    "issue 에는 **결론만** 쓴다. 판단 과정을 쓰지 마라 — 여러 해석을 늘어놓거나, "
    "'그러나' · '하지만' · '반면' 으로 앞말을 뒤집지 마라. 무엇이 어느 기준에 "
    "어긋나는지 한 문장이면 된다. 확신이 서지 않으면 그 기준은 통과로 답하라.\n\n"
    # 실측(2026-08-20, SKN56_CDMS_RVVR_Rev05.pdf): 지적 53건 중 20건이 **문서가
    # 아니라 우리 추출 결과**가 깨진 것이었다. 모델은 잘못이 없다 — 저 글자들이
    # 조각에 실재하니 "문장이 깨졌다"는 정확한 관찰이다. 깨뜨린 쪽이 우리다.
    #   원문(표)  [Rev.01] Not applicable: same evaluation results as Rev.00.
    #   조각      [Rev.01] Not applicable: same evaluation results as N/A N/A Rev.00.
    # 환각 관문도 이건 못 막는다. 지어낸 게 아니라 잔해를 충실히 인용한 것이다.
    # **부탁은 코드가 아니다** — 아래 _is_prose 가 실제 방어고, 이 문단은 애초에
    # 덜 나오게 하는 것이다.
    "[문서 조각]은 원본이 아니라 **기계가 뽑아낸 글**이다. 표·목차·쪽 경계에서 "
    "다음이 섞여 들어온다 — 이것은 **문서의 잘못이 아니므로 지적하지 마라.**\n"
    "  · 표의 칸이 이어붙어 문장처럼 보이는 것. `|` 가 있는 줄은 표의 한 행이다.\n"
    "  · 빈 칸이 `N/A` 로 채워져 문장 한가운데 끼어든 것 "
    "(`results as N/A N/A Rev.00`).\n"
    "  · 목차의 점선(`Purpose......6`), 줄바꿈에서 갈라진 낱말(`Shin- Kori`), "
    "참조 절 번호만 늘어선 줄(`3.1.1. 3.1.2.`).\n"
    "  · 조각 경계에서 앞뒤가 잘린 문장. 조각은 문서의 일부다 — 첫 문장이 "
    "주어 없이 시작하거나 끝 문장이 중간에 끊겨도 그것은 잘린 것이지 오류가 아니다.\n"
    "표 안에서는 **낱말의 오타만** 본다(`descripted` → `described`). "
    "표 행을 두고 '문장 구조가 깨졌다' · '주어와 동사가 안 맞는다' 고 하지 마라 — "
    "표의 칸은 애초에 문장이 아니다.\n\n"
    "[문서 조각]\n{text}"
)

# kind → 심각도. **중대성** 축이다 — "이 지적이 남아 있으면 팀이 이 문서를 그대로
# 낼 수 있는가"로 가른다(CLAUDE.md "기능 방침 — 심각도").
#
# 여기 없는 값(빠졌거나 어휘 밖)은 MINOR 로 떨어진다. 반대로 두면(기본 MAJOR)
# 모델이 칸을 빠뜨릴 때마다 거짓 경보가 된다 — 모르는 것을 위로 올리지 않는다.
#
# 이 체커 하나가 전체 지적의 90%대를 낸다. 예전엔 전부 MINOR 하드코딩이라
# "요구사항 모순"과 "'Dose' 는 'Does' 의 오타" 가 같은 칸에 앉아 있었다.
# 실측(기록 974개 표본): 모순·불일치 40% · 표기 20% · 모호 19% · 그 밖 21%.
#
# 실측(2026-08-05, Qwen3.6-27B, 8회 호출): 오타 조각("filed" · "Communicati on" ·
# "를구현하여")을 `표기` 로 정확히 붙여 MINOR 로 내려갔다 — 오타를 MAJOR 로 부풀리지
# 않았다. 다만 8회짜리 표본이라 분포·오분류율은 아직 모른다. 기록 974개로 제대로
# 재는 절차는 roadmap.md "일관성 지적의 kind 실측" 에 있다.
# 프롬프트가 받는 어휘. 이 밖의 말은 모델이 지어낸 것이라 화면에 내보내지 않는다.
_KINDS = ("모순", "표기", "모호")
_KIND_SEVERITY = {"모순": Severity.MAJOR}
_KIND_DEFAULT = Severity.MINOR

# 한 프롬프트에 실을 기준 수의 상한. 목록이 길어지면 모델이 뒤쪽 기준을 소홀히
# 하고, 그러면 "통과" 판정을 믿을 수 없게 된다 — 기준별 화면이 통과 판정 위에
# 서 있으므로 이 상한이 화면의 정직함을 떠받친다.
# 실측(2026-07-30, Qwen3.6-27B): 규칙 7개를 한꺼번에 주면 3/4(하나를 3회 모두
# 조용히 누락), 1개로 좁혀 물으면 4/4. 판정 능력이 아니라 커버리지 문제였다.
# 3~4 는 아직 추정이다. 골든셋이 생기면 묶음 크기별 recall 을 재서 정한다.
_BATCH = 4


class ChunkCriteriaChecker:
    """검토 기준을 문서 조각마다 적용하는 LLM 검사기.

    이름의 ``Criteria`` 는 검사 내용이 클래스에 고정되지 않고 주입된 기준의
    ``text``·``note`` 에서 온다는 뜻이다. 같은 실행기가 맞춤법·표기·모호성 등
    서로 다른 조각 기준을 처리한다.
    """

    name = "consistency"
    label = "표현 점검"

    def __init__(self, criteria: Sequence = ()):
        # 기준 없이 만들면 검사할 것이 없다. 예전처럼 일반 프롬프트로 훑지 않는다 —
        # 기준 없는 지적은 어느 기준에도 붙일 수 없어, 화면이 그 지적을 모든 항목에
        # 똑같이 복사해 보여주게 된다(그게 이 작업이 고치는 문제다).
        #
        # 기준은 no·text 속성으로만 읽는다. preset.Criterion 을 import 하지 않아
        # 이 모듈은 폴더째 떼어가도 돈다(README 의 의존성 목록 참고).
        self.criteria = list(criteria)
        # 기준 번호 → 통과|위반|해당없음|미판정. check() 가 채운다.
        self.verdicts: dict[str, str] = {}
        # 호출 몇 번 중 몇 번이 답을 못 받았나. **미판정의 이유를 가르는 값**이다 —
        # 전부 무응답이면 서버를 살려야 하고, 응답이 왔는데도 어떤 기준이 미판정이면
        # 모델이 그 기준을 빠뜨린 것이다(_BATCH 주석의 커버리지 문제). 검토자가
        # 할 일이 다르므로 조립 계층이 두 경우를 갈라 보여준다.
        self.calls = 0
        self.unanswered = 0

    def _batches(self) -> list[list]:
        return [self.criteria[i:i + _BATCH]
                for i in range(0, len(self.criteria), _BATCH)]

    def plan(self, doc: Document, ctx: Context) -> dict | None:
        if not self.criteria:
            return None
        return {"kind": "chunk",
                "total": len(ctx.chunks) * len(self._batches()),
                "label": self.label,
                "description": "문장·문단별 맞춤법, 모호성, 표현 오류",
                "scope": f"{len(ctx.chunks)}개 조각"}

    def _units(self, doc: Document, ctx: Context) -> tuple[list, list[Finding]]:
        """검사 단위와, 그에 딸린 알림. 조각은 청크마다 하나씩이다.

        하위 클래스가 이 자리를 갈아끼운다(WholeDocCriteriaChecker 는 문서 하나).
        """
        return list(ctx.chunks), []

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        batches = self._batches()
        units, notices = self._units(doc, ctx)
        if not units or not batches:
            return list(notices)

        # 작업 단위는 (검사단위, 기준묶음) 쌍이다. 단위 하나를 묶음 수만큼 묻는다.
        jobs = [(c, b) for c in units for b in batches]
        total = len(jobs)
        self.verdicts = {str(c.no): "미판정" for c in self.criteria}
        self.calls, self.unanswered = total, 0

        # 청크끼리는 서로를 보지 않는다(각 조각을 독립으로 판정한다). 그래서 동시에
        # 물어도 결과가 달라지지 않는다. vLLM 은 요청을 배치로 묶어 처리하도록
        # 만들어져 하나씩 보내면 GPU 가 계속 대기한다 — 실측(27B, L40S x2):
        #   순차 4건 145.0초(36.2초/건) · 동시 8건 33.3초(4.2초/건) → 8.7배.
        # 청크 83개 문서가 9분 39초에서 1분 안쪽이 된다.
        workers = max(1, min(int(getattr(ctx, "llm_concurrency", 1) or 1), total))

        done = [0]
        lock = threading.Lock()

        def report() -> None:
            """몇 개 끝났는지 알린다.

            동시에 돌면 완료 순서가 뒤섞이므로 "3번째 청크"가 아니라 "3개 끝남"으로
            센다. 화면 격자는 누적 개수를 받으므로 그대로 맞는다.
            """
            with lock:
                done[0] += 1
                i = done[0]
            ctx.on_progress({"key": "review", "status": "running",
                             "detail": f"{self.label} {i}/{total} 검사 중",
                             "step": {"kind": "chunk", "i": i, "total": total,
                                      "label": self.label}})

        def one(job) -> tuple[list, str | None, str | None, list[RescueCandidate], int]:
            """(청크, 기준묶음) → (판정 목록, 실패종류, 실패이유, 구조후보, 즉시폐기수).
            예외는 안 올린다.

            판정 목록의 한 줄은 (기준번호, 판정, 지적 또는 None) 이다.
            """
            chunk, batch = job
            rescues: list[RescueCandidate] = []
            dropped_outright = 0
            dropped_artifact = 0
            try:
                listing = "\n".join(_criterion_line(c) for c in batch)
                resp = ctx.llm.complete(
                    _PROMPT.format(criteria=listing, text=chunk.text))
                obj = _parse(resp.text or "", keys=("results",))
                if not obj or not isinstance(obj.get("results"), list):
                    # 모델이 답을 안 줬거나(빈 응답·연결 실패) 형식을 못 지켰다.
                    # "문제 없음"과 구분해야 한다 — 안 세면 LLM 을 안 붙였을 때도,
                    # 주소를 잘못 넣었을 때도 조용한 0건이 되어 통과한 것처럼 보인다.
                    # 이유도 남긴다: "응답을 받지 못했습니다"만 말하면 주소가 틀린
                    # 것인지 모델명이 틀린 것인지 알 수 없다(실제로 HTTP 404 를 이
                    # 메시지가 가려 한참 헤맸다).
                    return [], "unanswered", resp.error, [], 0, 0

                out = []
                for row in obj["results"]:
                    if not isinstance(row, dict):
                        continue
                    no = str(row.get("no", "")).strip()
                    verdict = str(row.get("verdict", "")).strip()
                    if verdict in ("통과", "해당없음"):
                        out.append((no, verdict, None))
                        continue
                    if verdict != "위반":
                        continue        # 어휘 밖 판정은 안 본 것으로 둔다
                    raw_issue = row.get("issue")
                    message = raw_issue.strip() if isinstance(raw_issue, str) else ""
                    if not message:
                        continue
                    kind = row.get("kind")
                    kind = kind.strip() if isinstance(kind, str) else ""
                    quotes = row.get("quotes")
                    quotes = ([q for q in quotes if isinstance(q, str)]
                              if isinstance(quotes, list) else [])
                    found, _missing = verify_quotes(doc, quotes)
                    if not found:
                        # 근거가 하나도 원문 대조를 통과하지 못했다. 지어낸 지적일
                        # 수도, 내용은 맞는데 인용만 고쳐 쓴 것일 수도 있다 — 즉시
                        # 버리지 않고 구조 라운드(rescue_round)에 넘긴다. 거기서도
                        # 실재 근거를 못 대면 그때 버린다. 판정은 남기지 않는다:
                        # 근거 없는 위반을 "통과"로 뒤집으면 검사한 척이 되고,
                        # "위반"으로 올리면 환각이 리포트에 오른다.
                        #
                        # 다만 구조는 **고쳐 쓴 인용**을 되살리는 것이다. 애초에
                        # 실질적 근거를 하나도 대지 않은 지적(quotes 없음 ·
                        # _MIN_QUOTE 미만 · 문장부호뿐)은 여기서 그대로 버린다 —
                        # 그 조각을 검색 키로 쓰면 짧아서 거부된 조각이 오히려
                        # 실문장을 찾아주는 열쇠가 된다(문턱 역전).
                        if any(_is_substantive(_norm(q)) for q in quotes):
                            rescues.append(RescueCandidate(
                                no=no, message=message,
                                kind=kind, quotes=quotes,
                                anchor=chunk.anchor))
                        else:
                            dropped_outright += 1
                        continue
                    prose = [e for e in found if _is_prose(e.quote)]
                    if not prose:
                        # 근거가 전부 잔해다. 지적을 내면 검토자가 문서에서 그
                        # 자리를 찾아보고 "이런 문장 없는데" 하게 된다 —
                        # 조용히 버리지 않고 아래에서 INFO 로 건수를 밝힌다.
                        dropped_artifact += 1
                        continue
                    found = prose
                    out.append((no, "위반", Finding(
                        checker=self.name,
                        severity=_KIND_SEVERITY.get(kind, _KIND_DEFAULT),
                        message=message,
                        # **근거가 있는 자리를 가리킨다.** 예전에는 모델이 보던
                        # 조각의 위치(chunk.anchor)를 달았는데, verify_quotes 는
                        # 문서 전체를 뒤지므로 근거가 다른 절에서 나올 수 있다.
                        # 그러면 지적을 눌러도 인용이 없는 절로 간다 — 실측:
                        # "'운영 파일'과 '운영파일'이 다르다" 지적이 §10.3 을
                        # 가리키는데 두 인용은 §10.1·§10.2 에 있었다. 검토자가
                        # 문제를 눈으로 확인할 수 없다.
                        #
                        # models.py 의 Finding.evidence 주석이 정한 계약이기도
                        # 하다 — "anchor 에는 첫 근거의 위치를 넣는다".
                        anchor=found[0].anchor if found else chunk.anchor,
                        evidence=found,
                        rule_id=no,
                        # 등급만 뽑고 버리던 값이다. 화면이 "표현 점검" 한 가지로
                        # 뭉뚱그려 보여주던 것을 이걸로 가른다. 어휘 밖이면 빈 값 —
                        # 지어낸 말을 뱃지에 그대로 내보내지 않는다.
                        kind=kind if kind in _KINDS else "",
                    )))
                return (out, ("dropped" if rescues else None), None, rescues,
                        dropped_outright, dropped_artifact)
            finally:
                report()

        if workers == 1:
            results = [one(j) for j in jobs]
        else:
            # map 은 입력 순서대로 결과를 낸다 — 지적 순서가 실행마다 흔들리면
            # 리포트의 번호가 달라지고 형광펜 짝도 어긋난다.
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="consistency") as pool:
                results = list(pool.map(one, jobs))

        # 한 번이라도 위반이 나온 기준은 위반이다. 청크마다 판정이 나오므로
        # 마지막 값으로 덮으면 앞선 위반이 지워진다.
        findings: list[Finding] = []
        for rows, _kind, _why, _cs, _do, _da in results:
            for no, verdict, finding in rows:
                if no not in self.verdicts:
                    continue          # 모델이 지어낸 번호는 버린다
                if verdict == "위반":
                    self.verdicts[no] = "위반"
                    if finding is not None:
                        findings.append(finding)
                elif verdict == "통과":
                    # 한 조각이라도 실제로 봤으면 통과다 — 해당없음보다 세다.
                    if self.verdicts[no] in ("미판정", "해당없음"):
                        self.verdicts[no] = "통과"
                elif verdict == "해당없음" and self.verdicts[no] == "미판정":
                    # 조각 **전부**가 해당없음일 때만 남는다. 통과로 뒤집으면
                    # "이 기준으로 봤고 문제 없다"는 거짓말이 된다 — 안 본 것이다.
                    self.verdicts[no] = "해당없음"

        unanswered = sum(1 for _r, kind, _w, _cs, _do, _da in results
                         if kind == "unanswered")
        self.unanswered = unanswered
        # 첫 실패 이유. 전부 같은 이유일 때가 많아 하나만 실어도 충분하다.
        why = next((w for _r, kind, w, _cs, _do, _da in results
                    if kind == "unanswered" and w), None)

        # 대조 실패 후보 전량. 즉시 버리지 않고 구조를 시도한다 — 실측으로 검토당
        # 5~7건이 여기서 죽었고, 그중 일부는 지적은 맞는데 인용만 고쳐 쓴 것이었다.
        cands = [c for _r, _k, _w, cs, _do, _da in results for c in cs]
        # 실질적 인용이 애초에 하나도 없었던 후보(구조 대기열에 들어가지도 못함).
        dropped_outright = sum(do for _r, _k, _w, _cs, do, _da in results)
        # 근거가 전부 추출 잔해였던 후보(표 칸 뭉치·목차 점선·번호 나열).
        dropped_artifact = sum(da for _r, _k, _w, _cs, _do, da in results)
        # 기본값 0(꺼짐): Task 4 가 Context 에 rescue_max 필드를 추가하기 전까지는
        # 이 속성을 아무도 설정하지 않은 호출부(기존 테스트 포함)가 옛 동작
        # 그대로 유지돼야 한다 — 기본을 켜두면 설정 안 한 모든 곳의 동작이
        # 조용히 바뀐다(그 자체가 1차 경로를 건드리는 것이다).
        rescue_max = max(0, int(getattr(ctx, "rescue_max", 0) or 0))
        revived = 0
        errored = 0
        # 1차가 전부 무응답이면 살릴 후보도 없고, LLM 이 죽어 있다 — 건너뛴다.
        if cands and rescue_max and self.unanswered < total:
            outcomes = rescue_round(
                cands, doc, ctx.llm, max_rescues=rescue_max,
                workers=max(1, int(getattr(ctx, "llm_concurrency", 1) or 1)),
                on_progress=ctx.on_progress, label=self.label)
            for cand, outcome in zip(cands, outcomes):
                if outcome.errored:
                    # 근거를 못 댄 것과 다르다 — LLM 이 응답을 안 준 것이다.
                    # "0건 통과"와 "검토를 못 했다"를 섞지 않는다(루트 CLAUDE.md).
                    errored += 1
                    continue
                found = outcome.evidence
                if not found or cand.no not in self.verdicts:
                    # 1차와 같은 규칙 — 실재하는 근거를 다시 댔더라도, 지어낸
                    # 기준 번호로는 지적을 올리지 않는다. 부활로도 세지 않는다
                    # (자연히 아래 "제외" 집계로 흐른다).
                    continue
                revived += 1
                self.verdicts[cand.no] = "위반"
                findings.append(Finding(
                    checker=self.name,
                    severity=_KIND_SEVERITY.get(cand.kind, _KIND_DEFAULT),
                    message=cand.message,
                    anchor=found[0].anchor,      # 검증 통과한 실제 근거의 위치
                    evidence=found,
                    rule_id=cand.no,
                    kind=cand.kind if cand.kind in _KINDS else "",
                    # 재질의 끝에 근거를 찾은 지적임을 남긴다 — 화면 뱃지와
                    # 실측(복원 지적만 골라 검수)이 이 표시를 읽는다.
                    rescued=True,
                    # 재확인 여정 — 처음 인용(실패)과 모델이 쓴 검색어. 확정
                    # 근거는 evidence 가 이미 담는다. 화면이 "어떻게 다시
                    # 찾았나"를 보여줄 수 있어야 에이전트가 일한 과정이
                    # 결과에서 사라지지 않는다.
                    rescue_trace={"failed_quotes": list(cand.quotes),
                                  "searched": list(outcome.searched)},
                ))
        else:
            # 구조 라운드를 건너뛴 경우(후보 없음 · 상한 0 · 전부 무응답) INFO
            # 문구가 "재확인했습니다"라 말하지 않도록 옛 문구로 떨어뜨린다.
            rescue_max = 0
        attempted = min(len(cands), rescue_max) if rescue_max else 0
        skipped = len(cands) - attempted
        dropped = len(cands) - revived

        if unanswered:
            everything = unanswered == total
            reason = f" ({why})" if why else ""
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                # 단위는 "청크"가 아니라 호출이다 — 청크 하나를 기준 묶음 수만큼
                # 묻기 때문에 둘이 다르다(청크 3 × 묶음 2 = 6회).
                message=(
                    f"표현 점검이 수행되지 않았습니다 — {total}회 호출 전부에서 LLM "
                    f"응답을 받지 못했습니다{reason}. 기준에 비춘 검사가 하나도 "
                    f"수행되지 않았습니다(지적 0건은 '문제 없음'이 아닙니다)."
                    if everything else
                    f"표현 점검에서 {unanswered}/{total}회 호출이 LLM 응답을 받지 "
                    f"못해 검토되지 않았습니다{reason}."),
                anchor=Anchor(page=None, section=None),
                suggestion=("LLM 이 연결돼 있는지 확인하세요(설정의 provider·base_url). "
                            "연결 없이 쓰려면 규칙 검사 결과만 유효합니다."),
                unreviewed=True,
            ))

        if dropped or revived:
            if not rescue_max:
                message = (f"표현 점검에서 지적 후보 {dropped}건이 원문 대조를 "
                           f"통과하지 못해 제외되었습니다 (인용한 문장을 문서에서 "
                           f"찾지 못함).")
            else:
                parts = [(f"표현 점검에서 지적 후보 {len(cands)}건이 원문 대조에 "
                          f"실패해 재확인했습니다")]
                detail = []
                if revived:
                    detail.append(f"{revived}건은 실재 근거를 찾아 복원")
                if errored:
                    # LLM 오류는 "근거를 대지 못함"과 다르다 — 검토를 못 한 것이다.
                    detail.append(f"{errored}건은 재확인 중 LLM 응답을 받지 못해 제외")
                no_evidence = dropped - skipped - errored
                if no_evidence:
                    detail.append(f"{no_evidence}건은 근거를 대지 못해 제외")
                if skipped:
                    detail.append(f"{skipped}건은 재확인 상한({rescue_max}건)에 "
                                  f"걸려 시도하지 못하고 제외")
                message = f"{parts[0]} — {', '.join(detail)}되었습니다."
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=message,
                anchor=Anchor(page=None, section=None),
                suggestion="제외된 지적은 모델이 실재 근거를 대지 못한 것입니다. "
                           "필요하면 해당 절을 직접 확인하세요.",
            ))

        if dropped_outright:
            # "재확인" 대상이 아니었던 건수다 — 위 절(재확인 결과)과 섞으면
            # 재확인이 실패한 것처럼 보인다. 별도 절로 정직하게 드러낸다.
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=(f"표현 점검에서 지적 후보 {dropped_outright}건은 실질적 "
                         f"인용이 없어 재확인 없이 제외되었습니다(인용 없음 또는 "
                         f"너무 짧음)."),
                anchor=Anchor(page=None, section=None),
                suggestion="제외된 지적은 원문 인용 없이 나온 것입니다. "
                           "필요하면 해당 절을 직접 확인하세요.",
            ))
        if dropped_artifact:
            # **조용히 지우면 "지적이 없다"는 거짓말이 된다**(CLAUDE.md).
            # 위 절(인용 없음)과 갈라 둔다 — 저쪽은 모델이 근거를 안 댄 것이고
            # 이쪽은 근거를 댔는데 그 근거가 우리 추출 잔해인 것이다. 뭉치면
            # 검토자가 "모델이 헛소리했다"로 읽는다.
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=(f"표현 점검에서 지적 {dropped_artifact}건은 근거가 문서 "
                         f"문장이 아니라 추출 잔해(표 칸 뭉치·목차 점선·번호 "
                         f"나열)여서 제외되었습니다."),
                anchor=Anchor(page=None, section=None),
                suggestion="문서가 아니라 파서가 깨뜨린 자리입니다. 그 절의 표를 "
                           "직접 확인하세요.",
            ))
        return findings + list(notices)


class WholeDocCriteriaChecker(ChunkCriteriaChecker):
    """문서를 **통째로** 한 프롬프트에 넣고 기준마다 묻는다.

    조각으로 자르면 멀리 떨어진 두 곳을 못 맞댄다 — 3쪽 표 제목과 40쪽 본문 참조,
    앞쪽 약어 목록과 뒤쪽 사용처, 개정기록 표와 본문 개정바 위치. 각 조각만 보는
    모델은 둘이 다른 조각에 들어가면 영원히 못 맞춘다.

    실측(2026-07-30, 사내 vLLM Qwen3.6-27B): 기준 1개 × 문서 통째가 4/4 로 가장
    정확했다(기준 7개를 한 프롬프트에 몰아 준 조각 방식은 3/4 — 하나를 3회 모두
    조용히 놓쳤다).

    문서가 창을 넘으면 조각으로 내려가되 **그 사실을 밝힌다.** 전체를 봐야 하는
    기준을 조각으로 훑고 "이상 없음"이라 하면 거짓말이 된다.
    """
    name = "consistency_doc"
    label = "문서 전체 점검"

    def __init__(self, criteria: Sequence = (), max_chars: int = 120_000):
        super().__init__(criteria)
        # 창 크기는 서버 설정(vLLM max_model_len)이 정한다 — 모델 고유 상수가
        # 아니라 배포 설정이라, 코드에 박지 않고 주입받는다(Config.llm_doc_max_chars).
        self.max_chars = max_chars

    def _batches(self) -> list[list]:
        """전체 기준은 하나씩 물어 진행률과 판정 누락을 기준별로 가른다.

        일반 표현 점검은 청크가 많아 기준을 최대 4개씩 묶지만, 전체 점검은 문서가
        한 단위라 같은 방식을 쓰면 공통+팀 기준 3개가 호출 한 번에 합쳐져 진행바가
        0%에서 100%로만 뛴다. 기준별 호출은 현재 최대 3개이고 병렬 실행되므로
        지연을 거의 늘리지 않으면서 실제 완료 기준 수(1/3, 2/3, 3/3)를 보여준다.
        기준 하나 × 문서 전체가 가장 정확했던 실측과도 맞는다.
        """
        return [[criterion] for criterion in self.criteria]

    def plan(self, doc: Document, ctx: Context) -> dict | None:
        """작업량은 **실제 호출 수**다. 청크 수로 신고하면 문서가 창에 들어갈 때
        1회만 부르고도 진행바가 절반에서 멈춘다."""
        if not self.criteria:
            return None
        units, _ = self._units(doc, ctx)
        text = "\n".join(s.text or "" for s in doc.iter_sections()) if doc else ""
        whole = bool(text.strip()) and len(text) <= self.max_chars
        return {"kind": "chunk", "total": len(units) * len(self._batches()),
                "label": self.label,
                "description": "용어·참조·수치·동일 ID의 문서 내 일관성",
                "scope": "문서 전체 입력" if whole else "분할 검사 · 전체 비교 제한",
                "limited": not whole}

    def _units(self, doc: Document, ctx: Context) -> tuple[list, list[Finding]]:
        text = "\n".join(s.text or "" for s in doc.iter_sections()) if doc else ""
        if not text.strip():
            return [], []
        if len(text) <= self.max_chars:
            first = next(doc.iter_sections(), None)
            anchor = first.anchor if first is not None else Anchor(page=None, section=None)
            return [_Unit(text=text, anchor=anchor)], []

        # 창을 넘었다. 조각으로 내려가고 알린다 — 이 기준들은 부분만 본 것이다.
        return list(ctx.chunks), [Finding(
            checker=self.name,
            severity=Severity.INFO,
            message=(f"문서가 커서({len(text):,}자, 한도 {self.max_chars:,}자) 문서 전체를 "
                     f"한 번에 보지 못하고 조각으로 나눠 검사했습니다. 멀리 떨어진 두 곳을 "
                     f"맞대야 하는 기준(표·그림 참조, 약어 목록과 사용처 등)은 "
                     f"부분만 본 결과입니다."),
            anchor=Anchor(page=None, section=None),
            suggestion=("설정의 llm_doc_max_chars 를 올리거나(서버 창이 허용하는 만큼), "
                        "해당 기준은 직접 확인하세요."),
            unreviewed=True,
        )]

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        findings = super().check(doc, ctx)
        # 부분만 봤으면 '통과'를 확정하지 않는다 — 못 본 곳에 위반이 있을 수 있다.
        if any(f.unreviewed and "문서가 커서" in f.message for f in findings):
            self.verdicts = {no: ("미판정" if v == "통과" else v)
                             for no, v in self.verdicts.items()}
        return findings


# 공개 이름을 바꿔도 기존 모듈 사용자와 저장된 확장 코드가 한 번에 깨지지 않게
# 구 이름을 호환 별칭으로 남긴다. 새 코드는 위의 직관적인 이름을 사용한다.
ConsistencyChecker = ChunkCriteriaChecker
WholeDocChecker = WholeDocCriteriaChecker

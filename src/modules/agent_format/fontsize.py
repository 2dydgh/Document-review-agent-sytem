"""규칙기반 체커: 표 안에 직접 박힌 글꼴 크기.

문서 간 md 가 요구한다 — *"테스트케이스 글꼴 크기가 8 pt 또는 9 pt로 맞춰져
있는지 세세하게 확인"*.

**"이 문서의 글꼴"을 재는 것이 아니다.** 워드는 대부분의 글자에 크기를 안 적고
문단 스타일이 정한다. 실측(시험 설계서): 런 405개 중 크기가 적힌 것은 23개다.
상속 사슬(docDefaults → 스타일 → 문단 → 런)과 theme 해석까지 해야 진짜 크기를
아는데, 그건 별도 작업이다.

여기서 보는 것은 **스타일을 벗어나 직접 박아둔 크기**다. 그게 곧 검사 대상과
겹친다 — 실측에서 8pt 139자가 전부 테스트케이스 표였고, 본문은 스타일에 맡기고
테스트케이스만 직접 박는 구조였다.

**표 안만 본다.** 같은 문서 표지 제목이 40pt 로 직접 박혀 있는데, 표 밖까지 재면
그것을 "8~9pt 가 아니다"로 지적한다 — 없는 결함을 만들어낸다.
"""
from __future__ import annotations

from dataclasses import dataclass

from modules.shared import Anchor, Document, Finding, Severity


@dataclass
class FontSizeChecker:
    """표 안에 직접 박힌 글꼴 크기가 허용 범위인가."""

    name = "completeness"
    # 화면 뱃지가 쓰는 이름. name 은 일곱 체커가 "completeness" 를 나눠 쓰므로
    # 무엇이 잡았는지 못 가린다 — label 이 그 자리를 진다.
    label = "표 글꼴 검사"
    allowed: tuple[float, ...] = ()
    document: str = ""

    def check(self, doc: Document, ctx: object = None) -> list[Finding]:
        if not self.allowed:
            # 허용 크기를 안 주면 **검사한 척하지 않는다.** 예전엔 조용히 0건이었다 —
            # 기준에 `check: fontsize` 라고 적어 놓고 `font_sizes` 를 빠뜨리면 화면이
            # "글꼴 이상 없음"으로 읽혔다. text_pattern·header_footer 와 같은 계약이다.
            #
            # case.py(폴더 검토)는 `if sizes:` 로 막고 있어 빈 검사기를 안 만든다.
            return [Finding(
                checker=self.name, severity=Severity.INFO,
                message=("허용 글꼴 크기가 검토 기준에 없어 표 글꼴 검사를 "
                         "수행하지 않았습니다."),
                anchor=Anchor(page=None, section=None), document=self.document,
                suggestion="검토 기준 항목의 params 에 font_sizes 를 적으면 이 검사가 됩니다.",
                unreviewed=True)]
        tables = (getattr(doc, "meta", None) or {}).get("tables") or []
        seen = {size: chars for tb in tables
                for size, chars in (tb.get("fontSizes") or {}).items()}
        if not seen:
            # 직접 박은 것이 하나도 없다 = 전부 스타일대로다. 그런데 그 스타일이
            # 규정에 맞는지는 여기서 못 본다 — "이상 없음"이 아니라 "못 봤음"이다.
            return [Finding(
                checker=self.name, severity=Severity.INFO,
                message=("표 안에 글꼴 크기가 직접 지정된 곳이 없어 서식 검사를 "
                         "수행하지 않았습니다. 문단 스타일이 정하는 크기는 아직 "
                         "읽지 못합니다."),
                anchor=Anchor(page=None, section=None), document=self.document,
                unreviewed=True)]

        allowed = ", ".join(f"{a:g}pt" for a in self.allowed)
        return [Finding(
            # 규칙이 잡은 것이라 MAJOR 다. 예전엔 여기만 MINOR 였는데 — 규칙
            # 체커가 MINOR 를 내는 유일한 자리였다 — 그건 "덜 중대하다"는 판단이고,
            # 심각도는 중대성이 아니라 **확실성** 축이다(shared/models.py Severity).
            # 8pt 가 9pt 인 것이 얼마나 나쁜지는 팀이 정할 값이지 이 코드가 정할
            # 값이 아니다.
            checker=self.name, severity=Severity.MAJOR,
            message=(f"표 안 글꼴 크기 {size:g}pt 가 규정({allowed}) 밖입니다 "
                     f"— {chars}자."),
            anchor=Anchor(page=None, section=None), document=self.document,
            suggestion=f"해당 표의 글꼴 크기를 {allowed} 중 하나로 맞추세요.")
            for size, chars in sorted(seen.items())
            if size not in self.allowed]

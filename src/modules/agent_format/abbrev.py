"""규칙기반 체커: 약어 목록과 본문 대조.

두 팀이 같은 것을 요구했다(EV2 26 · EV3 2). 둘 다 **양방향**이다:

  · 본문에 쓴 약어가 목록에 없다  → 추가해야 한다 (미등록)
  · 목록에 있는 약어가 본문에 없다 → 지워야 한다 (미사용)

LLM 없이 돈다. 멀리 떨어진 두 곳(3쪽 약어표 vs 40쪽 본문)을 맞대는 일이지만
대조가 문자열 일치라 규칙으로 충분하다 — 여기에 LLM 을 쓰면 지어낸 약어가 섞인다.

**두 방향의 오탐 성격이 반대라 목록을 읽는 방식도 다르다.**

  · 미등록 판정에는 약어 장절에 나온 **모든** 대문자 토큰을 등록된 것으로 본다.
    설명문에 섞인 토큰까지 등록으로 치면 미등록 지적이 줄어든다 — 이쪽이 시끄러운
    방향이라 조용한 쪽으로 기운다.
  · 미사용 판정에는 각 줄의 **첫** 토큰만 목록 항목으로 본다. 설명문의 토큰을
    항목으로 세면 있지도 않은 약어를 "지우라"고 하게 된다.

## 못 재는 상황을 셋으로 가른다 (2026-08-20, 실측 지적 279건 뒤)

  1. 약어 절이 없는데 **본문에도 약어가 없다** → 조용히 0건. 대조할 것이
     애초에 없었고 어긋난 것도 없다. 한글 서식(체크리스트·을지·시험의뢰서)이
     여기다 — 매번 뜨는 미검토 카드는 진짜 미검토까지 함께 무시하게 만든다.
  2. 약어 절이 없는데 **본문은 약어를 쓴다** → 미검토. 검토자가 알아야 한다.
  3. 약어 절은 **찾았는데 목록이 안 읽혔다** → 미검토. 빈 목록으로 재면 본문
     대문자가 전부 "미등록"으로 뜬다(실측 279건). 잴 자를 못 읽고 재는 꼴이라
     reflist 가 이미 같은 방어를 갖고 있다.

조용히 0건을 내는 것은 1 뿐이다. 나머지는 "약어를 대조했더니 이상 없음"으로
읽히면 안 된다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Context, Document, Evidence, Finding, Severity

#: 약어 후보. 2~8글자 **순수 대문자** 토큰.
#:
#: 숫자를 뺀 것은 실측 결과다. 숫자를 허용하면 문서번호·요건 ID·도면번호가 전부
#: 후보가 된다 — `Z11008` `J2005` `FR0050` `VR01` `A01` `SHN34`. 실문서 넷에서
#: 미등록 후보가 907 → 468 로 줄었고, 진짜 약어는 하나도 안 놓쳤다.
#:
#: 한 글자는 목차 기호·변수와 구분이 안 되고, 아홉 글자 이상은 약어가 아니라
#: 상수명이나 파일명 조각이다.
#:
#: **하이픈 뒤에 숫자가 붙으면 문서번호다** — `SST-26-999` `RN-26-999`
#: `SHN34_ESF-CCS`. 숫자를 뺀 규칙만으로는 하이픈이 토큰을 끊어 `SST` `RN` 이
#: 약어 후보로 남는다. 실측(시험 산출물 11종)에서 이 둘 때문에 약어를 하나도
#: 안 쓰는 서식 다섯 건에 "약어 목록이 없다" 카드가 떴다.
#: 진짜 약어 뒤의 하이픈은 숫자가 아니라 글자다(`ESF-CCS`) — 안 걸린다.
_CANDIDATE = re.compile(r"\b[A-Z]{2,8}\b(?!-\d)")

#: 약어 목록이 이만큼도 안 읽히면 "못 읽었다"로 본다.
#:
#: 실측된 실패는 **0종**이다(SHN34_ESF-CCS_SRS: 절은 찾았는데 내용이 안 잡혔다).
#: 잘 읽힌 쪽은 수십 종이었다(SKN56 CPS_SRS 61종). 그 사이 어디에 금을 그을지는
#: 근거가 없어 **가장 낮은 자리**에 둔다 — 한 종만 읽힌 목록은 자가 아니다.
_MIN_LISTED = 2


def _spelled_lowercase(doc) -> set[str]:
    """문서 어딘가에 **소문자·혼합 철자로도** 나타나는 낱말.

    `SERVER` `AND` `TRUE` `NUCLEAR` 같은 것은 약어가 아니라 제목·표 머리행에서
    대문자로 쓴 평범한 낱말이다. 같은 문서에 `server` `and` `true` 가 있으면
    그 증거가 된다 — 진짜 약어(`MTP` `ESF` `NSSS`)는 소문자로 안 쓰인다.

    실측(SKN56 CPS_SRS): 미등록 98종에 AND·TRUE·FALSE·ON·OFF·REMARK·SERVER·
    CLIENT·NUCLEAR·POWER·PLANT·UNIT·SPECIFIC 이 섞여 있었다. 무시목록으로는
    끝이 없어 문서 자신에게 묻는다.
    """
    out: set[str] = set()
    for s in doc.iter_sections():
        for w in re.findall(r"\b[A-Za-z]{2,8}\b", s.text or ""):
            if not w.isupper():
                out.add(w.upper())
    return out


#: 한 지적에 나열할 최대 개수. 넘으면 "…외 N종"으로 접는다.
_MAX_LISTED = 30


def _all_caps(line: str) -> bool:
    """줄 전체가 대문자인가.

    표지·목차·표 머리행이 통째로 대문자다 — `RECORD OF REVISION`, `LIST OF TABLES`,
    `KOREA HYDRO NUCLEAR POWER CO LTD`. 그 줄의 낱말은 약어가 아니라 그냥 대문자로
    쓴 영어라, 안 걸러내면 미등록 목록의 절반이 `OF` `BY` `ALL` `FOR` 가 된다.
    약어 장절 안에서는 이 규칙을 쓰지 않는다 — 거기는 대문자가 정상이다.
    """
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)

#: 약어 장절을 가리는 기본 제목 조각. 실측 문서가 쓰는 말이다
#: (한국어 "약어", RVVR 의 "4.0 Definitions and Abbreviations").
#:
#: **`용어` 는 뺐다(2026-08-20).**
#:
#: 실측(AI시험인증1팀 시험설계서): `용어 정의` 절이 걸렸는데 그 표는 "웹 홈페이지"
#: "로그인" 같은 **한글 용어 설명표**였다. 약어가 하나도 없는 표를 약어 목록으로
#: 삼으니, 본문의 영문 대문자가 전부 "목록에 없다"로 떴다 — AMD·CPU·GB·HDD·OS·
#: PC·RAM·SW 여덟 종.
#:
#: `용어` 를 빼면 그 문서는 "약어 절을 못 찾았다"가 된다. 실제로 약어 절이 없으니
#: 맞는 말이다 — 잘못된 목록으로 재는 것보다 못 쟀다고 말하는 쪽이 낫다.
#: 용어와 약어를 한 절에 적는 팀은 params.abbrev_sections 로 그 제목을 준다.
DEFAULT_SECTIONS = ("약어", "abbrevia")

#: 대문자 토큰이지만 **아무도 약어로 정의하지 않는 것들.**
#:
#: 실측에서 미등록 지적의 대부분이 이것들이었다 — 시험 환경 표에 적힌 하드웨어
#: 이름과 단위다. 팀이 늘릴 수 있게 params.abbrev_ignore 가 따로 있지만, 이 정도는
#: 어느 팀 문서에나 나오고 어느 팀도 정의하지 않는다.
#:
#: **여기 아무거나 넣지 않는다.** 팀이 실제로 정의하는 것을 넣으면 진짜 미등록을
#: 놓친다 — 예를 들어 `AI` 는 AI시험인증1팀 md 가 "AI / 인공지능" 을 용어 통일
#: 대상으로 콕 집어 말하므로 여기 없다.
DEFAULT_IGNORE = (
    # 하드웨어·단위·플랫폼
    "CPU", "GPU", "RAM", "ROM", "HDD", "SSD", "USB", "PC", "LCD", "LED",
    "OS", "SW", "HW",
    "GB", "MB", "KB", "TB", "HZ", "MHZ", "GHZ", "MS", "NS",
    # 파일 형식
    "PDF", "XML", "HTML", "CSV", "JSON", "TXT", "ZIP", "DOC", "DOCX", "PPT",
    "URL", "QR", "ID", "PW",
    # 판정·상태 표기
    "PASS", "FAIL", "OK", "NG", "YES", "TBD", "TBC",
    # 문서 표기
    "REV", "VER", "NO",
    # 대표적 제조사 이름 (약어가 아니라 상표다)
    "AMD", "IBM", "HP",
)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _descendants(section) -> list:
    out = []
    for child in section.children:
        out.append(child)
        out.extend(_descendants(child))
    return out


def _entry_token(line: str) -> str | None:
    """줄 하나에서 **목록 항목**으로 볼 토큰. 없으면 None.

    표 행(`| ABC | 설명 |`)이면 첫 칸에서, 아니면 줄 앞머리에서 찾는다. 어느 쪽이든
    설명문 안쪽은 보지 않는다 — 거기 섞인 토큰을 항목으로 세면 있지도 않은 약어를
    "안 쓰이니 지우라"고 하게 된다.
    """
    head = line.split("|")[1] if line.lstrip().startswith("|") else line
    m = _CANDIDATE.search(head)
    return m.group(0) if m else None


class AbbrevChecker:
    """약어 목록 ↔ 본문 대조.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "약어 목록 대조"

    def __init__(self, sections: tuple[str, ...] = DEFAULT_SECTIONS,
                 ignore: tuple[str, ...] = ()) -> None:
        self.sections = tuple(sections) or DEFAULT_SECTIONS
        # 약어가 아닌데 대문자 토큰인 것들. 기본값에 팀 것을 **더한다** —
        # 갈아끼우면 팀이 하나를 적는 순간 CPU·GB 가 다시 지적으로 쏟아진다.
        self.ignore = {t.upper() for t in DEFAULT_IGNORE} | {t.upper() for t in ignore}

    def check(self, doc: Document, ctx: Context | None = None) -> list[Finding]:
        keys = [_norm(k) for k in self.sections]
        listed_secs = [s for s in doc.iter_sections()
                       if any(k in _norm(s.title) for k in keys)]
        if not listed_secs:
            # **약어를 안 쓰는 문서에는 이 카드를 띄우지 않는다.** 약어 절이 없고
            # 본문에도 약어 후보가 없으면 대조할 것이 애초에 없다 — 어긋난 것이
            # 없는 것이 사실이므로 지적 0건이 거짓말이 아니다.
            #
            # 실측: 시험 산출물(체크리스트·을지·시험의뢰서)은 한글 서식이라 약어가
            # 아예 없는데 검토 때마다 "검사 못 함" 카드가 떴다. 매번 뜨는 미검토는
            # 진짜 미검토(아래 갈래)까지 함께 무시하게 만든다.
            #
            # 본문에 약어를 쓰는데 목록이 없는 것은 다른 얘기다 — 그건 검토자가
            # 알아야 하므로 그대로 미검토로 알린다.
            if not self._body_candidates(doc):
                return []
            return [self._unreviewed(
                "약어 목록 장절을 찾지 못해 약어 대조를 수행하지 "
                f"않았습니다 (찾아본 제목: {' / '.join(self.sections)}).",
                "이 문서에 약어 장절이 정말 없으면 그대로 두세요. 있는데 못 찾은 "
                "것이면 기준 관리자에게 그 절 제목을 기준에 넣어 달라고 "
                "알려주세요(항목의 params.abbrev_sections).")]

        # 하위 절까지 약어 장절로 본다. 빼면 "4.1 신호 약어" 같은 하위 표가 본문으로
        # 세어져, 거기 적힌 약어가 전부 "목록에 없다"로 뜬다.
        listed: list = []
        for s in listed_secs:
            listed.append(s)
            listed.extend(_descendants(s))
        listed_ids = {id(s) for s in listed}

        in_list: set[str] = set()      # 미등록 판정용 — 장절 안의 모든 토큰
        entries: dict[str, Anchor] = {}   # 미사용 판정용 — 줄머리 토큰만
        for s in listed:
            in_list.update(_CANDIDATE.findall(s.text or ""))
            for line in (s.text or "").splitlines():
                token = _entry_token(line)
                if token:
                    entries.setdefault(token, s.anchor)

        # **목록을 제대로 못 읽었으면 미등록 판정을 하지 않는다.** reflist 가 같은
        # 방어를 갖고 있다 — 잴 자를 못 읽고 재는 꼴이기 때문이다.
        #
        # 실측(SHN34_ESF-CCS_SRS.pdf): 약어 절 둘을 **찾았는데 목록 토큰이 0개**
        # 였다(표가 그림이거나 책갈피가 얕아 내용이 안 잡혔다). 빈 목록으로 재니
        # 본문 대문자 279종이 전부 "미등록"으로 떴다 — RECORD·TABLE·CONTENTS 까지.
        #
        # 미사용 방향(목록에 있는데 본문에 없다)은 그대로 둔다. 목록을 못 읽으면
        # entries 도 비어 지적이 안 나온다 — 오탐이 날 자리가 없다.
        list_unreadable = len(in_list) < _MIN_LISTED

        used: dict[str, Anchor] = {}
        for s in doc.iter_sections():
            if id(s) in listed_ids:
                continue
            for line in (s.text or "").splitlines():
                if _all_caps(line):
                    continue
                for token in _CANDIDATE.findall(line):
                    used.setdefault(token, s.anchor)

        spelled = _spelled_lowercase(doc)
        missing = {} if list_unreadable else {
            t: a for t, a in used.items()
            if t not in in_list and t not in self.ignore and t not in spelled}
        unused = {t: a for t, a in entries.items()
                  if t not in used and t not in self.ignore}

        findings: list[Finding] = []
        if list_unreadable:
            findings.append(self._unreviewed(
                f"약어 목록을 {len(in_list)}종밖에 읽지 못해 미등록 대조를 하지 "
                "않았습니다.",
                "PDF 라면 약어표가 그림이 아닌지, 책갈피가 약어 절 아래까지 있는지 "
                "확인하세요."))
        if missing:
            findings.append(self._listed(
                missing, f"약어 {len(missing)}종이 약어 목록에 없습니다",
                "약어 목록에 추가하거나, 약어가 아닌 것은 기준의 abbrev_ignore 에 넣으세요."))
        if unused:
            findings.append(self._listed(
                unused, f"약어 목록의 {len(unused)}종이 본문에서 쓰이지 않습니다",
                "약어 목록에서 지우세요."))
        return findings

    def _listed(self, tokens: dict, message: str, suggestion: str) -> Finding:
        """토큰 여럿을 **한 건**으로 낸다.

        낱개로 내면 실문서 하나에서 174건이 쏟아진다(실측: SHN34 RVVR). 그 목록은
        아무도 안 읽고, 다른 검사의 지적까지 파묻는다. 기준 원문도 낱개 지적이
        아니라 "식별하고 **리스트화**" 를 요구한다(ax-quality 9 · EV2 26).

        토큰마다의 위치는 evidence 로 남는다 — 화면이 짚어 갈 수 있어야 한다.
        """
        names = sorted(tokens)
        shown = ", ".join(names[:_MAX_LISTED])
        if len(names) > _MAX_LISTED:
            shown += f" 외 {len(names) - _MAX_LISTED}종"
        first = tokens[names[0]]
        return Finding(
            checker=self.name,
            severity=Severity.MINOR,
            message=f"{message} — {shown}",
            anchor=first,
            suggestion=suggestion,
            evidence=[Evidence(anchor=tokens[t], quote=t) for t in names],
        )

    def _body_candidates(self, doc: Document) -> bool:
        """본문에 약어로 볼 만한 토큰이 하나라도 있는가.

        무시목록과 소문자 철자를 뺀 뒤에 본다 — `PDF` 하나 때문에 "약어 목록이
        없다"고 하면 카드를 다시 매번 띄우는 꼴이다.
        """
        spelled = _spelled_lowercase(doc)
        for s in doc.iter_sections():
            for line in (s.text or "").splitlines():
                if _all_caps(line):
                    continue
                for token in _CANDIDATE.findall(line):
                    if token not in self.ignore and token not in spelled:
                        return True
        return False

    def _unreviewed(self, message: str, suggestion: str) -> Finding:
        """검사를 **못 했다**고 말하는 카드. 지적 0건과 절대 섞지 않는다."""
        return Finding(
            checker=self.name, severity=Severity.INFO, unreviewed=True,
            message=message, anchor=Anchor(page=None, section=None),
            suggestion=suggestion)

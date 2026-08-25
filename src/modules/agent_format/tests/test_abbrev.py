"""약어 목록 ↔ 본문 양방향 대조 (EV2 26 · EV3 2).

두 방향의 오탐 성격이 반대다. 미등록(본문 → 목록)은 대문자 토큰을 다 긁으므로
시끄럽고, 미사용(목록 → 본문)은 목록 항목만 보므로 조용하다. 목록을 읽는 방식이
방향마다 다른 이유가 그것이다.
"""
from modules.agent_format import AbbrevChecker
from modules.doc_parser import RawDoc, normalize
from modules.shared import Severity


def _doc(text):
    return normalize(RawDoc(source_path="d.md", text=text))


_WITH_LIST = """# 4.0 Abbreviations

| ESF | Engineered Safety Features |
| CCS | Component Control System |

# 5.0 본문

ESF 신호는 CCS 로 전달된다.
"""


def test_목록과_본문이_맞으면_지적_없음():
    assert AbbrevChecker().check(_doc(_WITH_LIST)) == []


def test_본문에만_있는_약어를_짚는다():
    doc = _doc(_WITH_LIST.replace("ESF 신호는 CCS 로", "ESF 신호는 CCS 를 거쳐 PAMS 로"))
    got = AbbrevChecker().check(doc)
    assert [f.severity for f in got] == [Severity.MINOR]
    assert "PAMS" in got[0].message and "약어 목록에 없습니다" in got[0].message


def test_목록에만_있는_약어를_짚는다():
    doc = _doc(_WITH_LIST.replace("| CCS | Component Control System |",
                                  "| CCS | Component Control System |\n| QIAS | Q |"))
    got = AbbrevChecker().check(doc)
    assert [f.severity for f in got] == [Severity.MINOR]
    assert "QIAS" in got[0].message and "쓰이지 않습니다" in got[0].message


def test_설명문의_토큰은_목록_항목으로_세지_않는다():
    """설명에 섞인 토큰을 항목으로 세면 있지도 않은 약어를 지우라고 하게 된다."""
    doc = _doc(_WITH_LIST.replace("| CCS | Component Control System |",
                                  "| CCS | Component Control System (IEEE 정의) |"))
    got = AbbrevChecker().check(doc)
    assert got == [], [f.message for f in got]


def test_약어_장절을_못_찾으면_미검토다():
    """조용한 0건은 "약어를 대조했더니 이상 없음"으로 읽힌다."""
    got = AbbrevChecker().check(_doc("# 1.0 개요\n\nESF 신호."))
    assert [f.severity for f in got] == [Severity.INFO]
    assert got[0].unreviewed


def test_장절_제목은_기준이_정한다():
    doc = _doc("# 신호 약칭\n\n| ESF | x |\n| CCS | y |\n\n# 본문\n\nESF 신호는 CCS 로 간다.")
    assert AbbrevChecker(sections=("약칭",)).check(doc) == []


def test_ignore_에_넣은_토큰은_안_짚는다():
    doc = _doc(_WITH_LIST.replace("ESF 신호는", "PDF 로 낸 ESF 신호는"))
    assert AbbrevChecker(ignore=("PDF",)).check(doc) == []


def test_하위_절의_약어표도_목록으로_본다():
    """빼면 하위 표에 적힌 약어가 전부 "목록에 없다"로 뜬다."""
    doc = _doc("# 4.0 Abbreviations\n\n## 4.1 신호 약어\n\n| ESF | x |\n| CCS | y |\n\n"
               "# 5.0 본문\n\nESF 신호는 CCS 로 간다.")
    assert AbbrevChecker().check(doc) == []


# ── 실문서 실측으로 정한 규칙 셋 ─────────────────────────────────────────
# 아래 셋은 취향이 아니라 data/ 의 실문서 넷에서 잰 결과다. 되돌리면 미등록
# 후보가 907 개로 돌아간다.


def test_여러_건을_한_지적으로_묶는다():
    """낱개로 내면 실문서 하나에서 174건이 쏟아진다(실측: SHN34 RVVR).

    그 목록은 아무도 안 읽고 다른 검사의 지적까지 파묻는다. 기준 원문도 낱개
    지적이 아니라 "식별하고 리스트화" 를 요구한다(ax-quality 9 · EV2 26).
    """
    doc = _doc(_WITH_LIST.replace("ESF 신호는 CCS 로",
                                  "ESF 신호는 CCS 를 거쳐 PAMS, QIAS, MMIS 로"))
    got = AbbrevChecker().check(doc)
    assert len(got) == 1, "미등록은 문서당 한 건이어야 한다"
    assert "약어 3종" in got[0].message
    # 토큰마다의 위치는 evidence 로 남는다 — 화면이 짚어 갈 수 있어야 한다.
    assert {e.quote for e in got[0].evidence} == {"PAMS", "QIAS", "MMIS"}


def test_숫자가_섞인_토큰은_약어가_아니다():
    """문서번호·요건 ID·도면번호가 전부 후보가 된다 — 실측에서 907 → 468.

    Z11008 · J2005 · FR0050 · VR01 · SHN34 가 "약어 목록에 없다"로 떴다.
    """
    doc = _doc(_WITH_LIST.replace("ESF 신호는 CCS 로",
                                  "ESF 신호는 CCS 로 (Z11008, FR0050, VR01 참조)"))
    assert AbbrevChecker().check(doc) == []


def test_줄_전체가_대문자면_약어로_안_센다():
    """표지·목차·표 머리행이 통째로 대문자다.

    안 걸러내면 미등록 목록의 앞자리가 OF · BY · ALL · FOR 로 찬다.
    """
    doc = _doc(_WITH_LIST.replace("# 5.0 본문", "# 5.0 본문\n\nRECORD OF REVISION\nLIST OF TABLES"))
    assert AbbrevChecker().check(doc) == []


def test_약어_장절_안에서는_대문자_줄도_읽는다():
    """거기는 대문자가 정상이다 — 본문 규칙을 그대로 적용하면 목록을 못 읽는다."""
    doc = _doc("# 4.0 Abbreviations\n\nESF ENGINEERED SAFETY FEATURE\n\n"
               "# 5.0 본문\n\nESF 신호를 본다.")
    assert AbbrevChecker().check(doc) == []


# ── 잘못된 목록으로 재지 않는다 (2026-08-20) ─────────────────────────

def _doc_with(title: str, listed: str, body: str):
    """제목이 `title` 인 절에 `listed`, 본문에 `body` 를 담은 문서."""
    from dataclasses import dataclass
    from dataclasses import field as _f

    from modules.shared import Anchor

    @dataclass
    class _S:
        title: str
        text: str
        children: list = _f(default_factory=list)
        anchor: Anchor = _f(default_factory=lambda: Anchor(page=1, section="1"))

    @dataclass
    class _D:
        sections: list
        meta: dict = _f(default_factory=dict)

        def iter_sections(self):
            return iter(self.sections)

    return _D([_S(title=title, text=listed), _S(title="본문", text=body)])


def test_용어_정의_절은_약어_목록이_아니다():
    """실측(AI시험인증1팀 시험설계서): `용어 정의` 절이 "웹 홈페이지"·"로그인"
    같은 **한글 용어 설명표**였는데 약어 목록으로 걸렸다. 약어가 하나도 없는 표를
    잣대로 삼으니 본문 영문 대문자가 전부 "목록에 없다"로 떴다(8종).

    못 찾았다고 말하는 편이 낫다 — 잘못된 잣대로 재면 멀쩡한 문서가 지적투성이가 된다.
    """
    doc = _doc_with("용어 정의", "| 용어 | 정의 | | 웹 홈페이지 | 인터넷에서 |", "SRS 를 따른다")
    got = AbbrevChecker().check(doc, None)
    assert len(got) == 1 and got[0].unreviewed
    assert "찾지 못해" in got[0].message


def test_약어_절은_그대로_걸린다():
    doc = _doc_with("약어", "SRS Software Requirements Specification | IRS Interface",
                    "SRS 와 SDD 를 본다")
    got = [f for f in AbbrevChecker().check(doc, None) if not f.unreviewed]
    assert got, "약어 절이 있는데 검사가 안 돌았다"
    assert any("SDD" in f.message for f in got)


def test_기본_무시목록은_지적하지_않는다():
    """CPU·GB·OS 는 어느 문서에나 나오고 아무도 약어로 정의하지 않는다."""
    doc = _doc_with("약어", "SRS Software Requirements Specification",
                    "CPU 와 RAM, 12 GB HDD, OS 는 PASS")
    got = [f for f in AbbrevChecker().check(doc, None) if not f.unreviewed]
    joined = " ".join(f.message for f in got)
    for t in ("CPU", "RAM", "GB", "HDD", "OS", "PASS"):
        assert t not in joined, f"{t} 가 미등록으로 떴다"


def test_팀_무시목록은_기본값에_더해진다():
    """갈아끼우면 팀이 하나를 적는 순간 CPU·GB 가 다시 쏟아진다."""
    doc = _doc_with("약어", "SRS Software Requirements Specification",
                    "CPU 와 SST 를 본다")
    got = [f for f in AbbrevChecker(ignore=("SST",)).check(doc, None) if not f.unreviewed]
    joined = " ".join(f.message for f in got)
    assert "SST" not in joined and "CPU" not in joined


def test_AI_는_무시하지_않는다():
    """AI시험인증1팀 md 가 "AI / 인공지능" 을 용어 통일 대상으로 콕 집어 말한다 —
    기본 무시목록에 넣으면 팀이 실제로 보는 것을 놓친다."""
    from modules.agent_format.abbrev import DEFAULT_IGNORE
    assert "AI" not in DEFAULT_IGNORE


# ── 잣대를 못 읽었을 때 · 대문자 영어 낱말 ───────────────────────────────
# 실측(SHN34_ESF-CCS_SRS.pdf · SKN56 CPS_SRS.pdf)에서 나온 두 오탐이다.

def test_빈_목록으로_재지_않는다():
    """약어 절을 **찾았는데 내용이 안 읽힌** 문서. 실측에서 이 상태로 대조하니
    본문 대문자 279종이 전부 "목록에 없다"로 떴다 — 잴 자를 못 읽고 잰 것이다.

    지적 0건이 아니라 **미검토**여야 한다. 조용한 0건은 "대조했더니 이상 없음"
    으로 읽힌다.
    """
    doc = _doc("# 3.1 Abbreviations\n\n(표가 그림이라 글자가 안 잡혔다)\n\n"
               "# 4.0 본문\n\nESF 신호는 CCS 로 전달되고 MTP 를 거친다.")
    got = AbbrevChecker().check(doc)
    assert [f.unreviewed for f in got] == [True]
    assert "밖에 읽지 못해" in got[0].message
    assert not [f for f in got if not f.unreviewed], "빈 목록으로 지적을 냈다"


def test_소문자로도_쓰이는_낱말은_약어가_아니다():
    """`SERVER`·`AND`·`TRUE` 는 제목·표 머리행에서 대문자로 쓴 평범한 낱말이다.
    같은 문서에 `server`·`and` 가 있으면 그것이 증거다 — 진짜 약어는 소문자로
    안 쓰인다. 무시목록으로는 끝이 없어 문서 자신에게 묻는다.
    """
    doc = _doc("# 4.0 Abbreviations\n\n| ESF | x |\n| CCS | y |\n\n# 5.0 본문\n\n"
               "ESF and CCS 는 the server 에 붙는다. 표: SERVER | AND | TRUE\n"
               "판정이 true 이면 통과한다. MTP 는 따로 본다.")
    missing = [f for f in AbbrevChecker().check(doc)
               if not f.unreviewed and "없습니다" in f.message]
    assert missing, "미등록 지적이 아예 안 나왔다 — 시험이 헛돈다"
    quoted = " ".join(e.quote for f in missing for e in f.evidence) + missing[0].message
    for word in ("SERVER", "AND", "TRUE"):
        assert word not in quoted, f"{word} 를 약어로 짚었다"
    assert "MTP" in quoted, "진짜 약어까지 같이 걸러졌다"


def test_약어를_안_쓰는_문서에는_카드를_안_띄운다():
    """실측: 시험 산출물(체크리스트·을지·시험의뢰서)은 한글 서식이라 약어가 아예
    없는데 검토 때마다 "약어 목록 장절을 찾지 못해…" 카드가 떴다. 매번 뜨는
    미검토는 진짜 미검토까지 함께 무시하게 만든다.

    대조할 것이 없었고 어긋난 것도 없으니 0건이 거짓말이 아니다.
    """
    doc = _doc("# 1. 시험 결과\n\n시험 항목을 확인하고 담당자가 서명한다. 12 GB 저장.")
    assert AbbrevChecker().check(doc) == []


def test_약어를_쓰는데_목록이_없으면_그대로_알린다():
    """앞 시험의 뒷면. 본문이 약어를 쓰는데 목록이 없는 것은 검토자가 알아야 한다 —
    조용해지는 것은 '약어가 없는 문서'뿐이다."""
    doc = _doc("# 1.0 개요\n\nESF 신호는 MTP 를 거친다.")
    got = AbbrevChecker().check(doc)
    assert len(got) == 1 and got[0].unreviewed
    assert "찾지 못해" in got[0].message


def test_문서번호_앞머리는_약어가_아니다():
    """`SST-26-999` 의 `SST`, `RN-26-999` 의 `RN`. 숫자를 뺀 규칙만으로는 하이픈이
    토큰을 끊어 앞머리가 후보로 남는다 — 실측(시험 산출물 11종)에서 이 둘 때문에
    약어를 하나도 안 쓰는 서식 다섯 건에 "약어 목록이 없다" 카드가 떴다.

    진짜 약어 뒤의 하이픈은 숫자가 아니라 글자다(`ESF-CCS`) — 안 걸려야 한다.
    """
    form = _doc("# 1. 시험 결과\n\n| 의뢰번호 | SST-26-999 | 접수번호 | RN-26-999 |")
    assert AbbrevChecker().check(form) == []

    real = _doc("# 1.0 개요\n\nESF-CCS 계통을 본다.")
    got = AbbrevChecker().check(real)
    assert len(got) == 1 and got[0].unreviewed, "ESF 까지 같이 걸러졌다"

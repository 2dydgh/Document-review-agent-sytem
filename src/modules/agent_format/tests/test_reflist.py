"""참조문서 목록 ↔ 본문 인용 대조 (EV2 25).

목록은 **번호 붙은 하위 절**이고 본문은 그 번호로 인용한다. 실측(SHN34
ESF-CCS RVVR·SRS, SKN56 CPS RVVR) 구조를 그대로 본뜬 문서로 검사한다.
"""
from modules.agent_format import RefListChecker
from modules.doc_parser import RawDoc, normalize
from modules.shared import Severity


def _doc(text):
    return normalize(RawDoc(source_path="d.md", text=text))


# 실측 구조: 3.0 References > 3.1 Regulations > 3.1.1 <문서>
_DOC = """# 3.0 References

# 3.1 Regulations

## 3.1.1 NUREG-0800, BTP 7-14, Rev.06

## 3.1.2 RG 1.168, Rev.02

# 3.2 Codes and Standards

## 3.2.1 IEEE Std. 610.12-1990

# 4.0 본문

용어 정의는 IEEE 표준을 따른다 (reference 3.2.1).
규제 요건은 reference 3.1.1 과 reference 3.1.2 를 적용한다.
"""


def test_모두_인용되면_지적_없음():
    assert RefListChecker().check(_doc(_DOC)) == []


def test_인용되지_않은_참조문서를_짚는다():
    """목록에만 있고 본문이 안 쓰는 문서는 지운다(EV2 25-3)."""
    got = RefListChecker().check(_doc(_DOC.replace("reference 3.1.2 를 적용한다", "적용한다")))
    assert [f.severity for f in got] == [Severity.MINOR]
    assert "3.1.2" in got[0].message
    assert [e.quote for e in got[0].evidence] == ["3.1.2"]


def test_목록에_없는_문서를_인용하면_짚는다():
    """본문이 목록에 없는 것을 참조한다(EV2 25-2). 이쪽이 더 무겁다."""
    got = RefListChecker().check(_doc(_DOC.replace("(reference 3.2.1)", "(reference 9.9.9)")))
    major = [f for f in got if f.severity is Severity.MAJOR]
    assert len(major) == 1 and "9.9.9" in major[0].message


def test_묶음_절은_참조문서가_아니다():
    """`3.0 References` · `3.1 Regulations` 는 묶음이지 문서가 아니다.

    세면 아무도 인용하지 않으므로 늘 "미인용" 으로 떠, 실측에서 지적 17건 중
    네 건이 이 묶음 절이었다.
    """
    got = RefListChecker().check(_doc(_DOC))
    assert got == [], [f.message for f in got]


def test_본문_상호참조는_인용이_아니다():
    """문서의 다른 절을 가리키는 참조를 "목록에 없는 문서" 로 세면 안 된다.

    실측(SHN34 RVVR)에서 `1.4.3.1` 을 가리키는 상호참조 네 건이 그렇게 떴다.
    """
    doc = _doc(_DOC + "\n\n# 5.0 다른 절\n\n자세한 것은 reference 4.0 을 본다.\n")
    assert [f for f in RefListChecker().check(doc)
            if f.severity is Severity.MAJOR] == []


def test_참조_절이_없으면_미검토다():
    got = RefListChecker().check(_doc("# 1.0 개요\n\n본문."))
    assert [f.severity for f in got] == [Severity.INFO] and got[0].unreviewed


def test_목록을_거의_못_읽었으면_지적하지_않는다():
    """잴 자를 못 읽고 재면 멀쩡한 인용이 전부 "목록에 없는 문서" 가 된다.

    실측: 책갈피가 얕은 PDF(SKN56 CDMS Rev05)가 항목을 한 건도 못 냈다.
    """
    doc = _doc("# 3.0 References\n\n## 3.1.1 하나뿐\n\n"
               "# 4.0 본문\n\nreference 3.2.1 과 reference 3.3.1 을 본다.\n")
    got = RefListChecker().check(doc)
    assert [f.severity for f in got] == [Severity.INFO] and got[0].unreviewed


def test_절_제목은_기준이_덮을_수_있다():
    doc = _doc("# 2.0 참고자료\n\n## 2.1.1 문서 하나\n\n## 2.1.2 문서 둘\n\n"
               "# 3.0 본문\n\n참조 2.1.1 을 본다.\n")
    got = RefListChecker(sections=("참고자료",)).check(doc)
    assert [f.severity for f in got] == [Severity.MINOR] and "2.1.2" in got[0].message


def test_Reference_Manual_같은_제목에_안_걸린다():
    """문서 제목에 Reference 가 들어간다 — 실측: 'RTP Communications Protocol
    Reference Manual'. 그걸 참조 절로 보면 엉뚱한 절을 목록으로 읽는다."""
    doc = _doc("# 1.0 RTP Protocol Reference Manual\n\n## 1.1.1 내용\n\n## 1.1.2 내용\n")
    got = RefListChecker().check(doc)
    assert got[0].unreviewed and "참조문서 절을 찾지 못해" in got[0].message

"""제출 파일명 검사.

규칙은 팀이 정한다(EV3 13: `계통문서번호_버전_문서명`). 코드는 형식을 모른다 —
기준이 안 적어주면 검사하지 않고 그 사실을 남긴다.
"""
from modules.agent_format import FilenameChecker
from modules.shared import Document, Severity

_EV3 = r"[^_]+_Rev\.\d+_.+"


def _doc(name):
    return Document(source_path=f"/up/{name}", doc_type="generic")


def test_규칙에_맞으면_지적_없음():
    ck = FilenameChecker(pattern=_EV3)
    assert ck.check(_doc("Z11008-940VD-011C_Rev.08_RVVR for ESF-CCS for SKN56.docx")) == []


def test_확장자는_빼고_잰다():
    """규칙을 적는 사람은 이름을 말하지 확장자를 말하지 않는다(EV3 예시에도 없다)."""
    ck = FilenameChecker(pattern=_EV3)
    assert ck.check(_doc("A-1_Rev.02_설계서.pdf")) == []
    assert ck.check(_doc("A-1_Rev.02_설계서.hwp")) == []


def test_형식이_다르면_지적한다():
    ck = FilenameChecker(pattern=_EV3, example="A_Rev.08_문서명")
    got = ck.check(_doc("RVVR 최종본.docx"))
    assert [f.severity for f in got] == [Severity.MAJOR]
    assert "RVVR 최종본" in got[0].message and "A_Rev.08_문서명" in got[0].message


def test_규칙이_없으면_검사_못_했다고_말한다():
    """조용한 0건은 "파일명을 봤더니 이상 없음"으로 읽힌다.

    EV2 19 가 이 경우다 — 본문이 "내부 규칙에 맞게"까지만 말하고 그 규칙이 없다.
    """
    got = FilenameChecker().check(_doc("아무거나.docx"))
    assert [f.severity for f in got] == [Severity.INFO]
    assert got[0].unreviewed


def test_깨진_정규식은_지적이_아니라_미검토다():
    """지적으로 내면 멀쩡한 파일명이 전부 틀린 것으로 뜬다."""
    got = FilenameChecker(pattern="[").check(_doc("A_Rev.01_문서.docx"))
    assert [f.severity for f in got] == [Severity.INFO]
    assert got[0].unreviewed


def test_금지_표시를_짚는다():
    """EV2 19-4: 임시 파일명·개인 작업 표시·중복본 표시."""
    ck = FilenameChecker(forbidden=("사본", "최종"))
    got = ck.check(_doc("설계서 사본.docx"))
    assert [f.severity for f in got] == [Severity.MINOR]
    assert "사본" in got[0].message


def test_금지_표시는_대소문자를_안_가린다():
    got = FilenameChecker(forbidden=("copy",)).check(_doc("SRS - Copy.docx"))
    assert len(got) == 1

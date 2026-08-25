"""표 안 글꼴 크기 검사.

문서 간 md: "테스트케이스 글꼴 크기가 8 pt 또는 9 pt". 워드는 대부분의 글자에
크기를 안 적으므로(실측: 런 405개 중 23개), 여기서 보는 것은 **스타일을 벗어나
직접 박아둔 크기**다. 실측에서 그게 곧 테스트케이스였다.
"""
from modules.agent_format import FontSizeChecker
from modules.shared import Document, Severity


def _doc(*tables):
    return Document(source_path="t.docx", doc_type=None,
                    meta={"tables": [{"columns": ["시험 항목"], "fontSizes": t}
                                     for t in tables]})


def test_규정_안이면_조용하다():
    assert FontSizeChecker(allowed=(8, 9)).check(_doc({8.0: 139})) == []


def test_규정_밖이면_지적한다():
    """심각도는 **확실성** 축이다 — 규칙이 잡았으면 MAJOR.

    예전엔 여기만 MINOR 였다. 규칙 체커가 MINOR 를 내는 유일한 자리였고, 그건
    "글꼴 크기는 덜 중대하다"는 판단이었다 — 중대성은 팀이 정할 값이지 이 코드가
    정할 값이 아니다(shared/models.py Severity).
    """
    got = FontSizeChecker(allowed=(8, 9)).check(_doc({11.0: 40}))
    assert len(got) == 1
    assert got[0].severity is Severity.MAJOR
    assert "11pt" in got[0].message and "8pt, 9pt" in got[0].message


def test_섞여_있으면_어긋난_것만_짚는다():
    got = FontSizeChecker(allowed=(8, 9)).check(_doc({8.0: 139, 11.0: 4}))
    assert [f.message.count("11pt") for f in got] == [1]


def test_직접_박힌_것이_없으면_미검토다():
    """"이상 없음"이 아니라 "못 봤음"이다 — 문단 스타일이 정하는 크기는 아직 못 읽는다."""
    got = FontSizeChecker(allowed=(8, 9)).check(_doc())
    assert len(got) == 1 and got[0].unreviewed
    assert got[0].severity is Severity.INFO


def test_허용_크기가_없으면_미검토다():
    """한때 조용한 0건이었다(2026-08-20 바꿈).

    폴더 검토(case.py)는 `if sizes:` 로 막아 빈 검사기를 안 만들지만, 단일 검토는
    기준이 `check: fontsize` 라고 적으면 만든다 — 그때 `font_sizes` 를 빠뜨리면
    화면이 "글꼴 이상 없음"으로 읽혔다. 안 잰 것을 잰 것처럼 보이게 두지 않는다.
    """
    got = FontSizeChecker(allowed=()).check(_doc({11.0: 40}))
    assert len(got) == 1 and got[0].unreviewed
    assert "수행하지 않았습니다" in got[0].message


def test_표_정보가_없으면_못_봤다고_말한다():
    """표 목록이 없으면 터지지 말고 "못 봤음"이라고 해야 한다.

    파서마다 meta 에 다른 것을 넣고 있었다. PDF 는 표 **개수**(정수), Word·HWP 는
    표마다 열·글꼴을 담은 **목록**. 이 검사기는 목록을 가정하고 훑어서, 팀 기준이
    표 글꼴 규격을 정한 채 PDF 를 올리면 `'int' object is not iterable` 로 죽었다.
    지금은 두 파서가 같은 모양을 남긴다(pdf_tables.table_meta).
    """
    from modules.shared import Anchor, Document, Section
    sec = Section(id="1", title="t", level=1, text="x",
                  anchor=Anchor(page=1, section="1"))
    doc = Document(source_path="a.pdf", doc_type="generic", sections=[sec])
    doc.meta = {}                       # 표가 없는 문서
    found = FontSizeChecker(allowed=(9.0,)).check(doc)
    assert len(found) == 1 and found[0].unreviewed, "못 본 것을 못 봤다고 해야 한다"

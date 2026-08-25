"""격자 레이아웃이 찢어놓은 절 제목 복구(§4-0 이슈㉒, pdf_backend._rescue_split_headings).

실측(SKN56_CDMS_RVVR_Rev05.pdf): 절 제목이 `|1.0|Purpose|||` 표 머리행으로,
또는 `**3.0**` 문단 + `# References` 로 찢겨 절 트리에 안 들어갔고, 필수 절
검사가 멀쩡한 문서에 "필수 항목 누락" MAJOR 를 냈다.
"""
from modules.doc_parser.model import HEADING, PARAGRAPH, TABLE, Block, TableData
from modules.doc_parser.pdf_backend import _rescue_split_headings


def test_표_머리행의_번호_제목이_절로_복구된다():
    t = Block(TABLE, 5, table=TableData(rows=2, cols=4,
              cells=[["1.0", "Purpose", "", ""], ["", "본문 문장.", "", ""]]))
    out = _rescue_split_headings([t])
    assert out[0].type == HEADING
    assert out[0].text == "1.0 Purpose"
    assert out[0].level == 1
    assert out[1] is t, "표 자체는 그대로 둔다 — 본문이 그 셀에 실려 있다"


def test_데이터_표는_건드리지_않는다():
    # 머리행이 [번호, 제목] 꼴이 아니면(열 이름 등) 복구 대상이 아니다
    t = Block(TABLE, 9, table=TableData(rows=2, cols=3,
              cells=[["개정번호", "일시", "사유"], ["00", "2026-01-01", "최초"]]))
    assert _rescue_split_headings([t]) == [t]


def test_번호_문단과_번호없는_제목이_합쳐진다():
    num = Block(PARAGRAPH, 7, text="**3.0**")
    h = Block(HEADING, 7, text="References", level=1)
    out = _rescue_split_headings([num, h])
    assert [b.text for b in out if b.type == HEADING] == ["3.0 References"]
    assert not [b for b in out if b.type == PARAGRAPH], "번호 문단은 제목에 흡수된다"


def test_짝이_애매하면_추측하지_않는다():
    blocks = [Block(PARAGRAPH, 7, text="3.0"), Block(PARAGRAPH, 7, text="5.0"),
              Block(HEADING, 7, text="References", level=1)]
    out = _rescue_split_headings(blocks)
    assert [b.text for b in out if b.type == HEADING] == ["References"]


def test_쪽번호_같은_정수_단독은_번호로_안_본다():
    blocks = [Block(PARAGRAPH, 7, text="21"),
              Block(HEADING, 7, text="References", level=1)]
    out = _rescue_split_headings(blocks)
    assert [b.text for b in out if b.type == HEADING] == ["References"]
    assert [b.text for b in out if b.type == PARAGRAPH] == ["21"]

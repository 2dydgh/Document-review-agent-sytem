"""쪽을 세로 밴드로 쪼개는지 지키는 테스트.

표와 본문이 한 쪽에 섞여 있다. 표는 행 단위로, 본문은 좌표 군집으로 처리해야
하므로 먼저 세로로 갈라야 한다. 갈린 조각을 top 순으로 이어붙이면 원래 읽기
순서가 유지된다.
"""
from modules.doc_parser.ingestion.pdf_layout import split_bands


def test_page_without_tables_is_one_text_band():
    bands = split_bands(842.0, [])
    assert bands == [{"kind": "text", "top": 0.0, "bottom": 842.0, "index": None}]


def test_table_in_the_middle_splits_into_three_bands():
    bands = split_bands(842.0, [(200.0, 500.0)])
    assert [(b["kind"], b["top"], b["bottom"]) for b in bands] == [
        ("text", 0.0, 200.0),
        ("table", 200.0, 500.0),
        ("text", 500.0, 842.0),
    ]
    assert bands[1]["index"] == 0


def test_two_tables_keep_their_indexes():
    bands = split_bands(842.0, [(100.0, 200.0), (400.0, 500.0)])
    tables = [b for b in bands if b["kind"] == "table"]
    assert [b["index"] for b in tables] == [0, 1]
    assert [b["kind"] for b in bands] == ["text", "table", "text", "table", "text"]


def test_table_touching_the_top_edge_makes_no_empty_band():
    # 본문 108쪽은 표가 쪽 거의 전체(71~758)를 차지한다.
    bands = split_bands(842.0, [(0.0, 758.0)])
    assert [b["kind"] for b in bands] == ["table", "text"]


def test_table_filling_the_whole_page_gives_one_band():
    bands = split_bands(842.0, [(0.0, 842.0)])
    assert [b["kind"] for b in bands] == ["table"]


def test_slivers_below_min_height_are_dropped():
    """0.5pt 짜리 틈은 밴드가 아니다 — 크롭하면 빈 문자열만 나온다."""
    bands = split_bands(842.0, [(0.5, 841.5)])
    assert [b["kind"] for b in bands] == ["table"]


def test_unsorted_spans_are_ordered_but_keep_original_indexes():
    bands = split_bands(842.0, [(400.0, 500.0), (100.0, 200.0)])
    tables = [b for b in bands if b["kind"] == "table"]
    assert [(b["top"], b["index"]) for b in tables] == [(100.0, 1), (400.0, 0)]

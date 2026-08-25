"""글자를 좌표로 묶어 줄로 되돌리는지 지키는 테스트.

PDF 도면은 작은 텍스트 상자 수십 개가 좌표에 흩어져 있다. 줄 단위로 읽으면
가로로 나란한 라벨들이 한 줄에 섞여 'A D M c i t a v...' 가 된다. 좌표로 묶으면
'Diverse', 'Actuation' 으로 되돌아온다.

줄글에 무손실인 것이 이 모듈의 핵심 계약이다 — 그래서 도면인지 판정하지 않고
늘 쓴다. 무손실이 깨지면 줄글 문서가 조용히 망가지므로 테스트로 못 박는다.
"""
from modules.doc_parser.ingestion.pdf_labels import cluster_chars, render_lines


def _ch(text, x0, top, w=5.0, h=10.0):
    """글자 하나. pdfplumber page.chars 와 같은 모양."""
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top, "bottom": top + h}


def _word(text, x0, top, w=5.0):
    return [_ch(c, x0 + i * w, top, w) for i, c in enumerate(text)]


def test_adjacent_chars_become_one_label():
    boxes = cluster_chars(_word("ITP", 100.0, 50.0))
    assert [b["text"] for b in boxes] == ["ITP"]


def test_far_apart_words_on_same_line_stay_separate():
    chars = _word("ITP", 100.0, 50.0) + _word("MTP", 300.0, 50.0)
    boxes = cluster_chars(chars)
    assert sorted(b["text"] for b in boxes) == ["ITP", "MTP"]


def test_stacked_words_at_same_left_edge_join_vertically():
    # 도면 상자 안에서 두 줄로 쓰인 라벨: "Diverse" 아래 "Actuation"
    chars = _word("Diverse", 100.0, 50.0) + _word("Actuation", 100.0, 61.0)
    boxes = cluster_chars(chars)
    assert [b["text"] for b in boxes] == ["Diverse Actuation"]


def test_interleaved_columns_are_untangled():
    # 세로로 쌓인 라벨 둘이 가로로 나란히 있는 실제 도면 배치.
    # 줄 단위로 읽으면 'D A' / 'i c' / ... 로 섞인다.
    left = _word("DPS", 100.0, 50.0)
    right = _word("PCCS", 300.0, 50.0)
    left2 = _word("GC", 100.0, 61.0)
    right2 = _word("MTP", 300.0, 61.0)
    boxes = cluster_chars(left + right + left2 + right2)
    assert sorted(b["text"] for b in boxes) == ["DPS GC", "PCCS MTP"]


def test_render_groups_boxes_on_the_same_row_into_one_line():
    chars = _word("AAA", 100.0, 50.0) + _word("BBB", 300.0, 50.0) + _word("CCC", 100.0, 200.0)
    lines = render_lines(cluster_chars(chars))
    assert lines == ["AAA   BBB", "CCC"]


def test_no_character_is_dropped():
    """무손실 계약. 한 글자짜리도 버리지 않는다 — 도면의 채널 라벨('G','2','C')이다."""
    chars = _word("GC", 100.0, 50.0) + [_ch("2", 300.0, 50.0)] + _word("MTP", 500.0, 50.0)
    got = "".join(render_lines(cluster_chars(chars))).replace(" ", "")
    assert sorted(got) == sorted("GC2MTP")


def test_hyphen_ending_box_joins_without_a_space():
    """세로로 쌓인 조각이 하이픈으로 끝나면 붙여야 한다 — 끊긴 ID 다.

    'FR-' 아래 'MTP_02' 는 한 낱말이다. 공백을 넣으면 'FR- MTP_02' 가 되어
    ID 추출이 실패하고, 하위문서에 실재하는 요건이 '누락'으로 보고된다.
    """
    chars = _word("FR-", 100.0, 50.0) + _word("MTP_02", 100.0, 61.0)
    boxes = cluster_chars(chars)
    assert [b["text"] for b in boxes] == ["FR-MTP_02"]


def test_empty_input_gives_no_lines():
    assert cluster_chars([]) == []
    assert render_lines([]) == []

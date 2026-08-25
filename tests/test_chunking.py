from modules.shared import Anchor, Document, Section
from modules.doc_parser import chunk


def _doc(text):
    s = Section(id="1", title="t", level=1, text=text,
                anchor=Anchor(page=None, section="1"), children=[])
    return Document(source_path="d.md", doc_type=None, sections=[s])


def test_short_section_single_chunk():
    chunks = chunk(_doc("짧은 본문"), max_chars=100)
    assert len(chunks) == 1
    assert chunks[0].section_id == "1"
    assert chunks[0].id == "1#0"


def test_long_section_split_by_max_chars():
    chunks = chunk(_doc("가" * 250), max_chars=100)
    assert len(chunks) == 3
    assert all(len(c.text) <= 100 for c in chunks)


def test_empty_section_skipped():
    assert chunk(_doc("   "), max_chars=100) == []

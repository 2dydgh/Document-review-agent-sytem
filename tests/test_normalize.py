from modules.doc_parser import RawDoc
from modules.doc_parser import normalize


def test_headings_build_section_tree():
    raw = RawDoc(source_path="d.md",
                 text="# 개요\n소개\n## 배경\n상세\n# 요구사항\n항목",
                 meta={})
    doc = normalize(raw)
    top = [s for s in doc.sections]
    assert [s.title for s in top] == ["개요", "요구사항"]
    assert top[0].children[0].title == "배경"
    assert top[0].anchor.section == "1"
    assert top[0].children[0].anchor.section == "1.1"


def test_preamble_without_heading_goes_to_root_body():
    raw = RawDoc(source_path="d.md", text="머리말 본문\n# 개요\n내용", meta={})
    doc = normalize(raw)
    assert doc.sections[0].title == "(본문)"
    assert "머리말" in doc.sections[0].text

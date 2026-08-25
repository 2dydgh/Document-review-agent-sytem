"""근거 재확인 검색 도구 — 파일 접근도 부작용도 없다."""
import pytest

from modules.shared import Anchor, DocTools, Document, Section


@pytest.fixture
def doc():
    sections = [
        Section(id="s0", title="개요", level=1, text="이 문서는 예측 기능을 다룬다.",
                anchor=Anchor(page=None, section="개요")),
        Section(id="s1", title="컴포넌트 목록", level=1,
                text="| 모듈 | 설명 |\n| 예측 | 위험도를 산정한다 |\n산문 한 줄.",
                anchor=Anchor(page=None, section="컴포넌트 목록")),
        Section(id="s2", title="부록", level=1, text="예측 기능 재언급.",
                anchor=Anchor(page=None, section="부록")),
    ]
    return Document(source_path="x", doc_type="generic", sections=sections)


def test_find_term_lists_every_line_with_location(doc):
    out = DocTools(doc).run("find_term", {"term": "예측"})
    assert "개요" in out and "컴포넌트 목록" in out and "부록" in out


def test_find_term_reports_absence(doc):
    out = DocTools(doc).run("find_term", {"term": "존재하지않는말"})
    assert "없" in out


def test_unknown_tool_explains(doc):
    out = DocTools(doc).run("semantic_search", {"query": "x"})
    assert "알 수 없는 도구" in out


def test_missing_arg_explains(doc):
    out = DocTools(doc).run("find_term", {})
    assert "term" in out


def test_specs_describe_every_tool(doc):
    names = {s["name"] for s in DocTools.SPECS}
    assert names == {"find_term"}

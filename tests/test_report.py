import json as _json

from modules.report import collect, render_json, render_markdown
from modules.shared import Anchor, Finding, Severity


def _f(sev, msg, sec="1"):
    return Finding(checker="c", severity=sev, message=msg,
                   anchor=Anchor(page=None, section=sec))


def test_collect_dedupes_identical():
    out = collect([_f(Severity.MINOR, "a"), _f(Severity.MINOR, "a")])
    assert len(out) == 1


def test_collect_sorts_by_severity_desc():
    out = collect([_f(Severity.INFO, "i"), _f(Severity.MINOR, "n"),
                   _f(Severity.MAJOR, "m")])
    assert [f.severity for f in out] == [
        Severity.MAJOR, Severity.MINOR, Severity.INFO]


def test_render_markdown_contains_message_and_source():
    md = render_markdown([_f(Severity.MAJOR, "필수 항목 누락: 요구사항")], "d.md")
    assert "d.md" in md
    assert "필수 항목 누락: 요구사항" in md
    assert md.lstrip().startswith("#")


def test_render_json_structure_and_hangul():
    findings = [_f(Severity.MAJOR, "필수 항목 누락: 요구사항")]
    payload = _json.loads(render_json(findings, "data/sample.md"))
    assert payload["source_path"] == "data/sample.md"
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["by_severity"]["major"] == 1
    item = payload["findings"][0]
    assert item["checker"] == "c"
    assert item["severity"] == "major"
    assert item["message"] == "필수 항목 누락: 요구사항"
    assert item["anchor"] == {"page": None, "section": "1"}
    # 한글이 유니코드 이스케이프되지 않고 그대로 출력되는지
    assert "요구사항" in render_json(findings, "data/sample.md")


def test_render_json_empty():
    payload = _json.loads(render_json([], "d.md"))
    assert payload["summary"]["total"] == 0
    assert payload["findings"] == []


def test_render_json_includes_document_when_set():
    f = Finding(checker="traceability", severity=Severity.MAJOR,
                message="하위문서에 누락된 ID: SR-001",
                anchor=Anchor(page=None, section="1"), document="parent")
    payload = _json.loads(render_json([f], "a.md ↔ b.md"))
    assert payload["findings"][0]["document"] == "parent"


def test_render_json_omits_document_when_none():
    payload = _json.loads(render_json([_f(Severity.MAJOR, "x")], "d.md"))
    assert "document" not in payload["findings"][0]


def test_collect_keeps_findings_differing_only_by_document():
    a = Finding(checker="t", severity=Severity.MAJOR, message="m",
                anchor=Anchor(None, "1"), document="parent")
    b = Finding(checker="t", severity=Severity.MAJOR, message="m",
                anchor=Anchor(None, "1"), document="child")
    assert len(collect([a, b])) == 2


def test_finding_to_dict_includes_evidence():
    """근거가 있으면 evidence 키가 JSON에 포함된다."""
    from modules.shared import Evidence
    f = Finding(
        checker="consistency", severity=Severity.MAJOR,
        message="검사항목과 설계가 일치하지 않음",
        anchor=Anchor(page=None, section="3.1"),
        evidence=[
            Evidence(anchor=Anchor(page=None, section="2.1"),
                    quote="요구사항 SR-001"),
        ]
    )
    payload = _json.loads(render_json([f], "data/test.md"))
    item = payload["findings"][0]
    assert "evidence" in item
    assert len(item["evidence"]) == 1
    assert item["evidence"][0]["quote"] == "요구사항 SR-001"
    assert item["evidence"][0]["section"] == "2.1"


def test_finding_to_dict_omits_evidence_when_empty():
    """근거가 없으면 evidence 키가 없다."""
    f = Finding(checker="content", severity=Severity.MINOR,
                message="오타", anchor=Anchor(page=None, section="1"))
    payload = _json.loads(render_json([f], "data/test.md"))
    item = payload["findings"][0]
    assert "evidence" not in item

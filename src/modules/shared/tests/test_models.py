from modules.shared import Anchor, Document, Evidence, Finding, Section, Severity


def _leaf(title, text, sid):
    return Section(id=sid, title=title, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def test_iter_sections_depth_first():
    child = _leaf("child", "c", "1.1")
    parent = Section(id="1", title="parent", level=1, text="p",
                     anchor=Anchor(page=None, section="1"), children=[child])
    doc = Document(source_path="x.md", doc_type=None, sections=[parent])
    titles = [s.title for s in doc.iter_sections()]
    assert titles == ["parent", "child"]


def test_severity_ordering_values():
    """중대성 3단. CRITICAL 은 없다 — 아무도 안 내는데 화면에는 늘 "0" 이 떠서
    "심각한 문제를 찾아봤고 없었다"는 거짓말이 됐다(models.py Severity 주석)."""
    assert [s.value for s in Severity] == ["info", "minor", "major"]
    assert not hasattr(Severity, "CRITICAL")


def test_finding_defaults():
    f = Finding(checker="c", severity=Severity.MINOR, message="m",
                anchor=Anchor(page=1, section="2"))
    assert f.suggestion is None

def test_finding_evidence_defaults_to_empty():
    """기존 코드가 evidence 없이 Finding을 만들어도 깨지지 않는다."""
    f = Finding(checker="x", severity=Severity.MINOR, message="m",
                anchor=Anchor(page=None, section="3.1"))
    assert f.evidence == []


def test_finding_carries_multiple_evidence():
    a = Evidence(anchor=Anchor(page=None, section="3.2"), quote="5초 이내")
    b = Evidence(anchor=Anchor(page=None, section="5.1"), quote="3초 이내")
    f = Finding(checker="consistency", severity=Severity.MINOR, message="불일치",
                anchor=a.anchor, evidence=[a, b])
    assert [e.quote for e in f.evidence] == ["5초 이내", "3초 이내"]
    assert f.anchor.section == "3.2"

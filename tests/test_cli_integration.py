import json as _json

from app.cli import main

#: 필수 장절 검사를 실제로 돌리려면 **팀 기준**을 골라야 한다.
#:
#: 예전 이 파일은 `settings.toml` 의 `[review] checklist` 로 required_sections 를
#: 줬다. 그때는 공통 기준이 검사기를 켜 주고 있어서 그것만으로 돌았다. 공통을 다시
#: 짜면서(2026-08-20) 필수 장절을 뺐다 — 장절 목록이 팀마다 달라, 값 없는 팀에서는
#: "검사하지 않았습니다"만 뜨는 공허한 공통 기준이었다. 지금은 값을 가진 팀 기준이
#: 스스로 켠다.
#:
#: 설정 파일로 주던 방식은 presets/README.md 가 이미 은퇴시킨 것이다
#: ("checklists/ — 지웠다. 지금은 매개변수를 기준이 params 로 정한다").
#:
#: EV2 기준의 필수 장절: 1.0 Purpose · 2.0 Scope · 3.0 References ·
#: 4.0 Definitions and Abbreviations (EV2.yaml No.40, 팀이 xlsx 에 적어준 값).
_TEAM = "EV2"

#: 필수 절 검사는 **번호가 붙은 절**을 찾는다. 번호 없는 문서에서는 검사 자체를
#: 걸지 않고 그 사실을 알린다 — 그래서 시험 문서도 번호를 달아야 한다.
_DOC = "# 1.0 Purpose\n이 문서의 목적.\n\n# 3.0 References\n참조 문서.\n"

#: 위 문서에 없는 필수 절. 지적 문구에 그대로 들어간다.
_MISSING = "2.0 Scope"


def _write_settings(tmp_path, required_yaml=""):
    """설정 파일. 검토 기준은 여기가 아니라 팀 yaml 이 준다."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
        encoding="utf-8")
    return settings


def test_review_command_prints_report(tmp_path, capsys):
    """팀 기준의 필수 장절이 실제로 돌아 지적이 리포트에 찍힌다."""
    doc = tmp_path / "d.md"
    doc.write_text(_DOC, encoding="utf-8")
    settings = _write_settings(tmp_path)

    rc = main(["review", str(doc), "--settings", str(settings), "--team", _TEAM])
    out = capsys.readouterr().out
    assert rc == 0
    assert "문서 검토 결과" in out
    assert _MISSING in out, "팀 기준의 필수 장절 지적이 안 나왔다"


def test_review_command_writes_out_file(tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("# 개요\n내용", encoding="utf-8")
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        "doc_type: generic\nrequired_sections: []\n", encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    out = tmp_path / "report.md"

    rc = main(["review", str(doc), "--settings", str(settings), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert "문서 검토 결과" in out.read_text(encoding="utf-8")


def test_review_format_json_outputs_valid_json(tmp_path, capsys):
    doc = tmp_path / "d.md"
    doc.write_text(_DOC, encoding="utf-8")
    settings = _write_settings(tmp_path)
    rc = main(["review", str(doc), "--settings", str(settings),
               "--team", _TEAM, "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    assert payload["source_path"] == str(doc)
    assert any(_MISSING in f["message"] for f in payload["findings"])


def test_review_emit_ui_writes_loadable_js(tmp_path, capsys):
    doc = tmp_path / "d.md"
    doc.write_text(_DOC, encoding="utf-8")
    settings = _write_settings(tmp_path)
    ui = tmp_path / "docreview-review-result.js"
    rc = main(["review", str(doc), "--settings", str(settings),
               "--team", _TEAM, "--emit-ui", str(ui)])
    assert rc == 0
    js = ui.read_text(encoding="utf-8")
    assert "window.DOCREVIEW.findings = r.findings;" in js
    assert _MISSING in js
    # compare 생성물과 키가 겹치지 않아야 공존할 수 있다
    assert "window.DOCREVIEW.compare" not in js
    assert "문서 검토 결과" in capsys.readouterr().out


def test_review_unsupported_format_is_friendly(tmp_path, capsys):
    bad = tmp_path / "d.xyz"
    bad.write_text("x", encoding="utf-8")
    settings = _write_settings(tmp_path)
    rc = main(["review", str(bad), "--settings", str(settings)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Traceback" not in captured.err
    assert captured.err.strip() != ""


def _write_trace_settings(tmp_path):
    (tmp_path / "checklists").mkdir(exist_ok=True)
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    return settings


def test_compare_command_json_reports_missing_and_orphan(tmp_path, capsys):
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001\nSR-002", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-002\nSR-003", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings), "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    docs = {f["document"] for f in payload["findings"]}
    assert docs == {"parent", "child"}
    assert any("SR-001" in f["message"] for f in payload["findings"])
    assert any("SR-003" in f["message"] for f in payload["findings"])


def test_compare_command_markdown_shows_full_rtm(tmp_path, capsys):
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001\nSR-002", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-002\nSR-003", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "추적성 매트릭스" in out
    # 연결된 SR-002도 표에 나온다 (예외만이 아니라 전체 대조표)
    assert "SR-002" in out and "연결됨" in out
    assert "SR-001" in out and "SR-003" in out


def test_compare_command_json_includes_rtm(tmp_path):
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001\nSR-002", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-002\nSR-003", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    out = tmp_path / "rtm.json"
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings), "--format", "json", "--out", str(out)])
    assert rc == 0
    payload = _json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 3
    assert {r["status"] for r in payload["rtm"]} == {"linked", "missing", "orphan"}


def test_compare_emit_ui_writes_loadable_js(tmp_path, capsys):
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001\nSR-002", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-002\nSR-003", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    ui = tmp_path / "docreview-result.js"
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings), "--emit-ui", str(ui)])
    assert rc == 0
    js = ui.read_text(encoding="utf-8")
    assert "window.DOCREVIEW.compare = {" in js
    assert '"requirements": 2' in js and '"matched": 1' in js
    # 마크다운 리포트는 --emit-ui와 무관하게 그대로 나온다
    assert "추적성 매트릭스" in capsys.readouterr().out


def test_compare_without_emit_ui_writes_nothing_extra(tmp_path):
    parent = tmp_path / "srs.md"
    parent.write_text("SR-001", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("SR-001", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings)])
    assert rc == 0
    assert not (tmp_path / "docreview-result.js").exists()


def test_compare_unsupported_format_is_friendly(tmp_path, capsys):
    parent = tmp_path / "srs.md"
    parent.write_text("SR-001", encoding="utf-8")
    child = tmp_path / "sdd.xyz"
    child.write_text("SR-001", encoding="utf-8")
    settings = _write_trace_settings(tmp_path)
    rc = main(["compare", "--parent", str(parent), "--child", str(child),
               "--settings", str(settings)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Traceback" not in captured.err

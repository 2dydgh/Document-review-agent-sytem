import json
import shutil
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import MAX_UPLOAD_BYTES, create_app  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    p = tmp_path / "settings.toml"
    p.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
                 '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    return p


@pytest.fixture
def history_dir(tmp_path):
    # 테스트가 저장소의 진짜 .docreview/history에 쓰면 안 된다.
    return tmp_path / "history"


@pytest.fixture
def client(settings, tmp_path, history_dir):
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=history_dir))


def _files(parent=b"# SRS\nSR-001\nSR-002", child=b"# SDD\nSR-002\nSR-003",
           pname="srs.md", cname="sdd.md"):
    return {"parent": (pname, parent, "text/markdown"),
            "child": (cname, child, "text/markdown")}


def _sse(response):
    """SSE 응답 본문 → 이벤트 dict 목록."""
    events = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_compare_returns_ui_payload(client):
    r = client.post("/api/compare", files=_files())
    assert r.status_code == 200
    body = r.json()
    assert body["stats"] == {"requirements": 2, "matched": 1, "missing": 1,
                             "mismatch": 0, "extra": 1, "out_of_scope": 0,
                             "rolled_up": 0}
    assert {f["type"] for f in body["findings"]} == {"missing", "extra"}
    assert any("SR-001" in f["message"] for f in body["findings"])


def test_compare_reports_original_filenames_not_temp_paths(client):
    body = client.post("/api/compare", files=_files(pname="요구사항.md")).json()
    assert body["docA"]["name"] == "요구사항.md"
    assert body["docB"]["name"] == "sdd.md"


def test_identical_filenames_do_not_collide(client):
    """상위·하위가 같은 이름이면 한쪽이 덮여 'orphan 0'이 나올 수 있다."""
    body = client.post("/api/compare", files=_files(pname="doc.md", cname="doc.md")).json()
    assert body["stats"]["missing"] == 1
    assert body["stats"]["extra"] == 1


def test_unsupported_format_is_400_not_500(client):
    r = client.post("/api/compare", files=_files(cname="sdd.xyz"))
    assert r.status_code == 400
    assert "검토할 수 없습니다" in r.json()["detail"]


def test_traversal_filename_cannot_escape_temp_dir(client):
    # "../../../tmp/evil.md" → basename만 남아야 한다. 500이면 경로가 새는 것.
    r = client.post("/api/compare", files=_files(pname="../../../tmp/evil.md"))
    assert r.status_code == 200
    assert r.json()["docA"]["name"] == "evil.md"


def test_oversized_upload_is_rejected(client):
    big = b"SR-001\n" + b"x" * (MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/compare", files=_files(parent=big))
    assert r.status_code == 413
    assert "너무 큽니다" in r.json()["detail"]


def test_empty_upload_is_rejected(client):
    r = client.post("/api/compare", files=_files(parent=b""))
    assert r.status_code == 400
    assert "비어 있습니다" in r.json()["detail"]


def test_missing_field_is_422(client):
    r = client.post("/api/compare", files={"parent": ("a.md", b"SR-001")})
    assert r.status_code == 422


def test_compare_runs_review_off_the_event_loop(client, monkeypatch):
    """LLM이 붙으면 비교는 수 분 걸린다 — 이벤트 루프 위에서 돌면 그동안
    서버 전체(다른 사용자 요청 포함)가 멈춘다. review_documents 는 반드시
    루프 밖(워커 스레드)에서 돌아야 한다."""
    import asyncio

    from app import server as server_mod
    from app.orchestrator import ReviewResult

    seen = {}

    def stub(parent_path, child_path, cfg):
        try:
            asyncio.get_running_loop()
            seen["in_loop"] = True
        except RuntimeError:
            seen["in_loop"] = False
        return ReviewResult(source_path=f"{parent_path} ↔ {child_path}")

    monkeypatch.setattr(server_mod, "review_documents", stub)
    r = client.post("/api/compare", files=_files())
    assert r.status_code == 200
    assert seen["in_loop"] is False


# /api/review는 SSE로 흐른다(아래 "/api/review SSE 스트림" 절 참고). 여기 있는
# 테스트는 done 이벤트의 payload를 봐서, 그 모양이 예전 JSON 응답과 같은지 본다.

def test_review_returns_doc_findings_stages(client):
    r = client.post("/api/review",
                    files={"file": (
                        "prd.md", b"# \xea\xb0\x9c\xec\x9a\x94\n\xeb\x82\xb4\xec\x9a\xa9")})
    assert r.status_code == 200
    body = _sse(r)[-1]["payload"]
    assert body["doc"]["name"] == "prd.md"
    assert len(body["stages"]) == 5
    assert isinstance(body["findings"], list)


def test_review_stages_reflect_the_actual_document(client):
    """done payload의 stages는 to_ui_review_payload(..., sections=...)로 실제 카운트가

    들어간 결과다. orchestrator가 내보내는 SSE stage 이벤트(별도 코드 경로)와는
    다른 배선이라, 여기서 따로 확인해야 한다.
    """
    r = client.post("/api/review", files={"file": ("d.md", b"# A\nxx\n\n# B\nyy")})
    body = _sse(r)[-1]["payload"]
    details = " ".join(s["detail"] for s in body["stages"])
    assert "2 sections" in details


def test_review_sse_stage_events_reflect_the_actual_document(client):
    """진행 중에 흐르는 SSE stage 이벤트 자체도 실제 문서를 반영해야 한다.

    위 테스트가 done payload(최종 결과 배선)를 보는 것과 별개로, 화면이 검토
    도중에 보는 문구도 맞아야 한다.
    """
    r = client.post("/api/review", files={"file": ("d.md", b"# A\nxx\n\n# B\nyy")})
    events = _sse(r)
    details = " ".join(e["detail"] for e in events if e["event"] == "stage")
    assert "2 sections" in details


def test_review_unsupported_format_is_reported_as_error_event(client):
    r = client.post("/api/review", files={"file": ("d.xyz", b"hello")})
    assert r.status_code == 200          # 스트림은 이미 열렸다 — 상태코드는 못 바꾼다
    last = _sse(r)[-1]
    assert last["event"] == "error"
    assert "검토할 수 없습니다" in last["message"]


def test_review_traversal_filename_is_stripped(client):
    r = client.post("/api/review", files={"file": ("../../evil.md", b"# A\nx")})
    body = _sse(r)[-1]["payload"]
    assert body["doc"]["name"] == "evil.md"


def test_health_exposes_id_pattern(client):
    assert client.get("/api/health").json()["id_pattern"] == r"SR-\d+"


def test_health_exposes_the_whole_active_criteria(client):
    """화면이 "지금 무슨 잣대로 재는 중"인지 말할 수 있어야 한다.

    이게 없어서 데모용 체크리스트로 실제 문서를 검토하고도 사용자는 "0건"만 봤다.
    """
    body = client.get("/api/health").json()
    assert body["checklist"] == "cl.yaml"
    assert body["doc_type"] == "generic"
    assert body["llm_provider"] == "echo"
    # 값이 비어 있어도 키는 있어야 한다 — 화면이 "지정 안 함"이라고 말할 수 있게.
    assert body["scope_pattern"] == ""
    assert body["required_sections"] == []
    assert body["placeholder_markers"] == ["TBD"]


def test_frontend_is_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200 and "ui" in r.text


# ---- 검토 이력 -------------------------------------------------------------

def test_compare_result_is_saved_to_history(client):
    body = client.post("/api/compare", files=_files()).json()
    assert body["history"]["saved"] is True

    entries = client.get("/api/history").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["kind"] == "compare"
    assert entries[0]["title"] == "srs.md ↔ sdd.md"
    assert entries[0]["findings"] == len(body["findings"])


def test_review_result_is_saved_to_history(client):
    client.post("/api/review", files={"file": ("solo.md", b"# A\nSR-001", "text/markdown")})
    entries = client.get("/api/history").json()["entries"]
    assert [(e["kind"], e["title"]) for e in entries] == [("review", "solo.md")]


def test_saved_result_can_be_reopened_intact(client):
    """목록에서 클릭하면 그때 그 결과 화면이 그대로 나와야 한다."""
    fresh = client.post("/api/compare", files=_files()).json()
    entry_id = fresh["history"]["id"]

    reopened = client.get(f"/api/history/{entry_id}").json()["payload"]
    assert reopened["stats"] == fresh["stats"]
    assert reopened["findings"] == fresh["findings"]
    assert reopened["docA"]["name"] == "srs.md"


def test_history_is_newest_first(client):
    client.post("/api/review", files={"file": ("a.md", b"SR-001", "text/markdown")})
    client.post("/api/review", files={"file": ("b.md", b"SR-001", "text/markdown")})
    titles = [e["title"] for e in client.get("/api/history").json()["entries"]]
    assert titles == ["b.md", "a.md"]


def test_uploaded_documents_are_not_kept(client, history_dir):
    """원본은 보관하지 않기로 했다. 이력 폴더에 결과 JSON만 남아야 한다."""
    client.post("/api/compare", files=_files())
    left = sorted(p.name.split(".")[-1] for p in history_dir.iterdir())
    assert left == ["json"]


def test_delete_removes_the_entry(client):
    entry_id = client.post("/api/compare", files=_files()).json()["history"]["id"]
    assert client.delete(f"/api/history/{entry_id}").status_code == 200
    assert client.get("/api/history").json()["entries"] == []
    assert client.get(f"/api/history/{entry_id}").status_code == 404


def test_missing_entry_is_404_not_500(client):
    assert client.get("/api/history/20260713T100000000000-deadbeef").status_code == 404


@pytest.mark.parametrize("bad", ["..%2F..%2Fsettings", "not-an-id", "....//x"])
def test_path_traversal_ids_never_succeed(client, settings, bad):
    """이력 ID는 파일 이름이 된다. 바깥 파일을 읽거나 지울 수 있으면 안 된다.

    상태 코드는 URL이 어떻게 정규화되느냐에 따라 404/405로 갈린다(요청이 핸들러에
    닿지도 않는 경우가 있다). 지켜야 하는 것은 코드가 아니라 "성공하지 않는다"와
    "바깥 파일이 멀쩡하다"는 사실이다.
    """
    assert client.get(f"/api/history/{bad}").status_code != 200
    assert client.delete(f"/api/history/{bad}").status_code != 200
    assert settings.is_file()   # 설정 파일이 지워지지 않았다


def test_history_is_empty_before_any_review(client):
    assert client.get("/api/history").json()["entries"] == []


# ---- LLM 선택 -------------------------------------------------------------
#
# 검토자가 고를 수 있는 건 "AI 검토를 켤까 끌까"뿐이다. 어떤 provider를 쓸지는
# 서버 설정이 정한다. 브라우저가 provider를 정할 수 있으면, 사내 문서를 외부
# API로 내보내는 경로가 열린다 — 이 문서들은 그러면 안 되는 문서다.

@pytest.fixture
def llm_settings(tmp_path):
    """provider가 echo가 아닌 설정. off/on이 실제로 갈리는지 보려면 필요하다."""
    (tmp_path / "checklists").mkdir(exist_ok=True)
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    p = tmp_path / "settings_llm.toml"
    p.write_text('[llm]\nprovider = "local"\nmodel = "Qwen/Qwen3.6-27B"\n\n'
                 '[chunking]\nmax_chars = 4000\n\n'
                 '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    return p


@pytest.fixture
def spy(monkeypatch):
    """build_llm이 실제로 어떤 provider로 불렸는지 기록한다 (네트워크는 안 탄다)."""
    from modules.llm_client import EchoLLM
    seen = []

    def fake(config):
        seen.append(config.llm_provider)
        return EchoLLM()

    monkeypatch.setattr("app.orchestrator.build_llm", fake)
    return seen


@pytest.fixture
def llm_client(llm_settings, tmp_path, history_dir):
    static = tmp_path / "frontend"
    static.mkdir(exist_ok=True)
    return TestClient(create_app(settings=llm_settings, frontend_dir=static,
                                 history_dir=history_dir))


def _doc(name="srs.md"):
    return {"file": (name, b"# SRS\nSR-001\n", "text/markdown")}


def test_기본은_설정에_적힌_provider를_쓴다(llm_client, spy):
    assert llm_client.post("/api/review", files=_doc()).status_code == 200
    assert spy == ["local"]


def test_llm_off이면_LLM을_부르지_않는다(llm_client, spy):
    r = llm_client.post("/api/review", files=_doc(), data={"llm": "off"})

    assert r.status_code == 200
    assert spy == ["echo"]


def test_llm_on이면_설정된_모델을_쓴다(llm_client, spy):
    r = llm_client.post("/api/review", files=_doc(), data={"llm": "on"})

    assert r.status_code == 200
    assert spy == ["local"]


def test_브라우저는_provider를_정할_수_없다(llm_client, spy):
    # "claude"는 외부 API다. 클라이언트가 이걸 고를 수 있으면 안 된다.
    r = llm_client.post("/api/review", files=_doc(), data={"llm": "claude"})

    assert r.status_code == 400
    assert spy == []  # 아예 검토가 시작되지 않는다


def test_비교도_llm_off를_받는다(llm_client, spy):
    r = llm_client.post("/api/compare", files=_files(), data={"llm": "off"})

    assert r.status_code == 200
    assert spy == ["echo"]


def test_health가_쓰는_모델을_알려준다(llm_client):
    body = llm_client.get("/api/health").json()

    assert body["llm_provider"] == "local"
    assert body["llm_model"] == "Qwen/Qwen3.6-27B"


# ---- /api/review SSE 스트림 -------------------------------------------------

def test_review_streams_stages_then_done(client):
    r = client.post("/api/review",
                    files={"file": ("d.md", "# 개요\n내용".encode(), "text/markdown")})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _sse(r)
    stages = [e for e in events if e["event"] == "stage"]
    done = [e for e in events if e["event"] == "done"]

    # 단계는 순서대로 완료된다.
    completed = [e["key"] for e in stages if e["status"] == "done"]
    assert completed == ["ingestion", "normalize", "chunking", "review", "report"]

    # 마지막 이벤트는 done이고, payload는 기존 JSON 응답과 같은 모양이다.
    assert events[-1]["event"] == "done"
    assert len(done) == 1
    payload = done[0]["payload"]
    assert set(payload) >= {"doc", "findings", "stages", "history"}
    assert payload["doc"]["name"] == "d.md"
    assert payload["history"]["saved"] is True


def test_review_reports_engine_failure_as_error_event(client):
    r = client.post("/api/review",
                    files={"file": ("d.xyz", b"content", "application/octet-stream")})
    assert r.status_code == 200          # 스트림은 이미 열렸다
    events = _sse(r)
    assert events[-1]["event"] == "error"
    assert "검토할 수 없습니다" in events[-1]["message"]


def test_review_rejects_empty_file_before_streaming(client):
    r = client.post("/api/review",
                    files={"file": ("d.md", b"", "text/markdown")})
    assert r.status_code == 400          # 스트림을 열기 전에 끝낸다


def test_review_sse_carries_plan_and_step(client):
    """orchestrator가 내보내는 plan/step은 순수 dict라 서버의 stage 봉투를

    그대로 통과해야 한다 — 화면이 문장을 파싱하지 않고 숫자를 바로 읽는다.
    """
    r = client.post("/api/review",
                    files={"file": (
                        "d.md", b"# A\nxx\n\n# B\nyy", "text/markdown")})
    events = _sse(r)
    stages = [e for e in events if e["event"] == "stage"]

    plan_events = [e for e in stages if "plan" in e]
    assert len(plan_events) == 1
    plan = plan_events[0]["plan"]
    assert plan and {p["kind"] for p in plan} <= {"rule", "chunk"}
    # 규칙 레인은 **실제로 도는 규칙 검사가 있을 때만** 실린다. 빈 레인을 그려두면
    # 검사한 척이 된다.
    #
    # 팀 없이 도는 이 검토에서도 공통 기준의 약어 대조(C2, check: abbrev)가 돈다.
    # 공통을 다시 짜기 전(2026-08-20)에는 공통의 유일한 규칙 기준이 필수 절이었고,
    # 그 목록은 팀이 줘야 해서 팀 없는 검토에서는 검사기가 아예 안 만들어졌다 —
    # 그때는 이 자리가 "규칙 레인 없음"이었다. 지금 공통은 **팀 값 없이 도는 것만**
    # 담으므로, 팀을 안 골라도 규칙 검사가 하나는 돈다.
    rule_lanes = [p for p in plan if p["kind"] == "rule"]
    assert len(rule_lanes) == 1, "공통의 약어 대조가 규칙 레인으로 실려야 한다"
    assert rule_lanes[0]["total"] >= 1
    # 화면이 kind→이름 매핑을 하드코딩하지 않으려면 레인 이름이 여기 실려 와야 한다.
    assert all(p["label"] for p in plan)

    step_events = [e for e in stages if "step" in e]
    assert step_events, "청크 진행 step이 SSE에 실려 나오지 않았다"
    planned_steps = [e["step"] for e in step_events
                     if e["step"]["kind"] in {"rule", "chunk"}]

    # 규칙·조각·문서 전체 레인마다 제 카운터를 따로 센다. 하나로 이어 세면
    # 서로의 진행이 섞여 격자가 어긋난다.
    by_label = {p["label"]: p["total"] for p in plan}
    for label, total in by_label.items():
        mine = [s for s in planned_steps if s["label"] == label]
        assert [s["i"] for s in mine] == list(range(1, total + 1)), label
        assert all(s["total"] == total for s in mine)
    assert {s["label"] for s in planned_steps} <= set(by_label)


def test_annotate_survives_a_korean_filename():
    """한글 파일명이 Content-Disposition에서 500을 내지 않아야 한다.

    HTTP 헤더는 latin-1만 담는다. 파일명을 그대로 넣었더니 Starlette이
    인코딩하다 죽어 화면에 500이 떴다 — 실무 문서는 파일명이 전부 한글이라
    이 경로는 거의 항상 밟힌다.
    """
    pdf = Path(__file__).parent / "data" / "probe.pdf"
    if not pdf.exists():
        pytest.skip("시험용 PDF 없음")
    pytest.importorskip("pdfplumber")

    with TestClient(create_app()) as client:
        res = client.post(
            "/api/annotate",
            files={"file": ("운영개념기술서_v2.0.pdf", pdf.read_bytes(),
                            "application/pdf")},
            data={"findings": "[]"},
        )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    # RFC 5987: ASCII 대체 이름 + UTF-8 퍼센트 인코딩이 함께 실린다.
    cd = res.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert cd.isascii()


def test_annotate_reports_summary_page_count_in_header():
    # 표시본을 인라인 뷰어에 띄우고 지적 page로 점프하려면, 앞에 몇 장이 밀렸는지
    # 화면이 알아야 한다. 헤더로 내려보내고 CORS로 노출한다.
    pdf = Path(__file__).parent / "data" / "probe.pdf"
    if not pdf.exists():
        pytest.skip("시험용 PDF 없음")
    pytest.importorskip("pdfplumber")

    findings = json.dumps([{
        "id": "f1", "sev": "minor", "checker": "consistency",
        "message": "응답시간 상충", "section": "0", "page": 1,
        "evidence": [{"quote": "예측", "section": "0", "page": 1}],
    }])
    with TestClient(create_app()) as client:
        res = client.post(
            "/api/annotate",
            files={"file": ("시험.pdf", pdf.read_bytes(), "application/pdf")},
            data={"findings": findings},
        )
    assert res.status_code == 200, res.text
    assert "X-Summary-Pages" in res.headers
    assert int(res.headers["X-Summary-Pages"]) >= 0
    assert "X-Summary-Pages" in res.headers["access-control-expose-headers"]


def test_render_pdf_reconstructs_hwpx():
    if shutil.which("soffice") is None:
        pytest.skip("soffice 없음")
    hwpx = Path("data/ACMD-AN-002_요구사항명세서_v2.1_260707.hwpx")
    if not hwpx.exists():
        pytest.skip("샘플 hwpx 없음")
    with TestClient(create_app()) as client:
        res = client.post("/api/render-pdf",
                          files={"file": (hwpx.name, hwpx.read_bytes(),
                                          "application/octet-stream")})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:4] == b"%PDF"


# (구 test_render_pdf_rejects_hwp 제거: hwp는 이제 H2Orestart로 변환한다 — 더는
#  '미지원'으로 거부하지 않는다. 변환 경로는 test_convert.py 가 커버한다.)


def test_annotate_reports_the_numbers_it_drew():
    """화면 카드가 표시본과 같은 번호를 달려면 그 표를 받아야 한다.

    본문은 PDF라서 번호를 실을 자리가 헤더뿐이다. 브라우저가 읽으려면
    expose 목록에도 있어야 한다 — 빠지면 조용히 안 읽힌다.
    """
    pdf = Path(__file__).parent / "data" / "시험.pdf"
    if not pdf.exists():
        pytest.skip("시험용 PDF 없음")
    pytest.importorskip("pdfplumber")

    findings = json.dumps([{
        "id": "f1", "sev": "minor", "checker": "consistency",
        "message": "응답시간 상충", "section": "0", "page": 1,
        "evidence": [{"quote": "예측", "section": "0", "page": 1}],
    }])
    with TestClient(create_app()) as client:
        res = client.post(
            "/api/annotate",
            files={"file": ("시험.pdf", pdf.read_bytes(), "application/pdf")},
            data={"findings": findings},
        )
    assert res.status_code == 200, res.text
    assert "X-Numbers" in res.headers
    assert json.loads(res.headers["X-Numbers"]) == {"f1": "1"}
    assert "X-Numbers" in res.headers["access-control-expose-headers"]


def test_suggest_returns_a_revision():
    """지적 + 원문 인용을 주면 수정안을 돌려준다."""
    with TestClient(create_app()) as client:
        res = client.post("/api/suggest", data={
            "message": "존재하지 않는 날짜다.",
            "quote": "제정일자: 2025.00.00.",
            "llm": "off",   # echo — 지어내지 않는지 보는 게 핵심이다
        })
    assert res.status_code == 200, res.text
    body = res.json()
    # llm 을 끄면 만들 수 없다. 여기서 ok=true 가 나오면 문장을 지어낸 것이다.
    assert body["ok"] is False
    assert body["revised"] == ""
    assert body["reason"], "왜 못 만들었는지 말하지 않으면 화면이 침묵한다"


def test_suggest_passes_the_criterion_through_to_the_prompt(monkeypatch):
    """화면이 보낸 기준이 실제로 프롬프트까지 간다.

    테스트가 함수 호출만 보면 프론트→서버 배선이 끊겨도 통과한다. 여기서는
    엔드포인트를 눌러 LLM 이 받은 프롬프트를 직접 본다.
    """
    seen = {}

    class _LLM:
        def complete(self, prompt, **opts):
            seen["prompt"] = prompt
            from modules.llm_client import Response
            return Response(text="수정안: 시험 대상 장비는 5 kg 이다.")

        def chat(self, messages, **opts):
            raise AssertionError("수정안은 complete() 를 쓴다")

    monkeypatch.setattr("app.server.build_llm", lambda cfg: _LLM())
    with TestClient(create_app()) as client:
        res = client.post("/api/suggest", data={
            "message": "띄어쓰기 오류",
            "quote": "시험 대상 장비 는 5kg 이다.",
            "criterion": "SI 단위계 표기: 수치와 단위 사이를 띄운다",
        })

    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert "[검토 기준]" in seen["prompt"]
    assert "SI 단위계" in seen["prompt"]


def test_suggest_without_a_criterion_still_works(monkeypatch):
    # 기준 없는 일반 검토는 지금처럼 동작한다 — 빈 절을 만들지 않는다.
    seen = {}

    class _LLM:
        def complete(self, prompt, **opts):
            seen["prompt"] = prompt
            from modules.llm_client import Response
            return Response(text="수정안: 고친 문장")

        def chat(self, messages, **opts):
            raise AssertionError("수정안은 complete() 를 쓴다")

    monkeypatch.setattr("app.server.build_llm", lambda cfg: _LLM())
    with TestClient(create_app()) as client:
        res = client.post("/api/suggest", data={"message": "오류", "quote": "원문"})

    assert res.json()["ok"] is True
    assert "[검토 기준]" not in seen["prompt"]


def test_suggest_rejects_a_client_chosen_provider():
    """provider 를 브라우저가 고르게 두면 문서가 밖으로 나갈 수 있다."""
    with TestClient(create_app()) as client:
        res = client.post("/api/suggest", data={
            "message": "m", "quote": "q", "llm": "claude",
        })
    assert res.status_code == 400


def test_health_lists_the_checklists_that_actually_exist():
    """화면이 목록을 지어내지 않게 서버가 내려준다.

    예전엔 화면에 실제로 없는 이름(Generic·PRD·API Spec)이 박혀 있었고, 골라도
    서버에 전달되지 않았다 — 고르는 시늉만 하는 UI였다.
    """
    with TestClient(create_app()) as client:
        h = client.get("/api/health").json()
        ids = [c["id"] for c in h["checklists"]]
        assert ids, "고를 수 있는 체크리스트가 하나도 없다"
        # 배포 설정은 기준을 박아두지 않는다 — 안 고른 상태가 정상이고, 화면은
        # 그걸 "지정 안 함"으로 말한다(빈 문자열).
        assert h["checklist_id"] == ""
        # 고르면 그 id 를 그대로 되돌려줘야 한다. 다른 잣대를 보여주면 이 패널이
        # 막으려던 사고("무슨 잣대로 재는지 모른 채 0건")가 그대로 난다.
        picked = client.get(f"/api/health?checklist={ids[0]}").json()
    assert picked["checklist_id"] == ids[0]


def test_review_rejects_a_team_that_is_not_on_the_list():
    """브라우저가 보낸 문자열을 경로로 쓰면 서버의 아무 파일이나 읽게 된다."""
    pdf = Path(__file__).parent / "data" / "probe.pdf"
    with TestClient(create_app()) as client:
        res = client.post(
            "/api/review",
            files={"file": ("a.pdf", pdf.read_bytes(), "application/pdf")},
            data={"llm": "off", "checklist": "../../etc/passwd"},
        )
    assert res.status_code == 400, res.text
    assert "팀 기준" in res.json()["detail"]


def test_health_rejects_an_unknown_team():
    with TestClient(create_app()) as client:
        res = client.get("/api/health", params={"checklist": "../settings"})
    assert res.status_code == 400


# --- 기준이 검사 매개변수를 정한다 -----------------------------------------
# 예전에는 presets/checklists/*.yaml 이 요건 ID 정규식을 갖고 있었다. 그 값은
# 개발 중에 실제 문서를 보고 거꾸로 뽑은 것이라 근거가 없었다 — 문서에서 뽑은
# 잣대로 그 문서를 재면 틀릴 수가 없다. 이제 기준(3층)이 params 로 정한다.

@pytest.fixture
def teams_client(tmp_path, history_dir):
    """공통 하나 + 팀 둘. 팀마다 요건 ID 형식이 다르다."""
    settings = tmp_path / "settings.toml"
    settings.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
                        encoding="utf-8")
    seeds = tmp_path / "seeds"
    (seeds / "teams").mkdir(parents=True)
    (seeds / "common.yaml").write_text(
        "name: 공통 기준\nsource_filename: x.xlsx\n"
        "items:\n"
        "- 'no': C-1\n  text: 오탈자·문법\n  agent: 표현·내용품질\n",
        encoding="utf-8")
    (seeds / "teams" / "alpha.yaml").write_text(
        "name: 알파팀\nteam: alpha\nsource_filename: x.xlsx\n"
        "items:\n"
        "- 'no': '1'\n  text: 상위-하위 추적성 분석\n  agent: 정합성·추적성\n"
        "  params:\n    id_pattern: \"FR-[A-Z]{2,4}(?:_\\\\d+)+\"\n"
        "    id_example: FR-GC_01\n",
        encoding="utf-8")
    (seeds / "teams" / "beta.yaml").write_text(
        "name: 베타팀\nteam: beta\nsource_filename: x.xlsx\n"
        "items:\n"
        "- 'no': '1'\n  text: 추적성 분석\n  agent: 정합성·추적성\n"
        "  params:\n    id_pattern: \"FR\\\\d-\\\\d{4}\"\n"
        "    id_example: FR1-0305\n",
        encoding="utf-8")
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=history_dir, seed_dir=seeds))


def test_teams_are_the_choosable_criteria(teams_client):
    """고를 수 있는 기준은 팀 프리셋이다. 공통은 늘 포함되므로 목록에 없다."""
    body = teams_client.get("/api/health").json()
    assert {c["id"]: c["name"] for c in body["checklists"]} == {
        "alpha": "알파팀", "beta": "베타팀"}


def test_nothing_is_pinned_by_default(teams_client):
    """배포 설정은 기준을 박아두지 않는다 — 안 고른 상태가 정상이다."""
    body = teams_client.get("/api/health").json()
    assert body["checklist_id"] == ""
    assert body["id_pattern"] == ""


def test_chosen_team_criteria_set_the_id_scheme(teams_client):
    """기준의 params 가 검사 매개변수를 정한다."""
    a = teams_client.get("/api/health", params={"checklist": "alpha"}).json()
    assert a["checklist_id"] == "alpha"
    assert a["id_example"] == "FR-GC_01"

    b = teams_client.get("/api/health", params={"checklist": "beta"}).json()
    assert b["id_pattern"] == r"FR\d-\d{4}"
    assert a["id_pattern"] != b["id_pattern"], "팀을 바꿨는데 잣대가 그대로다"


def test_detect_counts_ids_per_team(teams_client):
    """잘못된 기준의 실패는 에러가 아니라 조용한 0건이다 — 고르기 전에 잰다."""
    doc = b"# SRS\nFR-GC_01 first\nFR-GC_02 second\nFR-LC_01 third"
    body = teams_client.post(
        "/api/detect", files={"file": ("srs.md", doc, "text/markdown")}).json()
    assert {d["id"]: d["matches"] for d in body["detected"]} == {"alpha": 3, "beta": 0}
    assert body["best"] == "alpha"


def test_detect_recommends_nothing_when_no_pattern_matches(teams_client):
    """아무것도 안 맞으면 지어내지 않는다. 잘못된 추천은 조용한 0건을 부른다."""
    body = teams_client.post(
        "/api/detect",
        files={"file": ("x.md", "# 본문\n요건 없음".encode(), "text/markdown")}).json()
    assert body["best"] is None
    assert all(d["matches"] == 0 for d in body["detected"])


def test_detect_carries_the_human_readable_example(teams_client):
    """화면에 정규식을 띄울 수는 없다. 기준이 적어둔 예시를 쓴다."""
    body = teams_client.post(
        "/api/detect",
        files={"file": ("srs.md", b"FR-GC_01", "text/markdown")}).json()
    alpha = next(d for d in body["detected"] if d["id"] == "alpha")
    assert alpha["id_example"] == "FR-GC_01"


def test_a_team_without_params_leaves_the_scheme_empty(teams_client, tmp_path):
    """기준이 안 적어두면 코드가 지어내지 않는다 — 추적성은 '기준 없음'이 된다."""
    (tmp_path / "seeds" / "teams" / "gamma.yaml").write_text(
        "name: 감마팀\nteam: gamma\nsource_filename: x.xlsx\n"
        "items:\n- 'no': '1'\n  text: 서식 확인\n  agent: 형식·완전성\n",
        encoding="utf-8")
    body = teams_client.get("/api/health", params={"checklist": "gamma"}).json()
    assert body["id_pattern"] == ""


def test_detect_rejects_unsupported_format(teams_client):
    r = teams_client.post("/api/detect",
                          files={"file": ("a.zip", b"PK\x03\x04", "application/zip")})
    assert r.status_code == 400


# ── POST /api/locate — 지적 좌표(JSON). 화면 뷰어가 형광펜·점프에 쓴다. ──

def test_locate_returns_coordinates_as_json(client):
    pdf = Path(__file__).parent / "data" / "probe.pdf"
    if not pdf.exists():
        pytest.skip("시험용 PDF 없음")
    findings = json.dumps([{
        "id": "f1", "sev": "minor", "message": "m", "page": 1,
        "evidence": [{"quote": "RQ-SFR-PR-01-001 예측  응답시간은  3 초  이내여야  한다 .",
                      "page": 1}],
    }], ensure_ascii=False)
    r = client.post("/api/locate",
                    files={"file": ("probe.pdf", pdf.read_bytes(), "application/pdf")},
                    data={"findings": findings})
    assert r.status_code == 200
    body = r.json()
    assert body["pages"] >= 1
    it = body["items"][0]
    assert it["id"] == "f1"
    assert it["page"] >= 1                      # 1-based
    assert it["marks"][0]["page"] >= 1          # 1-based
    assert len(it["marks"][0]["rect"]) == 4


def test_locate_rejects_findings_that_are_not_a_list(client):
    r = client.post("/api/locate",
                    files={"file": ("a.pdf", b"%PDF-1.4\n", "application/pdf")},
                    data={"findings": '{"not": "a list"}'})
    assert r.status_code == 400


def test_locate_rejects_non_pdf(client):
    r = client.post("/api/locate",
                    files={"file": ("a.hwpx", b"x", "application/octet-stream")},
                    data={"findings": "[]"})
    assert r.status_code == 400

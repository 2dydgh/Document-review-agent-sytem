"""체크리스트 라이브러리 API."""
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402

CSV = "No,종류,체크리스트 항목,적용 문서\n1,스캔,서명 스캔 여부,전체\n2,책갈피,책갈피 확인,전체\n"


@pytest.fixture
def client(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
                        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=tmp_path / "history"))


def _upload(client, path="/api/checklists/preview", **data):
    return client.post(path, files={"file": ("IS16.csv", CSV.encode(), "text/csv")},
                       data=data)


def test_preview_reports_the_guessed_columns(client):
    body = _upload(client).json()
    table = body["tables"][0]
    assert table["header"] == ["No", "종류", "체크리스트 항목", "적용 문서"]
    assert table["columns"]["text"] == 2
    assert table["sample"][0]["text"] == "서명 스캔 여부"


def test_preview_rejects_an_unsupported_format(client):
    r = client.post("/api/checklists/preview",
                    files={"file": ("a.hwp", b"x", "application/octet-stream")})
    assert r.status_code == 400


def test_register_then_list_and_get(client):
    made = _upload(client, path="/api/checklists", name="내부검토",
                   table_index="0",
                   columns=json.dumps({"no": 0, "group": 1, "text": 2, "note": 3}))
    assert made.status_code == 200
    cid = made.json()["id"]
    assert made.json()["item_count"] == 2

    listed = client.get("/api/checklists").json()["checklists"]
    assert [c["name"] for c in listed] == ["내부검토"]
    assert listed[0]["item_count"] == 2

    got = client.get(f"/api/checklists/{cid}").json()
    assert [i["text"] for i in got["items"]] == ["서명 스캔 여부", "책갈피 확인"]


def test_register_refuses_when_no_text_column_is_given(client):
    """항목 내용 없이는 체크할 것이 없다. 빈 체크리스트를 등록시키지 않는다."""
    r = _upload(client, path="/api/checklists", name="가", table_index="0",
                columns=json.dumps({"no": 0}))
    assert r.status_code == 400


def test_delete(client):
    cid = _upload(client, path="/api/checklists", name="가", table_index="0",
                  columns=json.dumps({"text": 2})).json()["id"]
    assert client.delete(f"/api/checklists/{cid}").status_code == 200
    assert client.get("/api/checklists").json()["checklists"] == []
    assert client.get(f"/api/checklists/{cid}").status_code == 404


def test_csv_export_includes_unjudged_items(client):
    cid = _upload(client, path="/api/checklists", name="가", table_index="0",
                  columns=json.dumps({"no": 0, "group": 1, "text": 2})).json()["id"]
    # results 는 no 가 아니라 항목의 위치 인덱스(문자열)로 키잉한다 — "0" 은
    # 첫 항목(no="1")을 가리킨다.
    r = client.post(f"/api/checklists/{cid}/csv",
                    data={"results": json.dumps(
                        {"0": {"verdict": "Satisfied", "reason": "확인"}})})
    assert r.status_code == 200
    # BOM은 바이트에만 있고, 디코딩할 때 utf-8-sig 코덱이 제거한다.
    # BOM이 있는지 바이트에서 확인 — 엑셀이 윈도우에서 UTF-8 한글을 읽으려면 필요하다.
    assert r.content.startswith(b'\xef\xbb\xbf'), "CSV 응답이 BOM으로 시작해야 함"
    # utf-8-sig 코덱이 BOM을 제거하고 텍스트를 반환한다.
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "번호,분류,항목,판정,이유"
    assert "미판정" in lines[2]


def test_run_keeps_items_independently_judged_when_no_column_is_absent(client):
    """no 열을 고르지 않으면(columns 에 "no" 자체가 없으면) build_items 가
    모든 항목에 no="" 를 준다. no 를 결과 키로 쓰면 첫 항목을 판정하는
    순간 no="" 를 공유하는 나머지 전부가 같은 판정으로 뭉친다 — 위치
    인덱스로 찾아야 서로 독립적으로 남는다."""
    cid = _upload(client, path="/api/checklists", name="가", table_index="0",
                  columns=json.dumps({"group": 1, "text": 2})).json()["id"]
    got = client.get(f"/api/checklists/{cid}").json()
    assert [i["no"] for i in got["items"]] == ["", ""]

    # 첫 항목(위치 0)만 판정한다.
    r = client.post(f"/api/checklists/{cid}/run",
                    data={"document_name": "RVVR.pdf",
                          "results": json.dumps(
                              {"0": {"verdict": "Satisfied", "reason": "확인"}})})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["unjudged"] == body["total"] - 1  # 0이 아니어야 한다.

    entry = client.get(f"/api/history/{body['history']['id']}").json()
    # 두 번째 항목(no 도 "" 로 같음)은 판정되지 않은 채로 남아야 한다.
    assert [x["verdict"] for x in entry["results"]] == ["Satisfied", None]


def test_csv_filename_disposition_has_no_stray_quote_from_checklist_name(client):
    """c.name 은 업로드한 파일에서 온 이름이라 신뢰할 수 없다. 큰따옴표를 그대로
    _disposition(f"{c.name}.checklist.csv") 에 실으면 filename="..." 안에서
    따옴표가 일찍 닫혀 헤더가 깨진다."""
    cid = _upload(client, path="/api/checklists", name='이상한"이름', table_index="0",
                  columns=json.dumps({"text": 2})).json()["id"]
    r = client.post(f"/api/checklists/{cid}/csv", data={"results": json.dumps({})})
    assert r.status_code == 200
    disp = r.headers["content-disposition"]
    # filename="..." 필드 안(첫 "부터 다음 "; filename*= 앞까지)에 이스케이프
    # 되지 않은 "가 남아 있으면 그 지점에서 필드가 조기 종료된 것이다.
    inner = disp.split('filename="', 1)[1].split('"; filename*=', 1)[0]
    assert '"' not in inner, f"Content-Disposition 안에 이스케이프 안 된 큰따옴표가 남음: {disp!r}"


def test_unknown_checklist_is_404_not_500(client):
    assert client.get("/api/checklists/" + "z" * 16).status_code == 404


def test_run_is_saved_to_history_with_the_unjudged_count(client):
    """기록에서 다시 열었을 때 '몇 개를 안 봤는지'가 사라지면 다 본 것처럼 읽힌다."""
    cid = _upload(client, path="/api/checklists", name="가", table_index="0",
                  columns=json.dumps({"no": 0, "group": 1, "text": 2})).json()["id"]
    # results 는 no 가 아니라 항목의 위치 인덱스(문자열)로 키잉한다 — "0" 은
    # 첫 항목(no="1")을 가리킨다.
    r = client.post(f"/api/checklists/{cid}/run",
                    data={"document_name": "RVVR.pdf",
                          "results": json.dumps(
                              {"0": {"verdict": "Satisfied", "reason": "확인"}})})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["unjudged"] == 1
    assert body["history"]["saved"] is True

    entry = client.get(f"/api/history/{body['history']['id']}").json()
    assert entry["checklist_name"] == "가"
    assert entry["document_name"] == "RVVR.pdf"
    # 판정하지 않은 항목도 결과에 남는다 — 빠지면 안 본 것이 사라진다.
    assert [x["verdict"] for x in entry["results"]] == ["Satisfied", None]

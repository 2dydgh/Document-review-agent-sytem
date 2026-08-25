"""checklist_id 를 준 /api/review 가 항목별 결과를 낸다."""
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402


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
    # 씨앗 프리셋은 빈 디렉터리로 격리한다 — repo 의 로컬 씨앗이 검토에 새어들지
    # 않게(공통 프리셋이 있으면 항목 수가 달라진다).
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=tmp_path / "history",
                                 seed_dir=tmp_path / "seeds"))


def _register(client):
    csv = "No,종류,항목\n1,Consistency,용어가 일관된가\n2,스캔,서명 스캔 여부\n"
    r = client.post("/api/checklists", files={"file": ("c.csv", csv.encode(), "text/csv")},
                    data={"name": "c", "table_index": "0",
                          "columns": json.dumps({"no": 0, "group": 1, "text": 2})})
    return r.json()["id"]


def _sse_done(resp):
    for block in resp.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if ev.get("event") == "done":
                    return ev["payload"]
    return None


def test_review_with_checklist_returns_per_item(client):
    cid = _register(client)
    r = client.post("/api/review",
                    files={"file": ("d.md", b"# doc\ncontent", "text/markdown")},
                    data={"llm": "off", "checklist_id": cid})
    payload = _sse_done(r)
    assert payload is not None
    cl = payload["checklist"]
    assert payload["criteriaResults"] == cl
    # 업로드 체크리스트 항목엔 agent 가 없다(엑셀에 Agent 열 없음) → 둘 다 manual.
    # (종류=Consistency 는 group 에 남지만 자동 라우팅 안 함 — 키워드 추측을 버렸고,
    #  업로드 항목의 agent 지정은 사람 몫이다.)
    #
    # 항목은 체크리스트에서 온 둘뿐이다. 예전에는 여기에 "기본 검토" 합성 항목
    # 둘이 더 붙어 넷이었는데, 기준 하나도 그것을 요구하지 않았는데 검사된 것처럼
    # 보이는 것이 문제라 없앴다. 그 자리는 공통 프리셋이 가져갔고 — 이 픽스처는
    # 씨앗을 빈 디렉터리로 격리하므로 공통 기준도 안 들어온다.
    assert cl["summary"]["total"] == 2
    assert {i["no"]: i["status"] for i in cl["items"]} == {"1": "manual", "2": "manual"}
    assert all(i["no"] != "" for i in cl["items"]), "기준에 없는 항목을 지어내지 않는다"


def test_review_without_uploaded_criteria_keeps_flat_view_and_mapping(client):
    r = client.post("/api/review",
                    files={"file": ("d.md", b"# doc\ncontent", "text/markdown")},
                    data={"llm": "off"})
    payload = _sse_done(r)
    assert payload is not None
    # 일반 검토는 기존 평면 화면을 유지하지만, 내부 기준↔지적 연결은 버리지 않는다.
    assert "checklist" not in payload
    assert payload["criteriaResults"]["summary"]["total"] == 0
    assert "findings" in payload


def test_common_criterion_finding_survives_into_normal_ui_payload(tmp_path):
    """업로드 기준이 없어도 공통 기준이 낸 지적을 UI까지 역추적할 수 있다."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
        encoding="utf-8")
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "common.yaml").write_text(
        "name: 공통 기준\n"
        "items:\n"
        # YAML 1.1 은 따옴표 없는 `no` 를 불리언 False 로 읽는다 — 생성기가
        # `'no':` 로 쓰는 이유이고, 손으로 쓸 때도 따옴표가 있어야 번호가 산다.
        "- 'no': C-1\n"
        "  text: 미작성 표시가 없어야 한다\n"
        "  mode: 규칙\n"
        "  check: placeholder\n",
        encoding="utf-8")
    normal = TestClient(create_app(
        settings=settings, frontend_dir=static,
        history_dir=tmp_path / "history", seed_dir=seeds))
    response = normal.post(
        "/api/review",
        files={"file": ("d.md", b"# doc\nTBD", "text/markdown")},
        data={"llm": "off"})
    payload = _sse_done(response)

    assert "checklist" not in payload
    item = payload["criteriaResults"]["items"][0]
    assert item["no"] == "C-1" and item["status"] == "flagged"
    assert item["findings"][0]["id"] == payload["findings"][0]["id"]

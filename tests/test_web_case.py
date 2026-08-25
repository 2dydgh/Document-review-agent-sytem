"""케이스 검토 엔드포인트.

화면이 붙기 전에 여기까지 확인해 둔다 — 폴더째 올리면 산출물을 인식하고 대조까지
해서 SSE 로 돌려주는가.
"""
import asyncio
import json
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from conftest import sample  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.history import HistoryStore  # noqa: E402
from app.server import create_app  # noqa: E402

ZIP_NAME = "AI시험인증1팀_시험산출물 샘플.zip"
ZIP = sample(ZIP_NAME)


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
def client(settings, tmp_path):
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=tmp_path / "history"))


@pytest.fixture
def manual_app(settings, tmp_path):
    """원본 문서 파싱 없이 직접 입력 대조 API만 검증하는 이력."""
    static = tmp_path / "manual-frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    history_root = tmp_path / "manual-history"
    app = create_app(settings=settings, frontend_dir=static,
                     history_dir=history_root)
    return app, HistoryStore(history_root)


def _confirm(app, entry_id, body):
    endpoint = next(r.endpoint for r in app.routes
                    if getattr(r, "path", "") == "/api/history/{entry_id}/confirm")
    return asyncio.run(endpoint(entry_id, body))


def _manual_payload():
    return {
        "caseId": "SST-26-999", "team": "AI시험인증1팀",
        "manual": [{"id": "M-접수번호", "text": "접수번호 확인",
                    "against": "시스템 부여값"}],
        "outputs": [{"key": "시험의뢰서", "fields": [
            {"name": "접수번호", "value": "RN-26-001", "found": True,
             "at": "표 1"}]}],
        "findings": [],
        "stats": {"findings": 0, "unreviewed": 0, "manual": 1},
    }


@pytest.fixture(scope="module")
def case_files():
    """실산출물 (파일명, 바이트) 목록. data/ 가 없으면 skip."""
    if ZIP is None or not ZIP.exists():
        pytest.skip(f"{ZIP_NAME} 없음 — data/ 어딘가에 두면 이 검증이 돈다")
    out = []
    with zipfile.ZipFile(ZIP) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            out.append((Path(info.filename).name, z.read(info)))
    return out


def _sse(response):
    events = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def _post(client, files):
    return client.post(
        "/api/review-case",
        files=[("files", (name, data)) for name, data in files],
        data={"team": "ai-test-cert-1"})


def test_케이스를_올리면_산출물을_인식하고_대조한다(client, case_files):
    r = _post(client, case_files)

    assert r.status_code == 200
    payload = _sse(r)[-1]["payload"]
    assert payload["caseId"] == "SST-26-999"
    assert len(payload["outputs"]) == 10
    assert payload["missing"] == []


def test_한_글자_차이를_지적으로_돌려준다(client, case_files):
    payload = _sse(_post(client, case_files))[-1]["payload"]

    flagged = {f["ruleId"] for f in payload["findings"] if not f["unreviewed"]}
    # 성적서번호·시험기간 둘 다 전 산출물 대조가 낸다. 시험기간은 계획서·을지·갑지
    # 3곳에 있어 쌍으로 두면 같은 결함이 3번 난다.
    # 1-7/대표자 는 의뢰서·갑지 2곳뿐이라 쌍이 맞다 — 갑지가 '홍길동1' 이다(실측).
    #
    # F-성적서번호 는 **다른 말을 한다**. 갑지의 `SST-26-999C01` 은 하이픈이 빠져
    # 형식(pattern)을 위반한다. W- 는 "셋이 서로 다르다"까지만 말하고 어느 쪽이
    # 틀렸는지는 못 말한다 — F- 가 "갑지가 규칙 위반"이라고 짚어 줘야 검토자가
    # 어느 문서를 고칠지 안다. 층이 다르므로 kind 로 갈려 화면에서 겹치지 않는다.
    #
    # F-서명-* 는 갑지의 `성명    (서명)` 이 그대로 남은 것이다(실측). 서명란이
    # 가로 표라 at: below 를 주고서야 잡혔다 — 합성 문서 테스트는 전부 통과하는데
    # 실문서에서만 새던 자리다.
    assert flagged == {"W-성적서번호", "W-시험기간", "1-7/대표자",
                       "F-성적서번호", "F-서명-시험실무자", "F-서명-기술책임자"}
    assert {f["kind"] for f in payload["findings"]
            if f["ruleId"].startswith("F-")} == {"output"}


def test_지적에_양쪽_근거를_싣는다(client, case_files):
    # 기존 compare payload 는 evidence 를 버린다. 대조 지적에서 가장 값어치 있는
    # 정보라 케이스 payload 는 그대로 싣는다 — 화면이 "여기와 저기"를 보여야 한다.
    payload = _sse(_post(client, case_files))[-1]["payload"]

    f = next(f for f in payload["findings"] if f["ruleId"] == "W-성적서번호")
    assert [e["quote"] for e in f["evidence"]] == \
        ["성적서번호 | SST-26-999-C01", "성적서번호 | SST-26-999C01"]
    assert all(e["at"] for e in f["evidence"])


def test_미분류와_건너뛴_파일을_목록으로_돌려준다(client, case_files):
    payload = _sse(_post(client, case_files))[-1]["payload"]

    assert any("접수 문서" in u["file"] for u in payload["unclassified"])
    assert len(payload["ignored"]) == 2


def test_추출된_필드값을_산출물마다_돌려준다(client, case_files):
    # 화면이 "무엇을 읽었는지"를 보여줘야 검토자가 필드맵이 맞는지 판단할 수 있다.
    payload = _sse(_post(client, case_files))[-1]["payload"]

    gapji = next(o for o in payload["outputs"] if o["key"] == "갑지")
    names = {f["name"]: f for f in gapji["fields"]}
    assert names["의뢰기관명"]["value"] == "한국소프트웨어시험연구소"
    assert names["의뢰기관명"]["at"].startswith("표")


def test_진행을_SSE_로_흘린다(client, case_files):
    events = _sse(_post(client, case_files))

    kinds = [e.get("event") for e in events]
    assert "stage" in kinds
    assert kinds[-1] == "done"


def test_없는_팀을_고르면_스트림_전에_404(client, case_files):
    r = client.post("/api/review-case",
                    files=[("files", (n, d)) for n, d in case_files[:1]],
                    data={"team": "없는팀"})

    assert r.status_code == 404


def test_파일을_안_주면_400(client):
    r = client.post("/api/review-case", data={"team": "ai-test-cert-1"})

    assert r.status_code in (400, 422)


def test_직접_확인_항목을_돌려준다(client, case_files):
    """문서 간 md §4 — 접수번호·접수일·사업자등록증은 문서 대조로 판정할 수 없다.
    목록으로 내고 사람이 확인했다고 남긴다."""
    payload = _sse(_post(client, case_files))[-1]["payload"]

    assert [m["id"] for m in payload["manual"]] == \
        ["M-접수번호", "M-접수일", "M-의뢰기관명"]
    assert payload["stats"]["manual"] == 3


def test_확인_결과를_이력에_남긴다(client, case_files):
    """결과는 이미 이력에 남는데 확인 표시만 브라우저에 있으면, 나중에 그 기록을
    열었을 때 "이 건은 발급했나" 를 알 수 없다."""
    payload = _sse(_post(client, case_files))[-1]["payload"]
    entry_id = payload["history"]["id"]

    r = client.post(f"/api/history/{entry_id}/confirm",
                    json={"checked": ["M-접수번호", "M-접수일"], "inputs": {}})

    assert r.status_code == 200
    assert r.json()["manualChecked"] == ["M-접수번호", "M-접수일"]
    assert r.json()["confirmedAt"]
    # 다시 읽어도 남아 있어야 한다.
    again = client.get(f"/api/history/{entry_id}").json()
    assert again["payload"]["manualChecked"] == ["M-접수번호", "M-접수일"]


def test_직접_입력값으로_추가_대조하고_이력_건수도_갱신한다(manual_app):
    app, store = manual_app
    entry_id = store.save("case", _manual_payload()).id

    body = _confirm(app, entry_id, {
        "checked": ["M-접수번호"],
        "inputs": {"M-접수번호": "RN-99-999"}})

    assert body["manualInputs"] == {"M-접수번호": "RN-99-999"}
    assert next(x for x in body["manualResults"]
                if x["id"] == "M-접수번호")["status"] == "수정 필요"
    assert any(f["kind"] == "manual_input" for f in body["findings"])
    assert body["stats"]["findings"] == 1

    reopened = store.get(entry_id)
    assert reopened["payload"]["manualInputs"]["M-접수번호"] == "RN-99-999"
    listed = next(e for e in store.list() if e.id == entry_id)
    assert listed.findings == body["stats"]["findings"]


def test_직접_확인에_기준에_없는_항목을_넣을_수_없다(manual_app):
    app, store = manual_app
    entry_id = store.save("case", _manual_payload()).id

    with pytest.raises(fastapi.HTTPException) as exc:
        _confirm(app, entry_id, {"checked": [], "inputs": {"없는항목": "값"}})

    assert exc.value.status_code == 400


def test_확인이_검사_결과를_덮어쓰지_못한다(client, case_files):
    """확인 표시는 사람이 정하지만 지적은 도구가 정한다. payload 를 통째로 받으면
    브라우저가 보낸 것이 검사 결과를 덮어쓸 수 있다."""
    payload = _sse(_post(client, case_files))[-1]["payload"]
    entry_id = payload["history"]["id"]
    before = len(payload["findings"])

    client.post(f"/api/history/{entry_id}/confirm",
                json={"checked": ["M-접수번호"], "inputs": {}})

    again = client.get(f"/api/history/{entry_id}").json()
    assert len(again["payload"]["findings"]) == before


def test_없는_이력을_확인하면_404(client):
    r = client.post("/api/history/없는id/confirm", json={"checked": [], "inputs": {}})

    assert r.status_code == 404

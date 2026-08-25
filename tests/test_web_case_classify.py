"""산출물 인식 — 올리기 전에 파일명만으로 판별한다.

업로드는 수십 MB 다. 무엇이 무엇인지 확인받는 데 그걸 다 올릴 이유가 없다 —
판별 근거가 파일명의 양식번호뿐이라 이름만 보내면 된다.

여기서 확인받아야 하는 이유: 양식번호가 없는 파일을 추측으로 배정하면 엉뚱한
필드맵으로 검사해 거짓 지적이 난다. 사람이 지정하거나 제외해야 한다.
"""
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402

NAMES = [
    "SST-K-TP-7-01-02(08) 시험의뢰서.docx",
    "SST-K-TI-03-02(04)-시험 설계서_SST-26-999.docx",       # 구 양식 (최신은 05)
    "SST-K-TP-7-08-06(00) 시험성적서(일반_국문)_SST-26-999(갑지).docx",
    "시험 접수 문서(일반)_2026(문서 간 검토 시 사용).docx",     # 양식번호 없음
    "99. 일반성적서 예시.pdf",                                # 참고 예시
]


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


def _classify(client, names=None, team="ai-test-cert-1"):
    return client.post("/api/classify-case",
                       data={"names": json.dumps(names if names is not None else NAMES),
                             "team": team})


def test_파일명만으로_산출물을_판별한다(client):
    got = _classify(client).json()

    by_file = {r["file"]: r["key"] for r in got["recognized"]}
    assert by_file["SST-K-TP-7-01-02(08) 시험의뢰서.docx"] == "시험의뢰서"
    assert by_file[
        "SST-K-TP-7-08-06(00) 시험성적서(일반_국문)_SST-26-999(갑지).docx"] == "갑지"


def test_구_양식은_판별하되_표시한다(client):
    got = _classify(client).json()

    design = next(r for r in got["recognized"] if r["key"] == "시험설계서")
    assert design["formNo"]["stale"] is True
    assert design["formNo"]["expected"] == "SST-K-TI-03-02(05)"


def test_양식번호가_없으면_미분류로_넘긴다(client):
    got = _classify(client).json()

    assert any("접수 문서" in f for f in got["unclassified"])


def test_참고_예시는_건너뛰되_목록으로_남긴다(client):
    got = _classify(client).json()

    assert [i["file"] for i in got["ignored"]] == ["99. 일반성적서 예시.pdf"]


def test_안_올라온_산출물을_알려준다(client):
    got = _classify(client).json()

    # 10종 중 3종만 줬다.
    assert len(got["missing"]) == 7
    assert "을지" in got["missing"]


def test_미분류를_사람이_지정할_수_있게_선택지를_준다(client):
    got = _classify(client).json()

    assert "갑지" in got["outputKeys"]
    assert len(got["outputKeys"]) == 10


def test_없는_팀은_404(client):
    assert _classify(client, team="없는팀").status_code == 404


def test_이름이_JSON_이_아니면_400(client):
    r = client.post("/api/classify-case",
                    data={"names": "not json", "team": "ai-test-cert-1"})

    assert r.status_code == 400


def test_폴더_검토_기준이_없는_팀은_그_사실을_말한다(client):
    """`outputs` 절은 xlsx 에서 안 나온다 — 사람이 문서를 열어보고 채우는 절이라
    팀 기준이 있어도 없을 수 있다(7팀 중 하나만 갖고 있다).

    없는 채로 돌리면 모든 파일이 조용히 "미분류"로 떨어진다. 검토자는 자기가
    파일을 잘못 올렸다고 생각하지, 기준이 없다고는 생각하지 않는다.
    """
    r = client.post("/api/classify-case",
                    data={"names": json.dumps(["갑지.pdf"]), "team": "EV3"})
    assert r.status_code == 400
    assert "폴더 검토 기준" in r.json()["detail"]

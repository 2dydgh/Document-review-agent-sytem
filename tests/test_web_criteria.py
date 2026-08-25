"""팀 검토 기준을 화면에 내려준다.

지금까지 기준은 `presets/criteria/teams/*.yaml` 파일뿐이었다. 화면에서 볼 수가 없어
검토자가 "왜 시험항목명이 미검토지?"를 알려면 YAML 을 열어야 했다.

여기서 재는 것: 기준을 **판정에 쓰인 그대로** 내려주는가. 화면이 다시 계산하거나
요약하면 실제로 도는 규칙과 화면이 갈린다.
"""
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402


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


def _get(client, team="ai-test-cert-1"):
    r = client.get(f"/api/teams/{team}/criteria")
    assert r.status_code == 200
    return r.json()


def test_산출물과_필드맵을_내려준다(client):
    got = _get(client)

    assert got["team"] == "AI시험인증1팀"
    keys = [o["key"] for o in got["outputs"]]
    assert "갑지" in keys and "을지" in keys


def test_필드가_어디서_어떻게_뽑히는지_그대로_내려준다(client):
    """화면이 "왜 이게 지적이지?"에 답하려면 라벨·형식·필수 여부가 있어야 한다.
    이름과 값만 주면 지금 리포트와 다를 게 없다."""
    got = _get(client)

    gapji = next(o for o in got["outputs"] if o["key"] == "갑지")
    cert = next(f for f in gapji["fields"] if f["name"] == "성적서번호")

    assert cert["labels"] == ["성적서번호"]
    assert cert["at"] == "right"
    assert cert["pattern"] == r"SST-\d{2}-\d{3}-C\d+"
    assert cert["required"] is True


def test_표_전체를_보는_필드도_내려준다(client):
    """from: table_rows 는 labels 가 아니라 columns 로 표를 찾는다. 화면이
    "라벨 없음"으로 그리면 기준을 잘못 보여주게 된다."""
    got = _get(client)

    확인증 = next(o for o in got["outputs"] if o["key"] == "제출물 확인증")
    목록 = next(f for f in 확인증["fields"] if f["name"] == "제출물목록")

    assert 목록["from"] == "table_rows"
    assert "제출물명" in 목록["columns"]
    assert "제출물명" in 목록["requiredColumns"]


def test_고정문구와_서명란도_기준이다(client):
    got = _get(client)

    gapji = next(o for o in got["outputs"] if o["key"] == "갑지")

    assert any("슈어소프트테크" in s for s in gapji["fixedText"])
    assert [s["role"] for s in gapji["signatures"]] == ["시험실무자", "기술책임자"]
    assert gapji["signatures"][0]["at"] == "below"


def test_전_산출물_대조_항목을_내려준다(client):
    """리포트의 "시험항목명 0/4" 에서 여기로 건너뛴다 — 어느 4곳을 봐야 했는지
    알아야 왜 못 봤는지 짚을 수 있다."""
    got = _get(client)

    item = next(c for c in got["caseWide"] if c["id"] == "W-시험항목명")

    assert item["field"] == "시험항목명"
    assert len(item["outputs"]) == 4


def test_outputs_all_은_풀어서_내려준다(client):
    """화면이 "all" 이라는 글자를 그리면 검토자는 몇 곳인지 모른다."""
    got = _get(client)

    assert all(isinstance(c["outputs"], list) for c in got["caseWide"])


def test_쌍과_직접_확인도_내려준다(client):
    got = _get(client)

    assert [p["id"] for p in got["pairs"]] == ["1-7", "1-12", "1-16"]
    assert [m["id"] for m in got["manual"]] == \
        ["M-접수번호", "M-접수일", "M-의뢰기관명"]


def test_건너뛰는_규칙도_내려준다(client):
    """"왜 이 파일은 검사 안 했지?"의 답이다."""
    got = _get(client)

    assert got["ignore"] == [{"pattern": "^99\\.", "reason": "참고 예시"}]


def test_필드맵이_없는_팀도_거절하지_않는다(client):
    """EV1·EV3 등은 아직 items 만 있다. 비었다고 404 를 내면 화면이 "그런 팀이
    없다"고 말하는데, 실제로는 팀은 있고 기준이 아직 없는 것이다."""
    got = _get(client, "EV1")

    assert got["outputs"] == []
    assert got["caseWide"] == []


def test_팀이_준_요구사항_항목_수를_알려준다(client):
    """items 는 팀이 준 원문 요구사항이다. 전문은 길어 여기서 다 내리지 않되,
    몇 개인지는 알려야 "기준이 이게 다인가?"에 답할 수 있다.

    수를 박지 않는 이유: 이 팀 기준은 xlsx 13건 + 단일문서.md 45건으로 늘었고
    md 가 갱신되면 또 는다. 박아 두면 기준을 늘릴 때마다 이 줄이 깨진다 —
    여기서 지킬 것은 "0 이 아니고 화면이 세는 수와 같다"는 것뿐이다.
    """
    got = _get(client)

    assert got["itemCount"] == len(_load_items())
    assert got["itemCount"] > 0


def test_없는_팀은_404(client):
    r = client.get("/api/teams/없는팀/criteria")

    assert r.status_code == 404


def test_경로를_지어내지_못한다(client):
    """브라우저 문자열을 경로로 쓰면 서버의 아무 파일이나 읽힌다."""
    r = client.get("/api/teams/..%2F..%2Fsettings/criteria")

    assert r.status_code in (404, 400)


# ── 필드 중심 보기 ───────────────────────────────────────────────────────

def test_필드별로도_묶어_내려준다(client):
    """산출물별로만 주면 의뢰번호가 7번 반복된다(48줄 · 실제 필드는 20개).
    "의뢰번호를 어디서 어떻게 뽑나"가 한 자리에 모여야 한다."""
    got = _get(client)

    names = [f["name"] for f in got["fields"]]
    assert len(names) == len(set(names)), "필드 이름이 겹친다 — 안 묶였다"
    assert "의뢰번호" in names


def test_필드마다_어느_산출물에서_어떻게_뽑는지_붙는다(client):
    got = _get(client)

    req = next(f for f in got["fields"] if f["name"] == "의뢰번호")

    assert len(req["where"]) == 7
    계획서 = next(w for w in req["where"] if w["output"] == "시험계획서")
    assert 계획서["labels"] == ["의뢰번호"]
    assert 계획서["at"] == "below"       # 계획서 머리표는 가로다
    assert 계획서["required"] is True


def test_필드가_어느_대조에_쓰이는지_알려준다(client):
    """"7곳에서 같아야 한다"는 대조 규칙이고 "라벨은 이것"은 추출 규칙이다.
    둘이 한 자리에 있어야 검토자가 왜 미검토인지 짚을 수 있다."""
    got = _get(client)

    req = next(f for f in got["fields"] if f["name"] == "의뢰번호")
    assert req["caseWide"] == "W-의뢰번호"
    assert req["pairs"] == []

    rep = next(f for f in got["fields"] if f["name"] == "대표자")
    assert rep["caseWide"] == ""
    assert rep["pairs"] == ["1-7"]


def test_대조_기준은_있는데_뽑을_곳이_없는_필드도_낸다(client):
    """시험항목명은 4곳에서 같아야 하는데 어느 문서에도 필드맵이 없다.
    빠뜨리면 "0/4 미검토"를 눌러도 갈 곳이 없다."""
    got = _get(client)

    item = next(f for f in got["fields"] if f["name"] == "시험항목명")

    assert item["where"] == []
    assert item["caseWide"] == "W-시험항목명"


def test_산출물별_보기도_그대로_남는다(client):
    """"갑지를 검사할 때 뭘 보나"도 여전히 답해야 한다."""
    got = _get(client)

    assert any(o["key"] == "갑지" for o in got["outputs"])


def _load_items():
    """기준 파일에서 직접 센다. 서버가 세는 수와 맞는지 보려면 원본이 필요하다."""
    import yaml
    text = Path("presets/criteria/teams/ai-test-cert-1.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text).get("items", [])

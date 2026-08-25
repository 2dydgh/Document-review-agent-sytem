"""단일 검토에도 칸 값 검사를 건다.

`FieldPresenceChecker` 는 팀 기준의 `outputs` 절(어느 산출물의 어느 칸을 어떻게
뽑나)이 만든다. 그 절은 폴더 검토만 읽고 있었는데, 표지 정보·개정기록처럼 **문서
하나만 보고 판정되는** 항목이라 단일 검토의 몫이다
(docs/checker-inventory.md "A. 칸 값 검사" 8항목).

막혔던 지점은 판별이다 — 문서 하나만 받으면 어느 산출물인지부터 가려야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.case import presence_checker_for  # noqa: E402
from app.server import create_app  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def _spec(stem: str) -> dict:
    path = _ROOT / "presets" / "criteria" / "teams" / f"{stem}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_양식번호로_산출물을_가린다():
    checker, why = presence_checker_for(
        "SST-K-TP-7-08-06(00) 시험성적서(갑지).docx", _spec("ai-test-cert-1"))
    assert checker is not None and why == ""


def test_못_가리면_검사를_걸지_않고_이유를_남긴다():
    """추측해서 배정하면 엉뚱한 필드맵으로 검사해 거짓 지적이 난다."""
    checker, why = presence_checker_for("아무거나.docx", _spec("ai-test-cert-1"))
    assert checker is None
    assert "가리지 못해" in why


def test_후보가_하나뿐이면_그것이다():
    """추측이 아니라 선택지가 없는 것이다. EV2 는 RVVR 필드맵 하나뿐이고
    양식번호가 없어, 이 경로가 없으면 영영 칸 값 검사를 못 받는다."""
    checker, why = presence_checker_for("아무_이름.docx", _spec("EV2"))
    assert checker is not None and why == ""


def test_칸_값_기준이_없는_팀은_말할_것도_없다():
    checker, why = presence_checker_for("x.docx", _spec("EV3"))
    assert checker is None and why == ""


@pytest.fixture
def client(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
                        encoding="utf-8")
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=tmp_path / "history"))


def _findings(client, name: str, team: str) -> list[dict]:
    doc = "# 보고서\n\n| 작 성 자 : |  | Date : |  |\n".encode()
    r = client.post("/api/review",
                    files={"file": (name, doc, "text/markdown")},
                    data={"llm": "off", "checklist": team})
    assert r.status_code == 200, r.text
    events = [json.loads(l[5:]) for block in r.text.split("\n\n")
              for l in block.splitlines() if l.startswith("data:")]
    return events[-1]["payload"]["findings"]


def test_단일_검토가_빈_칸을_지적한다(client):
    msgs = [f["message"] for f in _findings(client, "RVVR_Rev08.md", "EV2")]
    assert any("'작성자'" in m and "비어 있습니다" in m for m in msgs), msgs


def test_못_찾은_칸은_지적이_아니라_미검토다(client):
    """라벨맵이 문서와 어긋난 것과 문서가 비어 있는 것은 다르다."""
    found = _findings(client, "RVVR_Rev08.md", "EV2")
    missing = [f for f in found if "'발행일'" in f["message"]]
    assert missing and missing[0]["sev"] == "info", found


def test_못_가린_문서는_그_사실을_남긴다(client):
    """조용히 건너뛰면 '표지를 봤는데 이상 없음'과 '아예 안 봤음'이 같아 보인다."""
    msgs = [f["message"] for f in _findings(client, "아무거나.md", "ai-test-cert-1")]
    assert any("칸 값 검사를 걸지 않았습니다" in m for m in msgs), msgs


def test_팀을_안_고르면_칸_값_검사를_걸지_않는다(client):
    msgs = [f["message"] for f in _findings(client, "RVVR_Rev08.md", "")]
    assert not any("비어 있습니다" in m for m in msgs), msgs

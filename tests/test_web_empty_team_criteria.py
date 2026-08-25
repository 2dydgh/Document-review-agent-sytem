"""팀 기준이 비어 있으면 그 사실을 말한다.

`presets/criteria/teams/` 에는 `items: []` 3줄짜리 빈 껍데기가 있다(우주항공SW기술팀
· 미래국방SW기술팀 · 미래국방SW검증팀). 그 팀을 골라 단일 검토를 돌리면 공통 기준만
돌고, 팀 기준은 하나도 안 붙는다.

그런데 화면은 아무 말도 안 했다 — orchestrator 의 "기준 없음" 가드는 criteria 가
**완전히** 빌 때만 뜨는데 공통 기준이 늘 들어가서 절대 안 뜨고, 칸 값 검사 쪽은
`output_spec_for` 가 이유를 빈 문자열로 돌려줘 서버의 `if why:` 를 그냥 빠져나갔다.

결과가 "팀 기준으로 검토했더니 이상 없음"과 구분되지 않는다. CLAUDE.md 가 금지한
조용한 0건이다 — "0건 통과"와 "검토를 못 했다"를 절대 섞지 않는다.
"""
from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402

# 빈 껍데기 팀과, 비교 대조군으로 쓸 실제 기준이 있는 팀.
EMPTY_TEAM = "aero-sw-tech"
FILLED_TEAM = "EV2"

# 경고에 실리는 팀 이름. 파일 stem 이 아니라 yaml 의 `name` 이다 — 검토자가 화면에서
# 보는 값이라 그것으로 검사한다.
EMPTY_TEAM_NAME = "우주항공SW기술팀"

# 빈 팀 경고를 알아보는 표식. **실제 메시지에 있는 문자열이어야 한다.**
# 예전에는 "검토 기준이 비어" 를 찾았는데 메시지는 "검토 기준이 **아직** 비어" 라
# 부분문자열이 안 맞았다. `not in` 이 늘 참이 되어 아무것도 안 지키는 검사였다.
# 팀 이름으로도 안 된다 — 경고가 모든 팀에 발동하면 그 팀 이름이 실려 나가므로
# 빈 팀 이름은 여전히 안 보인다. 경고 **자체**를 가리키는 문구를 쓴다.
EMPTY_TEAM_NOTICE = "공통 기준으로만"


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


def _findings(client, team: str) -> list[dict]:
    r = client.post("/api/review",
                    files={"file": ("d.md", b"# A\n\xea\xb0\x9c\xec\x9a\x94\n", "text/markdown")},
                    data={"checklist": team, "llm": "off"})
    assert r.status_code == 200, r.text
    events = [json.loads(line[5:].strip())
              for block in r.text.split("\n\n") for line in block.splitlines()
              if line.startswith("data:")]
    return events[-1]["payload"]["findings"]


def test_빈_팀_기준은_검토하지_못했다고_말한다(client):
    msgs = " ".join(f["message"] for f in _findings(client, EMPTY_TEAM))
    assert EMPTY_TEAM_NOTICE in msgs, (
        f"팀 기준이 비었는데 그 사실을 말하지 않는다:\n{msgs}")
    # 어느 팀인지도 말해야 한다. 경고만 뜨고 이름이 없으면 검토자는 자기 팀 얘기인지
    # 모른다.
    assert EMPTY_TEAM_NAME in msgs, f"경고에 팀 이름이 없다:\n{msgs}"


def test_기준이_있는_팀에는_그_경고를_붙이지_않는다(client):
    """빈 팀 경고가 모든 검토에 붙으면 그건 그냥 소음이다.

    **문구가 아니라 팀 이름으로 본다.** 예전에는 "검토 기준이 비어" 를 찾았는데
    실제 메시지는 "검토 기준이 **아직** 비어" 라 부분문자열이 안 맞았다. `not in`
    이 늘 참이 되어, 가드가 모든 팀에 발동해도 초록불이었다. 이름은 화면에 그대로
    나가는 값이라 문구를 다듬어도 이 검사가 살아 있는다.
    """
    msgs = " ".join(f["message"] for f in _findings(client, FILLED_TEAM))
    assert EMPTY_TEAM_NOTICE not in msgs, msgs

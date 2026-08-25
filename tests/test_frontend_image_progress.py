"""그림 읽는 동안 화면이 멈춘 것처럼 보이지 않게 지키는 회귀 테스트.

프론트엔드는 빌드도 JS 테스트 러너도 없는 바닐라 SPA라, 소스 수준에서 막는다.

진행 이벤트 계약이 이렇다(src/app/orchestrator.py · web/api.js):

    key="review"  이면  plan → step 으로 격자를 채운다
    그 밖의 key   이면  done 일 때만 결과로 접어 보여준다

그림 해석은 `key="ingestion"` 으로 `status="running"` 을 보낸다. 한 장에 2~3초라
(실측 1.8~3.4초) 그림이 여럿이면 준비 단계가 수십 초 걸리는데, done 만 보던 옛
코드에서는 그 동안 준비 문구에서 멈춘 것처럼 보였다.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
API_JS = (_ROOT / "web" / "api.js").read_text(encoding="utf-8")
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
IMAGES_PY = (_ROOT / "src" / "app" / "images.py").read_text(encoding="utf-8")


def test_engine_sends_running_progress_while_reading_images():
    """보내는 쪽이 먼저 있어야 화면이 받을 것이 있다."""
    assert '"status": "running"' in IMAGES_PY
    assert '"key": "ingestion"' in IMAGES_PY
    assert "읽는 중" in IMAGES_PY


def test_api_js_shows_running_detail_of_non_review_stages():
    """준비 단계의 running detail 을 버리지 않는다.

    옛 코드는 `if (ev.status === "done")` 만 있어 running 이 조용히 사라졌다.
    """
    # ev.key !== "review" 분기 안에 done 아닌 경우의 처리가 있어야 한다.
    branch = API_JS.split('if (ev.key !== "review") {', 1)[1].split("} else if (ev.plan)", 1)[0]
    assert "ev.status === \"done\"" in branch
    assert "else if (ev.detail)" in branch, "running detail 을 받는 분기가 없다"
    assert "r.note = ev.detail" in branch, "진행 문장을 note 로 흘려야 화면에 뜬다"
    assert "partial = true" in branch, "부분 갱신이어야 '검토 취소' 버튼이 깜빡이지 않는다"


def test_views_js_renders_the_note_before_lanes_exist():
    """레인이 생기기 전(준비 단계)에도 note 가 보여야 한다.

    이게 없으면 api.js 가 note 를 채워도 화면에 나타나지 않는다.
    """
    assert re.search(r"var note = !lanes\s*\?", VIEWS_JS), \
        "레인이 없을 때의 note 렌더가 사라졌다"
    # 기본 문장은 "무엇을" 준비하는지 말한다 — 예전 "검토를 준비하는 중…"은
    # 수십 초 도는 동안 무엇을 기다리는지 알려주지 않았다.
    assert "준비하고 있습니다" in VIEWS_JS
    # note 가 있으면 그것을, 없으면 기본 문장을 쓴다.
    assert re.search(r"esc\(r\.note \|\| \"[^\"]*준비하고 있습니다", VIEWS_JS)


def test_끝나도_진행_줄이_사라지지_않는다():
    """완료 순간 아래 진행 줄이 통째로 빠지면 진행이 되감긴 것처럼 보인다.

    `전체 100% · 0:03 경과` 를 말하던 자리가 갑자기 빈칸이 되었다. 실제로
    "진행바가 리셋된다"고 읽혔다. 사라져야 하는 것은 취소 단추뿐이다 —
    끝난 일을 취소할 수는 없다.
    """
    body = VIEWS_JS[VIEWS_JS.index("function singleProgress("):]
    body = body[:body.index("\n  }")]
    foot = body[body.index("var foot ="):]
    foot = foot[:foot.index("return '<div data-scroll=\"progress\"")]

    assert 'var foot = v.done ? ""' not in foot, "끝나면 진행 줄을 통째로 지운다"
    assert "pg-pct" in foot and "pg-elapsed" in foot, "퍼센트·경과가 빠졌다"
    # 취소 단추만 조건부로 빠진다.
    assert 'v.done ? "" :' in foot, "끝나도 취소 단추가 남는다"
    assert "cancelReview" in foot


def test_끝난_화면을_읽을_시간을_준다():
    """800ms 는 "검토 완료" 를 읽기 전에 결과 화면으로 넘어가 버렸다."""
    api = (_ROOT / "web" / "api.js").read_text(encoding="utf-8")
    hold = re.search(r"DONE_HOLD_MS = (\d+)", api)
    assert hold, "완료 화면을 붙잡는 시간이 없다"
    assert int(hold.group(1)) >= 1200, f"너무 짧다: {hold.group(1)}ms"


def test_완료_머리말은_한_번만_등장한다():
    """이력 응답과 완료 타이머가 같은 등장 애니메이션을 거듭 시작하면 안 된다."""
    hold = API_JS[API_JS.index("function holdDone("):]
    hold = hold[:hold.index("\n  function errMessage")]
    reveal = hold[hold.index("function revealDone()") :]
    assert "markDone();" not in hold[:hold.index("function revealDone()")], \
        "완료 공개 전에 상태를 바꿔 다른 render가 먼저 완료 화면을 그린다"
    assert reveal.index("markDone();") < reveal.index("render();"), \
        "최종 render 한 번에서 완료 상태를 공개하지 않는다"
    assert "loadHistory(true)" in API_JS, \
        "백그라운드 이력 동기화가 완료 애니메이션을 다시 시작한다"


def test_마지막_진행바는_끝까지_찬_뒤_완료로_바뀐다():
    """run 노드를 바로 교체하면 마지막 몇 %의 transform 전환이 잘려 점프한다."""
    app = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    update = app[app.index("function updateLanesInPlace"):]
    update = update[:update.index("\n  }")]
    assert 'before === "run" && m.status === "done"' in update
    assert 'setAttribute("data-lane-status", "finishing")' in update
    assert 'lastFill.style.transform = "scaleX(1)"' in update
    # 300ms fill 뒤 80ms 지연된 300ms 체크까지 끝낼 여유가 있어야 한다.
    settle = re.search(r"function \(\) \{ if \(state\.screen.*?\},\s*.*?(\d+)\);", API_JS, re.S)
    assert settle and int(settle.group(1)) >= 700


def test_진행_화면에_떠다니는_배경_장식이_없다():
    """검토는 최대 5분이고, 그동안 사용자는 이 화면을 본다.

    예전엔 600·500px 짜리 흐린 원(floatOrb1/2)이 15초·12초 주기로 떠다녔다.
    3초 스치는 로그인 화면과 달리 여기서는 5분을 본다 — 느린 전면 반복은
    설정으로 줄일 게 아니라 애초에 없어야 한다.

    가로 스크롤을 막던 `overflow-x:hidden` 도 같이 없앴다. 오른쪽으로
    삐져나가 스크롤을 만들던 것이 바로 그 원들이었기 때문이다 — 원인이 사라진
    가드를 남겨 두면 진짜 넘침이 생겼을 때 조용히 잘려 안 보인다.
    """
    for key in ("progress", "case-progress"):
        box = VIEWS_JS[VIEWS_JS.index(f'data-scroll="{key}"'):]
        box = box[:box.index("progressHead(")]
        assert "floatOrb" not in box, f"{key} 에 떠다니는 배경 장식이 남아 있다"
        assert "overflow-y:auto" in box, f"{key} 가 세로로 안 넘어간다"
        # 진행 패널은 홈·결과와 같은 불투명 면이다 — 한 흐름 안에서 재질이 튀면
        # 같은 앱의 다른 단계가 아니라 다른 앱처럼 읽힌다.
        assert "backdrop-filter" not in box, f"{key} 패널이 아직 유리다"
        assert "var(--panel)" in box, f"{key} 패널이 불투명 면을 안 쓴다"

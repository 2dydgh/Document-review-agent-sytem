"""헤더의 프로필·알림 팝오버.

바닐라 SPA 라 소스 수준에서 막는다. 여기서 지키는 것은 둘.

1. **소속 팀을 보여준다.** 로그인한 팀이 곧 검사 기준이다(app.js doLogin 이
   state.checklist 에 건다). 어느 팀으로 들어와 있는지 확인할 자리가 없으면,
   팀 기준 수십 건이 빠진 채로 돈 것을 검토자가 알 방법이 없다.
2. **바깥을 누르면 닫힌다.** 팝오버를 열어둔 채 다른 곳을 눌러도 계속 떠 있으면
   사용자는 같은 버튼을 다시 찾아 눌러야 한다.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")


def _profile_menu() -> str:
    """프로필 팝오버를 만드는 구간만 잘라 온다."""
    start = VIEWS_JS.index("if (state.profileMenuOpen) {")
    # 끝 표시는 바로 뒤에 오는 검색 모달이다. 예전엔 알림 팝오버(`var dropNoti`)가
    # 그 자리에 있었는데 지어낸 알림이라 지웠다(test_알림은_지어내지_않는다).
    return VIEWS_JS[start:VIEWS_JS.index('var searchModal = ""', start)]


def test_프로필에_소속_팀이_뜬다() -> None:
    menu = _profile_menu()
    assert "소속 팀" in menu, "소속 팀 줄이 없다"
    assert "teamLabel(" in menu, "팀 이름을 어디서 가져오는지가 없다"


def test_프로필_이니셜은_두_테마에서_솔리드다() -> None:
    """사용자 표식은 상태 칩이 아니므로 반투명 --accent-weak를 쓰지 않는다."""
    menu = _profile_menu()
    assert 'class="profile-menu-avatar"' in menu
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    start = css.index(".profile-menu-avatar {")
    rule = css[start:css.index("}", start)]
    assert "background: var(--accent-surface)" in rule
    assert "accent-weak" not in rule


def test_팀은_id_가_아니라_이름으로_뜬다() -> None:
    """state.user.team 에는 기준 파일명("ai-test-cert-1")이 들어 있다.

    그대로 찍으면 사람이 읽을 것이 아니다. 목록은 서버가 /api/health 로 주는
    {id, name} 이고, 목업 모드에서는 문자열이라 id 와 이름이 같다 — 둘 다 받는다.
    """
    assert "function teamLabel(" in VIEWS_JS, "id → 이름 변환이 없다"
    fn = VIEWS_JS[VIEWS_JS.index("function teamLabel("):]
    fn = fn[:fn.index("\n  }") + 4]
    assert 'typeof o === "string"' in fn, "목업 목록(문자열)에서 깨진다"
    assert "o.id === id" in fn, "서버 목록({id, name})에서 이름을 못 찾는다"
    # 못 찾았을 때 빈칸을 주면 "팀 미지정"으로 읽혀 실제 미지정과 구분이 안 된다.
    assert fn.rstrip().rstrip("}").rstrip().endswith("return id;"), \
        "못 찾았을 때 빈칸을 돌려준다 — 미지정과 구분이 안 된다"


def test_팀이_없으면_있는_척하지_않는다() -> None:
    """팀이 안 걸린 계정은 공통 기준만으로 돈다 — 그 사실이 눈에 띄어야 한다."""
    menu = _profile_menu()
    assert "미지정" in menu, "팀이 비었을 때 아무 말도 안 한다"


def test_요금제_관리는_없다() -> None:
    """사내망 도구라 요금제가 없다. 있지도 않은 것을 흉내내면 나머지 항목까지
    목업으로 읽힌다.

    주석은 "왜 뺐는가"를 적을 수 있으므로 화면에 나가는 줄만 본다 — 안 그러면
    이 변경을 설명하는 주석 자신이 걸린다(test_frontend_case.py 와 같은 함정).
    """
    visible = "\n".join(l for l in VIEWS_JS.split("\n")
                        if not l.lstrip().startswith("//"))
    for gone in ("요금제", "Pro Plan"):
        assert gone not in visible, f"'{gone}' 가 화면에 남아 있다"


def test_팝오버는_바깥을_누르면_닫힌다() -> None:
    """열어둔 채 다른 곳을 눌러도 남아 있으면 같은 버튼을 다시 찾아 눌러야 한다.

    이미 내보내기 메뉴(#exportMenu)가 쓰던 규칙이다 — 프로필·알림만 빠져 있었다.
    (알림 팝오버는 지웠다 — test_알림은_지어내지_않는다 참고.)
    """
    click = APP_JS[APP_JS.index('document.addEventListener("click"'):]
    guard = click[:click.index('if (act !== "selToggle"')]
    for menu_id, open_flag, toggle in (
        ("#profileMenu", "state.profileMenuOpen", "toggleProfile"),
    ):
        assert menu_id in guard, f"{menu_id} 안을 눌렀는지 안 본다"
        assert open_flag in guard, f"{open_flag} 를 안 본다"
        # 자기 자신을 여닫는 버튼은 빼야 한다 — 안 그러면 여기서 닫고 액션이
        # 다시 열어 버튼이 먹통이 된다.
        assert f'act !== "{toggle}"' in guard, f"{toggle} 버튼이 먹통이 된다"

    # 팝오버 안의 로그아웃은 위 규칙이 못 잡는다(메뉴 안이라 제외된다).
    set_mode = APP_JS[APP_JS.index("setMode: function (m) {"):]
    set_mode = set_mode[:set_mode.index("render();")]
    assert "state.profileMenuOpen = false" in set_mode, \
        "로그아웃하면 메뉴가 열린 채로 남는다"


def test_팝오버에_id_가_붙어_있다() -> None:
    """바깥 클릭 규칙이 이 id 로 안팎을 가른다 — 마크업에서 빠지면 조용히 깨진다."""
    for menu_id in ('id="profileMenu"',):
        assert menu_id in VIEWS_JS, f"{menu_id} 가 마크업에 없다"


def test_알림은_지어내지_않는다() -> None:
    """헤더 종에 목업 알림 둘과, 늘 켜져 있는 안 읽음 빨간 점이 떠 있었다.

    홈에서 목업 4건을 걷어낸 것과 같은 문제였다 — 없는 것을 지어내 보여주면
    진짜와 구별할 방법이 없다.

    지금은 **앱이 직접 본 사건만** 담는다. 검사를 걸어놓고 다른 화면으로 옮겨도
    SSE 스트림은 계속 돌아서(setMode 가 안 끊는다) 끝나도 그 화면에 없으면
    조용히 끝난다 — 그때만 쌓인다.

    주석은 "왜 뺐는가"를 적으므로 화면에 나가는 줄만 본다.
    """
    visible = "\n".join(l for l in VIEWS_JS.split("\n")
                        if not l.lstrip().startswith("//"))
    for gone in ("알림 센터", "모두 읽음 처리", "결제 모듈 명세서", "김개발"):
        assert gone not in visible, f"'{gone}' 가 화면에 남아 있다"

    # 목록은 state 에서 온다 — 마크업에 박힌 항목이 아니다.
    assert "state.notis" in VIEWS_JS, "알림을 state 에서 안 읽는다"

    # 빨간 점은 **안 읽은 것이 있을 때만**. 늘 떠 있으면 아무 뜻도 없다.
    bell = VIEWS_JS[VIEWS_JS.index('data-act="toggleNoti"'):]
    bell = bell[:bell.index("</span>' +\n        '<div style=\"width:1px")]
    assert "unread" in bell, "안 읽은 것이 없어도 점이 뜬다"

    # 세션 목록이라는 것을 화면이 말해야 한다. 안 밝히면 새로고침 뒤 빈 목록이
    # 고장으로 읽힌다.
    assert "새로고침하면 비워집니다" in VIEWS_JS, "세션 목록임을 안 밝힌다"


def test_보고_있었으면_알리지_않는다() -> None:
    """진행 화면을 지켜본 사람에게 "끝났습니다"는 이미 아는 말이다.

    화면을 떠났는지는 mode 와 screen 을 **둘 다** 봐야 안다 — setMode 는 screen 을
    건드리지 않으므로, 홈으로 옮겨도 screen 은 "progress" 로 남아 있다.
    screen 만 보면 홈에 있는 사람을 "보고 있다"로 판정해 알림을 놓친다.
    """
    api = (Path(__file__).resolve().parents[1] / "web" / "api.js").read_text(encoding="utf-8")
    assert "function notify(" in api, "알림 헬퍼가 없다"
    body = api[api.index("function notify("):]
    body = body[:body.index("\n  }")]
    assert "opts.watching" in body, "보고 있었는지를 안 본다"

    # 단일 검토 완료 지점.
    call = api[api.index("notify(("):]
    call = call[:call.index("});")]
    assert "state.mode ===" in call and "state.screen ===" in call, \
        "화면을 떠났는지를 mode·screen 둘 다로 안 본다"


def test_검색은_진짜_목록을_뒤진다() -> None:
    """예전엔 "최근 검색 항목"이라며 목업 둘이 박혀 있었다 — 검색어를 저장한
    적이 없으므로 그건 아무의 최근 검색도 아니었다.

    지금은 이미 받아 둔 목록 둘(검토 기록 제목·체크리스트 이름)을 뒤진다.
    """
    visible = "\n".join(l for l in VIEWS_JS.split("\n")
                        if not l.lstrip().startswith("//"))
    assert "최근 검색 항목" not in visible, "지어낸 최근 검색이 남아 있다"
    assert "PRD 체크리스트 설정" not in visible, "목업 검색 결과가 남아 있다"

    # 결과는 state 의 진짜 목록에서 나온다.
    body = VIEWS_JS[VIEWS_JS.index("function searchResultsHtml("):]
    body = body[:body.index("\n  function ")]
    assert "state.history" in body, "검토 기록을 안 뒤진다"
    assert "state.clib" in body, "체크리스트를 안 뒤진다"

    # 자른 건수를 드러낸다 — 조용히 8건만 보이면 "그게 전부"로 읽힌다.
    group = VIEWS_JS[VIEWS_JS.index("function searchGroup("):]
    group = group[:group.index("\n  var SEARCH_MAX")]
    assert "더 있습니다" in group, "잘린 건수를 안 밝힌다"

    # 입력은 state 에 있어야 한다 — DOM 에 들고 있으면 render() 한 번에 날아간다.
    assert "state.searchQ" in APP_JS, "검색어를 state 에 안 둔다"
    # 타이핑 중에는 결과 목록만 갈아끼운다. render()를 부르면 <input> 이 새로
    # 만들어져 포커스도 캐럿도 조합 중인 한글도 날아간다.
    listener = APP_JS[APP_JS.index('closest("[data-search-q]")'):]
    listener = listener[:listener.index("});")]
    assert "searchResultsHtml" in listener, "결과만 갈아끼우지 않는다"
    assert "render()" not in listener, "타이핑마다 화면을 다시 그린다"


def test_로그아웃은_세션을_비운다() -> None:
    """`setMode("login")` 은 화면만 바꾼다 — 앞사람의 state 가 그대로 남는다.

    실제로 kase.team 이 살아남아, 팀 없는 계정으로 로그인해도 화면엔 "미지정"이
    뜨면서 요청은 앞사람 팀으로 나갔다. 남의 팀 기준으로 검토된다는 뜻이다.
    """
    menu = _profile_menu()
    assert 'data-act="doLogout"' in menu, "로그아웃이 doLogout 을 안 부른다"
    assert 'data-act="setMode" data-arg="login"' not in menu

    start = APP_JS.index("doLogout: function")
    body = APP_JS[start:APP_JS.index("},", start)]
    assert "location.reload()" in body, "state 를 손으로 비우면 반드시 하나 빠진다"


def test_팀_없는_계정으로_로그인하면_앞사람_팀이_안_남는다() -> None:
    start = APP_JS.index("doLogin: function")
    body = APP_JS[start:APP_JS.index("toggleProfile:", start)]
    assign = body.index("state.kase.team = uTeam")
    guard = body.index("if (uTeam) {")
    assert assign < guard, "팀 대입이 if (uTeam) 안에 있으면 빈 팀일 때 안 비워진다"


# ── 검토 결과의 상태 어휘 ──────────────────────────────────────────────────
# "검사 안 됨" 하나로 뭉쳐 있던 것을 넷으로 갈랐다. 검토자가 할 일이 다르기 때문이다.
#   응답 없음      LLM 이 아예 안 답했다      → 서버·설정을 고친다
#   검사 안 됨     기준값이 비었거나(규칙)     → 기준을 채운다
#                  그 기준 판정만 안 왔다(LLM) → 다시 돌린다
#   해당 없음      이 기준이 이 문서 대상이 아니다 → 고칠 것 없음
#   검토 대상 아님 애초에 문서 검토 항목이 아니다  → 고칠 것 없음

def test_결과_상태가_할_일별로_갈려_있다() -> None:
    views = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
    body = "\n".join(l for l in views.split("\n") if not l.lstrip().startswith("//"))
    for status, label in (("noanswer", "응답 없음"),
                          ("unreviewed", "검사 안 됨"),
                          ("na", "해당 없음"),
                          ("outofscope", "검토 대상 아님"),
                          ("manual", "사람 확인 필요")):
        assert f'it.status === "{status}"' in body or status == "manual", \
            f"{status} 를 항목 배지가 안 본다"
        assert label in body, f"'{label}' 라벨이 없다"


def test_고칠_것이_없는_상태는_그렇다고_말한다() -> None:
    """'해당 없음'·'검토 대상 아님' 을 "검사 안 됨" 으로 읽으면 검토자가 장비·설정을
    뒤진다. 정상이라는 것을 문구로 분명히 한다."""
    views = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
    assert "고칠 것이 없습니다" in views, "해당 없음이 정상임을 안 말한다"
    assert "산출물을 만들거나 이력을 관리하는 기능" in views, \
        "검토 대상 아님의 이유가 없다"

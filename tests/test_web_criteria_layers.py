"""검토 기준 화면이 3층을 다 보여준다.

검토는 공통 ∪ 팀 ∪ 업로드를 합쳐 돌지만(resolve_criteria), 화면에는 어디서 온
기준인지 갈라 보여야 한다 — 고칠 수 있는 층은 업로드뿐이고, 팀에 "이건 전사 공통,
저건 우리 기준"이라고 말할 수 있어야 한다.

`/api/teams/{team}/criteria` 와 다르다. 그쪽은 폴더 검토가 쓰는 구조 절(어느
산출물의 어느 칸을 어떻게 뽑나)을 내고 items 는 개수만 낸다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")


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


def test_팀을_고르면_공통과_팀_두_층이_온다(client):
    body = client.get("/api/criteria", params={"team": "EV2"}).json()
    scopes = [L["scope"] for L in body["layers"]]
    assert scopes[:2] == ["공통", "팀별"]
    assert body["layers"][1]["name"] == "에너지검증 2팀"


def test_팀을_안_고르면_공통만_온다(client):
    body = client.get("/api/criteria").json()
    assert [L["scope"] for L in body["layers"]] == ["공통"]


def test_씨앗_층은_읽기_전용이다(client):
    """팀 프리셋·공통 프리셋은 일반 사용자가 고칠 수 없다(기능명세서 2.3)."""
    body = client.get("/api/criteria", params={"team": "EV2"}).json()
    assert all(L["editable"] is False for L in body["layers"])


def test_항목마다_실제로_검사되는지를_말한다(client):
    """기준은 수십 건인데 검사기가 받는 것은 그중 일부다. 그 차이가 안 보이면
    검토자는 "기준에 있으니 검사됐겠지"라고 읽는다."""
    body = client.get("/api/criteria", params={"team": "EV2"}).json()
    team = next(L for L in body["layers"] if L["scope"] == "팀별")
    hows = {i["howChecked"] for i in team["items"]}
    assert hows <= {"규칙 · 자동", "LLM · 자동", "사람이 확인"}
    assert "사람이 확인" in hows and "규칙 · 자동" in hows, hows
    # 본문이 개수만이 아니라 전문으로 와야 이 화면이 값어치가 있다.
    assert all(i["text"] for i in team["items"])


def test_없는_팀은_거절한다(client):
    assert client.get("/api/criteria", params={"team": "../settings"}).status_code == 400


def test_화면이_읽기전용_층을_그린다():
    view = VIEWS_JS[VIEWS_JS.index("function checklistsView("):
                    VIEWS_JS.index("function clibPreviewCard(")]
    assert "criteriaLayersSection(v)" in view, "3층이 화면에 안 붙었다"
    assert "내가 올린 체크리스트" in view, "업로드 층의 이름표가 없다"
    section = VIEWS_JS[VIEWS_JS.index("function criteriaLayerCard("):
                       VIEWS_JS.index("function checklistsView(")]
    assert "읽기 전용" in section
    for how in ("규칙 · 자동", "LLM · 자동", "사람이 확인"):
        assert how in VIEWS_JS, f"{how} 배지가 없다"


def test_못_읽는_업로드_하나가_화면_전체를_죽이지_않는다(tmp_path):
    """깨진 업로드 한 건 때문에 공통·팀 층까지 통째로 사라지면 안 된다.

    ChecklistStore.list() 는 깨진 파일을 건너뛰지만 get() 은 던진다. 그 예외를
    안 받아서 /api/criteria 가 500 이 났고, 이 화면은 진입할 때마다 부른다.
    """
    settings = tmp_path / "settings.toml"
    settings.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
                        encoding="utf-8")
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")

    uploads = tmp_path / "criteria" / "uploads"
    uploads.mkdir(parents=True)
    # JSON 으로는 읽히지만 Criterion 이 모르는 키가 든 파일 — list() 는 통과하고
    # get() 만 죽는다. 옛 버전이 저장한 파일이 딱 이 모양이었다.
    (uploads / "aaaaaaaabbbbbbbb.json").write_text(
        '{"name": "깨진것", "items": [{"없는열": 1}]}', encoding="utf-8")

    cl = TestClient(create_app(settings=settings, frontend_dir=static,
                               history_dir=tmp_path / "history"))
    r = cl.get("/api/criteria", params={"team": "EV2"})
    assert r.status_code == 200
    layers = r.json()["layers"]
    assert [L["scope"] for L in layers[:2]] == ["공통", "팀별"]
    broken = [L for L in layers if L["scope"] == "업로드"]
    assert len(broken) == 1 and broken[0]["items"] == [] and broken[0]["error"]


def test_검사기_없는_규칙_기준은_자동이라고_말하지_않는다(client):
    """"규칙"이라고 적혀 있어도 그 기준을 볼 검사기가 없으면 사람이 확인해야 한다.

    실측: 규칙 mode 기준은 전 팀 합쳐 서른 개인데 규칙 검사기는 몇 개뿐이다.
    mode 만 보고 "규칙 · 자동"이라 적으면 팀에 "이건 됩니다"라고 거짓말하게 된다.
    이 화면의 값어치가 바로 그 차이를 보여주는 데 있다.
    """
    body = client.get("/api/criteria", params={"team": "EV2"}).json()
    rules = [it for L in body["layers"] for it in L["items"] if it["mode"] == "규칙"]
    assert rules, "규칙 기준이 하나는 있어야 이 테스트가 뜻을 갖는다"
    for it in rules:
        if it["check"]:
            assert it["howChecked"] == "규칙 · 자동"
        else:
            assert it["howChecked"] == "사람이 확인", it["no"]
    # 실제로 검사되는 것과 아닌 것이 둘 다 있어야 화면이 차이를 보여준다.
    assert any(it["check"] for it in rules) and any(not it["check"] for it in rules)


def test_본문이_있는_줄만_손잡이를_달고_펴진다():
    """접힌 줄은 **제목 한 줄**이다 — 그래야 203 건이 한눈에 훑히는 체크리스트가
    된다. 본문은 필요할 때 편다.

    "왜 어떤 줄은 눌리고 어떤 줄은 안 눌리나"는 실제 차이다(203 건 중 114 건은
    note 가 아예 없어 펼 것이 없다). 그 차이를 **화살표로 드러낸다** — 눌림
    여부가 데이터에 숨어 있으면 변덕으로 보이지만, 손잡이가 보이면 규칙으로
    읽힌다.
    """
    row = VIEWS_JS[VIEWS_JS.index("function criteriaItemRow("):]
    row = row[:row.index("\n  function ")]
    assert '.split("\\n")[0]' not in row, "본문을 첫 줄에서 자르고 있다"
    # 접힌 줄에는 본문이 아예 없다 — 두 줄 미리보기는 짧은 본문에서 "누르면
    # 줄만 바뀌는" 어중간함을 만들었다.
    assert "(open ? '<div class=\"clay-note\">'" in row, "접힌 줄에도 본문이 들어간다"
    # 손잡이와 클릭은 **같은 조건**(note 있음)에 걸려야 한다. 하나만 걸리면
    # 없는 기능을 약속하거나, 있는 기능을 숨기게 된다.
    assert row.count("(note") >= 2, "손잡이와 클릭이 다른 조건에 걸렸다"
    assert 'class="clay-rowchev"' in row, "펴지는 줄에 손잡이가 없다"
    assert 'data-act="toggleCriteriaItem"' in row
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    base = css[css.index(".clay-row {"):]
    assert "cursor" not in base[:base.index("}")], "본문 없는 줄에도 손가락 커서가 붙는다"
    assert ".clay-row.is-fold:hover" in css, "펴지는 줄에 hover 가 없다"
    assert 'class="clay-title"' in row and "width:34px" not in row
    no = css[css.index(".clay-no {"):]
    no = no[:no.index("}")]
    assert "min-width: 34px" in no and "white-space: nowrap" in no, \
        "번호 열이 고정 폭이거나 줄바꿈된다"

    card = VIEWS_JS[VIEWS_JS.index("function criteriaLayerCard("):
                    VIEWS_JS.index("function criteriaLayersSection(")]
    assert "펼치기" not in card and "접기" not in card, "여닫힘을 글자로 적고 있다"
    assert 'class="clay-head"' in card and "clay-chev" in card, "hover·회전 신호가 없다"
    assert 'class="clay-name"' in card, "층 이름이 제목 서체를 안 쓴다"


def test_검사_방식으로_걸러_볼_수_있다():
    """이 화면의 값어치는 "무엇이 자동이고 무엇이 사람 몫인가"다. 층이 접혀 있으면
    필터가 죽은 것처럼 보이므로, 필터를 걸면 층을 자동으로 편다."""
    sec = VIEWS_JS[VIEWS_JS.index("function criteriaLayersSection("):
                   VIEWS_JS.index("function checklistsView(")]
    assert 'data-act="setCriteriaHow"' in sec, "검사 방식 필터가 없다"
    assert "s.open[L.id] || !!s.how" in sec, "필터를 걸어도 층이 접힌 채 남는다"
    # 층을 가로지르는 합계 — "공통 12 + 팀 30" 을 사람이 더하게 두지 않는다.
    assert "전체 <b" in sec


def test_층_머리와_항목_줄이_다른_hover_를_쓴다():
    """머리는 누르면 열리는 **제목**이고 항목 줄은 읽는 자리다. 둘 다 같은 중립
    회색이 깔리면 "왜 여기가 헤더인지"가 안 보인다 — 머리는 테두리가 서고, 줄은
    면이 깔린다."""
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    head = css[css.index(".clay-head:hover"):]
    assert "border-color: var(--accent)" in head[:head.index("}")], "머리 hover 가 면이다"
    # 테두리 자리를 늘 비워 두지 않으면 hover 때 1px 씩 밀린다.
    rest = css[css.index(".clay-head {"):]
    assert "border: 1px solid transparent" in rest[:rest.index("}")], "hover 때 머리가 밀린다"
    # 소제목이 스타일 없이 맨 div 로 그려지던 때가 있었다 — CSS 를 넣는 편집이
    # 통째로 빠졌는데 아무 검사도 안 걸려 화면에서만 어색했다.
    assert ".clay-group {" in css, "소제목 CSS 가 없다"
    # 카드가 padding 을 들고 머리를 음수 margin 으로 끌어내면, 머리의 테두리가
    # 카드 안쪽 어중간한 자리에 "살짝 좁은 네모"로 뜬다. 여백은 각자 든다.
    assert "padding" not in css[css.index(".clay-card {"):css.index(".clay-head {")], \
        "카드가 다시 여백을 들었다 — 머리 테두리가 카드 모서리에서 어긋난다"
    row = css[css.index(".clay-row.is-fold:hover"):]
    assert "var(--state-hover-neutral)" in row[:row.index("}")], "항목 줄 hover 가 브랜드색이다"
    assert ".clay-head:hover .clay-name" in css, "머리 글자가 hover 에 응답하지 않는다"
    # 홈 기준 타일이 이미 .crit-note 를 쓴다 — 같은 이름을 다시 정의하면 나중
    # 규칙이 이겨 그 타일의 흰 글씨가 조용히 죽는다.
    assert css.count(".crit-note {") == 1, "홈 타일의 .crit-note 를 덮어쓰고 있다"


def test_자동과_사람_몫이_색만이_아니라_꼴로_갈린다():
    """웜 뉴트럴(규칙 · 자동)과 회색(사람이 확인)은 11px 칩에서 거의 같은 회색이다.
    자동으로 도는 것은 면이 차고, 사람 몫은 테두리만 남은 빈 칩이다."""
    tone = VIEWS_JS[VIEWS_JS.index("var HOW_TONE"):]
    tone = tone[:tone.index("};")]
    rule = next(l for l in tone.splitlines() if "규칙 · 자동" in l)
    manual = next(l for l in tone.splitlines() if "사람이 확인" in l)
    def cells(line):
        return [c.strip() for c in line[line.index("[") + 1:line.rindex("]")].split(",")]
    assert cells(rule)[0] == '"var(--neutral-weak)"' and cells(rule)[2] == '"transparent"', \
        "규칙 · 자동 칩이 면을 안 채운다"
    # 사람 몫: 배경이 비고 테두리가 선다.
    inner = cells(manual)
    assert inner[0] == '"transparent"', "사람 몫 칩이 아직 면을 채운다"
    assert "--sev-info-bd" in inner[2], "빈 칩의 테두리가 없다"
    assert "--sev-info-fg" in inner[1], "글자색이 규칙 칩과 같은 웜 계열이다"


def test_검사_방식을_글자로_적는다():
    """한때 왼쪽에 글리프(✓·사람·대시)만 두고 칩을 뺐다. 규칙 · 자동과 LLM · 자동이
    **둘 다 ✓** 로 같아져서 "규칙이 확실히 잡는가, 모델 판단인가"가 화면에서
    사라졌다 — 이 목록에서 제일 알아야 하는 구분이다. 그림 하나로 못 가르는
    것은 글자로 적는다.
    """
    row = VIEWS_JS[VIEWS_JS.index("function criteriaItemRow("):]
    row = row[:row.index("\n  function ")]
    assert "howChip(it.howChecked)" in row, "검사 방식 뱃지가 줄에 없다"
    assert "markFor(" not in VIEWS_JS, "글리프와 뱃지가 같은 말을 두 번 한다"
    card = VIEWS_JS[VIEWS_JS.index("function criteriaLayerCard("):]
    assert "howChip(" in card[:card.index("\n  }")], "층 머리의 칩 요약이 사라졌다"


def test_펼친_층이_어디부터_열렸는지_밝힌다():
    """머리 아래로 실선을 그어야 "여기부터 열린 것"이 읽힌다 — 없으면 카드가
    그냥 길어진 것처럼 보인다. 다만 무게는 다르다: 바깥 층은 실선 하나, 안쪽
    본문은 파인 면. 층마다 면을 깔면 면 위에 면이라 목록이 무거워진다."""
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    items = css[css.index(".clay-items {"):]
    items = items[:items.index("}")]
    assert "border-top" in items, "펼친 층의 경계가 없다"
    assert "background" not in items, "층에도 면을 깔았다 — 본문 면과 무게가 같아진다"
    assert ".clay-items::before" in css, "왼쪽 레일이 없다"


def test_세_섹션의_카드가_같은_껍데기를_쓴다():
    """공통·팀별 층과 올린 체크리스트는 한 화면에 나란히 쌓인다. 껍데기가 다르면
    (44px 아이콘 칩 · 15px 제목) 혼자 다른 물건처럼 보이고, 높이도 몇 px 씩
    어긋나 목록이 흔들린다. 높이를 정하는 것은 이름 아래 메타 줄인데 층 카드는
    거기에 칩이 들고 체크리스트는 글자만 든다 — 최소 높이를 칩 쪽에 맞춘다."""
    view = VIEWS_JS[VIEWS_JS.index("var rows = (v.clib.list"):
                    VIEWS_JS.index("function clibPreviewCard(")]
    for cls in ('class="clay-card"', 'class="clay-head"', 'class="clay-name"',
                'class="clay-metarow"', 'class="clay-scope"'):
        assert cls in view, f"체크리스트 카드가 {cls} 를 안 쓴다"
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    metarow = css[css.index(".clay-metarow {"):]
    assert "min-height" in metarow[:metarow.index("}")], "칩 유무로 카드 높이가 갈린다"


def test_펼쳐진_본문이_요약과_다른_바닥에_앉는다():
    """요약 줄과 같은 바닥에 같은 여백으로 놓으면 줄이 그냥 길어진 것처럼 보인다 —
    방금 열린 것이라고 말하지 못한다. disclosure 의 관례대로 한 단 들어간 면에
    얹는다."""
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    note = css[css.index(".clay-note {"):]
    note = note[:note.index("}")]
    assert "background" in note and "padding" in note, "펼쳐진 본문이 요약과 같은 바닥에 있다"
    assert "white-space: pre-wrap" in note, "yaml 의 줄바꿈이 죽는다"

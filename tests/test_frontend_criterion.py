from pathlib import Path

VIEWS = (Path(__file__).resolve().parent.parent / "web" / "views.js").read_text(encoding="utf-8")


def test_reverse_map_prefers_all_criteria_results():
    # 항목→지적을 역으로 finding.id→기준 라벨로 만든다.
    assert "critByFinding" in VIEWS
    assert "D.criteriaResults || D.checklist" in VIEWS


def test_many_to_one_label_uses_외_n건():
    assert "외 " in VIEWS and "건" in VIEWS


def test_card_renders_기준_line_conditionally():
    # 지적 카드가 f.criteria 있을 때만 기준 줄을 그린다.
    assert "f.criteria" in VIEWS
    assert "기준:" in VIEWS


# ── 수정안이 기준을 함께 보낸다 ────────────────────────────────────────────
# 기준을 모르면 모델이 어느 방향으로 고칠지 알 수 없다. SI 단위계는 수치와 단위
# 사이를 띄우는 것이 규칙이라 "5 kg" 가 맞는데, "띄어쓰기 오류"만 주면 반대로
# 붙여놓고도 그럴듯한 문장을 낸다 — 검토자가 원문을 안 보고 갈아끼우면 규칙을
# 어긴 채로 남는다.

APP = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")


def test_views_exposes_criterion_text_for_lookup():
    # 역맵은 renderVals 안의 지역 변수라, 밖에서 읽을 길을 열어야 한다.
    assert "criterionTextFor" in VIEWS
    assert "criterionTextFor: criterionTextFor" in VIEWS, "export 에 없으면 app.js 가 못 쓴다"


def test_lookup_returns_criterion_text_not_the_display_label():
    # 라벨("… 외 2건")은 화면용 축약이라 프롬프트에 쓰기엔 모자라다.
    body = VIEWS[VIEWS.index("function criterionTextFor("):]
    body = body[:body.index("\n  }")]
    assert "_critByFinding" in body
    assert "외 " not in body, "축약 라벨을 보내면 모델이 기준 전문을 못 본다"


def test_suggest_call_sends_the_criterion():
    call = APP[APP.index("suggestFix:"):]
    call = call[:call.index("api/suggest")]
    assert 'fd.append("criterion"' in call, "기준을 안 실으면 서버가 기준 절을 못 만든다"
    assert "criterionTextFor" in call


# ── 검토 기준 화면은 제목과 상세를 갈라 그린다 ──────────────────────────────
# 기준 yaml 의 필드 뜻이 파일마다 달랐다 — common 은 text 가 제목이고 note 가 상세인데
# 팀 기준은 text 에 문단이 통째로 들어 있었다. 화면은 head 를 group(엑셀의 "검증 대상"
# 열)에서, body 를 text 첫 줄에서 가져왔다. yaml 을 text=제목 · note=상세 로 통일하면서
# 화면도 옮겼는데, 그때 이 자리를 안 고치면 왼쪽 칸이 비고 상세가 아예 안 보인다.


def test_기준_화면이_제목과_상세를_갈라_그린다():
    row = VIEWS[VIEWS.index("function criteriaItemRow("):]
    row = row[:row.index("\n  function ")]   # 뒤따르는 itemsHtml 까지 삼키지 않게
    assert "var head = (it.text" in row, "제목은 text 에서 온다"
    assert "var note = (it.note" in row, "상세는 note 에서 온다 — 없으면 화면이 빈다"
    assert "var head = (it.group" not in row, "group 이 다시 제목 자리에 왔다"
    # group 은 줄이 아니라 **소제목**이 진다 — 줄마다 되풀이하면 서른 줄에 같은
    # 말이 서른 번 붙는다.
    assert "it.group" not in row, "group 이 다시 줄 안으로 들어왔다"
    layer = VIEWS[VIEWS.index("function itemsHtml("):]
    assert 'class="clay-group"' in layer[:layer.index("\n  }")], "검증 대상 소제목이 없다"

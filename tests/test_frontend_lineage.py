from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
VIEWS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
API = (_ROOT / "web" / "api.js").read_text(encoding="utf-8")


def test_api_stores_lineage_in_state():
    # done payload 의 lineage/lineage_candidate 를 window.DOCREVIEW 에 보관한다.
    assert "lineage" in API


def test_views_builds_lineage_view():
    # D.lineage 를 읽어 화면용 뷰 오브젝트를 만든다(checklistReview 와 같은 패턴).
    assert "D.lineage" in VIEWS


def test_views_has_status_vocab_and_new():
    # 이전 지적별 상태(열림/닫힘/해당없음)와 신규 지적 라벨.
    assert "열림" in VIEWS and "닫힘" in VIEWS and "해당없음" in VIEWS
    assert "신규" in VIEWS


def test_views_has_confirm_banner_text():
    # 이전 검토 발견 → 이어서 확인 배너.
    assert "반영 확인" in VIEWS or "이전 검토" in VIEWS


def test_판정을_바꾸면_그_판정을_읽는_자리를_전부_다시_그린다():
    """판정 하나가 화면 네 군데를 먹인다 — 반영 확인 패널 · 셈 · 문서 형광펜 ·
    **지적 카드의 `해당없음` 뱃지**.

    마지막 하나가 빠져 있었다. 카드의 뱃지는 renderVals 의 `na: !!naIds[f.id]`
    에서 오고, 그 naIds 는 lineageNaIds() 가 status === "해당없음" 인 matchId 를
    모아 만든다. 그런데 setLineageVerdict 는 repaintCard 를 안 불러서, 판정을
    `해당없음` 으로 바꿔도 뱃지는 다음 전체 렌더까지 옛 상태로 남았다 —
    검토자가 반영 확인에서 정리한 것을 지적 목록만 아직 모르는 것처럼 보였다.

    여기서 render() 를 부르는 것으로 때우면 안 된다. 통째로 그리면 pdf-mount 가
    새로 만들어져 뷰어가 PDF 를 다시 열고 형광펜이 날아간다(그래서 부분 갱신을
    쓰는 것이다). 읽는 자리를 하나씩 다시 그려야 한다.
    """
    app = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    body = app[app.index("setLineageVerdict: function"):]
    body = body[:body.index("\n    },")]

    for fn in ("repaintLineagePanel", "repaintLineageCounts", "paintMarks", "repaintCard"):
        assert fn in body, f"판정을 바꾼 뒤 {fn} 을 안 부른다"
    # 카드는 이 판정이 가리키는 지적 하나다. 전체를 다시 그리면 뷰어가 리로드된다.
    assert "repaintCard(item.match_id)" in body, "어느 카드를 다시 그릴지가 틀렸다"

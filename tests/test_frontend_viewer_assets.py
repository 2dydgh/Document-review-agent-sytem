"""이력에서 되살린 원본이 PDF 뷰어에서 열리는지 지키는 회귀 테스트.

프론트엔드는 빌드도 JS 테스트 러너도 없는 바닐라 SPA라, 뷰어가 깨지는 조건을
소스 수준에서 막는다. 여기서 잡는 버그는 실제로 한 번 났던 것이다 —
`new File([blob], name)` 은 세 번째 인자를 주지 않으면 MIME 타입을 빈 문자열로
만든다. 서버가 `application/pdf` 로 보내도 File 로 다시 감싸는 순간 타입이
버려지고, 그 blob URL 을 받은 iframe 은 PDF 를 렌더링하지 못한다.

증상은 "업로드 직후 첫 확인은 되는데 이력에서 다시 열면 깨진다" 였다. 업로드
경로는 `input.files[0]` 라 브라우저가 타입을 채워주고, 이력 경로만 File 로
다시 감쌌기 때문이다. 표시본(annotate)은 blob 을 그대로 써서 멀쩡했다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "web" / "app.js"
SERVER_PY = Path(__file__).resolve().parent.parent / "src" / "app" / "server.py"

# `new File(` 부터 짝이 맞는 닫는 괄호까지가 아니라, 인자 세 개짜리 호출인지만 본다.
# 세 번째 인자(옵션 객체)가 있으면 타입을 넘기고 있다는 뜻이다.
NEW_FILE_CALL = re.compile(r"new\s+File\s*\(([^;]*?)\)\s*;")


def _new_file_calls(src: str) -> list[str]:
    return [m.group(1) for m in NEW_FILE_CALL.finditer(src)]


def test_app_js_has_a_new_file_call() -> None:
    """아래 테스트가 대상 없이 조용히 통과하지 않도록 앵커를 둔다."""
    calls = _new_file_calls(APP_JS.read_text(encoding="utf-8"))
    assert calls, "app.js 에서 new File( 호출을 찾지 못했다 — 테스트가 무의미해졌다"


def test_restored_original_keeps_its_mime_type() -> None:
    """이력 원본을 File 로 감쌀 때 MIME 타입을 반드시 넘겨야 한다.

    타입 없이 만든 File 의 blob URL 은 iframe 이 PDF 로 못 읽는다.
    """
    for call in _new_file_calls(APP_JS.read_text(encoding="utf-8")):
        assert "type" in call, (
            "new File(...) 이 type 을 넘기지 않는다 — 이력에서 되살린 PDF 가 "
            f"뷰어에서 깨진다. 문제의 호출: new File({call.strip()})"
        )


def test_server_sends_pdf_content_type() -> None:
    """프론트가 물려받을 타입이 애초에 서버에 있어야 한다."""
    src = SERVER_PY.read_text(encoding="utf-8")
    assert '".pdf": "application/pdf"' in src, (
        "history_original 이 PDF 에 application/pdf 를 안 붙이면 "
        "프론트가 blob.type 을 물려받아도 소용이 없다"
    )


VIEWS_JS = Path(__file__).resolve().parent.parent / "web" / "views.js"


def test_selecting_a_finding_does_not_rerender_the_whole_screen() -> None:
    """카드 선택이 전체 렌더를 타면 PDF 뷰어가 새로고침된다.

    iframe 은 DOM 에서 옮기기만 해도 브라우저가 문서를 다시 읽는다(HTML 명세).
    render() 는 root.innerHTML 을 통째로 갈아엎으므로 뷰어가 재부착되고, 카드를
    누를 때마다 읽던 자리를 잃는다. select 는 바뀐 카드만 갈아끼워야 한다.
    """
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("    select: function (id) {")
    body = src[start:src.index("\n    },", start)]

    assert "repaintCard" in body, (
        "select 가 카드만 갈아끼우지 않는다 — 전체 렌더로 돌아갔다면 "
        "PDF 뷰어가 매 클릭마다 새로고침된다"
    )
    # 텍스트 폴백(iframe 없는 화면)에서만 전체 렌더로 빠지는 건 정상이라,
    # render() 호출 자체가 아니라 '가드 없이' 부르는 것을 막는다.
    assert 'document.getElementById("pdf-mount")' in body, (
        "PDF 뷰어가 떠 있는지 확인하지 않고 렌더를 고른다 — 텍스트 폴백과 "
        "뷰어 화면은 처리가 달라야 한다"
    )


def test_card_markup_is_shared_between_full_render_and_partial_update() -> None:
    """카드 마크업이 두 곳에 갈라지면 부분 갱신만 옛 모양으로 남는다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "findingCardClass: findingCardClass" in views, "views 가 카드 헬퍼를 안 내보낸다"
    assert "findingCardInner: findingCardInner" in views, "views 가 카드 헬퍼를 안 내보낸다"
    assert views.count("data-card=") == 1, "카드 앵커(data-card)가 한 곳에서만 나와야 한다"


def test_finding_numbers_come_from_the_located_marks() -> None:
    """화면이 번호를 스스로 매기면 형광펜의 번호와 어긋난다.

    번호는 /api/locate 가 형광펜에 매긴 것(st.marks)을 그대로 쓴다 — 근거가 둘이면
    "1, 2", 못 칠했으면 없다. 화면이 순번을 새로 매기면 "3번 지적"이 서로 다른
    것을 가리킨다. (예전엔 표시본 PDF의 X-Numbers 였다 — 이제 locate 좌표에서 온다.)
    """
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "st.marks" in views, "지적 좌표(st.marks)에서 번호를 읽지 않는다"
    assert "markNumbers[f.id]" in views, (
        "카드 번호를 형광펜 좌표의 번호에서 가져오지 않는다 — 화면이 따로 매기면 어긋난다"
    )


INDEX_HTML = Path(__file__).resolve().parent.parent / "web" / "index.html"


def test_finding_card_styling_lives_in_css_not_inline() -> None:
    """카드 모양이 인라인이면 :hover 가 인라인에 밀려 안 먹는다.

    한 번 인라인으로 돌아가면 hover 는 조용히 죽는다 — 눌리긴 하니 버그로
    보이지도 않는다. 그래서 규칙이 CSS 에 있는지를 지킨다.
    """
    css = INDEX_HTML.read_text(encoding="utf-8")
    assert ".fcard {" in css, "지적 카드 규칙(.fcard)이 CSS 에 없다"
    assert ".fcard:hover" in css, "지적 카드에 hover 가 없다"
    assert ".fcard.on" in css, "펼쳐진 카드 상태(.on) 규칙이 없다"
    assert ".fcard.on:hover" in css, (
        "고른 카드가 hover 로 흐려지면 어디가 선택됐는지 잃는다"
    )

    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "findingCardClass" in views, "카드가 클래스 대신 인라인 스타일로 돌아갔다"


def test_긴_지적_문장이_접힌_카드를_무너뜨리지_않는다() -> None:
    """모델이 판단 과정을 issue 칸에 통째로 쏟을 때가 있다.

    실제로 "그러나/하지만/반면" 으로 결론을 네 번 뒤집는 15문장짜리가 나왔다
    (2026-08-12). 그걸 반굵은 글씨로 전부 펼치면 카드 하나가 화면을 먹고 옆
    지적들이 안 보인다 — 목록이 목록이 아니게 된다.

    자르지 않고 접는다. 인용이 검증된 진짜 지적일 수 있고, 결론이 뒤에 올 때가
    있어 앞을 자르면 결론이 날아가기 때문이다. 내보내기(md·csv·html)에는 전문이
    그대로 가야 한다 — 화면에서 접는 것과 데이터를 버리는 것은 다르다.
    """
    css = INDEX_HTML.read_text(encoding="utf-8")
    assert ".fmsg" in css, "지적 문장 규칙(.fmsg)이 CSS 에 없다"
    assert "line-clamp: 3" in css, "접힌 카드에서 지적 문장을 세 줄로 접지 않는다"
    assert ".fcard:not(.on) .fmsg" in css, (
        "펼친 카드까지 접으면 긴 지적의 전문을 볼 방법이 사라진다"
    )

    views = VIEWS_JS.read_text(encoding="utf-8")
    assert 'class="fmsg"' in views, "지적 문장이 인라인 스타일로 돌아갔다 — CSS 가 안 먹는다"
    # 전문은 내보내기로 나간다. 화면이 접는 것과 데이터가 잘리는 것은 다르다.
    assert "f.message" in views, "내보내기가 지적 원문을 싣지 않는다"


def test_there_is_a_way_back_to_the_upload_screen() -> None:
    """검토가 끝나면 screen 이 results 에 머문다.

    setMode 는 mode 만 바꾸므로 홈을 거쳐 돌아와도 묵은 결과가 다시 떴다 —
    페이지를 새로고침하지 않는 한 다음 문서를 검토할 수 없었다.
    """
    views = VIEWS_JS.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")

    assert 'data-act="newReview"' in views, "결과 화면에서 새 문서로 갈 길이 없다"
    assert "newReview: function" in app, "newReview 액션이 없다"

    start = app.index("    newReview: function")
    body = app[start:app.index("\n    },", start)]
    assert 'state.screen = "upload"' in body, "업로드 화면으로 돌아가지 않는다"
    # 앞 문서의 흔적이 남으면 새 문서 위에 이전 지적·PDF 가 얹혀 보인다.
    assert "revokeObjectURL" in body, "이전 문서의 blob URL 을 회수하지 않는다(누수)"
    assert "state.files.single = null" in body, "이전 파일이 남는다"
    assert "viewerFor = null" in body, (
        "뷰어 캐시를 안 비우면 다음 문서가 와도 같은 blob 으로 보고 이전 PDF 가 남는다"
    )


def test_home_quick_start_does_not_reopen_stale_results() -> None:
    """홈의 '단일 문서 정밀 검토'가 setMode 만 부르면 묵은 결과로 돌아간다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert 'data-act="setMode" data-arg="single"' not in views, (
        "홈 빠른시작이 setMode 로 돌아갔다 — 이전 검토 결과가 다시 뜬다"
    )


def test_viewer_shows_the_original_with_a_live_overlay() -> None:
    """화면은 원본을 그리고 형광펜은 그 위에 얹는다(표시본을 굽지 않는다).

    예전엔 표시본 PDF를 서버에서 구워 iframe에 띄웠다 — 그래서 요약 페이지
    오프셋 보정이 필요했고 쪽 이동이 문서 리로드였다. 이제 pdf.js가 원본을
    canvas에 그리고, /api/locate 좌표로 <div> 형광펜을 얹는다.
    """
    app = APP_JS.read_text(encoding="utf-8")
    start = app.index("  function syncViewer")
    body = app[start:app.index("\n  }", start)]
    assert "state.viewer.baseBlob" in body, "뷰어가 base blob(원본/변환본)을 그리지 않는다"
    assert "DR.pdfview.open" in body, "pdf.js 뷰어를 열지 않는다"

    # 좌표는 굽지 않는 /api/locate 로 받아 오버레이로 얹는다.
    assert "api/locate" in app, "지적 좌표를 받아오지 않는다"
    assert "DR.pdfview.setMarks" in app, "형광펜 오버레이를 얹지 않는다"


def test_original_is_not_shown_while_the_marked_copy_is_being_made() -> None:
    """원본을 잠깐 띄웠다 바꾸면 iframe 을 두 번 읽어 깜빡인다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert 'v.viewerMode === "marked" && v.annot.busy && !v.annot.viewUrl' in views, (
        "표시본을 굽는 동안 원본으로 폴백하면 로드가 두 번 일어난다"
    )


def test_theme_is_remembered_across_reloads() -> None:
    """예전엔 <html>에 data-theme 만 걸고 어디에도 남기지 않았다.

    상태 기본값이 light 라 새로고침할 때마다 라이트로 되돌아갔다 — "설정"이라
    불러놓고 지켜지지 않았다.
    """
    app = APP_JS.read_text(encoding="utf-8")
    start = app.index("    setTheme: function")
    body = app[start:app.index("\n    },", start)]
    assert 'localStorage.setItem("dr_theme"' in body, "테마를 저장하지 않는다"


def test_theme_is_applied_before_first_paint() -> None:
    """app.js 가 걸면 이미 라이트로 칠해진 뒤라 다크 사용자에게 흰 화면이 번쩍인다."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    head = html[:html.index("</head>")]
    assert 'localStorage.getItem("dr_theme")' in head, (
        "테마 복원이 <head> 에 없다 — 첫 페인트 뒤에 걸리면 흰 화면이 번쩍인다"
    )
    assert "prefers-color-scheme" in head, "첫 방문 때 OS 설정을 따르지 않는다"
    # 두 곳에서 각자 계산하면 설정 화면의 선택 표시가 실제 화면과 어긋난다.
    app = APP_JS.read_text(encoding="utf-8")
    assert 'state.theme = document.documentElement.getAttribute("data-theme")' in app, (
        "app.js 가 <head> 가 정한 값을 따르지 않고 따로 계산한다"
    )


def test_glass_panels_flip_with_the_theme() -> None:
    """검토 진행 화면의 반투명 유리 패널.

    흰색을 직접 박으면 다크에서 어두운 배경 위에 흰 막이 덮여 회색 상자가 된다.
    hex 만 훑는 검사로는 안 잡히는 자리다(rgba 로 적혀 있다).
    """
    views = VIEWS_JS.read_text(encoding="utf-8")
    # 문제가 되는 건 '배경'에 박은 흰색이다. 항상 파란 브랜드 패널 위의 흰 '글자색'
    # (color:rgba(255,255,255,...)) 은 두 테마에서 모두 옳으므로 막으면 안 된다.
    offenders = [
        m.group(0)[:80]
        for m in re.finditer(r'background(?:-color)?\s*:[^;"\']*', views)
        if "rgba(255,255,255" in m.group(0) or "rgba(255, 255, 255" in m.group(0)
    ]
    assert not offenders, (
        "흰색을 고정한 반투명 배경이 남아 있다 — 다크에서 회색 상자로 보인다: "
        + "; ".join(offenders)
    )

    css = INDEX_HTML.read_text(encoding="utf-8")
    dark = css[css.index('[data-theme="dark"]'):]
    # 검토 진행 화면의 유리 넷(--glass·-weak·-line·-line-strong)은 그 화면이
    # 홈·결과와 같은 불투명 패널로 내려오면서 통째로 사라졌다. 남은 반투명은
    # 로그인 계열의 --panel-glass 하나뿐이고, 규칙은 그대로다 — 테마마다 뒤집어야 한다.
    assert "--panel-glass:" in dark, "다크 블록에 --panel-glass 재정의가 없다 — 라이트 값이 그대로 쓰인다"


# (구 test_hwpx_is_not_routed_through_the_pdf_viewer 제거: hwpx는 이제 H2Orestart로
#  진짜 레이아웃 PDF로 변환해 뷰어에 띄운다. 반대 동작은
#  test_maybe_convert_routes_hwp_and_hwpx_to_render_pdf 가 지킨다.)


def test_export_menu_items_share_one_text_colour() -> None:
    """항목마다 색이 다르면 중요도가 아니라 그냥 들쭉날쭉해 보인다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    start = views.index('id="exportMenu"')
    block = views[start:views.index("      : \"\";", start)]
    assert "color:var(--accent)" not in block, (
        "--accent 를 글자색으로 쓴다 — 채움 전용 토큰이고, 항목 색도 어긋난다"
    )
    assert 'class="mi"' in block and 'class="mi-mini"' in block, (
        "내려받기 항목이 공용 클래스를 쓰지 않는다(hover 도 빠진다)"
    )


def test_document_background_does_not_scroll_with_its_content() -> None:
    """흰 배경이 스크롤되는 요소에 붙으면 본문이 길 때 배경이 중간에 끊긴다.
    hwpx 를 텍스트로 볼 때 드러났던 증상이다.

    예전엔 흰 카드가 스크롤 컨테이너 *안*에 있어서, 카드를 내용만큼만 키우는
    식으로(align-items:flex-start) 막았다. 지금은 구조가 반대다 — 배경은
    스크롤하지 않는 카드가 갖고 본문만 그 안에서 흐른다(PDF 분기와 같은 방식).
    배경이 아예 움직이지 않으므로 잘릴 수가 없다.
    """
    views = VIEWS_JS.read_text(encoding="utf-8")
    start = views.index('id="doc-scroll"')
    style = views[start:views.index(">", start)]

    assert "overflow:auto" in style, "재현본 본문이 스크롤되지 않는다"
    assert "background" not in style, (
        "스크롤되는 요소가 배경을 갖는다 — 본문이 길면 흰 배경이 중간에 끊긴다"
    )
    # 배경은 스크롤 컨테이너를 감싼 카드가 갖는다 — 그 카드 스타일은 viewerCardCss 가 낸다.
    # (PDF·재현본 카드가 공유하므로 인라인이 아니라 함수 한 곳에 모여 있다.)
    cardstart = views.index("function viewerCardCss")
    cardcss = views[cardstart:views.index("\n  }", cardstart)]
    assert "background:var(--panel)" in cardcss and "flex-direction:column" in cardcss, (
        "카드 스타일(viewerCardCss)이 배경을 갖지 않는다 — 배경을 낼 곳이 없다"
    )


def test_document_card_starts_level_with_the_issues_panel() -> None:
    """문서 뷰어와 오른쪽 '검토 결과' 패널은 같은 높이에서 시작해야 한다.

    예전엔 재현본(hwpx) 분기만 제목 헤더를 카드 밖 위에 깔고 스크롤 컨테이너에
    padding:32px 을 줘서, 문서 시작이 패널보다 ~65px 아래였다. hwpx 는 늘 이
    분기라(docx 만 PDF 로 변환된다) 주력 포맷에서 항상 어긋나 보였다.
    """
    views = VIEWS_JS.read_text(encoding="utf-8")

    # 래퍼는 공용 viewerWrap 하나다 — 문자열은 정의 안에만 있고, 단일 PDF·재현본·
    # 폴더 검토 세 사용처가 그 함수를 부른다. 복사하면 한쪽만 고쳐진다.
    wrapper = "flex:1;overflow:hidden;display:flex;justify-content:center;padding:4px 32px 12px;"
    assert views.count(wrapper) == 1, (
        "뷰어 래퍼 문자열이 viewerWrap 밖에도 있다 — 시작 높이가 갈라질 자리가 생겼다"
    )
    assert views.count("viewerWrap(") == 4, (
        "viewerWrap 사용처가 4(정의 + 단일 PDF·재현본·폴더 검토)가 아니다"
    )
    # 오른쪽 패널도 같은 4px 에서 시작한다. 패널 껍데기는 issuesShell 이 그린다 —
    # 단일 검토와 폴더 검토가 같은 것을 쓰므로 여백도 한 곳에서 정해진다.
    shell = views[views.index("function issuesShell("):]
    shell = shell[:shell.index("function sevChipsOf(")]
    assert "margin:4px 32px 12px 0" in shell, (
        "검토 결과 패널의 상단 여백이 문서 뷰어와 다르다"
    )


def test_checklist_list_comes_from_the_server() -> None:
    """화면이 목록을 지어내면 안 된다.

    예전엔 docreview-data.js 의 목업(Generic·PRD·API Spec)을 그렸다. 셋 다 서버에
    없는 이름이었고, 골라도 전달되지 않아 '고르는 시늉'만 하는 UI였다.
    settings.toml 주석에 그 사고가 적혀 있다 — 데모용 기준으로 실제 문서를 재고
    0건을 받았다.
    """
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "D.checklists" not in views, "화면이 아직 목업 체크리스트를 그린다"
    assert "st.server.checklists" in views, "서버가 준 목록을 쓰지 않는다"

    app = APP_JS.read_text(encoding="utf-8")
    assert 'fd.append("checklist"' in app, "고른 기준을 서버로 보내지 않는다"
    assert 'checklist: "prd"' not in app, "서버에 없는 목업 id 가 기본값으로 남아 있다"


def test_model_row_is_honest_when_the_llm_is_off() -> None:
    """LLM 을 끄면 모델은 돌지 않는다. 이름을 띄우면 그 모델로 쟀다는 거짓이 된다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert 'state.llm === "off"' in views, (
        "LLM 을 꺼도 모델 이름을 그대로 보여준다 — 이 패널의 존재 이유와 어긋난다"
    )


def test_criteria_panel_follows_the_chosen_checklist() -> None:
    """example 을 고르고 검토하면 화면도 example 의 잣대를 말해야 한다."""
    api = (Path(__file__).resolve().parent.parent / "web" / "api.js").read_text(encoding="utf-8")
    assert "?checklist=" in api, (
        "health 를 물을 때 고른 기준을 안 보낸다 — 기본값의 id 패턴이 그대로 뜬다"
    )
    app = APP_JS.read_text(encoding="utf-8")
    start = app.index("    setChecklist: function")
    body = app[start:app.index("\n    },", start)]
    assert "loadServerConfig()" in body, "기준을 바꿔도 잣대를 다시 묻지 않는다"


def test_cancelling_a_review_restores_the_screen() -> None:
    """abort() 만 불러선 안 된다.

    api.js 의 catch 는 AbortError 를 "새 검토가 스스로 취소한 것"으로 보고 아무것도
    하지 않는다(그 경우 새 검토가 이미 화면을 세웠다). 사용자가 누른 중단은
    세워줄 사람이 없어, 화면 복구를 중단 액션이 직접 해야 진행 화면에서 안 굳는다.
    """
    app = APP_JS.read_text(encoding="utf-8")
    start = app.index("    cancelReview: function")
    body = app[start:app.index("\n    },", start)]
    assert "abort()" in body, "스트림을 끊지 않는다"
    assert 'state.screen = "upload"' in body, (
        "화면을 되돌리지 않는다 — AbortError 는 조용히 무시되므로 진행 화면에서 굳는다"
    )
    assert "clearTimers()" in body, "경과 시간 타이머가 계속 돈다"

    views = VIEWS_JS.read_text(encoding="utf-8")
    assert 'data-act="cancelReview"' in views, "중단 버튼이 화면에 없다"


def test_open_popovers_close_on_an_outside_click() -> None:
    """예전엔 항목을 고르거나 같은 버튼을 다시 눌러야만 닫혔다.

    다른 곳을 눌러도 메뉴가 열린 채 남아, 누를 때마다 다시 그려지면서 계속
    선택된 것처럼 보였다.
    """
    app = APP_JS.read_text(encoding="utf-8")
    assert 'e.target.closest("#exportMenu")' in app, (
        "바깥 클릭을 구분하지 않는다 — 메뉴가 계속 열린 채 남는다"
    )
    assert 'act !== "toggleExportMenu"' in app, (
        "여닫기 버튼까지 바깥으로 쳐서 토글이 즉시 되닫힌다"
    )


def test_vertical_rail_label_keeps_digits_upright() -> None:
    """세로쓰기 기본값(mixed)은 한글만 세우고 숫자는 90도 눕힌다."""
    css = INDEX_HTML.read_text(encoding="utf-8")
    start = css.index(".rail-label")
    rule = css[start:css.index("}", start)]
    assert "text-orientation: upright" in rule, (
        "'검토 결과 16건'의 숫자만 옆으로 누워 읽기 어색해진다"
    )


def test_picking_a_checklist_repaints_once() -> None:
    """짧은 사이에 화면을 두 번 갈아엎으면 새로고침처럼 번쩍인다."""
    app = APP_JS.read_text(encoding="utf-8")
    start = app.index("    setChecklist: function")
    body = app[start:app.index("\n    },", start)]
    assert "servedOverHttp()" in body, (
        "선택 즉시 그리고 서버 응답에 또 그린다 — 렌더가 두 번 돈다"
    )


def test_every_scrolling_container_keeps_its_position_across_renders() -> None:
    """innerHTML 로 통째로 다시 그리면 스크롤이 날아간다.

    예전엔 id 두 개(main-scroll·doc-scroll)만 되살렸는데, 업로드·비교 설정 화면은
    그 안에 자기 스크롤러를 하나 더 둔다(height:100% + overflow:auto). 실제로
    스크롤되는 건 그쪽이라 복원에서 빠졌고, 체크리스트를 고를 때마다 화면이 맨
    위로 튀었다.
    """
    app = APP_JS.read_text(encoding="utf-8")
    assert 'querySelectorAll("[data-scroll]")' in app, (
        "스크롤 복원이 특정 id 만 본다 — 새 스크롤 컨테이너는 매번 맨 위로 튄다"
    )

    views = VIEWS_JS.read_text(encoding="utf-8")
    keys = re.findall(r'data-scroll="([^"]+)"', views)
    assert len(keys) == len(set(keys)), f"스크롤 키가 겹친다: {keys}"
    # 스스로 스크롤하는 컨테이너에는 표식이 있어야 한다.
    for m in re.finditer(r"<div ([^>]*overflow:auto[^>]*)>", views):
        attrs = m.group(1)
        if "height:100%" in attrs and "data-scroll" not in attrs:
            raise AssertionError(
                f"표식 없는 스크롤 컨테이너가 있다 — 렌더마다 맨 위로 튄다: {attrs[:90]}"
            )


# ── pdf.js 뷰어로 교체된 뒤의 자산·구조 가드 ──

VENDOR = APP_JS.parent / "vendor"
PDFVIEW_JS = APP_JS.parent / "pdfview.js"


def test_pdfjs_is_vendored() -> None:
    """CDN을 쓰지 않는다 — 인트라넷 배포다. 빠지면 뷰어가 통째로 안 뜬다."""
    assert (VENDOR / "pdf.min.mjs").exists()
    assert (VENDOR / "pdf.worker.min.mjs").exists()


def test_cmaps_are_vendored_for_cjk() -> None:
    """한글(CJK) 글리프는 CMap 이 있어야 그려진다 — 없으면 네모로 나온다."""
    assert (VENDOR / "cmaps").is_dir()
    assert any((VENDOR / "cmaps").glob("*.bcmap"))


def test_worker_src_points_at_the_vendored_worker() -> None:
    """워커 경로가 틀리면 pdf.js가 조용히 메인 스레드로 폴백해 큰 문서에서 멎는다."""
    assert "vendor/pdf.worker.min.mjs" in PDFVIEW_JS.read_text(encoding="utf-8")


def test_the_iframe_viewer_is_gone() -> None:
    """iframe으로 돌아가면 쪽 이동이 다시 문서 리로드가 된다(크롬은 같은 문서 안의
    프래그먼트 변경을 이동으로 치지 않아 노드를 갈아끼워야 했다 — 매번 깜빡였다).
    """
    src = APP_JS.read_text(encoding="utf-8")
    assert 'createElement("iframe")' not in src
    assert "#page=" not in src


def test_summary_page_offset_is_gone() -> None:
    """화면이 원본을 그리므로 요약 페이지만큼 밀 이유가 없다(오프셋 보정 제거)."""
    assert "summaryPages" not in APP_JS.read_text(encoding="utf-8")


def test_maybe_convert_routes_hwp_and_hwpx_to_render_pdf() -> None:
    """hwp·hwpx도 변환 PDF로 뷰어에 띄운다(텍스트 폴백이 아니라)."""
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("function maybeConvert")
    body = src[start:src.index("\n  }", start)]
    assert "api/render-pdf" in body
    assert "HWPX" in body, "hwpx를 변환 경로로 보내지 않는다"
    assert "HWP" in body, "hwp를 변환 경로로 보내지 않는다"

    # 변환하더라도 showPdf(=convertible)가 hwp/hwpx를 포함해야 뷰어에 뜬다.
    views = VIEWS_JS.read_text(encoding="utf-8")
    cstart = views.index("var convertible")
    cline = views[cstart:views.index("\n", cstart)]
    assert '"HWPX"' in cline and '"HWP"' in cline, "convertible이 hwp/hwpx를 안 넣어 뷰어가 텍스트 폴백으로 간다"


# ── 브라우저가 선언 없이 찾는 자산 ──────────────────────────────────────────
# 콘솔에 404 가 쌓이던 것을 막는 회귀 테스트. `<link rel="icon">` 을 아무리 잘
# 선언해도 브라우저는 **루트** /favicon.ico 를 별도로 요청하고, iOS Safari 는
# 홈 화면에 추가할 때 /apple-touch-icon.png 를 찾는다. 둘 다 web/ 루트에 있어야 한다.
# (precomposed·manifest.json·robots.txt 는 그대로 404 다 — 같은 이미지를 세 번 두거나
#  사내망에 크롤러 파일을 둘 이유가 없다.)

_WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.mark.parametrize("name", ["favicon.ico", "favicon-16.png", "favicon-32.png",
                                  "apple-touch-icon.png"])
def test_browser_icons_live_at_web_root(name):
    """규칙: 브라우저가 찾는 아이콘은 루트, 앱이 코드로 부르는 그림은 public/.

    예전에는 브라우저 아이콘과 앱 마크가 두 위치에 같은 바이트로 섞여 있었다.
    한 곳으로 모으고 사본을 없앴다.
    """
    p = _WEB / name
    assert p.is_file(), f"web/{name} 이 없으면 브라우저 콘솔에 404 가 남는다"
    assert p.stat().st_size > 0


def test_no_duplicate_icon_bytes_between_root_and_public():
    """같은 바이트가 두 곳에 있으면 한쪽만 고쳐지고 언젠가 어긋난다."""
    import hashlib

    def digest(p):
        return hashlib.md5(p.read_bytes()).hexdigest()

    root = {digest(p) for p in _WEB.glob("*.png")} | {digest(p) for p in _WEB.glob("*.ico")}
    pub = {digest(p) for p in (_WEB / "public").glob("*.png")}
    assert not (root & pub), "루트와 public/ 에 같은 파일이 중복으로 있다"


def test_app_images_live_under_public():
    """public/에는 화면이 실제로 부르는 이미지 자산만 둔다."""
    # 홈 인사말 마스코트(독수리 조각 셋)는 화면에서 걷어냈다 — 원본과 조각은
    # web/brand/ 로 옮겼다(gitignore 대상, 참고용). 안 부르는 이미지를 public/ 에
    # 남겨 두면 이 검사가 지키려는 것이 바로 흐려진다.
    #
    # **목록은 화면을 따라간다.** 검사가 옛 목록을 고집하면, 규칙을 지키며 새 그림을
    # 쓰기 시작한 화면이 위반으로 뜬다 — 2026-08-20 에 views.js 가
    # mascot-investigator 를 부르기 시작했는데 여기가 안 따라와 실패했다.
    expected = {"logo-mark-transparent-96.png", "login_hero.png",
                "mascot-investigator-192.png"}
    actual = {
        path.name for path in (_WEB / "public").iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico"}
    }
    assert actual == expected


def test_animation_easings_are_defined_tokens():
    """미정의 var()는 **선언 전체**를 무효로 만든다 — 오타 하나에 연출이 통째로 죽는다.

    한때 이 검사는 홈 인사말 마스코트 하나를 이름으로 못박고 있었다. 그 연출을
    걷어내자 검사도 같이 죽었는데, 정작 지키려던 교훈은 마스코트의 것이 아니었다.
    CSS 는 못 읽는 값을 만나면 그 속성만 버리는 게 아니라 선언을 통째로 버리므로,
    `var(--ease-ou)` 같은 오타는 조용히 "애니메이션이 아예 안 도는" 화면을 만든다.
    그래서 이름이 아니라 **모든 animation 선언이 정의된 이징만 쓰는지**를 본다.
    """
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--ease-[\w-]+):\s*cubic-bezier", html))
    assert defined, "이징 토큰이 하나도 정의돼 있지 않다"
    used = set(re.findall(r"animation:[^;{}]*?var\((--[\w-]+)\)", html))
    assert used <= defined, f"정의되지 않은 이징을 쓴다: {sorted(used - defined)}"


def test_apple_touch_icon_is_declared_too():
    """관례에 기대지 않고 명시한다 — 선언이 있으면 경로를 옮겨도 따라온다."""
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon"' in html
    # 판올림 문자열을 박아 두면 아이콘을 새로 그릴 때마다 이 테스트가 같이 깨진다
    # — 판올림 자체는 옳은 일이라 테스트가 막을 것이 아니다. 대신 **넷이 같은
    # 값을 쓰는지**를 본다. 하나만 옛 값에 남으면 그 아이콘만 캐시에서 안 바뀐다.
    vs = set(re.findall(r'href="(?:favicon[^"]*|apple-touch-icon)\.\w+\?v=([^"]+)"', html))
    assert len(vs) == 1, f"아이콘 링크의 판올림 값이 갈렸다: {sorted(vs)}"
    assert f'href="apple-touch-icon.png?v={vs.pop()}"' in html


def test_render_keeps_the_open_viewer_alive() -> None:
    """통째로 다시 그려도 PDF 뷰어는 안 깜빡여야 한다.

    `root.innerHTML = ...` 는 `#pdf-mount` 를 새 빈 노드로 갈아치운다. 그러면
    syncViewer 가 빈 자리를 보고 PDF 를 **처음부터 다시 읽는다** — 읽던 자리가
    날아가고 화면이 깜빡인다. 내려받기 메뉴를 열거나 닫기만 해도 그랬다
    (exportAs·toggleExportMenu 가 render 를 부른다).

    그래서 그리기 전에 살아 있는 뷰어를 붙잡아 두었다가 새 자리에 도로 꽂는다.
    같은 노드라 pdfview 가 든 참조(host·pages[].el)도 그대로 산다.
    """
    src = APP_JS.read_text(encoding="utf-8")
    body = src[src.index("function render()"):]
    body = body[:body.index("root.innerHTML")]
    assert 'document.getElementById("pdf-mount")' in body, \
        "그리기 전에 뷰어를 안 붙잡는다"
    assert "oldMount.firstChild" in body, "mount 가 아니라 알맹이를 붙잡아야 한다"

    after = src[src.index("root.innerHTML"):]
    after = after[:after.index("\n  }")]
    # **자리는 새로 그린 것을 쓴다.** 옛 mount 노드를 통째로 바꿔치기하면 그 노드가
    # 들고 있던 크기 규칙이 새 화면과 어긋나 빈 화면이 났다.
    assert "viewerSlot.appendChild(keptHost)" in after, "알맹이를 새 자리로 안 옮긴다"
    assert "replaceWith" not in after, "자리를 통째로 바꿔치기한다"
    assert 'setAttribute("style"' not in after, "새 자리의 크기 규칙을 덮어쓴다"
    # 새 화면에 뷰어 자리가 없으면 안 옮겨야 한다 — syncViewer 가 닫는 몫이다.
    assert "if (viewerSlot)" in after, "뷰어 자리가 없는 화면에서도 옮기려 든다"
    # 노드를 DOM 에서 떼면 스크롤 위치가 0 이 된다 — 되돌리지 않으면 내려받기
    # 한 번에 문서가 맨 위로 튄다.
    assert "keptHost.scrollTop = keptTop" in after, "읽던 자리로 안 되돌린다"

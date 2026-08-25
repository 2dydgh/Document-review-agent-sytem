"""뷰어 도구줄과 이력 일괄 삭제 — 소스 수준 회귀.

프론트엔드는 빌드도 JS 러너도 없는 바닐라 SPA라, DOM 을 타는 배선은 여기서 막는다
(순수 함수는 web/tests/*.test.js 가 node 로 실제 돌린다).
"""
from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"
APP_JS = (_WEB / "app.js").read_text(encoding="utf-8")
VIEWS_JS = (_WEB / "views.js").read_text(encoding="utf-8")
PDFVIEW_JS = (_WEB / "pdfview.js").read_text(encoding="utf-8")


def test_형광펜을_끄고_켤_수_있다() -> None:
    """지적이 수십 건이면 색이 겹쳐 원문이 안 보인다 — 끄고 읽다가 다시 켠다."""
    assert 'data-act="toggleMarks"' in VIEWS_JS, "단추가 없다"
    act = APP_JS[APP_JS.index("toggleMarks: function"):]
    act = act[:act.index("\n    },")]
    assert "setMarksVisible" in act, "뷰어에 안 전한다"
    assert "state.marksOn" in act, "켜짐 여부를 안 들고 있다"
    # 형광펜 하나를 끄려고 전체 결과 DOM을 다시 만들면 오른쪽 패널의 스크롤이
    # 맨 위로 돌아간다. 상태가 바뀐 단추만 제자리에서 갱신해야 한다.
    assert "render()" not in act, "형광펜 토글이 검토 결과 전체를 다시 그린다"
    assert 'querySelectorAll(\'[data-act="toggleMarks"]\')' in act, \
        "전체 렌더 없이 단추 상태를 갱신하지 않는다"
    assert 'setAttribute("aria-pressed"' in act, "켜짐 상태를 보조기술에 갱신하지 않는다"


def test_pdf_도구가_눌리는_버튼으로_반응한다() -> None:
    """형광펜·축소·맞춤·확대·전체화면은 같은 hover/focus 언어를 쓴다."""
    assert 'class="viewer-tool viewer-mark-tool"' in VIEWS_JS
    assert VIEWS_JS.count('class="viewer-tool"') >= 4
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert ".viewer-tool:hover" in css
    assert ".viewer-tool:focus-visible" in css


def test_검토_결과_패널이_pdf를_유지하며_접힌다() -> None:
    """패널 폭과 레일 폭을 맞바꿔 문서는 자연스럽게 넓어지고 iframe은 유지된다."""
    act = APP_JS[APP_JS.index("toggleIssues: function"):]
    act = act[:act.index("\n    },")]
    assert "getBoundingClientRect" in act, "현재 패널 폭에서 전환을 시작하지 않는다"
    assert "p.animate([" in act and "r.animate([" in act, \
        "패널과 접힌 레일이 순간 교체된다"
    assert "reduceMotion()" in act, "움직임 줄이기 설정을 무시한다"
    # DOM이 있는 정상 경로에서는 전체 렌더를 하지 않는다. fallback 한 줄만 허용한다.
    assert act.count("render()") == 1, "패널을 접으며 PDF iframe을 다시 만든다"


def test_보고_있는_쪽과_배율을_알려준다() -> None:
    """긴 문서에서 몇 쪽인지 모르면 형광펜 번호만으로는 위치 감이 안 온다."""
    assert 'id="pdf-where"' in VIEWS_JS, "적을 자리가 없다"
    assert "onViewChange:" in PDFVIEW_JS and "viewState:" in PDFVIEW_JS, \
        "뷰어가 값을 안 내준다"

    fn = APP_JS[APP_JS.index("function paintWhere("):]
    fn = fn[:fn.index("\n  }")]
    # 스크롤마다 통째로 그리면 화면이 쉼 없이 흔들린다. 글자만 갈아끼운다.
    assert "render()" not in fn, "스크롤마다 화면을 다시 그린다"
    assert "pdf-where" in fn


def test_기록을_한_번에_비울_수_있다() -> None:
    """하나씩 지우면 스무 건에 스무 번을 눌러야 한다."""
    assert 'data-act="askDeleteAll"' in VIEWS_JS, "전체 삭제 단추가 없다"
    # 지우기 전에 반드시 묻는다 — 되돌릴 수 없는 일이다.
    ask = APP_JS[APP_JS.index("askDeleteAll: function"):]
    ask = ask[:ask.index("\n    },")]
    assert "state.confirmDelete" in ask, "묻지 않고 지운다"

    act = APP_JS[APP_JS.index("deleteHistory: function"):]
    act = act[:act.index("\n    },")]
    assert 'id === "*"' in act, "전체를 가리키는 열쇠를 안 읽는다"
    assert "Promise.all" in act, "건마다 부르고 기다리지 않는다"


DATA_JS = (_WEB / "docreview-data.js").read_text(encoding="utf-8")


def test_검토_전에는_보여줄_지적이_없다() -> None:
    """프로토타입 시절의 가짜 지적 11건이 시작값으로 들어 있었다.

    검토를 한 번도 안 돌려도 `지적사항` 화면에 그것이 떴다 — 진짜 결과와 구별할
    방법이 없다. 이력 목록에서 목업을 지운 것과 같은 이유다.

    stages·checklists 는 지적이 아니라 화면 뼈대라 남는다(검토 전에도 파이프라인
    단계를 그려야 한다).
    """
    assert "var findings = [];" in DATA_JS, "가짜 지적이 살아 있다"
    assert "sections: []," in DATA_JS, "가짜 본문이 미리보기에 뜬다"
    assert "var stages = [" in DATA_JS, "파이프라인 뼈대까지 지웠다"


def test_안_간_단계로는_못_뛴다() -> None:
    """폴더 검토(goCaseStep)는 막는데 단일 검토만 아무 데나 갈 수 있었다."""
    act = APP_JS[APP_JS.index("\n    go: function (s) {"):]
    act = act[:act.index("\n    },")]
    assert "state.reviewed" in act, "결과가 있는지 안 본다"
    assert '"results"' in act, "지적사항으로 그냥 갈 수 있다"

    # 검토를 새로 시작하면 아직 결과가 없다 · 끝나면 갈 수 있다.
    assert "state.reviewed = false" in APP_JS, "새 검토에서 표식을 안 지운다"
    api = (_WEB / "api.js").read_text(encoding="utf-8")
    assert "state.reviewed = true" in api, "검토가 끝나도 못 간다"
    # 이력에서 되살린 것도 진짜 결과다.
    assert APP_JS.count("state.reviewed = true") >= 1, "이력 복원에 표식이 없다"


def test_번호마다_그_자리로_간다() -> None:
    """한 지적이 여러 곳을 물면 번호도 여럿인데 늘 첫 번호로만 갔다.

    카드를 다시 누르는 것으로는 못 돈다 — 그건 선택 해제다(select 는 토글).
    그래서 번호 칩을 쪼개 각각 누르게 한다. 칩 쪼개기는 node 가 실제로 확인한다
    (web/tests/lineage_view.test.js).
    """
    act = APP_JS[APP_JS.index("goMark: function"):]
    act = act[:act.index("\n    },")]
    assert "String(x.no) === String(no)" in act, "그 번호의 마크를 안 찾는다"
    assert "pdfview.goTo" in act, "문서를 안 옮긴다"
    assert "pdfview.highlight" in act, "간 자리를 강조하지 않는다"


def test_내보내기_메뉴는_화면을_다시_안_그리고_닫힌다() -> None:
    """팝오버 하나 닫자고 통째로 그리면 검토 결과도 뷰어도 같이 흔들린다.

    내려받기를 누르면 화면이 새로고침된 것처럼 보였다.
    """
    fn = APP_JS[APP_JS.index("function closeExportMenu()"):]
    fn = fn[:fn.index("\n  }")]
    assert "render()" not in fn, "메뉴 닫자고 화면을 다시 그린다"
    assert "menu.remove()" in fn, "그 노드만 지우지 않는다"

    for act in ("exportAs: function", "downloadMarked: function"):
        body = APP_JS[APP_JS.index(act):]
        body = body[:body.index("\n    },")]
        assert "closeExportMenu()" in body, f"{act} 가 메뉴를 옛 방식으로 닫는다"

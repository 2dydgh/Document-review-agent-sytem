"""케이스 검토 화면.

바닐라 SPA 라 소스 수준에서 막는다. 여기서 지키는 것은 둘.

1. **고른 값은 state 에 둔다.** DOM 에 들고 있으면 render() 한 번에 날아간다 —
   회원가입 폼이 그렇게 아팠고(app.js selToggle 주석), 여기는 파일 10개에
   드롭다운이 붙어 훨씬 크게 아프다.
2. **추측하지 않고 사람에게 묻는다.** 양식번호가 없는 파일을 임의로 배정하면
   엉뚱한 필드맵으로 검사해 거짓 지적이 난다.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
API_JS = (_ROOT / "web" / "api.js").read_text(encoding="utf-8")


def test_폴더_검토가_사이드바에_있다() -> None:
    """세 기능은 **입력 문서 수**로 갈린다 — 1개 · 2개 · 폴더. 이름이 그 축을
    드러내야 검토자가 어디로 갈지 안다.

    끝을 "검토"로 맞춘다(단일·비교·폴더). 예전엔 축이 섞여 있었다 — "단일 검토"는
    범위+동작, "문서 비교"는 대상+동작, "산출물 세트"는 대상만 있고 동작이 없어
    나란히 놓으면 읽히지 않았다.

    "발급"은 쓰지 않는다. AI시험인증1팀 어휘라 EV2·AX품질팀에는 없는 말인데,
    이 화면은 팀 공용이고 기준만 팀별로 갈아끼운다.

    "케이스"라는 말도 안 쓴다 — 이 도메인에서 케이스는 테스트케이스다
    (md §3-2 "테스트케이스 글꼴", 을지의 TF1-1). 코드 식별자만 case* 로 둔다.
    """
    assert '{ k: "case", label: "폴더 검토"' in VIEWS_JS
    assert '{ k: "compare", label: "비교 검토"' in VIEWS_JS
    assert '{ k: "single", label: "단일 검토"' in VIEWS_JS
    upload = VIEWS_JS[VIEWS_JS.index("function caseUpload("):
                      VIEWS_JS.index("function caseRecognize(")]
    assert "폴더" in upload, "언제 쓰는 화면인지 안내가 없다"
    # 주석은 "왜 안 쓰는가"를 적을 수 있으므로 화면에 나가는 줄만 본다.
    visible = "\n".join(line for line in VIEWS_JS.split("\n")
                        if not line.lstrip().startswith("//"))
    assert "발급" not in visible, "팀 종속 어휘가 화면 문구에 남아 있다"
    assert "비교 검토" in upload, "단계별 검토는 어디로 가야 하는지 안내가 없다"
    assert "케이스" not in VIEWS_JS[VIEWS_JS.index("function caseUpload("):
                                  VIEWS_JS.index("function caseProgress(")], \
        "화면 문구에 '케이스'가 남아 있다"
    for view in ("caseUpload", "caseRecognize", "caseProgress"):
        assert f"function {view}(" in VIEWS_JS, f"{view} 화면이 없다"
        assert view in VIEWS_JS.split("function body(v)")[1], f"body 가 {view} 를 안 그린다"


def test_폴더_검토_화면이_다른_검토와_같은_관용구를_쓴다() -> None:
    """업로드·인식 확인이 단일·비교 검토와 같은 껍데기를 써야 한 흐름으로 읽힌다.

    예전엔 이 두 화면만 갈라져 있었다 — 업로드는 그림도 형식 안내도 없는 점선
    상자 하나(오른쪽은 빈 채)였고, 인식 확인은 공용 제목 규격을 쓰지 않아
    2단계에서 다른 앱으로 넘어간 것처럼 보였다.

    폴더를 통째로 받는 화면이라 dropzone() 함수 자체는 못 쓴다(slot 이 없고 파일
    목록이 아래 붙는다). 그래서 함수가 아니라 **겉모습**을 맞춘 것이고, 그 겉모습이
    다시 갈라지지 않게 여기서 잡는다.
    """
    # 드롭존은 caseDropzone() 이 그린다 — caseUpload() 는 그것을 부른다.
    upload = VIEWS_JS[VIEWS_JS.index("function caseDropzone("):
                      VIEWS_JS.index("function caseRecognize(")]
    recognize = VIEWS_JS[VIEWS_JS.index("function caseRecognize("):
                         VIEWS_JS.index("function caseStat(")]

    # 업로드: 드롭존이 단일·비교와 같은 관용구(그림 + 15px 안내 + 형식 줄)를 쓴다.
    assert "52px;height:52px" in upload, "드롭존에 그림이 없다"
    assert "지원 형식" in upload, "무엇을 올릴 수 있는지 안 적혀 있다"
    # 오른쪽 단계 패널 — 단일 검토의 "AI 분석 파이프라인" 자리다. 검사 전에
    # 무엇을 하는지 말해주는 유일한 곳이라 비어 있으면 안 된다.
    assert "CASE_STAGES.map" in upload, "검사 단계 패널이 없다"
    # 폴더 검토인데 클릭이 파일 하나만 고르게 하면 안 된다. 파일만 고르는 길은
    # 따로 남긴다 — 하위 폴더 없이 몇 장만 볼 때가 있다.
    assert 'data-act="pickCaseFolder"' in upload, "드롭존 클릭이 폴더를 안 연다"
    assert 'data-act="pickCaseFiles"' in upload, "파일만 고르는 길이 없다"

    # 인식 확인도 좌측 메뉴가 계속 보이는 최상위 폴더 검토 흐름이다. 홈 링크를
    # 한 줄 더 두면 존재하지 않는 상하 관계를 만들고 제목만 아래로 밀린다.
    assert 'backLink("home"' not in recognize, "중복 홈 링크가 남아 있다"
    # 제목 규격은 공용 pageHead(22px·이사만루 공체 Bold)가 진다 — 다른 화면과 같은 헤더.
    assert 'pageHead("폴더 검토"' in recognize, "제목이 공용 페이지 헤더를 안 쓴다"
    assert "border-radius:var(--r-lg)" in recognize, "카드가 앞뒤 화면과 다른 모양이다"


def test_최상위_메뉴_화면은_같은_시작선을_쓴다() -> None:
    """좌측 메뉴에서 직접 여는 화면은 홈의 하위처럼 만들지 않고 시작선을 맞춘다."""
    blocks = {
        "단일 검토": VIEWS_JS[VIEWS_JS.index("function singleUpload("):
                              VIEWS_JS.index("function progressHead(")],
        "문서 비교": VIEWS_JS[VIEWS_JS.index("function compareSetup("):
                              VIEWS_JS.index("function compareProgress(")],
        "폴더 업로드": VIEWS_JS[VIEWS_JS.index("function caseUpload("):
                                VIEWS_JS.index("function caseRecognize(")],
        "폴더 인식 확인": VIEWS_JS[VIEWS_JS.index("function caseRecognize("):
                                  VIEWS_JS.index("function caseStat(")],
        "검토 기준": VIEWS_JS[VIEWS_JS.index("function checklistsView("):
                              VIEWS_JS.index("function clibPreviewCard(")],
        "검토 기록": VIEWS_JS[VIEWS_JS.index("function historyView("):
                              VIEWS_JS.index("function settingsView(")],
        "설정": VIEWS_JS[VIEWS_JS.index("function settingsView("):
                         VIEWS_JS.index("function appHomeView(")],
    }
    for name, block in blocks.items():
        assert 'backLink("home"' not in block, f"{name}에 중복 홈 링크가 남아 있다"
        assert 'page-shell page-shell-primary' in block, f"{name} 제목이 상단에 붙는다"


def test_리포트_헤더가_결과와_검토범위를_구분한다() -> None:
    """지적·미검토와 산출물 수·대조율은 다른 숫자다. 같은 칸에 늘어놓으면
    무엇이 문제 수인지 알 수 없다."""
    report = VIEWS_JS[VIEWS_JS.index("function caseReport("):
                      VIEWS_JS.index("function caseCriteria(")]
    assert '"전체 지적"' in report
    assert '"미검토"' in report
    assert '"직접 확인"' in report
    assert "검토 범위" in report
    assert "산출물 인식 <b>" in report
    assert "전체 필드 대조 판정 <b>" in report
    assert "분류가 필요한 파일 <b>" in report
    assert "참고자료 제외 <b>" in report
    assert "확인할 것" not in report


def test_고른_값을_state_에_둔다() -> None:
    """파일·지정·제외가 DOM 이 아니라 state 에 있어야 render 가 안 날린다."""
    kase = APP_JS[APP_JS.index("kase: {"):APP_JS.index("setMode: function")]
    for key in ("files:", "assign:", "exclude:", "recog:", "step:"):
        assert key in kase, f"state.kase 에 {key} 가 없다"


def test_지정_드롭다운은_클릭이_아니라_change_로_다룬다() -> None:
    """select 에 data-act 가 붙어 있으면 클릭 델리게이션이 먼저 잡는다. 그러면
    사용자가 고르기도 전에 액션이 돌고 render 가 드롭다운을 닫아버린다."""
    click = APP_JS[APP_JS.index('document.addEventListener("click"'):]
    guard = click[:click.index("if (actions[act]) actions[act](arg);")]
    assert 'tagName !== "SELECT"' in guard, "클릭 델리게이션이 select 를 안 걸러낸다"
    assert 'el.getAttribute("data-act") !== "assignOutput"' in APP_JS, \
        "assignOutput 을 change 로 받는 자리가 없다"


def test_폴더_드롭은_내용까지_훑는다() -> None:
    """dataTransfer.files 만 보면 폴더는 이름만 담겨 와 내용이 사라진다.
    산출물이 00.~03. 하위 폴더로 나뉘어 있어 이게 없으면 폴더 드롭이 무의미하다."""
    assert "webkitGetAsEntry" in APP_JS
    assert "createReader" in APP_JS
    # readEntries 는 한 번에 다 주지 않는다 — 반복해서 읽어야 한다.
    assert APP_JS.count("readEntries") >= 1
    assert "readMore" in APP_JS


def test_드롭은_네모_밖에_놓아도_받는다() -> None:
    """갈 곳이 하나뿐인데 조준을 요구할 이유가 없다.

    화면에 드롭존이 **하나뿐이면**(단일 검토·폴더 검토) 어디에 놓아도 그 하나로
    보낸다. 비교 검토는 A·B 둘이라 어디에 놓았는지가 곧 어느 쪽인지이므로
    넓히지 않는다 — 넓히면 우리가 찍어서 배정하게 된다. 그래서 판단 기준은
    "드롭존이 하나인가"이지 "단일 검토인가"가 아니다.
    """
    assert "function soleZone(" in APP_JS, "드롭존이 하나인지 보는 자리가 없다"
    sole = APP_JS[APP_JS.index("function soleZone("):]
    sole = sole[:sole.index("function hasZone(")]
    assert "all.length === 1" in sole, "둘 이상일 때도 한 곳으로 몰아넣는다"
    # 두 갈래(단일·비교 / 폴더) 모두 같은 규칙을 쓴다.
    for sel in ('"[data-drop]"', '"[data-casedrop]"'):
        assert f"soleZone({sel})" in APP_JS, f"{sel} 이 넓힌 규칙을 안 쓴다"


def test_빗나간_드롭이_올려둔_문서를_날리지_않는다() -> None:
    """드롭을 안 삼키면 브라우저가 그 파일로 페이지를 이동한다.

    비교 검토에서 A를 올려둔 채 B를 빗맞히면 A까지 잃는다 — 넓힌 인식 범위가
    안 닿는 유일한 화면이 하필 잃을 것이 가장 많은 화면이다.
    """
    assert "function hasZone(" in APP_JS, "드롭존 유무를 보는 자리가 없다"
    guard = APP_JS[APP_JS.index("function hasZone("):]
    guard = guard[:guard.index('document.addEventListener("dragover", function (e) { var z')]
    assert 'addEventListener("drop"' in guard and "preventDefault" in guard, \
        "빗나간 드롭을 삼키는 자리가 없다"


def test_webkitGetAsEntry_가_빈손이면_파일이라도_받는다() -> None:
    """메서드가 있는지만 보고 들어갔다가 그게 null 만 주면 0건으로 조용히 끝난다.

    사용자는 드롭이 씹힌 줄도 모른다. dataTransfer 는 핸들러가 끝나면 비워지므로
    되돌아갈 목록은 **동기적으로** 떠 둬야 한다.
    """
    drop = APP_JS[APP_JS.index("var kz = caseZoneOf(e);"):]
    drop = drop[:drop.index("}, true);")]
    assert "var fallback =" in drop, "되돌아갈 목록을 안 떠 둔다"
    assert drop.index("var fallback =") < drop.index("collectDropped("), \
        "fallback 을 비동기 콜백 안에서 읽으면 이미 비워져 있다"
    assert "files.length ? files : fallback" in drop, "빈손일 때 되돌아가지 않는다"


def test_미분류는_추측하지_않고_지정을_묻는다() -> None:
    recognize = VIEWS_JS[VIEWS_JS.index("function caseRecognize("):
                         VIEWS_JS.index("function caseStat(")]
    assert 'data-act="assignOutput"' in recognize, "지정 드롭다운이 없다"
    assert 'data-act="toggleExclude"' in recognize, "제외 버튼이 없다"
    assert "outputKeys" in recognize, "지정 선택지를 안 보여준다"


def test_안_올라온_산출물은_미검토라고_말한다() -> None:
    """지적 0건과 구분해야 한다. 없는 문서가 필요한 대조를 조용히 넘기면
    검사하지 않은 것이 통과로 보인다."""
    recognize = VIEWS_JS[VIEWS_JS.index("function caseRecognize("):
                         VIEWS_JS.index("function caseStat(")]
    assert "안 올라온 산출물" in recognize
    assert "미검토" in recognize


def test_구_양식은_판별하되_표시한다() -> None:
    recognize = VIEWS_JS[VIEWS_JS.index("function caseRecognize("):
                         VIEWS_JS.index("function caseStat(")]
    assert "구 양식" in recognize
    assert "formNo" in recognize


def test_검사가_끝나면_리포트로_간다() -> None:
    assert 'k.step = "results"' in API_JS
    assert "function caseReport(" in VIEWS_JS
    assert "v.kResults" in VIEWS_JS


def test_리포트는_인식표를_지적보다_먼저_보여준다() -> None:
    """산출물 하나가 안 올라온 걸 모르고 "지적 없음"을 보면 통과로 읽는다."""
    report = VIEWS_JS[VIEWS_JS.index("function caseReport("):
                      VIEWS_JS.index("function caseCsvText(")]
    tabs = report[report.index("var tabs = "):report.index("var tabBar")]
    assert tabs.index('"summary"') < tabs.index('"compare"')
    table = VIEWS_JS[VIEWS_JS.index("function caseOutputTable("):
                     VIEWS_JS.index("function caseFieldsPanel(")]
    assert "올라오지 않았습니다" in table
    assert "미검토로 남습니다" in table


def test_대조_지적은_양쪽_근거를_보여준다() -> None:
    """대조는 본질적으로 "여기와 저기"다. 한쪽만 보여주면 어디를 고칠지 모른다."""
    lst = VIEWS_JS[VIEWS_JS.index("function caseFindingList("):
                   VIEWS_JS.index("function caseOtherPanel(")]
    assert "f.evidence" in lst
    assert "e.at" in lst and "e.quote" in lst


def test_못_찾은_필드는_값이_빈_것과_구분해_보여준다() -> None:
    """필드맵이 문서와 어긋난 것이라 사람이 봐야 한다."""
    panel = VIEWS_JS[VIEWS_JS.index("function caseFieldsPanel("):
                     VIEWS_JS.index("function caseFindingList(")]
    assert "찾지 못했습니다" in panel
    assert "(빈 값)" in panel


def test_CSV_는_판정_못_한_것도_내보낸다() -> None:
    """판정한 것만 내보내면 받아 본 사람은 그게 전부라고 읽는다
    (preset/export.py 와 같은 원칙)."""
    csv = VIEWS_JS[VIEWS_JS.index("function caseCsvText("):]
    assert '"미판정"' in csv
    assert "p.missing" in csv and "p.unclassified" in csv and "p.ignored" in csv


def test_진행_단계는_부분_갱신한다() -> None:
    """stage 이벤트마다 전체 render 를 하면 파일 목록·버튼이 재생성된다."""
    assert 'id="kase-stages"' in VIEWS_JS
    assert 'id="kase-elapsed"' in VIEWS_JS
    assert "repaintCaseStages" in API_JS


def test_스트림이_조용히_끊기면_실패로_다룬다() -> None:
    """done/error 없이 닫히면 화면이 진행 중인 채로 굳는다."""
    stream = API_JS[API_JS.index("function streamCase("):
                    API_JS.index("function streamReview(")]
    assert "sawEnd" in stream
    assert "연결이 끊겼습니다" in stream


def test_backend_함수는_구조분해된_이름으로_쓴다() -> None:
    """app.js 는 _be(backend)를 **개별 이름으로 구조분해**해 쓴다. `be.foo` 처럼
    객체째 부르면 ReferenceError 가 나는데 문자열 검사로는 안 잡힌다 —
    실제로 케이스 인식이 그렇게 깨졌다(be is not defined).

    api.js 가 내보내는 이름 중 app.js 가 부르는 것은 전부 구조분해에 있어야 한다.
    """
    import re

    # api.js 의 return { ... } 에서 내보내는 이름
    tail = API_JS[API_JS.rindex("return {"):]
    exported = set(re.findall(r"(\w+)\s*:", tail))

    # app.js 의 var ... = _be.X 구조분해
    bound = set(re.findall(r"(\w+)\s*=\s*_be\.(\w+)", APP_JS))
    bound_names = {local for local, _ in bound}

    # app.js 가 로컬로 정의한 것도 세어 준다(이름이 겹칠 수 있다)
    local = set(re.findall(r"\bfunction\s+(\w+)", APP_JS))

    called = {n for n in exported if re.search(r"(?<![\w.$])" + n + r"\s*\(", APP_JS)}
    missing = sorted(called - bound_names - local)

    assert not missing, f"_be 에서 구조분해하지 않고 부른다: {missing}"
    assert re.search(r"(?<![_\w.$])be\s*\.", APP_JS) is None, \
        "app.js 에 `be.` 가 있다 — 이 파일의 이름은 _be 다"


def test_지적에서_그_문서를_열_수_있다() -> None:
    """리포트가 위치를 "표2 7행" 글자로만 말하면 사람이 문서를 직접 열어 찾아야 한다."""
    lst = VIEWS_JS[VIEWS_JS.index("function caseFindingList("):
                   VIEWS_JS.index("function caseOtherPanel(")]
    assert 'data-act="openCaseDoc"' in lst
    # 대조 지적은 문서 **여럿**을 가리킨다 — 전부 열 수 있어야 한다. 쌍 대조(↔)는
    # 둘이지만 전체 대조(·)는 서넛이다. 예전엔 ↔ 만 갈라서 전체 대조가 한 덩어리로
    # 남았고, 세 이름이 붙은 버튼이 눌러도 안 열렸다.
    assert "docSides(f.document)" in lst


def test_뷰어는_단일_검토와_같은_부품을_쓴다() -> None:
    """부품을 복사하면 한쪽만 고쳐지는 버그가 생긴다. 출처만 갈라야 한다."""
    assert "function viewerSource(" in APP_JS
    convert = APP_JS[APP_JS.index("function maybeConvert("):
                     APP_JS.index("function syncViewer(")]
    assert "viewerSource()" in convert, "maybeConvert 가 단일 검토에 묶여 있다"
    assert 'state.mode !== "single"' not in convert
    marks = APP_JS[APP_JS.index("function loadMarks("):APP_JS.index("function repaintCard(")]
    assert "viewerSource()" in marks
    assert "window.DOCREVIEW.findings" not in marks, "loadMarks 가 단일 검토 payload 를 직접 읽는다"


def test_문서를_열_때_그_문서_근거만_넘긴다() -> None:
    """상대 문서의 인용을 함께 넘기면 여기서는 못 찾아 unlocated 만 쌓인다."""
    act = APP_JS[APP_JS.index("openCaseDoc: function"):APP_JS.index("closeCaseDoc: function")]
    assert 'sides.indexOf(key)' in act
    assert "ev[i]" in act


def test_문서를_바꾸면_이전_뷰어_상태를_지운다() -> None:
    """baseBlob·marks 가 남아 있으면 이전 문서의 형광펜이 새 문서에 얹힌다."""
    bounds = (("openCaseDoc: function", "closeCaseDoc: function"),
              ("closeCaseDoc: function", "loadCriteriaLayers: function"))
    for name, next_name in bounds:
        act = APP_JS[APP_JS.index(name):APP_JS.index(next_name)]
        assert "state.marks = null" in act, f"{name} 이 marks 를 안 지운다"
        assert "baseBlob: null" in act, f"{name} 이 baseBlob 을 안 지운다"


def test_특정_지적에서_문서를_열어도_그_문서의_전체_표시를_보존한다() -> None:
    """클릭한 지적은 첫 위치만 정한다. 나머지를 필터링하면 같은 문서의 서명 누락
    두 건이 PDF에서 사라지고, 사용자는 오른쪽 목록과 PDF 숫자가 왜 다른지 모른다."""
    act = APP_JS[APP_JS.index("openCaseDoc: function"):
                 APP_JS.index("closeCaseDoc: function")]
    assert "focus: only" in act, "처음 이동할 지적을 보존하지 않는다"
    assert "f.id === only" not in act, "클릭하지 않은 지적을 PDF에서 버린다"


def test_뷰어_화면에_pdf_마운트가_있다() -> None:
    doc = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                   VIEWS_JS.index("function caseReport(")]
    assert 'id="pdf-mount"' in doc
    assert "closeCaseDoc" in doc


def test_필드_대조표가_맞은_곳까지_보여준다() -> None:
    """지적 목록만으로는 맞은 곳이 안 보인다. 검토자는 "6곳 다 봤고 1곳이 틀렸다"를
    알아야지 "1곳이 틀렸다"만 알면 안 된다 — 팀이 xlsx No.13 에서 "비교용 엑셀"이라
    부른 것이 이 표다."""
    m = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                 VIEWS_JS.index("function caseFindingList(")]
    assert "p.matrix" in m
    # 가로가 산출물, 세로가 항목인 격자여야 교차점 하나로 어디서 틀어졌는지 보인다.
    assert "var cols = []" in m, "산출물이 열로 서지 않는다"
    # 안 올라온 곳·못 찾은 곳도 칸으로 남아야 몇 곳을 못 봤는지 보인다.
    assert "올라오지 않았습니다" in m and "값을 찾지 못했습니다" in m
    assert "설정 없음" in m and "대조 대상 아님" in m
    assert "m.seen" in m and "m.total" in m, "몇 곳을 봤는지 안 보여준다"


def test_어느_칸이_틀렸는지는_서버_판정을_쓴다() -> None:
    """버전 무시 같은 정규화가 서버에 있다. 화면이 값을 다시 비교하면 두 곳의
    판정이 어긋난다 — 갑지 "Apple (Ver 1.0.1 )" 와 을지 "Apple" 이 그 예다."""
    m = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                 VIEWS_JS.index("function caseFindingList(")]
    assert "c.ok === false" in m, "cell.ok 를 안 쓴다"


def test_격자_칸에서_그_문서를_열_수_있다() -> None:
    m = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                 VIEWS_JS.index("function caseFindingList(")]
    assert 'data-act="openCaseDoc"' in m


def test_지적_탭을_요약_바로_뒤에서_찾을_수_있다() -> None:
    report = VIEWS_JS[VIEWS_JS.index("function caseReport("):
                      VIEWS_JS.index("function caseCsvText(")]
    tabs = report[report.index("var tabs = "):report.index("var tabBar")]
    assert '"matrix"' in tabs
    assert tabs.index('"compare"') < tabs.index('"matrix"')
    assert '"지적 "' in tabs and '"필드 대조 "' in tabs


def test_CSV_에_매트릭스가_실린다() -> None:
    """팀이 요구한 산출물은 지적 목록이 아니라 비교용 엑셀이다."""
    csv = VIEWS_JS[VIEWS_JS.index("function caseCsvText("):]
    assert "p.matrix" in csv
    assert '"전 산출물 대조"' in csv


def test_제출_여부를_도구가_정하지_않는다() -> None:
    """도구는 **아직 확인 안 된 것**을 세어 말하고, 제출 여부는 사람이 정한다.

    "제출 보류"라고 쓰던 때가 있었는데 둘이 문제였다. (1) 제출은 조직의 결정이라
    도구가 막을 근거가 없다. (2) "못 본 것" 5건은 문서에 그 칸이 없거나 표기가
    달라 **팀 답변이 와야** 풀린다 — 도구가 아무리 잘 돌아도 못 없앤다. 그래서
    배지가 영원히 빨갛고, 늘 빨간 신호는 배경이 된다.
    """
    report = _case_report()

    assert "제출" not in report, "도구가 제출 여부를 판정하고 있다"
    assert "st.findings" in report and "st.unreviewed" in report
    assert "wideTotal" in report, "전 산출물 대조 범위를 안 보여준다"
    assert "manual.length" in report


def test_의미가_다른_숫자를_확인할_것으로_합산하지_않는다() -> None:
    """지적·미검토·미완료 직접 확인을 더한 17은 단위가 없어 해석할 수 없다."""
    report = _case_report()

    assert '"확인할 것"' not in report
    assert "caseLeft(" not in VIEWS_JS


def test_확정_시각은_확정_버튼_옆에_있다() -> None:
    """누르는 자리와 결과가 떨어져 있으면 눌렀는지 확인하러 다른 데를 봐야 한다."""
    manual = VIEWS_JS[VIEWS_JS.index("function caseManual("):
                      VIEWS_JS.index("function caseCriteria(")]

    assert "confirmedAt" in manual


def test_직접_확인은_사람이_눌러야_한다() -> None:
    """문서 대조로 판정할 수 없다(기준 §4). 도구가 대신 판정하면 안 된다."""
    m = VIEWS_JS[VIEWS_JS.index("function caseManual("):
                 VIEWS_JS.index("function caseReport(")]
    assert 'data-act="toggleManual"' in m
    assert 'data-act="confirmCase"' in m
    assert "대조 원천" in m, "무엇과 맞춰야 하는지 안 보여준다"


def test_확인_결과를_서버에_남긴다() -> None:
    """결과는 이미 이력에 남는데 확인 표시만 브라우저에 있으면, 나중에 그 기록을
    열었을 때 "이 건은 발급했나"를 알 수 없다."""
    act = APP_JS[APP_JS.index("confirmCase: function"):APP_JS.index("setCaseTab: function")]
    assert "api/history/" in act and "/confirm" in act
    assert "manualInputs" in act and '"Content-Type": "application/json"' in act
    assert "k.payload = body" in act, "추가 대조 결과를 현재 리포트에 반영하지 않는다"
    # 다시 손대면 확정이 풀려야 한다 — 옛 확정 시각이 남으면 거짓말이 된다.
    toggle = APP_JS[APP_JS.index("toggleManual: function"):APP_JS.index("confirmCase: function")]
    assert "invalidateManualResult(k, id)" in toggle
    assert 'k.confirmedAt = ""' in APP_JS


def test_직접_확인_수정과_저장이_경합하지_않는다() -> None:
    manual = VIEWS_JS[VIEWS_JS.index("function caseManual("):
                      VIEWS_JS.index("function caseReport(")]
    confirm = APP_JS[APP_JS.index("confirmCase: function"):
                     APP_JS.index("setCaseTab: function")]

    assert manual.count('v.kase.confirming ? "disabled "') >= 2
    assert "if (k.confirming) return" in confirm
    assert "body.manualChecked" in confirm


def test_직접_확인_오류와_csv_결과를_숨기지_않는다() -> None:
    report = _case_report()
    csv = VIEWS_JS[VIEWS_JS.index("function caseCsvText("):]

    assert 'role="alert"' in report and "k.error" in report
    assert "p.manualResults" in csv and '"외부 기준값 대조"' in csv


def test_기록에서_점검을_다시_열_수_있다() -> None:
    """저장은 하는데 여는 쪽이 없으면 목록에 뜨고도 눌리지 않는다 — 실제로
    그랬다. 확인 표시(manualChecked)까지 되살려야 "이 건은 발급했나"를 안다."""
    assert 'rec.kind === "case"' in APP_JS
    branch = APP_JS[APP_JS.index('if (rec.kind === "case")'):
                    APP_JS.index('if (rec.kind === "compare")')]
    assert "p.manualChecked" in branch
    assert "p.manualInputs" in branch
    assert "p.history" in branch, "기록에서 연 뒤 다시 확정할 이력 id가 없다"
    assert "p.confirmedAt" in branch
    assert 'step: "results"' in branch
    # 원본 파일은 브라우저가 안 들고 있다 — 뷰어를 열려고 하면 안 된다.
    assert "view: null" in branch and "files: []" in branch


def test_직접_확인에_외부_원천값_입력과_추가_대조_결과가_있다() -> None:
    manual = VIEWS_JS[VIEWS_JS.index("function caseManual("):
                      VIEWS_JS.index("function caseReport(")]

    assert "data-manual-input" in manual
    assert "추가 대조" in manual
    assert "manualResults" in manual
    assert "result.status" in manual and "일괄 수정 필요" in manual
    assert "affectedCount" in manual and "correctValue" in manual


def test_csv_가_칸_값_검사를_따로_이름짓는다():
    """단일 문서 지적을 "산출물 간 대조"로 적으면 CSV 를 받은 사람이 어느
    문서 둘을 맞대본 결과인 줄 안다."""
    src = VIEWS_JS

    i = src.index("function caseCsvText")
    body = src[i:i + 2200]
    assert '"칸 값 검사"' in body


def test_산출물_표에_지적_수가_보인다():
    """산출물 표가 파일 이름과 양식번호만 보여주면, 어느 문서를 봐야 하는지
    지적 목록을 다시 훑어야 한다."""
    src = VIEWS_JS

    i = src.index("function caseOutputTable")
    body = src[i:i + 3200]
    assert "o.findings" in body
    assert "검사 안 됨" in body
    assert "문서 단독 검사 " in body
    assert "문서 간 불일치 " in body
    assert "관련 미검토 " in body
    assert "관련 지적 없음" in body
    assert "!manualInput" in body, "외부 불일치와 '관련 지적 없음'을 함께 표시한다"
    assert "이상 없음" not in body


def _case_report() -> str:
    return VIEWS_JS[VIEWS_JS.index("function caseReport("):
                    VIEWS_JS.index("function caseCsvText(")]


def test_지적_출처_요약이_실제로_렌더된다() -> None:
    """전체 숫자만 보여주지 않고 문서 단독 검사와 문서 간 불일치로 풀어준다."""
    assert "caseFindingSummary(p)" in _case_report()
    summary = VIEWS_JS[VIEWS_JS.index("function caseFindingSummary("):
                       VIEWS_JS.index("function caseOutputTable(")]
    for label in ("전체 지적", "문서 단독 검사", "문서 간 불일치"):
        assert label in summary
    assert "c.case_wide + c.pair" in summary


def test_직접_확인은_탭_안에_있다() -> None:
    """탭을 옮길 때마다 체크박스 3줄이 따라다니면 안 된다. 결론(판정 배지)만
    항상 보이고, 확인 목록은 제 탭에서 본다."""
    report = _case_report()

    assert '["manual", ' in report, "직접 확인 탭이 없다"
    # 탭 밖(항상 보이는 자리)에서 부르면 안 된다.
    tail = report[report.index("var panel = "):]
    # 화면 컨테이너의 padding 값에 매달지 않는다 — 디자인이 바뀌면 같이 깨진다.
    # (data-scroll 은 탭 아래 스크롤 칸으로 이사했다 — return 문 자체를 잡는다.)
    always = tail[tail.index("return '<div class=\"page-shell\""):]
    assert "caseManual(" not in always, "직접 확인이 탭 밖에 걸려 있다"


def test_산출물_행을_누르면_그_문서를_연다() -> None:
    """행 전체의 숨은 클릭 대신 이름이 분명한 버튼으로 원문을 연다."""
    table = VIEWS_JS[VIEWS_JS.index("function caseOutputTable("):
                     VIEWS_JS.index("function caseFieldsPanel(")]

    assert 'data-act="openCaseDoc"' in table
    assert "문서에서 보기" in table
    assert "badge, 'openCaseDoc'" not in table


def test_요약의_이동은_명시적인_버튼이다() -> None:
    """카드 전체가 눌리는 구조는 눌러 보기 전까지 목적지를 알 수 없다."""
    summary = VIEWS_JS[VIEWS_JS.index("function caseFindingSummary("):
                       VIEWS_JS.index("function caseOutputTable(")]
    assert "전체 지적 보기" in summary
    assert "대조표 보기" in summary
    assert 'data-act="setCaseTab"' in summary


def test_필드_이름은_대조_상세를_펼치고_기준_이동은_분리한다() -> None:
    matrix = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                      VIEWS_JS.index("function caseFindingList(")]
    assert 'data-act="openMatrixDetail"' in matrix
    assert "대조 상세" in matrix
    assert "문서에서 읽은 값이 서로 다릅니다" in matrix
    assert "필요한 문서값을 모두 확보하지 못해" in matrix
    assert "이 기준 보기" in matrix
    assert "문서에서 보기" in matrix


def test_필드_대조_행은_호버되고_열린_상세는_본문과_구분된다() -> None:
    matrix = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                      VIEWS_JS.index("function caseFindingList(")]
    css = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert 'class="case-matrix-row' in matrix
    assert 'data-act="openMatrixDetail"' in matrix
    assert 'aria-expanded="' in matrix
    assert 'class="case-matrix-detail"' in matrix
    assert "case-matrix-doc-cell" not in matrix
    assert ".case-matrix-row:hover" in css
    assert ".case-matrix-doc-cell:hover" not in css
    opened = css[css.index(".case-matrix-row.is-open {"):]
    opened = opened[:opened.index("}")]
    assert "box-shadow" not in opened
    assert "background: var(--panel)" in opened
    detail = css[css.index(".case-matrix-detail {"):]
    detail = detail[:detail.index("}")]
    assert "background: var(--accent-weak)" in detail
    assert "border-left" not in detail
    assert "margin: 4px 10px 10px" in detail
    assert "border-radius: var(--r-md)" in detail
    assert "font-size: 12px" in detail


# ── 검토 기준 보기 ───────────────────────────────────────────────────────

def test_기준_탭이_있다() -> None:
    """리포트가 "시험항목명 0/4" 라고만 말하면 검토자는 어느 라벨을 찾다 실패한
    건지 모른다. 지금까지는 YAML 을 열어야 알 수 있었다."""
    assert '["criteria", ' in _case_report()


def test_기준을_서버에서_받아온다() -> None:
    """화면이 payload 로 다시 지어내면 실제로 도는 규칙과 갈린다."""
    assert "/api/teams/" in API_JS and "criteria" in API_JS
    assert "loadCriteria" in APP_JS


def test_기준_화면이_라벨과_형식을_보여준다() -> None:
    """이름만 보여주면 지금 산출물 탭과 다를 게 없다."""
    view = VIEWS_JS[VIEWS_JS.index("function caseCriteria("):
                    VIEWS_JS.index("function caseCsvText(")]

    for token in ("labels", "pattern", "required", "columns", "caseWide",
                  "signatures", "fixedText"):
        assert token in view, f"기준 화면이 {token} 를 안 보여준다"


def test_미검토_항목에서_기준으로_건너뛴다() -> None:
    """"못 봤다"만 알려주고 왜인지 못 짚으면 검토자가 할 수 있는 게 없다."""
    matrix = VIEWS_JS[VIEWS_JS.index("function caseMatrix("):
                      VIEWS_JS.index("function caseFindingList(")]

    assert "openCriteria" in matrix


def test_기준_탭을_직접_눌러도_불러온다() -> None:
    """openCriteria(필드 대조표에서 넘어오는 길)에서만 부르면, 탭을 직접 누른
    검토자는 criteria 가 null 인 화면 — "불러오지 못했습니다"만 본다."""
    tab = APP_JS[APP_JS.index("setCaseTab:"):APP_JS.index("pickCaseOutput:")]

    assert "loadCriteria" in tab


def test_안_불러온_것과_실패를_섞지_않는다() -> None:
    """criteria 가 null 인 이유는 셋이다 — 아직 안 부름 · 부르는 중 · 실패.
    셋을 "불러오지 못했습니다" 하나로 뭉치면 검토자가 뭘 해야 할지 모른다."""
    view = VIEWS_JS[VIEWS_JS.index("function caseCriteria("):
                    VIEWS_JS.index("function caseCsvText(")]

    assert "criteriaError" in view


def test_폴더를_놓으면_드롭존이_첨부됐다고_바뀐다() -> None:
    """단일 검토는 파일이 붙으면 같은 자리가 문서 카드 + "첨부 완료" 로 바뀐다.

    폴더 검토만 안 바뀌어서, 폴더를 놓아도 드롭존이 "폴더를 끌어다 놓거나..."
    그대로였다. 파일 목록이 아래 붙는 것을 못 본 사람은 업로드가 안 된 줄 알고
    다시 놓았다 — 같은 앱에서 같은 동작이 다르게 보이면 안 된다.
    """
    zone = VIEWS_JS[VIEWS_JS.index("function caseDropzone("):
                    VIEWS_JS.index("function caseUpload(")]

    assert "첨부 완료" in zone, "담긴 상태를 말하지 않는다"
    # 담긴 것을 실제로 보여준다 — 개수와 크기.
    assert "k.files.length" in zone, "몇 개가 담겼는지 안 센다"
    assert "fmtSize(" in zone, "담긴 용량을 안 보여준다"
    # 빈 상태와 담긴 상태가 갈려 있어야 한다.
    assert "if (!n) {" in zone, "상태가 하나뿐이다 — 담겨도 안 바뀐다"
    # 담긴 상태에서도 더 놓을 수 있어야 한다(addCaseFiles 가 중복을 거른다).
    # 주석에도 같은 낱말이 나오므로 마크업만 센다.
    assert zone.count("<div data-casedrop") == 2, "담긴 뒤 드롭을 안 받는다"


def test_비우는_버튼이_하나다() -> None:
    """드롭존 안의 "제거" 와 아래 "비우기" 가 같은 일을 했다.

    둘을 나란히 두면 어느 쪽이 무엇을 지우는지(고른 파일? 인식 결과?) 안 읽힌다.
    """
    upload = VIEWS_JS[VIEWS_JS.index("function caseDropzone("):
                      VIEWS_JS.index("function caseRecognize(")]
    assert upload.count('data-act="clearCaseFiles"') == 1, "비우는 버튼이 둘이다"


def test_지적이_걸친_문서를_전부_짚는다() -> None:
    """Finding.document 는 세 모양이다 — 낱장 · 쌍 대조(↔) · 전체 대조(·).

    화면이 `split(" ↔ ")` 하나만 알아서 전체 대조가 한 덩어리로 남았다. 그러면
    "시험의뢰서 · 시험계획서 · 시험설계서 에서 보기" 라는 버튼이 뜨고, 그 이름의
    산출물이 없으니 눌러도 아무 일이 없었다(openCaseDoc 의 `if (!out) return`).
    작성일자 선후 검사가 이 경로다.
    """
    helpers = (_ROOT / "web" / "helpers.js").read_text(encoding="utf-8")
    assert "H.docSides" in helpers, "문서 목록을 가르는 자리가 공용이 아니다"
    # 두 구분자를 다 안다.
    fn = helpers[helpers.index("H.docSides"):]
    assert "↔" in fn and "·" in fn, "구분자 하나만 안다"

    # 화면과 액션이 **같은** 규칙을 쓴다 — 갈리면 버튼은 뜨는데 눌러도 안 열린다.
    assert "docSides(f.document)" in VIEWS_JS, "화면이 공용 규칙을 안 쓴다"
    assert "docSides(f.document)" in APP_JS, "액션이 공용 규칙을 안 쓴다"
    assert 'split(" ↔ ")' not in VIEWS_JS, "화면에 옛 가정이 남아 있다"
    assert 'split(" ↔ ")' not in APP_JS, "액션에 옛 가정이 남아 있다"

    # 상대 문서가 여럿이면 버튼도 여럿이다.
    view = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                    VIEWS_JS.index("function caseManual(")]
    assert "var others = sides.filter" in view, "상대 문서를 하나만 가정한다"
    assert "others.map(" in view, "상대 문서마다 버튼을 안 그린다"


def test_심각도가_단일_검토와_같은_뱃지다() -> None:
    """폴더 쪽은 `<span class="mono">major</span>` 맨 글자였다.

    같은 심각도가 한쪽에서는 색 채운 알약, 한쪽에서는 회색 소문자로 보여
    두 화면이 다른 도구처럼 읽혔다. 뱃지 함수는 이미 있었는데 안 쓰고 있었다.
    거기에 색까지 --sev-maj-fg 로 박혀 있어 minor·info 도 주황이었다.
    """
    assert "function sevBadge(" in VIEWS_JS, "심각도 뱃지가 공용이 아니다"
    badge = VIEWS_JS[VIEWS_JS.index("function sevBadge("):
                     VIEWS_JS.index("function numberChip(")]
    # 모양은 한 곳(badge)에서 나온다. 예전에는 색 채운 알약(solidBadge)이었는데,
    # 노랑(minor)만 흰 글자 대비가 안 나와 어두운 글자를 써서 같은 굵기인데도
    # minor 만 굵어 보였다 — 지금은 셋 다 연한 뱃지고 색만 다르다.
    assert "return badge(pal" in badge, "단일 검토와 같은 뱃지를 안 쓴다"
    assert "solidBadge(" not in badge, "모양이 심각도마다 갈린다"
    # 미검토는 심각도가 아니다 — 채우면 지적으로 읽힌다.
    assert "f.unreviewed" in badge and 'badge(SEV.unknown' in badge, \
        "미검토를 심각도처럼 칠한다"

    # 리포트 목록은 지적과 **미검토가 섞인다** — 거기서는 뱃지가 둘을 가른다.
    lst = VIEWS_JS[VIEWS_JS.index("function caseFindingList("):
                   VIEWS_JS.index("function caseOtherPanel(")]
    assert "caseFindingBadge(f)" in lst, "리포트 목록이 공용 뱃지를 안 쓴다"
    assert "color:var(--sev-maj-fg);flex:none" not in lst, "주황이 박혀 있다"


def test_심각도_뱃지는_형광펜의_짝이라_남긴다() -> None:
    """PDF 위 형광펜이 심각도 색으로 칠해진다(pdfview.js _SEV).

    카드에서 등급을 빼면 노란 형광펜을 보고도 왜 노란지 알 길이 없다. 폴더
    검토는 규칙만 돌아 지금은 전부 MAJOR 라 뱃지가 늘 같지만, 여기서 뱃지가
    하는 일은 "등급을 가른다"가 아니라 "형광펜 색이 무엇을 뜻하는지 말한다"이다.
    """
    view = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                    VIEWS_JS.index("function caseManual(")]
    assert "caseFindingBadge(f)" in view, "형광펜 색을 설명할 자리가 없다"


def test_폴더_검토_뱃지는_엔진_용어를_사람_말로_바꾼다() -> None:
    badge = VIEWS_JS[VIEWS_JS.index("function caseFindingBadge("):
                     VIEWS_JS.index("function caseFindingSummary(")]
    for label in ("문서 단독 검사", "전체 필드 대조", "두 문서 대조", "외부 기준값 대조"):
        assert label in badge
    assert "labels[f.kind]" in badge


def test_기준_내부_id_는_화면에_안_낸다() -> None:
    """`F-성적서번호` · `W-작성일자-순서` · `1-7/대표자` — 셋이 규칙도 출처도 다르다.

    코드가 칸 이름으로 만든 것 · 팀 yaml 의 case_wide · 팀 yaml 의 pairs 가 한 자리에
    나란히 서면 검토자가 읽을 수 없다. 뱃지가 무엇이 잡았는지를 이미 사람 말로
    말하므로(label), id 는 그 옆에서 자리만 차지했다.

    값 자체는 payload 에 남는다 — CSV·리포트가 되짚을 때 쓴다.
    """
    # ruleId 는 버튼의 data-arg 로만 남고, 카드 본문 텍스트로 출력하지 않는다.
    lists = VIEWS_JS[VIEWS_JS.index("function caseFindingList("):
                     VIEWS_JS.index("function caseOtherPanel(")]
    assert "esc(f.ruleId) + '</span>'" not in lists
    # 뱃지가 그 자리를 대신한다 — 사람이 읽는 이름이어야 한다.
    badge = VIEWS_JS[VIEWS_JS.index("function sevBadge("):
                     VIEWS_JS.index("function numberChip(")]
    assert "f.label" in badge, "무엇이 잡았는지를 뱃지가 안 말한다"


def test_폴더_pdf_번호가_카드에도_연결된다() -> None:
    view = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                    VIEWS_JS.index("function caseManual(")]
    assert 'data-case-number="' in view
    assert "numberChip(markNos[f.id]" in view

    marks = APP_JS[APP_JS.index("function loadMarks("):
                   APP_JS.index("function repaintCard(")]
    assert 'querySelectorAll("[data-case-number]")' in marks
    assert "numberChip(byNo[id]" in marks
    assert "state.kase.view && state.kase.view.focus" in marks


def test_한_등급뿐이면_분포바를_안_그린다() -> None:
    """한 칸으로 꽉 찬 바와 `● Major 12` 한 줄은 위의 큰 숫자를 두 번 더 말한다.

    형광펜과 짝이 있는 뱃지와 달리 분포 바는 짝이 없다 — 값이 안 갈리면 뺀다.
    CRITICAL 을 지운 것과 같은 이유다(shared/models.py Severity).
    """
    view = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                    VIEWS_JS.index("function caseManual(")]
    assert "chips:" not in view, "셀 것이 하나뿐인데 범례를 넘긴다"

    shell = VIEWS_JS[VIEWS_JS.index("function issuesShell("):
                     VIEWS_JS.index("function sevChipsOf(")]
    assert "chips.length > 1" in shell, "한 등급뿐일 때도 분포 바를 그린다"


def test_검토_결과_패널이_단일_검토와_같은_껍데기다() -> None:
    """같은 일을 하는 자리가 다르면 두 화면이 다른 도구처럼 읽힌다.

    예전엔 단일은 400px 에 그림자·40px 큰 숫자·분포 바·범례였고, 폴더는 340px 에
    13px 한 줄("이 문서의 지적 3건")이었다.

    카드까지 합치지는 않는다 — 폴더 검토 카드는 지적이 걸친 문서 여럿과
    "저 문서에서 보기" 버튼을 진다. 단일 검토에는 그 개념이 없다.
    """
    assert "function issuesShell(" in VIEWS_JS, "패널 껍데기가 공용이 아니다"
    view = VIEWS_JS[VIEWS_JS.index("function caseDocView("):
                    VIEWS_JS.index("function caseManual(")]
    assert "issuesShell({" in view, "폴더 검토가 공용 껍데기를 안 쓴다"

    single = VIEWS_JS[VIEWS_JS.index("var issuesPanel = "):]
    assert single.startswith("var issuesPanel = issuesShell({"), \
        "단일 검토가 공용 껍데기를 안 쓴다"

    # 껍데기가 한 곳에서만 그려진다 — 치수를 두 곳에 두면 다시 갈라진다.
    # (그림자 값 자체는 다른 카드도 쓰는 공용 값이라 세면 안 된다.)
    assert VIEWS_JS.count("flex:none;margin:4px 32px 12px 0") == 1, \
        "패널 치수가 두 곳에 있다"
    # 폭은 화면을 따라간다. 400px 고정은 그 값이 맞던 한 화면 크기에서만 맞았다 —
    # 27인치에서는 지적 문장이 서너 글자마다 꺾이고, 13인치에서는 문서를 절반
    # 가까이 먹었다. 되돌리면 두 화면이 다시 같이 나빠지므로 여기서 막는다.
    # (고정폭 자체를 금지하는 건 아니다 — 모달은 400px 이 맞다. 이 패널만이다.)
    shell = VIEWS_JS[VIEWS_JS.index("function issuesShell("):]
    shell = shell[:shell.index("\n  function ")]
    assert "width:clamp(" in shell, "패널 폭이 고정값으로 되돌아갔다"


def test_필터가_없는_화면은_누르는_시늉을_안_한다() -> None:
    """폴더 검토에는 심각도 필터 상태가 없다(state.kase 에 sevFilter 가 없다).

    범례를 그대로 베껴 오면 눌러도 아무 일이 없는 버튼이 된다.
    """
    shell = VIEWS_JS[VIEWS_JS.index("function issuesShell("):
                     VIEWS_JS.index("function sevChipsOf(")]
    assert "c.on === undefined" in shell, "거를 수 있는지 안 가린다"
    assert 'cursor:pointer' in shell, "거를 수 있을 때의 어피던스가 없다"

    # 폴더 검토는 애초에 범례를 안 넘긴다(위 테스트 참고). 그래도 규칙은 남겨
    # 둔다 — 나중에 LLM 지적이 폴더 검토에 들어오면 등급이 갈리고, 그때 범례를
    # 넘기게 되는데 필터 상태는 여전히 없다.
    assert "sevChipsOf(findings, sevFilter)" in VIEWS_JS, "칩 생성이 공용이 아니다"


def test_뱃지를_그리는_자리가_하나다() -> None:
    """단일 검토 카드가 solidBadge 를 따로 불러서 거기만 `MAJOR` 가 남아 있었다.

    같은 카드 관용구가 화면마다 다른 말을 했다 — 폴더 검토는 종류 이름인데
    단일 검토는 심각도 이름이었다. 뱃지는 sevBadge 하나로만 낸다.
    """
    # solidBadge 를 직접 부르는 곳: 정의 1 + sevBadge 1 + 추적성 타입 뱃지 1.
    calls = [i for i in range(len(VIEWS_JS))
             if VIEWS_JS.startswith("solidBadge(", i)]
    assert len(calls) <= 3, f"solidBadge 를 {len(calls)}곳에서 직접 부른다"
    inner = VIEWS_JS[VIEWS_JS.index("function findingCardInner("):
                     VIEWS_JS.index("function findingCardHtml(")]
    assert "sevBadge(f)" in inner, "단일 검토 카드가 공용 뱃지를 안 쓴다"
    assert "solidBadge(" not in inner, "단일 검토 카드가 뱃지를 따로 그린다"


def test_뱃지가_지적_종류를_함께_보여준다() -> None:
    """표현 점검 하나가 스물몇 건을 낸다 — 오타와 앞뒤 모순이 같은 뱃지를 달았다.

    갈리는 것은 뱃지 **색**뿐이었다(주황=major 노랑=minor). 검토자가 그 뜻을 알 리
    없으니 종류를 글자로 드러낸다: `표현 점검 · 모순`.

    색은 그대로 심각도다 — PDF 형광펜이 심각도 색으로 칠해지므로(pdfview.js) 색까지
    종류로 바꾸면 형광펜과 카드가 끊긴다.
    """
    badge = VIEWS_JS[VIEWS_JS.index("function sevBadge("):
                     VIEWS_JS.index("function numberChip(")]
    assert "f.kind" in badge, "종류를 안 읽는다"
    assert "f.label" in badge, "무엇이 잡았나(label)는 남아야 한다"
    # 색은 심각도가 정한다 — 팔레트를 심각도로 골라 그대로 넘긴다.
    assert "SEV[f.sev]" in badge, "색이 심각도를 안 따른다"
    assert "badge(pal" in badge, "고른 팔레트를 안 쓴다"


def test_지적_목록이_종류를_떨어뜨리지_않는다() -> None:
    """payload 를 화면용으로 **다시 짓는** 자리가 둘이다 — 평면 목록과 체크리스트
    항목별 목록. 새 필드를 거기 안 적으면 뱃지까지 못 간다.

    실제로 그랬다: 서버는 kind 를 실어 보내고 sevBadge 는 f.kind 를 읽는데,
    중간에서 객체를 다시 만들며 빠뜨려 화면에는 아무 변화가 없었다.
    """
    lines = VIEWS_JS.splitlines()
    # 단일 검토의 지적만 본다. 문서 간 비교는 모양이 달라(type·typeLabel) 종류가 없다.
    builders = [i for i, ln in enumerate(lines)
                if "return { id: f.id, open: open" in ln and "sev: f.sev" in ln]
    assert len(builders) >= 2, f"지적 객체를 짓는 자리를 못 찾았다: {builders}"
    for i in builders:
        assert "kind: f.kind" in lines[i], f"{i + 1}행이 kind 를 안 옮긴다"


def test_평면_목록이_해당없음_판정을_떨어뜨리지_않는다() -> None:
    """검토자가 반영 확인에서 정리한 지적임을 카드가 말해야 한다.

    kind 와 같은 사고를 막는다 — 뷰 모델이 계산해도 객체를 다시 짓는 자리에서
    빠뜨리면 화면에는 아무 변화가 없다. 체크리스트 항목별 목록은 재검토
    맥락이 없어(반영 확인은 단일 검토에만 붙는다) 여기서 안 본다.
    """
    lines = VIEWS_JS.splitlines()
    hit = [ln for ln in lines if "isNew: !!newIds[f.id]" in ln]
    assert hit, "평면 목록이 신규 표시를 안 옮긴다"
    assert all("na: !!naIds[f.id]" in ln for ln in hit), \
        "해당없음 판정이 카드까지 안 간다"
    assert "lineageNaIds()" in VIEWS_JS, "판정을 어디서도 안 읽는다"

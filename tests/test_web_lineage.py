"""회신본을 올리면 이전 검토를 찾아 반영 확인(lineage)을 곁들인다."""
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text('[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
                        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    static = tmp_path / "frontend"; static.mkdir()
    (static / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    # 공통 기준을 하나 심는다. 기준이 검사를 이끄므로, 없으면 미작성 표시(TBD)
    # 검사기도 안 붙어 이 시나리오의 지적이 아예 안 난다 — repo 씨앗을 끌어오지
    # 않으려고 격리하되, 필요한 최소 기준은 여기서 만든다.
    seeds = tmp_path / "seeds"; seeds.mkdir()
    (seeds / "common.yaml").write_text(
        "name: 공통 기준\nitems:\n"
        "- 'no': '12'\n"
        "  text: 미작성 표시 잔존 확인\n"
        "  agent: 형식·완전성\n"
        "  mode: 규칙\n"
        # 기준이 자기를 검사할 규칙 이름을 댄다. 안 대면 사람 몫으로 떨어져
        # 이 시나리오의 TBD 지적이 아예 안 난다.
        "  check: placeholder\n", encoding="utf-8")
    return TestClient(create_app(settings=settings, frontend_dir=static,
                                 history_dir=tmp_path / "history",
                                 seed_dir=seeds))


def _sse_done(resp):
    for block in resp.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if ev.get("event") == "done":
                    return ev["payload"]
    return None


def _review(client, name, text):
    r = client.post("/api/review",
                    files={"file": (name, text.encode(), "text/markdown")},
                    data={"llm": "off"})
    return _sse_done(r)


def test_revision_upload_detects_prior_and_shows_lineage(client):
    # 1) 원본 검토: TBD 가 있어 지적이 하나 남는다.
    first = _review(client, "품기문서.md", "# 문서\nTBD\n본문 한 줄")
    assert first is not None and first.get("findings")

    # 2) 회신본(_수정): TBD 를 고쳐 그 지적이 사라진다.
    second = _review(client, "품기문서_수정.md", "# 문서\n본문 한 줄")
    assert second is not None
    # 이전 검토를 찾아 후보로 알린다.
    assert second.get("lineage_candidate"), "이전 검토를 못 찾았다"
    assert "품기문서" in second["lineage_candidate"]["title"]
    # 반영 확인: 이전 TBD 지적이 새 검토엔 없어 '안 보임'.
    lin = second.get("lineage")
    assert lin and lin["items"], "lineage 항목이 비었다"
    # 기계가 본 것이다 — "고쳐졌다"가 아니라 "같은 인용을 못 찾았다".
    assert any(it["status"] == "안 보임" for it in lin["items"])


def test_지적이_미검토_여부를_들고_나온다(client):
    """payload 의 지적마다 `unreviewed` 가 실려야 한다.

    이 칸이 통째로 빠져 있었다. 그래서 반영 확인이 **검토 과정 보고**(미검토·절단)와
    진짜 지적을 구별하지 못하고, 실행마다 문구가 바뀌는 보고를 "고쳐졌다"로 읽었다.
    """
    first = _review(client, "품기문서.md", "# 문서\nTBD\n본문 한 줄")
    assert all("unreviewed" in f for f in first["findings"]), "미검토 여부가 안 실렸다"


def test_plain_upload_without_prior_has_no_lineage(client):
    only = _review(client, "새문서.md", "# 문서\n본문")
    assert only is not None
    assert not only.get("lineage_candidate")
    assert not only.get("lineage")


# ── 검토자가 내린 판정을 이력에 남긴다 ─────────────────────────────────────
# 예전에는 판정 드롭다운에 아무것도 안 붙어 있었다(views.js 의 <select> 에 data-act
# 도 onchange 도 없었고 API 도 없었다). 검토자가 지적을 하나씩 판정해도 새로고침
# 한 번에 사라진다 — 화면은 고칠 수 있다고 보여주면서 실제로는 못 고쳤다.


def _lineage_review(client):
    """이전 검토 → 회신본 순으로 돌려 lineage 가 붙은 payload 를 돌려준다."""
    _review(client, "품기문서.md", "# 문서\nTBD\n본문 한 줄")
    second = _review(client, "품기문서_수정.md", "# 문서\n본문 한 줄")
    assert second and second.get("lineage"), "lineage 가 없다"
    assert second.get("history", {}).get("id"), "이력에 저장되지 않았다"
    return second


def test_판정을_저장하면_이력에_남는다(client):
    payload = _lineage_review(client)
    entry_id = payload["history"]["id"]

    r = client.post(f"/api/history/{entry_id}/lineage",
                    data={"verdicts": json.dumps({"0": "해당없음"})})
    assert r.status_code == 200, r.text
    assert r.json()["lineageVerdicts"] == {"0": "해당없음"}

    # 이력을 다시 열어도 남아 있어야 한다 — 그게 저장의 목적이다.
    again = client.get(f"/api/history/{entry_id}").json()
    assert again["payload"]["lineageVerdicts"] == {"0": "해당없음"}
    assert again["payload"]["lineageConfirmedAt"]


def test_판정을_붙일_열쇠를_함께_준다(client):
    """lineage 항목마다 `key` — 이 판정이 **어느 지적에 대한 것인가**.

    예전에는 화면이 순번으로 저장했다(`{"3": "해당없음"}`). 그 검토 안에서만 뜻이
    있어서, 다음 검토의 3번째는 다른 지적이다 — 판정을 이어줄 수가 없다.
    """
    payload = _lineage_review(client)
    items = payload["lineage"]["items"]
    keys = [it.get("key") for it in items]
    assert all(keys), "판정을 붙일 열쇠가 없다"
    assert len(set(keys)) == len(keys), "열쇠가 겹치면 판정이 엉뚱한 지적에 붙는다"
    # 열쇠는 지적의 신원에서 나온다 — 순번이면 안 된다.
    assert not any(k.isdigit() for k in keys)

    from modules.agent_history import verdict_key
    assert keys == [verdict_key(it["finding"]) for it in items]


def test_해당없음_판정이_다음_검토로_이어진다(client):
    """3회차 검토가 2회차의 "해당없음"을 초기값으로 들고 나와야 한다.

    안 이으면 검토자가 매번 같은 지적을 다시 "해당없음"으로 눌러야 한다 — 검사기는
    다음에도 똑같이 내기 때문이다.
    """
    from modules.agent_history import verdict_key

    # 1·2회차: 지적이 계속 남아 있는 문서(TBD 를 안 고친다).
    _review(client, "품기문서.md", "# 문서\nTBD\n본문 한 줄")
    second = _review(client, "품기문서_수정.md", "# 문서\nTBD\n본문 한 줄")
    items = second["lineage"]["items"]
    key = items[0]["key"]
    assert verdict_key(items[0]["finding"]) == key

    # 검토자가 "우리 문서엔 해당 안 된다"고 판정한다.
    r = client.post(f"/api/history/{second['history']['id']}/lineage",
                    data={"verdicts": json.dumps({key: "해당없음"})})
    assert r.status_code == 200, r.text

    # 3회차: 같은 지적이 또 나오지만, 다시 묻지 않는다.
    third = _review(client, "품기문서_v2.md", "# 문서\nTBD\n본문 한 줄")
    carried = third.get("lineageVerdicts") or {}
    assert carried, "지난 판정을 안 이어받았다"
    assert set(carried.values()) == {"해당없음"}
    assert carried.get(third["lineage"]["items"][0]["key"]) == "해당없음"
    # 어느 것이 이어받은 것인지도 알려야 한다 — 안 알리면 검토자가 기계가 정한
    # 판정으로 오해한다. 화면이 "지난 판정" 표시를 여기서 얻는다.
    assert third.get("lineageCarried") == carried, "이어받은 사실을 안 알린다"

    # 검토자가 덮어쓰면 더 이상 "지난 판정"이 아니다. 안 떼면 이번에 자기가
    # 바꿔놓고도 지난번 것을 물려받은 줄 안다 — 실측으로 그렇게 남아 있었다.
    tid = third["history"]["id"]
    key3 = third["lineage"]["items"][0]["key"]
    body = client.post(f"/api/history/{tid}/lineage",
                       data={"verdicts": json.dumps({key3: "미반영"})}).json()
    assert body["lineageVerdicts"] == {key3: "미반영"}
    assert body["lineageCarried"] == {}, "덮어썼는데 지난 판정으로 남았다"


def test_반영됨_판정은_다음_검토로_안_이어진다(client):
    """`반영됨` 은 이번 회차에 고쳐졌나에 대한 답이다. 이으면 안 고친 결함이 넘어간다."""
    _review(client, "품기문서.md", "# 문서\nTBD\n본문 한 줄")
    second = _review(client, "품기문서_수정.md", "# 문서\nTBD\n본문 한 줄")
    key = second["lineage"]["items"][0]["key"]
    client.post(f"/api/history/{second['history']['id']}/lineage",
                data={"verdicts": json.dumps({key: "반영됨"})})

    third = _review(client, "품기문서_v2.md", "# 문서\nTBD\n본문 한 줄")
    assert not (third.get("lineageVerdicts") or {}), "반영됨이 따라왔다"


def test_기계_판정을_덮지_않는다(client):
    """판정 근거가 사라지면 검토자가 자동 판정을 믿을지 판단할 수 없다."""
    payload = _lineage_review(client)
    entry_id = payload["history"]["id"]
    before = [i["status"] for i in payload["lineage"]["items"]]

    client.post(f"/api/history/{entry_id}/lineage",
                data={"verdicts": json.dumps({"0": "미반영"})})

    after = client.get(f"/api/history/{entry_id}").json()["payload"]
    assert [i["status"] for i in after["lineage"]["items"]] == before, \
        "사람 판정이 기계 판정을 덮었다"


def test_모르는_판정은_거절한다(client):
    """브라우저가 보낸 값을 그대로 믿지 않는다."""
    entry_id = _lineage_review(client)["history"]["id"]
    r = client.post(f"/api/history/{entry_id}/lineage",
                    data={"verdicts": json.dumps({"0": "대충됨"})})
    assert r.status_code == 400 and "대충됨" in r.json()["detail"]


def test_없는_이력에는_저장하지_않는다(client):
    r = client.post("/api/history/없는id/lineage",
                    data={"verdicts": json.dumps({"0": "반영됨"})})
    assert r.status_code == 404


# ── 화면이 판정을 실제로 보내는가 ──────────────────────────────────────────
# 이 저장소의 프론트는 빌드가 없어 파일을 글로 검사한다. 서버가 받을 준비를 해도
# 드롭다운이 아무 데도 안 보내면 예전과 똑같다 — 그게 원래 결함이었다.

from pathlib import Path  # noqa: E402

_WEB = Path(__file__).resolve().parent.parent / "web"
_VIEWS = (_WEB / "views.js").read_text(encoding="utf-8")
_APP = (_WEB / "app.js").read_text(encoding="utf-8")
_API = (_WEB / "api.js").read_text(encoding="utf-8")


def test_서버가_미검토_검사기를_반영확인에_알린다():
    """이번에 제 몫을 다 못 한 검사기를 `blind` 로 넘겨야 한다.

    안 넘기면 그 검사기의 이전 지적이 `안 보임` → 초기 판정 `반영됨` 이 된다. 안 본
    것을 고쳐졌다고 읽는 것이라, 안 고친 결함이 그대로 나간다.
    """
    src = (Path(__file__).resolve().parents[1]
           / "src" / "app" / "server.py").read_text(encoding="utf-8")
    assert "blind=incomplete_checkers(" in src, "미검토 검사기를 안 넘긴다"



def test_화면이_순번이_아니라_열쇠로_저장한다():
    """views.js·app.js 가 서버가 준 key 를 쓰는지 글로 확인한다(빌드가 없다)."""
    assert "item.key || String(idx)" in _APP, "app.js 가 아직 순번으로 저장한다"
    assert "saved[it.key]" in _VIEWS, "views.js 가 아직 순번으로 읽는다"
    # 옛 이력은 순번으로 저장돼 있다. 폴백을 지우면 그 판정이 빈 값으로 보인다.
    assert "saved[String(i)]" in _VIEWS, "옛 이력의 판정을 못 읽는다"


def test_내보내기_본문은_액션이_아니라_뷰가_만든다():
    """네 형식에 판정이 실리는지는 node 가 실제로 돌려 확인한다.

    (web/tests/lineage_view.test.js — tests/test_frontend_js.py 가 감싼다.)

    여기서는 그 검사가 닿는 자리에 코드가 있는지만 지킨다. 본문 만들기가 액션
    안으로 돌아가면 DOM 없이 못 돌려서, 판정이 실렸는지를 글자 대조로만 지키게
    된다 — 실제로 그랬고, 조건만 꺼도 문자열이 남아 안 잡혔다.
    """
    body = _APP[_APP.index("exportAs: function"):]
    body = body[:body.index("\n    },")]
    for kind in ("reviewHtml", "reviewJson", "reviewMd", "reviewCsv"):
        assert f"_views.{kind}()" in body, f"{kind} 를 뷰에서 안 가져온다"
    assert "lineageView" not in body, "본문 만들기가 액션으로 돌아왔다"


def test_판정_드롭다운에_동작이_붙어_있다():
    """고른 값이 저장으로 이어져야 한다. 안 이으면 새로고침 한 번에 사라진다.

    네이티브 `<select>` 가 아니라 앱이 그리는 셀렉트를 쓴다(펼친 목록을 OS 가
    그리면 화면의 다른 목록과 안 어울린다). 그래서 change 가 아니라 id 앞머리
    `lnv-` 로 잇는다 — app.js 의 selPick 이 그걸 보고 판정 저장을 부른다.
    """
    block = _VIEWS[_VIEWS.index("function lineageHtml("):]
    block = block[:block.index("</div>';\n    }")]
    assert "selectField('lnv-'" in block, "고른 값이 아무 데도 안 간다"
    # 주석에 적힌 <select> 는 세지 않는다 — 마크업을 내는 자리만 본다.
    code = "\n".join(ln for ln in block.split("\n") if "//" not in ln)
    assert "'<select" not in code, "네이티브 셀렉트로 되돌아갔다"

    pick = _APP[_APP.index("selPick: function"):]
    pick = pick[:pick.index("\n    },")]
    assert 'selId.indexOf("lnv-")' in pick, "selPick 이 판정을 안 잇는다"
    assert "setLineageVerdict" in pick, "고른 값이 저장으로 안 간다"


def test_반영_확인_항목을_누르면_문서로_간다():
    """`그대로 있음` 은 이번 문서에도 그 지적이 있다 — 눌러서 그 자리로 가야 한다.

    예전에는 `select` 가 "갈아끼울 카드가 없으면 통째로 다시 그리고 끝"이었다.
    반영 확인 탭에는 지적 카드가 아예 없어서, 항목을 눌러도 새로고침만 되고 문서는
    그대로였다. **갈아끼울 카드가 없는 것과 갈 곳이 없는 것은 다르다.**
    """
    block = _VIEWS[_VIEWS.index("function lineageHtml("):]
    block = block[:block.index("</div>';\n    }")]
    assert 'data-act=\"select\"' in block, "항목이 문서로 안 이어진다"
    assert "it.matchId" in block, "짝이 없는 항목까지 누르게 두면 안 된다"

    act = _APP[_APP.index("select: function"):]
    act = act[:act.index("suggestFix:")]
    assert "if (cards.length) repaintCard" in act, "카드가 없으면 도로 통째로 그린다"
    assert "pdfview.goTo" in act, "문서를 안 옮긴다"


def test_판정을_바꾸면_문서_형광펜도_바뀐다():
    """"판정을 왜 바꾸나"에 대한 답이 화면에 있어야 한다.

    거르는 규칙은 views.js 가 진다(node 로 실제 돌려 확인 — lineage_view.test.js).
    여기서는 액션이 그걸 부르는지, 탭을 옮길 때도 다시 칠하는지를 지킨다.
    """
    assert "_views.lineageMarkIds()" in _APP, "탭에 따라 안 거른다"
    # 색도 바꾼다. 이 탭에서 칠해진 것은 전부 "지난 지적인데 아직 미반영" 하나라,
    # 심각도 색으로 칠하면 두 탭이 같은 것을 말하는 것처럼 보인다.
    marks = _APP[_APP.index("function markItems()"):]
    marks = marks[:marks.index("\n  }")]
    assert 'sev: "past"' in marks, "반영 확인 탭인데 심각도 색으로 칠한다"
    assert "--sev-past-hl" in (_WEB / "pdfview.js").read_text(encoding="utf-8"), \
        "그 색을 뷰어가 모른다"
    assert "--sev-past-hl:" in (_WEB / "index.html").read_text(encoding="utf-8"), \
        "색 토큰이 없다"
    # 탭 기본값은 views.js 한 곳에서만 정한다. 두 곳에 두었더니 화면과 로직이
    # 다른 탭을 봤다 — 판정을 바꿔도 형광펜이 안 바뀌었다.
    assert "_views.reviewTabNow()" in _APP, "탭 기본값을 또 따로 정하고 있다"
    # 판정 하나에 통째로 다시 그리면 뷰어가 PDF 를 다시 연다(pdf-mount 재생성).
    act = _APP[_APP.index("setLineageVerdict: function"):]
    act = act[:act.index("\n    },")]
    # 정상 경로만 본다. 저장 실패·이력 없음은 배너를 띄워야 하니 통째로 그리는
    # 것이 맞다 — 거기선 이미 뷰어가 깜빡여도 알릴 것이 있다.
    happy = act[:act.index("if (!D.historyId)")]
    happy = "\n".join(ln for ln in happy.split("\n") if "//" not in ln)
    assert "render()" not in happy, "판정을 바꿀 때마다 문서가 깜빡인다"
    assert "repaintLineageCounts()" in happy, "셈이 안 갱신된다"
    for act in ("setReviewTab", "setLineageVerdict"):
        block = _APP[_APP.index(act + ": function"):]
        block = block[:block.index("\n    },") if "\n    }," in block[:4000] else 400]
        assert "paintMarks()" in block, f"{act} 뒤에 문서를 다시 안 칠한다"


def test_좌표가_도착하면_반영_확인_패널을_다시_그린다():
    """형광펜 번호는 검토가 **끝난 뒤** 오는 좌표에서 온다.

    이 패널은 지적 카드가 아니라 repaintCard 가 못 닿는다. 안 그리면 번호가 영영
    안 붙어 "카드를 눌러도 어딘지 모르겠다"가 된다. 통째로 render() 하면 뷰어가
    PDF 를 다시 여니 이 패널만 갈아끼운다.
    """
    load = _APP[_APP.index("function loadMarks("):]
    load = load[:load.index("\n  }")]
    assert "repaintLineagePanel()" in load, "좌표가 와도 패널을 안 그린다"

    fn = _APP[_APP.index("function repaintLineagePanel()"):]
    fn = fn[:fn.index("\n  }")]
    assert "render()" not in fn, "패널 하나 그리려고 문서를 다시 연다"
    assert "lineagePanelHtml()" in fn, "패널을 어디서 짓는지 모른다"


def test_형광펜_번호가_인용마다_붙는다():
    """배지를 지적당 하나만 그리면 인용이 셋이어도 문서엔 `1` 하나만 보인다.

    좌표 쪽은 tests/test_locate.py 가 실제 PDF 로 확인한다. 여기서는 뷰어가 그
    번호를 쓰는지, 배지를 번호마다 그리는지를 지킨다.
    """
    view = (_WEB / "pdfview.js").read_text(encoding="utf-8")
    assert "m.no != null ? m.no : it.no" in view, "마크의 제 번호를 안 쓴다"
    assert 'var badgeKey = m.id + "|" + m.no;' in view, "배지를 지적당 하나만 그린다"
    # 한 곳을 여러 지적이 물면 배지도 여럿이다 — 겹쳐 찍으면 맨 위만 보인다.
    assert "atSpot[spot]" in view, "같은 자리 배지를 안 밀어낸다"
    # 밀어내는 폭은 배지 실제 폭(w) 기준 — 세 자리 번호(100+)는 원이 아니라
    # 알약으로 늘어나므로 d 로 밀면 겹친다.
    assert "(w + 3) * slot" in view, "밀어내는 폭이 없다"


def test_판정_액션이_서버로_보낸다():
    act = _APP[_APP.index("setLineageVerdict: function"):]
    act = act[:act.index("setCaseTab:")]
    assert "/lineage" in act and "POST" in act, "서버로 안 보낸다"
    assert "historyId" in act, "어느 이력에 남길지 모른다"


def test_저장된_판정을_다시_읽는다():
    assert "lineageVerdicts" in _API, "이력을 다시 열 때 판정이 사라진다"
    assert "historyId" in _API, "판정을 남길 이력 id 를 안 들고 있다"


def test_화면과_엔진의_어휘가_같다():
    """어휘가 파이썬(lineage.py)과 JS(views.js) 두 곳에 적혀 있다.

    빌드가 없어 상수를 공유할 수 없으니 글로 대조한다. 어긋나면 서버가 400 을 내거나
    (모르는 판정) 드롭다운이 빈 값으로 뜬다 — 검토자는 이유를 알 길이 없다.
    """
    from modules.agent_history import DEFAULT_VERDICT, LEGACY, OBSERVED, STATUSES

    opts = _VIEWS[_VIEWS.index("statusOpts:"):]
    opts = opts[:opts.index("]")]
    for s in STATUSES:
        assert s in opts, f"드롭다운에 {s!r} 가 없다"

    block = _VIEWS[_VIEWS.index("function lineageView() {"):]
    block = block[:block.index("\n  }")]
    for word in OBSERVED:
        assert word in block, f"화면이 관찰값 {word!r} 를 모른다"
    for old, new in LEGACY.items():
        assert f'"{old}": "{new}"' in block, f"옛 어휘 {old!r} 를 못 읽는다"
    for auto, verdict in DEFAULT_VERDICT.items():
        assert f'"{auto}": "{verdict}"' in block, f"{auto!r} 의 초기 판정이 없다"


# ── 재검토 화면은 탭 둘로 나뉜다 ───────────────────────────────────────────
# 예전에는 반영 확인 패널과 지적 카드가 한 열에 세로로 이어져, 지난번 지적 스물몇
# 건을 지나야 이번 결과가 나왔다. 게다가 신규 지적이 위(목록)와 아래(카드)에 두 번
# 보였다.


def test_재검토면_패널이_탭_둘로_나뉜다():
    assert 'data-act="setReviewTab"' in _VIEWS, "탭이 없다"
    # 반영 확인 탭 이름은 lineageTabLabel() 이 짓는다 — 진행률 셈이 화면과
    # app.js 두 곳에 있어 갈릴 뻔해서 한 곳으로 모았다(node 로 실제 확인한다).
    assert '["lineage", lineageTabLabel(v.lineage)]' in _VIEWS
    assert '"findings", "이번 검토' in _VIEWS
    # 이력이 없으면 탭도 없다 — 처음 검토하는 문서는 지금과 같아야 한다.
    # 기본값은 reviewTabNow() 한 곳에서만 정한다 — 두 곳에 두었더니 화면과
    # 형광펜 필터가 서로 다른 탭을 봤다.
    now = _VIEWS[_VIEWS.index("function reviewTabNow()"):]
    now = now[:now.index("\n  }")]
    assert 'D.lineage ? (state.reviewTab || "lineage") : "findings"' in now, \
        "이력 없이도 탭이 뜬다"


def test_신규_지적을_두_번_그리지_않는다():
    """목록과 카드에 같은 지적이 두 번 나오던 것을 카드 뱃지로 대신한다."""
    block = _VIEWS[_VIEWS.index("function lineageHtml("):]
    block = block[:block.index("function findingCardInner(")]
    assert "newFindings.length ?" not in block, "신규 목록을 아직 그린다"
    assert "f.isNew" in _VIEWS, "카드에 신규 표시가 없다"


def test_뷰어는_그대로다():
    """탭은 오른쪽 패널 안에만 든다 — 좌우 2단 구조를 건드리면 뷰어가 줄어든다."""
    row = _VIEWS[_VIEWS.index('id="results-row"'):]
    row = row[:row.index("</div>';")]
    assert "docViewer" in row and "issuesPanel" in row
    assert "setReviewTab" not in row, "탭이 뷰어와 같은 단에 있다"

// 반영 확인 뷰 모델. 화면과 회신서(내보내기)가 함께 쓰는 자리라, 여기가 틀리면
// 검토자가 화면에서 본 판정과 작성자에게 보낸 판정이 갈린다.
//
// views.js 는 DOM 을 안 만지는 순수 함수도 한 파일에 들어 있어서, window 와
// 의존 모듈만 흉내 내면 Node 에서 그대로 돌릴 수 있다.
// 실행: node --test web/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const SEP = "\u001f";                       // lineage.KEY_SEP 과 같아야 한다
const key = (...parts) => ["q", "consistency", ...parts].join(SEP);

function loadViews() {
  const win = { DR: {} };
  win.DR.ICONS = new Proxy({}, { get: () => "" });
  win.DR.helpers = {
    esc: (s) => String(s == null ? "" : s), rgba: () => "", fmtSize: () => "",
    download: () => {}, downloadBlob: () => {}, docSides: () => ({}),
    sentences: (s) => [String(s == null ? "" : s)],
  };
  const src = fs.readFileSync(path.join(__dirname, "..", "views.js"), "utf8");
  new Function("window", src)(win);
  const st = {};                       // 앱 상태. 테스트가 필요한 것만 채운다
  const views = win.DR.views({
    state: st, props: {}, render: () => {},
    backend: { errorBanner: () => "", ago: () => "", fmtElapsed: () => "" },
  });
  return { win, views, st };
}

function withLineage(verdicts) {
  const { win, views } = loadViews();
  win.DOCREVIEW = {
    lineage: {
      items: [
        { finding: { message: "용어 혼용", section: "10.1", checker: "consistency" },
          status: "그대로 있음", key: key("운영 파일") },
        { finding: { message: "수일치 오류", section: "7.3", checker: "consistency" },
          status: "안 보임", key: key("all contents") },
        { finding: { message: "영문 문법", section: "12", checker: "consistency" },
          status: "판단 못 함", key: key("Does the") },
      ],
      new_findings: [{ message: "새 결함", section: "7.1", sev: "minor" }],
    },
    lineageVerdicts: verdicts || {},
  };
  global.window = win;                      // views.js 안의 window 참조용
  return views.lineageView();
}

test("기계는 고쳐졌다고 단정하지 않는다", () => {
  const L = withLineage();
  // 셋 다 미반영이다. 실측에서 `안 보임` 은 거의 다 "못 찾았을 뿐" 이었고,
  // 안 고쳤는데 `반영됨` 이면 결함이 그대로 나간다.
  assert.deepStrictEqual(L.items.map((i) => i.status),
                         ["미반영", "미반영", "미반영"]);
  // 기계가 본 것은 그대로 남는다 — 그게 검토자가 판정할 근거다.
  assert.deepStrictEqual(L.items.map((i) => i.auto),
                         ["그대로 있음", "안 보임", "판단 못 함"]);
});

test("검토자가 고른 판정이 초기값을 이긴다", () => {
  const L = withLineage({ [key("Does the")]: "해당없음" });
  assert.strictEqual(L.items[2].status, "해당없음");
  // 기계가 본 것은 안 바뀐다 — 판정의 근거라 지우면 안 된다.
  assert.strictEqual(L.items[2].auto, "판단 못 함");
});

test("판정은 순번이 아니라 지적의 신원에 붙는다", () => {
  // 순번으로 저장하면 다음 검토에서 3번째가 다른 지적이라 엉뚱한 데 붙는다.
  const L = withLineage({ [key("all contents")]: "해당없음" });
  assert.strictEqual(L.items[1].status, "해당없음");
  assert.strictEqual(L.items[0].status, "미반영");
});

test("옛 이력은 순번으로 저장돼 있다 — 그것도 읽는다", () => {
  const L = withLineage({ 0: "해당없음" });
  assert.strictEqual(L.items[0].status, "해당없음");
});

test("요약은 사람 판정으로 센다", () => {
  const L = withLineage({ [key("Does the")]: "해당없음" });
  assert.deepStrictEqual(L.summary, { closed: 0, open: 2, na: 1, added: 1 });
});

// 검토자가 작성자에게 돌려줄 물건이 회신서다. 네 형식 어느 것으로 받아도 판정이
// 함께 나가야 한다 — 안 실으면 드롭다운은 눌러도 자기만 보고 끝난다.
function exportsOf(verdicts) {
  const { win, views } = loadViews();
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, sections: [],
    findings: [{ id: 1, sev: "major", checker: "consistency", section: "3",
                 message: "이번 검토 지적", evidence: [] }],
    sevMeta: { major: { label: "치명", order: 0 }, minor: { label: "주의", order: 1 },
               info: { label: "참고", order: 2 } },
    lineage: {
      items: [{ finding: { message: "용어 혼용", section: "10.1", checker: "consistency" },
                status: "안 보임", key: key("운영 파일") }],
      new_findings: [],
    },
    lineageVerdicts: verdicts || {},
  };
  global.window = win;
  return { html: views.reviewHtml(), md: views.reviewMd(),
           csv: views.reviewCsv(), json: views.reviewJson() };
}

test("내보내기 넷 모두에 판정이 실린다", () => {
  const out = exportsOf();
  for (const kind of ["html", "md", "csv", "json"]) {
    assert.match(out[kind], /용어 혼용/, kind + " 에 지난번 지적이 없다");
  }
  assert.match(out.html, /반영 확인 1건/);
  assert.match(out.md, /## 반영 확인 1건/);
  assert.match(out.csv, /판정,기계 관찰,위치,지난번 지적/);
  assert.strictEqual(JSON.parse(out.json).lineage.items[0].verdict, "미반영");
});

test("검토자가 바꾼 판정이 회신서에 그대로 나간다", () => {
  const out = exportsOf({ [key("운영 파일")]: "해당없음" });
  const j = JSON.parse(out.json);
  assert.strictEqual(j.lineage.items[0].verdict, "해당없음");
  // 기계가 본 것도 함께 — 검토자가 왜 그렇게 판정했는지 근거가 남는다.
  assert.strictEqual(j.lineage.items[0].observed, "안 보임");
  assert.deepStrictEqual(j.lineage.summary, { closed: 0, open: 0, na: 1, added: 0 });
  assert.match(out.csv, /"해당없음","안 보임"/);
  assert.match(out.md, /\*\*\[해당없음\]\*\*/);
});

test("이번 검토 지적은 그대로 실린다", () => {
  const out = exportsOf();
  assert.strictEqual(JSON.parse(out.json).total, 1);
  assert.match(out.csv, /"이번 검토 지적"/);
  assert.match(out.md, /이번 검토 지적/);
});


// 판정 드롭다운은 앱이 그리는 셀렉트(.sel)여야 한다. 네이티브 <select> 는 펼친
// 목록을 OS 가 그려서 화면의 다른 목록과 안 어울린다.
function lineagePanel(verdicts) {
  const { win, views } = loadViews();
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: {
      items: [{ finding: { message: "용어 혼용", section: "10.1", checker: "consistency" },
                status: "안 보임", key: key("운영 파일") }],
      new_findings: [],
    },
    lineageVerdicts: verdicts || {},
  };
  global.window = win;
  return views.lineageCardHtml === undefined ? null : views;
}

test("판정 셀렉트는 앱이 그린다", () => {
  const views = lineagePanel();
  const html = views.selectField("lnv-0", "판정", ["미반영", "반영됨", "해당없음"],
                                 { value: "반영됨", cls: "sel-sm" });
  assert.match(html, /class="sel sel-sm"/);
  assert.match(html, /data-value="반영됨"/);
  // 고른 값이 단추에 보이고, 목록에서도 체크로 표시된다.
  assert.match(html, /<span class="sel-label">반영됨<\/span>/);
  assert.match(html, /aria-selected="true"[^>]*data-arg="lnv-0\|반영됨"/);
  // 안 고른 것들은 체크가 없어야 한다.
  assert.strictEqual((html.match(/aria-selected="true"/g) || []).length, 1);
  // id 앞머리로 app.js 의 selPick 이 판정 저장으로 잇는다.
  assert.match(html, /id="lnv-0"/);
});

test("아직 안 고른 셀렉트는 placeholder 로 남는다", () => {
  const views = lineagePanel();
  const html = views.selectField("signupTeam", "팀 선택", ["EV1", "EV2"]);
  assert.match(html, /data-ph="1">팀 선택</);
  assert.strictEqual((html.match(/aria-selected="true"/g) || []).length, 0);
});


test("지난 검토에서 이어받은 판정은 그렇다고 표시한다", () => {
  const { win, views } = loadViews();
  const k = key("운영 파일");
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: {
      items: [{ finding: { message: "용어 혼용", section: "10.1", checker: "consistency" },
                status: "그대로 있음", key: k }],
      new_findings: [],
    },
    lineageVerdicts: { [k]: "해당없음" },
    lineageCarried: { [k]: "해당없음" },
  };
  global.window = win;
  const L = views.lineageView();
  assert.strictEqual(L.items[0].status, "해당없음");
  // 기계가 정한 것으로 오해하면 안 된다 — 지난번에 검토자가 내린 판정이다.
  assert.strictEqual(L.items[0].carried, true);
  assert.match(views.lineageCardHtml(), /지난 판정/);
});

test("이번에 누른 판정은 이어받은 것으로 표시하지 않는다", () => {
  const { win, views } = loadViews();
  const k = key("운영 파일");
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: {
      items: [{ finding: { message: "용어 혼용", section: "10.1", checker: "consistency" },
                status: "그대로 있음", key: k }],
      new_findings: [],
    },
    lineageVerdicts: { [k]: "해당없음" },
  };
  global.window = win;
  assert.strictEqual(views.lineageView().items[0].carried, false);
});


// "그래서 어딘데" — 목록만 있으면 검토자가 문서의 그 자리를 못 찾는다.
function panelWith(item, verdicts, marks) {
  const { win, views, st } = loadViews();
  if (marks) st.marks = marks;         // 뷰어가 매긴 형광펜 번호
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: { items: [item], new_findings: [] },
    lineageVerdicts: verdicts || {},
  };
  global.window = win;
  return views;
}

const 지적 = { message: "용어 혼용", section: "10.1", checker: "consistency",
             evidence: [{ quote: "운영 파일 과 운영파일" }] };

test("그대로 있는 지적은 눌러서 문서의 그 자리로 간다", () => {
  const views = panelWith({ finding: 지적, status: "그대로 있음",
                            key: key("운영 파일"), match_id: "F-7" });
  const L = views.lineageView();
  assert.strictEqual(L.items[0].matchId, "F-7");
  const html = views.lineageCardHtml();          // 뷰 모델이 살아 있는지만 확인
  assert.match(html, /용어 혼용/);
});

test("안 보이는 지적은 갈 자리가 없으니 지난 근거를 보여준다", () => {
  const views = panelWith({ finding: 지적, status: "안 보임",
                            key: key("운영 파일"), match_id: "" });
  const L = views.lineageView();
  assert.strictEqual(L.items[0].matchId, "");
  // 문서에서 직접 찾을 수 있게 지난번 인용을 들고 있어야 한다.
  assert.strictEqual(L.items[0].quote, "운영 파일 과 운영파일");
});


test("화면이 어떻게 봐야 하는지를 스스로 말한다", () => {
  // 어휘를 아무리 골라도 처음 보는 사람은 `그대로 있음`·`안 보임` 이 무엇의
  // 결과인지 모른다 — 기계가 본 것인지 자기가 해야 할 일인지부터 안 갈린다.
  const views = panelWith({ finding: 지적, status: "안 보임",
                            key: key("운영 파일"), match_id: "" });
  const html = views.lineageHtml(views.lineageView(), null);
  assert.match(html, /고쳐졌다고 단정하지는 않으니/);
  for (const word of ["그대로 있음", "안 보임", "판단 못 함", "해당없음"]) {
    assert.match(html, new RegExp(word), word + " 의 뜻을 안 알려준다");
  }
});


// 판정을 바꾸면 문서에서도 뭐가 달라져야 한다. `반영 확인` 탭에서는 지난 지적 중
// 아직 미반영으로 둔 것만 칠한다 — 그게 "판정을 왜 바꾸나"에 대한 답이다.
function marksFor(items, verdicts) {
  const { win, views } = loadViews();
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: { items: items, new_findings: [] },
    lineageVerdicts: verdicts || {},
  };
  global.window = win;
  lastViews = views;
  return views.lineageMarkIds();
}
let lastViews = null;

const 지적2 = { message: "수일치", section: "7.3", checker: "consistency",
              evidence: [{ quote: "all contents was" }] };

test("아직 미반영인 지난 지적만 문서에 칠한다", () => {
  const keep = marksFor([
    { finding: 지적, status: "그대로 있음", key: key("운영 파일"), match_id: "F-1" },
    { finding: 지적2, status: "그대로 있음", key: key("all contents"), match_id: "F-2" },
  ], { [key("all contents")]: "반영됨" });          // 검토자가 하나를 정리했다
  assert.deepStrictEqual(keep, { "F-1": true });
});

test("해당없음으로 두면 문서에서도 빠진다", () => {
  const keep = marksFor(
    [{ finding: 지적, status: "그대로 있음", key: key("운영 파일"), match_id: "F-1" }],
    { [key("운영 파일")]: "해당없음" });
  assert.deepStrictEqual(keep, {});
});

test("안 보이는 지적은 칠할 자리가 없다", () => {
  const keep = marksFor(
    [{ finding: 지적, status: "안 보임", key: key("운영 파일"), match_id: "" }],
    { [key("운영 파일")]: "미반영" });              // 미반영이어도 가리킬 곳이 없다
  assert.deepStrictEqual(keep, {});
});

test("재검토가 아니면 거를 것이 없다", () => {
  const { win, views } = loadViews();
  win.DOCREVIEW = { doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {} };
  global.window = win;
  assert.strictEqual(views.lineageMarkIds(), null);
});


test("반영 확인도 지적 카드와 같은 관용구로 그린다", () => {
  // 목록형으로 두었더니 이번 검토 탭과 나란히 놓았을 때 딴 화면처럼 보였다.
  const views = panelWith({ finding: 지적, status: "그대로 있음",
                            key: key("운영 파일"), match_id: "F-7" });
  const html = views.lineageHtml(views.lineageView(), null);
  assert.match(html, /class="fcard"/);
  assert.match(html, /data-act="select" data-arg="F-7"/);
  assert.match(html, /그대로 있음/);
});

test("갈 곳 없는 항목은 누를 수 있게 두지 않는다", () => {
  const views = panelWith({ finding: 지적, status: "안 보임",
                            key: key("운영 파일"), match_id: "" });
  const html = views.lineageHtml(views.lineageView(), null);
  assert.ok(!/data-act="select"/.test(html), "가리킬 자리가 없는데 누르게 뒀다");
  assert.match(html, /지난 근거: 운영 파일 과 운영파일/);
});


// 탭 기본값이 두 곳에 있으면 화면과 로직이 다른 탭을 본다. 실제로 그랬다 —
// 화면은 재검토면 반영 확인부터 그리는데 state.reviewTab 은 null 이라, 형광펜
// 필터가 "반영 확인 탭이 아니다"로 판단해 판정을 바꿔도 아무 일도 안 났다.
test("재검토면 아무것도 안 눌러도 반영 확인 탭이다", () => {
  const views = panelWith({ finding: 지적, status: "그대로 있음",
                            key: key("운영 파일"), match_id: "F-1" });
  assert.strictEqual(views.reviewTabNow(), "lineage");
  // 그 상태에서 형광펜 필터가 실제로 걸려야 한다.
  assert.deepStrictEqual(views.lineageMarkIds(), { "F-1": true });
});

test("재검토가 아니면 이번 검토 탭이다", () => {
  const { win, views } = loadViews();
  win.DOCREVIEW = { doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {} };
  global.window = win;
  assert.strictEqual(views.reviewTabNow(), "findings");
});


test("해당없음도 처리한 것으로 센다", () => {
  // 다섯 건을 정리해도 숫자가 안 움직이면 일한 티가 안 난다.
  // 탭 이름을 직접 읽는다 — 여기서 산수를 되풀이하면 코드가 아니라 테스트를 잰다.
  const { win, views } = loadViews();
  win.DOCREVIEW = {
    lineage: {
      items: [
        { finding: 지적, status: "그대로 있음", key: key("a"), match_id: "F-1" },
        { finding: 지적, status: "안 보임", key: key("b"), match_id: "" },
        { finding: 지적, status: "그대로 있음", key: key("c"), match_id: "F-3" },
      ],
      new_findings: [],
    },
    lineageVerdicts: { [key("a")]: "해당없음", [key("c")]: "반영됨" },
  };
  global.window = win;
  assert.strictEqual(views.lineageTabLabel(views.lineageView()), "반영 확인 2/3");
});

test("해당없음으로 둔 지적은 이번 검토 카드에도 표시된다", () => {
  // 카드를 지우지는 않는다 — 기계가 낸 것을 화면이 삼키면 안 된다. 대신
  // "이미 해당없음으로 정리됐다"를 말해준다.
  const { win, views } = loadViews();
  const k = key("운영 파일");
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, sections: [],
    findings: [{ id: "F-1", sev: "major", checker: "consistency", section: "10.1",
                 message: "용어 혼용", evidence: [] }],
    sevMeta: { major: { label: "치명", order: 0 }, minor: { label: "주의", order: 1 },
               info: { label: "참고", order: 2 } },
    lineage: {
      items: [{ finding: 지적, status: "그대로 있음", key: k, match_id: "F-1" }],
      new_findings: [],
    },
    lineageVerdicts: { [k]: "해당없음" },
  };
  global.window = win;
  const html = views.reviewHtml();
  assert.match(html, /용어 혼용/);      // 지워지지 않는다
});


test("해당없음으로 정리한 지적을 이번 검토 쪽에 알린다", () => {
  const keep = marksFor([
    { finding: 지적, status: "그대로 있음", key: key("a"), match_id: "F-1" },
    { finding: 지적2, status: "그대로 있음", key: key("b"), match_id: "F-2" },
  ], { [key("a")]: "해당없음" });
  assert.deepStrictEqual(keep, { "F-2": true });        // 형광펜에선 빠지고
  const { views } = { views: lastViews };
  assert.deepStrictEqual(views.lineageNaIds(), { "F-1": true });   // 카드엔 표시된다
});

test("카드에 해당없음 뱃지가 붙는다", () => {
  const { win, views } = loadViews();
  win.DOCREVIEW = { sevMeta: { major: { label: "치명", order: 0 } } };
  global.window = win;
  const f = { id: "F-1", sev: "major", checker: "consistency", kind: "표기",
              message: "용어 혼용", loc: "§10.1", no: 1, open: false };
  assert.ok(!/해당없음/.test(views.findingCardInner(f, {})),
            "판정하지 않았는데 뱃지가 붙었다");
  assert.match(views.findingCardInner(Object.assign({}, f, { na: true }), {}),
               /해당없음/, "정리한 지적인데 카드가 말하지 않는다");
});


test("그대로 있는 지적은 형광펜과 같은 번호를 단다", () => {
  // 번호는 뷰어가 매긴 것을 그대로 쓴다. 화면이 따로 매기면 "3번"이 형광펜과
  // 카드에서 서로 다른 것을 가리킨다.
  const views = panelWith({ finding: 지적, status: "그대로 있음",
                            key: key("운영 파일"), match_id: "F-7" },
                          null, { items: [{ id: "F-7", no: 3 }] });
  assert.strictEqual(views.lineageView().items[0].no, 3);
});

test("안 보이는 지적은 번호가 없다", () => {
  // 문서에 자리가 없으니 가리킬 번호도 없다. 지어내지 않는다.
  const views = panelWith({ finding: 지적, status: "안 보임",
                            key: key("운영 파일"), match_id: "" },
                          null, { items: [{ id: "F-7", no: 3 }] });
  assert.strictEqual(views.lineageView().items[0].no, null);
});


// 좌표(POST /api/locate)는 검토가 **끝난 뒤에** 온다. 형광펜 번호가 그때 정해지니,
// 도착하면 반영 확인 패널을 다시 그려야 번호가 붙는다. 안 그리면 영영 안 붙는다.
test("좌표가 늦게 와도 패널을 다시 그리면 번호가 붙는다", () => {
  const { win, views, st } = loadViews();
  win.DOCREVIEW = {
    lineage: {
      items: [{ finding: 지적, status: "그대로 있음",
                key: key("운영 파일"), match_id: "F-7" }],
      new_findings: [],
    },
    lineageVerdicts: {},
    lineageCandidate: { title: "품기문서.docx", at: "" },
  };
  global.window = win;

  // 아직 좌표가 안 왔다 — 번호가 없다.
  assert.strictEqual(views.lineageView().items[0].no, null);
  const before = views.lineagePanelHtml();
  assert.match(before, /id="lineagePanel"/, "다시 그릴 자리를 못 잡는다");

  // 좌표 도착.
  st.marks = { items: [{ id: "F-7", no: "3" }] };
  const after = views.lineagePanelHtml();
  assert.strictEqual(views.lineageView().items[0].no, "3");
  assert.ok(after.length > before.length || after !== before,
            "좌표가 왔는데 패널이 그대로다");
  assert.match(after, /번 형광펜/, "번호 칩이 안 붙었다");
  // 어느 검토와 대조했는지도 같이 나온다 — 안내 상자 머리행의 문서명이다.
  // 물음("이어서 반영 확인?")으로 두었더니 누르는 것처럼 보여 평서문 안내로 바꿨다.
  assert.match(after, /다시 찾아본 결과입니다/);
});


test("검토자가 덮어쓰면 지난 판정이 아니다", () => {
  // 실측으로 이렇게 남아 있었다 — 이어받은 값은 `해당없음`, 저장된 값은 `미반영`,
  // 그런데 태그는 그대로. 이번에 자기가 바꿔놓고도 물려받은 줄 안다.
  const { win, views } = loadViews();
  const k = key("운영 파일");
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: {
      items: [{ finding: 지적, status: "그대로 있음", key: k, match_id: "" }],
      new_findings: [],
    },
    lineageVerdicts: { [k]: "미반영" },          // 검토자가 바꿨다
    lineageCarried: { [k]: "해당없음" },          // 이어받은 값은 이것이었다
  };
  global.window = win;
  const it = views.lineageView().items[0];
  assert.strictEqual(it.status, "미반영");
  assert.strictEqual(it.carried, false, "덮어썼는데 지난 판정으로 남았다");
});

test("이어받은 값 그대로면 지난 판정이다", () => {
  const { win, views } = loadViews();
  const k = key("운영 파일");
  win.DOCREVIEW = {
    doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {},
    lineage: {
      items: [{ finding: 지적, status: "그대로 있음", key: k, match_id: "" }],
      new_findings: [],
    },
    lineageVerdicts: { [k]: "해당없음" },
    lineageCarried: { [k]: "해당없음" },
  };
  global.window = win;
  assert.strictEqual(views.lineageView().items[0].carried, true);
});


// ── 검토 중 화면 ────────────────────────────────────────────────────────
// 끝난 순간 아래 진행 줄이 통째로 사라져, 방금까지 100% 를 말하던 자리가 빈칸이
// 되었다 — 진행이 되감긴 것처럼 읽혔다.

function progressScreen(done) {
  const { win, views, st } = loadViews();
  st.done = done;
  st.rev = { startedAt: 1, prepAt: 1, prep: {}, lanes: [], done: {}, note: "" };
  win.DOCREVIEW = { doc: { name: "문서.pdf" }, findings: [], sections: [], sevMeta: {} };
  global.window = win;
  return views.progressFragments({
    done: done, totalCount: 6,
    review: { lanes: [{ kind: "chunk", label: "표현 점검", total: 10,
                        doneCount: 10, status: "done" }],
              pct: 100, note: "", elapsed: "0:03" },
  });
}

test("끝나도 진행 조각은 100% 그대로다", () => {
  for (const done of [false, true]) {
    const frag = progressScreen(done);
    assert.match(frag.pct, /100%/, `done=${done} 에서 퍼센트가 사라졌다`);
    assert.ok(frag.lanes.length > 0, `done=${done} 에서 레인이 비었다`);
  }
});

test("작업량을 받기 전 진행 본문도 살아 있는 상태로 보인다", () => {
  const { views } = loadViews();
  const frag = views.progressFragments({
    done: false,
    review: { lanes: [], pct: null, note: "", elapsed: "0:01" },
  });
  assert.match(frag.note, /class="review-warmup"/);
  assert.match(frag.note, /검토 기준과 검사 순서를 준비하고 있습니다/);
  assert.match(frag.pct, /class="review-live"/);
  assert.match(frag.pct, /review-loading-dots/);
});

test("첫 결과 전의 활성 레인도 검사 중으로 읽힌다", () => {
  const { views } = loadViews();
  const metrics = views.laneMetrics({ total: 10, doneCount: 0, status: "run" });
  assert.strictEqual(metrics.counter, "0/10 · 검사 중");
});

test("검토 중 머리말에는 움직이는 모래시계 상태 표시가 붙는다", () => {
  const { views } = loadViews();
  const running = views.progressHead(false, 0, ["검토 중…", "문서를 확인합니다"], 35, 0);
  assert.match(running, /class="review-hourglass"/);
  assert.match(running, /검토 중…/);

  const done = views.progressHead(true, 0, ["", ""], 100, 0);
  assert.doesNotMatch(done, /review-hourglass/);
  assert.match(done, /검토 완료/);
});

test("레인에서 검사 대상과 실제 범위를 함께 설명한다", () => {
  const { views } = loadViews();
  const html = views.laneInner({
    label: "문서 전체 점검", total: 3, doneCount: 1, status: "run",
    description: "용어·참조·수치·동일 ID의 문서 내 일관성",
    scope: "분할 검사 · 전체 비교 제한", limited: true,
  }, false);
  assert.match(html, /동일 ID/);
  assert.match(html, /전체 비교 제한/);
  assert.match(html, /1\/3/);
});

test("진행 중인 바만 브랜드색이고 완료 바와 체크는 같은 회색이다", () => {
  const { views } = loadViews();
  const active = views.laneInner({
    label: "표현 점검", total: 4, doneCount: 2, status: "run",
  }, false);
  assert.match(active, /linear-gradient\(90deg, var\(--accent\), var\(--brand-highlight\)\)/);

  const done = views.laneInner({
    label: "표현 점검", total: 4, doneCount: 4, status: "done",
  }, false);
  assert.match(done, /data-lane-fill[^>]+background:var\(--neutral\)/);
  assert.match(done, /color:var\(--neutral\)/);
  assert.doesNotMatch(done, /brand-highlight/);
});

test("방금 끝난 레인은 진행색에서 완료색으로 이어지는 전환을 쓴다", () => {
  const { views } = loadViews();
  const changed = views.laneInner({
    label: "표현 점검", total: 4, doneCount: 4, status: "done",
  }, true);
  assert.match(changed, /review-lane-fill is-completing/);
  assert.match(changed, /review-lane-check is-new/);

  const settled = views.laneInner({
    label: "표현 점검", total: 4, doneCount: 4, status: "done",
  }, false);
  assert.doesNotMatch(settled, /is-completing/);
  assert.doesNotMatch(settled, /is-new/);
});

test("완료 문구는 지적과 미검토를 구분한다", () => {
  const { views } = loadViews();
  assert.match(views.progressHead(true, 0, ["", ""], 100, 0), /모든 자동 검사 완료/);
  assert.match(views.progressHead(true, 0, ["", ""], 100, 2), /일부 기준 미검토/);
  const mixed = views.progressHead(true, 3, ["", ""], 100, 1);
  assert.match(mixed, /지적 3건/);
  assert.match(mixed, /미검토 1건/);
});


// ── 심각도 뱃지 ─────────────────────────────────────────────────────────
// 색만 심각도를 말한다. 모양은 셋 다 같아야 한다 — 예전에는 노랑(minor)만 흰 글자
// 대비가 안 나와 어두운 글자를 써서, 같은 굵기인데도 minor 만 굵어 보였다.

test("심각도 뱃지는 색만 다르고 모양은 같다", () => {
  const { win, views } = loadViews();
  win.DOCREVIEW = { sevMeta: {} };
  global.window = win;
  const of = (sev) => views.findingCardInner(
    { id: "F", sev: sev, checker: "c", message: "m", loc: "§1", open: false }, {});
  const shape = (html) => html
    .replace(/var\(--sev-[a-z]+-(bg|fg|bd)\)/g, "COLOR")   // 색만 지운다
    .match(/<span style="[^"]*COLOR[^"]*"/)[0];
  const [maj, min, info] = ["major", "minor", "info"].map((s) => shape(of(s)));
  assert.strictEqual(maj, min, "minor 만 모양이 다르다");
  assert.strictEqual(maj, info, "info 만 모양이 다르다");
  // 색은 여전히 심각도를 말한다.
  assert.match(of("major"), /--sev-maj-/);
  assert.match(of("minor"), /--sev-min-/);
});


test("번호가 여럿이면 하나씩 누를 수 있다", () => {
  // 한 지적이 여러 곳을 물면 번호도 여럿이다("3, 4, 5, 6"). 예전에는 한 덩어리라
  // 카드를 눌러도 늘 첫 번호로만 갔고 나머지로 갈 길이 없었다.
  const { win, views } = loadViews();
  win.DOCREVIEW = { sevMeta: {} };
  global.window = win;

  const many = views.numberChip("3, 4, 5", null, "F-1");
  const args = [...many.matchAll(/data-arg="([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(args, ["F-1|3", "F-1|4", "F-1|5"]);

  // 하나뿐이어도 번호 자체가 PDF의 같은 번호로 간다. 폴더 검토 카드는 카드 전체를
  // 숨은 클릭 대상으로 쓰지 않으므로, 이 연결이 없으면 숫자와 원문이 끊긴다.
  const one = views.numberChip("3", null, "F-1");
  assert.match(one, /data-act="goMark"/);
  assert.match(one, /data-arg="F-1\|3"/);

  // id 를 안 주는 자리는 이동할 지적이 없으므로 예전 그대로 한 덩어리다.
  const plain = views.numberChip("W-작성일자", "기준 번호");
  assert.ok(!/data-act/.test(plain));
  assert.match(plain, /기준 번호/);
});

// 검토 결과 화면 — 큰 숫자는 진짜 지적(major+minor)만 세고, info·미검토는
// 부제로 따로 말한다. 미검토는 info 칩이 아니라 자기 칩으로 켜고 끈다.
// 실행: node --test web/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function build(st, findings) {
  const win = { DR: {}, location: { protocol: "http:", href: "http://x/" } };
  win.DR.ICONS = new Proxy({}, { get: () => "<svg/>" });
  win.DR.helpers = {
    esc: (s) => String(s == null ? "" : s), rgba: () => "", fmtSize: () => "1KB",
    download: () => {}, downloadBlob: () => {}, docSides: () => ({}),
    sentences: (s) => [String(s == null ? "" : s)],
  };
  new Function("window", fs.readFileSync(path.join(__dirname, "..", "views.js"), "utf8"))(win);
  const views = win.DR.views({
    state: st, props: { accent: "#356998" }, render: () => {},
    backend: { errorBanner: () => "", ago: () => "1분 전", fmtElapsed: () => "0:03" },
  });
  win.DOCREVIEW = {
    doc: { name: "문서.pdf", type: "PDF" }, sections: [], findings: findings, stages: [],
    images: [], compare: { stages: [], findings: [], docA: {}, docB: {}, stats: {} },
    sevMeta: { major: { label: "치명", kr: "치명", order: 0 },
               minor: { label: "주의", kr: "주의", order: 1 },
               info: { label: "참고", kr: "참고", order: 2 } },
    typeMeta: { missing: { label: "누락" }, mismatch: { label: "불일치" },
                extra: { label: "초과" } },
  };
  global.window = win;
  return views;
}

function state(over) {
  return Object.assign({
    mode: "single", screen: "results", stageIndex: -1, done: true, reviewed: true,
    sevFilter: { major: true, minor: true, info: true, unreviewed: true },
    checkerFilter: "all", sort: "severity", exportMenuOpen: false, issuesCollapsed: false,
    rev: { startedAt: 0, prepAt: 0, prep: {}, lanes: [], done: {}, note: "" },
    kase: { step: "upload", checked: {}, tab: "summary" },
    cstep: "setup", cstageIndex: -1, cdone: false,
    files: {}, annot: { busy: false, msg: "", numbers: {} },
    viewer: { baseBlob: null, mode: "orig", converting: false, convertError: null },
    marks: null, selected: null, theme: "light", fix: null,
    user: { name: "김검토", team: "ai-test-cert-1" },
    server: { checklists: [], checklist: "", scope_label: "", llm_provider: "local",
              llm_model: "qwen", placeholder_markers: ["TBD"],
              teams: [{ id: "ai-test-cert-1", name: "AI시험인증1팀" }] },
    history: [], detect: null, runChecklistId: "",
    crun: { checklist: null, results: {}, name: "", documentName: "" },
    clib: { list: [], detail: null }, checklist: "",
  }, over || {});
}

// 진짜 지적 둘 + 검토 과정 보고(info) 하나 + 미검토 보고 하나.
const FINDINGS = [
  { id: "f1", checker: "consistency", label: "표현 점검", sev: "major",
    message: "앞뒤 모순", section: "2.1", evidence: [] },
  { id: "f2", checker: "completeness", label: "필수 항목 확인", sev: "minor",
    message: "항목 누락", section: "3", evidence: [] },
  { id: "f3", checker: "consistency", label: "표현 점검", sev: "info",
    message: "인용 대조 실패 2건 제외", evidence: [] },
  { id: "f4", checker: "consistency_doc", label: "문서 전체 점검", sev: "info",
    unreviewed: true, message: "LLM 무응답", evidence: [] },
];

test("지적 수는 major+minor 만 — info·미검토는 따로 센다", () => {
  const v = build(state(), FINDINGS).renderVals();
  assert.strictEqual(v.issueCount, 2);
  assert.strictEqual(v.infoCount, 1);
  assert.strictEqual(v.unreviewedCount, 1);
  const unrev = v.sevChips.filter((c) => c.sev === "unreviewed")[0];
  assert.ok(unrev, "미검토 칩이 따로 있다");
  assert.strictEqual(unrev.count, 1);
  const info = v.sevChips.filter((c) => c.sev === "info")[0];
  assert.strictEqual(info.count, 1, "info 칩은 미검토를 세지 않는다");
});

test("info 칩을 꺼도 미검토 보고는 남는다", () => {
  const st = state({ sevFilter: { major: true, minor: true, info: false, unreviewed: true } });
  const ids = build(st, FINDINGS).renderVals().tableFindings.map((f) => f.id);
  assert.ok(!ids.includes("f3"), "info 지적은 걸러진다");
  assert.ok(ids.includes("f4"), "미검토 보고는 info 칩과 무관하게 남는다");
});

test("미검토 칩은 미검토만 가린다", () => {
  const st = state({ sevFilter: { major: true, minor: true, info: true, unreviewed: false } });
  const ids = build(st, FINDINGS).renderVals().tableFindings.map((f) => f.id);
  assert.ok(ids.includes("f3"));
  assert.ok(!ids.includes("f4"));
});

test("검사기 칩은 내부 이름이 아니라 검토자용 분류로 묶는다", () => {
  const v = build(state(), FINDINGS).renderVals();
  assert.deepStrictEqual(v.checkerChips.map((c) => c.k), ["all", "form", "expr"]);
  assert.deepStrictEqual(v.checkerChips.map((c) => c.label),
    ["전체", "형식 검사", "표현 검사"]);
});

test("분류 필터는 그 분류의 검사기들을 함께 거른다", () => {
  const st = state({ checkerFilter: "expr" });
  const ids = build(st, FINDINGS).renderVals().tableFindings.map((f) => f.id);
  // consistency(f1,f3)와 consistency_doc(f4) 모두 표현 검사다
  assert.deepStrictEqual(ids.sort(), ["f1", "f3", "f4"]);
});

test("정렬·검사기 칩이 실제로 화면에 붙는다", () => {
  const views = build(state(), FINDINGS);
  const html = views.view(views.renderVals());
  assert.ok(html.includes('data-act="setSort"'), "정렬 칩");
  assert.ok(html.includes('data-act="setChecker"'), "검사기 칩");
  assert.ok(html.includes("참고 1 · 미검토 1"), "부제가 info·미검토를 말한다");
});

test("지적 0건이어도 미검토가 남았으면 이상 없음이라 말하지 않는다", () => {
  const views = build(state(), [FINDINGS[3]]);
  const html = views.view(views.renderVals());
  assert.ok(!html.includes("이상 없음"));
});

test("지적의 기준 라벨에 층(공통/팀별/업로드)이 붙는다", () => {
  const views = build(state(), FINDINGS);
  global.window.DOCREVIEW.checklist = {
    items: [
      { no: "1", text: "용어 일관성", group: "", status: "flagged", layer: "업로드",
        mode: "LLM-조각", note: "", findings: [{ id: "f1" }] },
      { no: "2", text: "오탈자", group: "", status: "flagged", layer: "공통",
        mode: "LLM-조각", note: "", findings: [{ id: "f2" }] },
    ],
    summary: { flagged: 2, clean: 0, unreviewed: 0, na: 0, outofscope: 0,
               noanswer: 0, manual: 0, total: 2 },
  };
  const v = views.renderVals();
  const byId = {};
  v.tableFindings.forEach((f) => { byId[f.id] = f; });
  assert.strictEqual(byId.f1.criteria, "[업로드] 용어 일관성");
  assert.strictEqual(byId.f2.criteria, "[공통] 오탈자");
  // 수정안 프롬프트로 가는 기준 본문에는 층 표기가 섞이지 않는다
  assert.strictEqual(views.criterionTextFor("f1"), "용어 일관성");
  // 항목별 묶음 화면의 항목 헤더에도 층 태그가 산다
  const html = views.view(v);
  assert.ok(html.includes(">업로드</span>"), "층 태그 렌더");
});

test("펼친 카드의 인용마다 자기 형광펜 번호 칩이 붙는다", () => {
  // 같은 절 인용이 둘이면(용어 모순) 번호 없이는 둘째 인용을 문서에서 못 찾는다.
  const findings = [{ id: "f1", checker: "consistency", label: "표현 점검", sev: "major",
    message: "용어 불일치", section: "22.2",
    evidence: [{ quote: "운영권 조정", section: "22.2" },
               { quote: "운영권조정", section: "22.2" }] }];
  const marks = { items: [{ id: "f1", no: "14, 15", page: 1, marks: [],
                            quote_nos: [14, 15] }], pages: {} };
  const views = build(state({ marks, selected: "f1" }), findings);
  const html = views.view(views.renderVals());
  assert.ok(html.includes('data-arg="f1|14"'));
  assert.ok(html.includes('data-arg="f1|15"'), "둘째 인용도 제 번호로 점프");
});

test("완료 뒤 진행 탭에 돌아와도 검토 중이라 말하지 않는다", () => {
  // 완료 처리(api.js)가 done 을 유지한다 — 예전엔 결과 화면으로 넘어가며 false 로
  // 되돌려서, 진행 탭 재방문이 끝난 검토를 "검토 중…"이라고 보여줬다.
  const views = build(state({ screen: "progress", done: true, stageIndex: -1 }), FINDINGS);
  const html = views.view(views.renderVals());
  assert.ok(html.includes("검토 완료"));
  assert.ok(!html.includes("검토 중…"));
});

test("형광펜 번호가 많으면 접힌 카드는 +N 으로 줄인다", () => {
  const many = Array.from({ length: 18 }, (_, i) => String(i + 1)).join(", ");
  const marks = { items: [{ id: "f1", no: many, page: 1, marks: [] }], pages: {} };
  const closed = build(state({ marks }), FINDINGS);
  assert.ok(closed.view(closed.renderVals()).includes(">+13<"), "18개 → 5개 + '+13'");
  const open = build(state({ marks, selected: "f1" }), FINDINGS);
  const html = open.view(open.renderVals());
  assert.ok(!html.includes(">+13<"), "펼치면 전부 보인다");
  assert.ok(html.includes('data-arg="f1|18"'), "마지막 번호까지 누를 수 있다");
});

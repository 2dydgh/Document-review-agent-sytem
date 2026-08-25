// 수정안은 **인용마다** 붙는다. 지적 하나가 문장 여럿을 근거로 들 때(실측:
// 수일치 오류 지적 하나에 인용 18개) 첫 인용만 고쳐 주면 나머지는 검토자가
// 손으로 옮겨 적어야 했다.
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
    marks: null, selected: "f1", theme: "light", fixes: {},
    anim: {},
    user: { name: "김검토", team: "ai-test-cert-1" },
    server: { checklists: [], checklist: "", scope_label: "", llm_provider: "local",
              llm_model: "qwen", placeholder_markers: ["TBD"],
              teams: [{ id: "ai-test-cert-1", name: "AI시험인증1팀" }] },
    history: [], detect: null, runChecklistId: "",
    crun: { checklist: null, results: {}, name: "", documentName: "" },
    clib: { list: [], detail: null }, checklist: "",
  }, over || {});
}

const FINDINGS = [
  { id: "f1", checker: "consistency", label: "표현 점검", sev: "minor", kind: "표기",
    message: "주어-서술어 수일치 오류", section: "22.1",
    evidence: [{ quote: "Are the requirement correct?", section: "22.1" },
               { quote: "Are the requirements feasible?", section: "22.1" }] },
];

function html(st) {
  const views = build(st, FINDINGS);
  return views.view(views.renderVals());
}

test("인용마다 수정안 버튼이 하나씩 붙는다", () => {
  const h = html(state());
  assert.ok(h.includes('data-act="suggestFix" data-arg="f1|0"'), "첫 인용");
  assert.ok(h.includes('data-act="suggestFix" data-arg="f1|1"'), "둘째 인용");
});

test("받아온 수정안은 그 인용 자리에만 보인다", () => {
  const h = html(state({ fixes: { "f1|1": { busy: false, ok: true,
    original: "Are the requirements feasible?",
    revised: "고친 문장" } } }));
  assert.ok(h.includes("고친 문장"), "수정안 본문");
  assert.ok(h.includes('data-act="copyFix" data-arg="f1|1"'), "복사도 인용별이다");
  assert.ok(!h.includes('data-act="copyFix" data-arg="f1|0"'),
    "안 만든 인용에는 복사 버튼이 없다");
});

test("고칠 곳이 없다는 답은 그대로 보여준다 — 잘못 끌려온 인용을 드러낸다", () => {
  const h = html(state({ fixes: { "f1|1": { busy: false, ok: false, revised: "",
    reason: "이 문장에서는 고칠 곳을 찾지 못했습니다" } } }));
  assert.ok(h.includes("이 문장에서는 고칠 곳을 찾지 못했습니다"));
});

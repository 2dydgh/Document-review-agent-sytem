// 검토 기준 화면(공통·팀별 층). 항목 줄은 기준 본문 **전문**을 품고, 여닫힘은
// 글자가 아니라 클래스로 말한다 — 예전엔 note 의 첫 줄만 그리고 "펼치기 ▼" 를
// 적어 뒀다. 실행: node --test "web/tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function views(state) {
  const win = { DR: {}, location: { protocol: "http:", href: "http://x/" } };
  win.DR.ICONS = new Proxy({}, { get: () => "<svg/>" });
  win.DR.helpers = {
    esc: (s) => String(s == null ? "" : s), rgba: () => "", fmtSize: () => "1KB",
    download: () => {}, downloadBlob: () => {}, docSides: () => ({}),
    sentences: (s) => [String(s == null ? "" : s)],
  };
  new Function("window", fs.readFileSync(path.join(__dirname, "..", "views.js"), "utf8"))(win);
  return win.DR.views({
    state: state, props: { accent: "#356998" }, render: () => {},
    backend: { errorBanner: (e) => "<err>" + e + "</err>", ago: () => "", fmtElapsed: () => "" },
  });
}

const NOTE = "1. 본문 내 신호값 추출\n2. 표에 기재된 인터페이스 추출\n3. 그림의 신호 추출";
function layers() {
  return [{
    scope: "팀별", id: "EV1", name: "에너지검증 1팀", editable: false,
    items: [
      { no: "3", text: "일관성 분석 데이터 추출", note: NOTE, group: "신호 데이터 추출",
        agent: "문서작성·생성", source: "EIS문서검증 No.3", mode: "규칙", check: "",
        howChecked: "사람이 확인" },
      { no: "12(팀별)", text: "요건 ID 형식", note: "SRS-XXX-000 형태", group: "형식",
        agent: "형식·완전성", source: "EIS문서검증 No.12", mode: "규칙", check: "req_id",
        howChecked: "규칙 · 자동" },
    ],
  }];
}
function st(over) {
  return { clayers: Object.assign(
    { list: layers(), busy: false, error: null, open: {}, openItem: {}, how: "" }, over || {}) };
}

test("접힌 줄은 제목 한 줄이고, 편 줄은 본문 전문을 품는다", () => {
  const shut = st({ open: { EV1: true } });
  let html = views(shut).criteriaLayersSection(shut);
  assert.ok(html.includes("일관성 분석 데이터 추출"), "제목이 없다");
  assert.ok(!html.includes("2. 표에 기재된 인터페이스 추출"), "접힌 줄에 본문이 있다");
  // 본문이 있는 줄에만 손잡이가 붙는다 — 없는 줄은 그게 전부라는 뜻이다.
  assert.equal(html.split('class="clay-rowchev"').length - 1, 2, "손잡이 수가 본문 수와 다르다");

  const open = { clayers: { list: layers(), busy: false, error: null,
                            open: { EV1: true }, openItem: { "EV1|3|0": true }, how: "" } };
  html = views(open).criteriaLayersSection(open);
  assert.ok(html.includes("2. 표에 기재된 인터페이스 추출"), "본문 둘째 줄이 없다");
  assert.ok(html.includes("3. 그림의 신호 추출"), "본문 셋째 줄이 없다");
});

test("층이 접혀 있으면 항목을 안 그린다", () => {
  const s = st();
  const html = views(s).criteriaLayersSection(s);
  assert.ok(!html.includes("일관성 분석 데이터 추출"));
  assert.ok(html.includes('aria-expanded="false"'), "여닫힘 상태를 안 말한다");
});

test("검증 대상으로 묶어 소제목을 세운다 — 내부 이름은 안 보인다", () => {
  const open = { clayers: { list: layers(), busy: false, error: null,
                            open: { EV1: true }, openItem: {}, how: "" } };
  const html = views(open).criteriaLayersSection(open);
  // 줄마다 되풀이하지 않고 목차로 세운다.
  assert.ok(html.includes('<div class="clay-group">신호 데이터 추출<span>1개</span></div>'));
  assert.ok(html.includes('<div class="clay-group">형식<span>1개</span></div>'));
  // 출처(요구사항 xlsx 행 번호)·담당 Agent·검사기 이름은 이 화면을 보는 사람의
  // 것이 아니다. 화면에서 뺐고, 값은 yaml 에 그대로 있다.
  assert.ok(!html.includes("EIS문서검증 No.3"), "출처가 아직 화면에 있다");
  assert.ok(!html.includes("문서작성·생성"), "담당 Agent 가 아직 화면에 있다");
  assert.ok(!html.includes("req_id"), "검사기 이름이 아직 화면에 있다");
});

test("검사 방식으로 거르면 층이 저절로 펴진다", () => {
  const s = { clayers: { list: layers(), busy: false, error: null,
                         open: {}, openItem: {}, how: "규칙 · 자동" } };
  const html = views(s).criteriaLayersSection(s);
  assert.ok(html.includes("요건 ID 형식"), "필터를 걸었는데 층이 접힌 채다");
  assert.ok(!html.includes("일관성 분석 데이터 추출"), "안 고른 방식이 남아 있다");
});

test("번호 열은 고정 폭이 아니다 — 층이 겹치면 '12(팀별)' 로 늘어난다", () => {
  const s = { clayers: { list: layers(), busy: false, error: null,
                         open: { EV1: true }, openItem: {}, how: "" } };
  const html = views(s).criteriaLayersSection(s);
  assert.ok(html.includes("12(팀별)"));
  assert.ok(!html.includes("flex:none;width:34px"), "번호 열이 고정 폭이다");
});

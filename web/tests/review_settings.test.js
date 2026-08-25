// 진행 화면의 "이번 검토 설정"은 서버가 실제 합치는 기준과 같은 목록이어야 한다.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function loadViews() {
  const win = { DR: {} };
  win.DR.ICONS = new Proxy({}, { get: () => "" });
  win.DR.helpers = {
    esc: (s) => String(s == null ? "" : s), rgba: () => "", fmtSize: () => "",
    download: () => {}, downloadBlob: () => {}, docSides: () => ({}),
    sentences: (s) => [String(s == null ? "" : s)],
  };
  new Function("window", fs.readFileSync(path.join(__dirname, "..", "views.js"), "utf8"))(win);
  return win.DR.views({
    state: {}, props: {}, render: () => {},
    backend: { errorBanner: () => "", ago: () => "", fmtElapsed: () => "" },
  });
}

const item = (no, text, howChecked, mode) => ({ no, text, howChecked, mode, note: "" });
const layers = [
  { scope: "공통", id: "common", name: "공통", editable: false, items: [
    item("1", "필수 절", "규칙 · 자동", "규칙"),
    item("2", "용어 통일", "LLM · 자동", "LLM-조각"),
  ] },
  { scope: "팀별", id: "team", name: "팀", editable: false, items: [
    item("1", "표 참조 일치", "LLM · 자동", "LLM-문서"),
    item("3", "용어 통일", "LLM · 자동", "LLM-조각"), // 공통과 중복: 서버도 제외
  ] },
  { scope: "업로드", id: "picked", name: "선택본", editable: true, items: [
    item("7", "사람 승인", "사람이 확인", "사람"),
  ] },
  { scope: "업로드", id: "other", name: "미선택본", editable: true, items: [
    item("8", "이번에 안 씀", "사람이 확인", "사람"),
  ] },
];

test("공통·팀·선택한 업로드 기준만 실제 합성 순서로 센다", () => {
  const info = loadViews().reviewCriteriaInfo(
    { list: layers, busy: false, error: "" }, "picked", true, false);
  assert.deepStrictEqual(info.layers.map((l) => l.id), ["common", "team", "picked"]);
  assert.strictEqual(info.total, 4); // 중복 1건과 미선택 업로드 1건은 제외
  assert.deepStrictEqual(info.counts,
    { rule: 1, expression: 1, whole: 1, manual: 1, disabled: 0 });
  assert.strictEqual(info.layers[1].items[0].no, "1(팀별)", "겹친 번호도 서버처럼 구분한다");
});

test("AI를 끄면 LLM 기준을 자동 검사했다고 표시하지 않는다", () => {
  const info = loadViews().reviewCriteriaInfo(
    { list: layers, busy: false, error: "" }, "picked", false, true);
  assert.strictEqual(info.counts.expression, 0);
  assert.strictEqual(info.counts.whole, 0);
  assert.strictEqual(info.counts.disabled, 2);
  assert.strictEqual(info.open, true);
  assert.ok(info.layers.flatMap((l) => l.items)
    .filter((i) => i.mode && i.mode.startsWith("LLM"))
    .every((i) => i.howChecked === "AI 꺼짐 · 미검토"));
});

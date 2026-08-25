// 뷰어의 선택 링 — 어느 요소에 두를 것인가. DOM 없이 규칙만 확인한다.
// 실행: node --test web/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function loadViewer() {
  // 브라우저에서 하는 일(리사이즈 감시 등)만 흉내 낸다 — 여기서 재는 것은
  // 링을 두를 자리를 가르는 규칙 하나다.
  const win = { DR: {}, addEventListener: () => {}, devicePixelRatio: 1 };
  const doc = { createElement: () => ({ style: {}, setAttribute: () => {},
                                        addEventListener: () => {} }) };
  const src = fs.readFileSync(path.join(__dirname, "..", "pdfview.js"), "utf8");
  new Function("window", "document", src)(win, doc);
  return win.DR.pdfview;
}

test("고른 지적의 형광펜에만 링을 두른다", () => {
  const { ringed } = loadViewer();
  assert.strictEqual(ringed("F-1", "F-1"), true);
  assert.strictEqual(ringed("F-2", "F-1"), false);
});

test("선택을 해제하면 아무 데도 링이 안 켜진다", () => {
  // layer 의 자식에는 형광펜 rect 와 숫자 배지가 둘 다 있다. 배지는 data-mark 를
  // 안 달아 getAttribute 가 null 을 준다. 해제하면 picked 도 null 이라 예전에는
  // `null === null` 이 성립해 **배지 전부에 링이 켜졌다** — 아무것도 안 골랐는데
  // 문서가 전부 강조된 것처럼 보였다.
  const { ringed } = loadViewer();
  assert.strictEqual(ringed(null, null), false, "숫자 배지에 링이 켜진다");
  assert.strictEqual(ringed("F-1", null), false);
  assert.strictEqual(ringed(undefined, null), false);
});

test("고른 상태에서도 배지에는 링을 안 두른다", () => {
  const { ringed } = loadViewer();
  assert.strictEqual(ringed(null, "F-1"), false);
});


// ── 보고 있는 쪽·배율 ────────────────────────────────────────────────────
// 긴 문서에서 "몇 쪽을 보고 있나"를 모르면 형광펜 번호만으로는 위치 감이 안 온다.

test("아직 안 열렸으면 알릴 값이 없다", () => {
  // 지어내지 않는다 — 빈 값이면 도구줄도 빈칸으로 둔다.
  const { viewState } = loadViewer();
  assert.strictEqual(viewState(), null);
});

test("형광펜을 끄고 켜는 손잡이가 있다", () => {
  const v = loadViewer();
  assert.strictEqual(typeof v.setMarksVisible, "function");
  assert.strictEqual(typeof v.onViewChange, "function");
});

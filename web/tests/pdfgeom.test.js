// 뷰어의 좌표 계산. DOM이 없어 Node에서 그대로 돌릴 수 있다.
// 실행: node --test frontend/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const geom = require("../pdfgeom.js");

test("pageOffsets 는 페이지를 간격만큼 띄워 쌓는다", () => {
  assert.deepStrictEqual(geom.pageOffsets([100, 200, 50], 10), [0, 110, 320]);
});

test("docHeight 는 마지막 페이지 뒤 간격을 세지 않는다", () => {
  assert.strictEqual(geom.docHeight([100, 200, 50], 10), 370);
  assert.strictEqual(geom.docHeight([], 10), 0);
});

test("rectToCss 는 y축을 뒤집는다", () => {
  // PDF는 왼쪽 아래가 원점, CSS는 왼쪽 위가 원점. 페이지 800pt, 배율 2.
  const css = geom.rectToCss([10, 700, 110, 720], 800, 2);
  assert.strictEqual(css.left, 20);
  assert.strictEqual(css.width, 200);
  assert.strictEqual(css.height, 40);
  // 사각형 윗변(y=720)이 페이지 위에서 80pt 아래 → 160px
  assert.strictEqual(css.top, 160);
});

test("visiblePages 는 보이는 범위에 overscan 을 더한다", () => {
  const heights = [100, 200, 50];
  const offsets = geom.pageOffsets(heights, 10);   // [0, 110, 320]
  // 화면이 y 120..270 을 덮는다 → 1쪽만 보인다
  assert.deepStrictEqual(geom.visiblePages(offsets, heights, 120, 150, 0), [1, 1]);
  // overscan 1 → 양옆 한 장씩 더
  assert.deepStrictEqual(geom.visiblePages(offsets, heights, 120, 150, 1), [0, 2]);
});

test("visiblePages 는 문서 밖으로 넘어가지 않는다", () => {
  const heights = [100, 200, 50];
  const offsets = geom.pageOffsets(heights, 10);
  assert.deepStrictEqual(geom.visiblePages(offsets, heights, 0, 50, 5), [0, 2]);
});

test("centerScrollTop 은 대상을 화면 가운데 둔다", () => {
  // 대상 위 1000, 높이 20 → 중심 1010. 화면 600 → 스크롤 710
  assert.strictEqual(geom.centerScrollTop(1000, 20, 600, 5000), 710);
});

test("centerScrollTop 은 문서 처음과 끝에서 잘린다", () => {
  assert.strictEqual(geom.centerScrollTop(10, 20, 600, 5000), 0);
  // 4900+10-300 = 4610 이지만 최대는 5000-600 = 4400
  assert.strictEqual(geom.centerScrollTop(4900, 20, 600, 5000), 4400);
});

test("centerScrollTop 은 문서가 화면보다 짧으면 0 이다", () => {
  assert.strictEqual(geom.centerScrollTop(100, 20, 600, 400), 0);
});

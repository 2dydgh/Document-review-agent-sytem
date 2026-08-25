// 뷰어 문서 내 검색(Ctrl+F)의 순수 로직 — 색인·일치·좌표 환산. DOM 없이 확인한다.
// 실행: node --test web/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function loadViewer() {
  const win = { DR: {}, addEventListener: () => {}, devicePixelRatio: 1 };
  const doc = { createElement: () => ({ style: {}, setAttribute: () => {},
                                        addEventListener: () => {} }) };
  const src = fs.readFileSync(path.join(__dirname, "..", "pdfview.js"), "utf8");
  new Function("window", "document", src)(win, doc);
  return win.DR.pdfview._search;
}

test("색인은 항목을 그대로 잇고 줄 끝만 공백으로 만든다", () => {
  const { buildIndex } = loadViewer();
  const idx = buildIndex([
    { str: "운영권 조정, ", hasEOL: false },
    { str: "DB Data", hasEOL: true },
    { str: "Server 설정", hasEOL: false },
  ]);
  assert.strictEqual(idx.text, "운영권 조정, DB Data Server 설정");
  assert.deepStrictEqual(idx.spans.map((s) => [s.start, s.end, s.i]),
    [[0, 8, 0], [8, 15, 1], [16, 25, 2]]);
});

test("일치는 대소문자를 가리지 않고 전부 찾는다", () => {
  const { findRanges } = loadViewer();
  assert.deepStrictEqual(findRanges("CDMS server and cdms Server", "cdms"),
    [[0, 4], [16, 20]]);
  assert.deepStrictEqual(findRanges("abc", ""), [], "빈 검색어는 일치 없음");
});

test("항목 둘에 걸친 일치는 상자 둘로, 일부 걸침은 비율로 자른다", () => {
  const { buildIndex, findRanges, rangeRects } = loadViewer();
  const idx = buildIndex([{ str: "abcd", hasEOL: false }, { str: "efgh", hasEOL: false }]);
  const geoms = [{ x: 0, y: 700, w: 40, h: 10 }, { x: 40, y: 700, w: 40, h: 10 }];
  const [range] = findRanges(idx.text, "cdef");
  const rects = rangeRects(range, idx, geoms);
  assert.strictEqual(rects.length, 2);
  // "cd" = abcd 의 뒤 절반, "ef" = efgh 의 앞 절반
  assert.deepStrictEqual(rects[0], [20, 700, 40, 710]);
  assert.deepStrictEqual(rects[1], [40, 700, 60, 710]);
});

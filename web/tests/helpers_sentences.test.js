// 지적 문장을 줄로 나누는 규칙. 실행: node --test web/tests/
//
// 모델이 판단 과정을 issue 칸에 통째로 쏟은 15문장짜리가 실제로 나왔고
// (2026-08-12), 그걸 한 문단으로 그리면 카드가 벽이 된다. 문장마다 줄을 바꾸면
// 읽히는데 — **마침표로 자르면 안 된다.** 이 제품의 글에는 문장 끝이 아닌
// 마침표가 수두룩하다. 그게 이 파일이 지키는 것이다.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const win = {};
new Function("window", fs.readFileSync(path.join(__dirname, "..", "helpers.js"), "utf8"))(win);
const { sentences } = win.DR.helpers;

test("한국어 종결어미 뒤에서 문장을 끊는다", () => {
  assert.deepEqual(
    sentences("'1 시간'도 명사이므로 띄어쓰기가 맞다. 반면 '95 %'는 기호다."),
    ["'1 시간'도 명사이므로 띄어쓰기가 맞다.", "반면 '95 %'는 기호다."]
  );
});

test("문장 끝이 아닌 마침표는 안 끊는다", () => {
  // 이 셋이 이 검사의 존재 이유다. 마침표만 보고 자르면 전부 쪼개진다.
  for (const s of ["'500.00 GB' 는 SI 단위다.",
                   "ex) 01/12. 01/13, 01/15 로 적혀 있다.",
                   "버전 v1.2 문서를 말한다."]) {
    assert.deepEqual(sentences(s), [s], `쪼개면 안 된다: ${s}`);
  }
});

test("종결어미라도 뒤에 공백이 없으면 안 끊는다", () => {
  // 공백이 문장 끝이라는 증거다. `…한다.그러나` 는 오타지 두 문장이 아니다.
  assert.deepEqual(sentences("맞다.반면 틀리다."), ["맞다.반면 틀리다."]);
});

test("이어붙인 한 문장은 길어도 한 덩어리로 둔다", () => {
  // 못 끊는 것을 못 끊는다고 말해 두는 검사다. 연결어미(…으나,)를 기계가
  // 끊으면 뜻이 바뀐다 — 길이는 화면(.fmsg 접기)이 받는다.
  const run = "SI 단위는 띄어야 하나, '%'는 붙여쓰는 경우가 많으나, 여기서는 다르다.";
  assert.equal(sentences(run).length, 1);
});

test("빈 값과 여백만 있는 값은 빈 목록이다", () => {
  for (const v of [null, undefined, "", "   ", "\n\n"]) {
    assert.deepEqual(sentences(v), [], `빈 목록이어야 한다: ${JSON.stringify(v)}`);
  }
});

test("원래 있던 줄바꿈도 문장 경계다", () => {
  assert.deepEqual(sentences("첫 줄\n둘째 줄"), ["첫 줄", "둘째 줄"]);
});

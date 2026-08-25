(function () {
  "use strict";
  window.DR = window.DR || {};
  var H = window.DR.helpers = {};
  H.esc = function (v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  // 한 문단으로 뭉친 글을 문장 단위로 끊는다. 지적 문장이 길게 나올 때(모델이
  // 판단 과정을 통째로 쏟을 때) 벽처럼 보이는 걸 화면에서 줄로 나누는 데 쓴다.
  //
  // **마침표로 자르면 안 된다.** 이 제품의 글에는 마침표가 문장 끝이 아닌 자리에
  // 수두룩하다 — `500.00 GB` · `01/12. 01/13` · `v1.2`. 그래서 한국어 종결어미
  // (다·요·죠·까) 뒤의 마침표에서만 끊는다. 위 셋은 앞 글자가 종결어미가 아니라
  // 그대로 남는다.
  //
  // 뒤에 공백이 있어야 끊는다 — 문장 끝이라는 증거다. 원래 있던 줄바꿈도 함께
  // 문장 경계로 본다.
  //
  // 못 끊는 것도 분명히 해둔다: 쉼표와 연결어미(…이나, …으나,)로 이어붙인 한
  // 문장은 아무리 길어도 한 덩어리다. 그건 문장이 길어서가 아니라 글이 그렇게
  // 쓰인 것이고, 기계가 끊으면 뜻이 바뀐다.
  H.sentences = function (text) {
    return String(text == null ? "" : text)
      .replace(/((?:다|요|죠|까)[.?!])\s+/g, "$1\n")
      .split(/\n+/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }
  H.rgba = function (hex, a) {
    var h = (hex || "#356998").replace("#", "");  // 기본값 = 브랜드 블루(--accent)
    var r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + a + ")";
  }
  H.downloadBlob = function (name, blob) {
    try {
      var u = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(u); }, 1000);
    } catch (e) { /* noop */ }
  }
  H.download = function (name, text, mime) {
    try {
      var b = new Blob([text], { type: mime });
      var u = URL.createObjectURL(b);
      var a = document.createElement("a");
      a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(u); }, 1000);
    } catch (e) { /* noop */ }
  }
  H.fmtSize = function (n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
  // Finding.document → 문서 이름 목록. 백엔드가 세 모양으로 낸다:
  //
  //   "시험계획서"                            낱장      (field_presence · fontsize)
  //   "을지 ↔ 갑지"                           쌍 대조   (pairs)
  //   "시험의뢰서 · 시험계획서 · 시험설계서"    전체 대조 (case_wide)
  //
  // 여기 있는 이유는 **두 곳이 같은 규칙을 써야 하기** 때문이다 — 화면(views.js)이
  // "저 문서에서 보기" 버튼을 그리고, 액션(app.js openCaseDoc)이 그 문서의 근거만
  // 골라 뷰어에 넘긴다. 둘이 갈리면 버튼은 뜨는데 눌러도 아무 일이 없다.
  //
  // 예전에는 양쪽 다 `split(" ↔ ")` 하나만 알아서 전체 대조가 한 덩어리로 남았다.
  // 그러면 세 이름이 붙은 버튼이 뜨고, 그 이름의 산출물이 없어 openCaseDoc 이
  // `if (!out) return` 으로 조용히 끝났다. 작성일자 선후 검사가 이 경로다.
  H.docSides = function (document_) {
    return String(document_ == null ? "" : document_)
      .split(/ ↔ | · /)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }
})();

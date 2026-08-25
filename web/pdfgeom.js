// 뷰어의 좌표 계산만 모은다. DOM을 만지지 않으므로 Node에서 그대로 검증할 수 있다
// (frontend/tests/pdfgeom.test.js). 좌표계 뒤집기와 가상 스크롤 경계는 눈으로
// 확인하기 어렵고 조용히 틀리기 쉬운 곳이라, 여기만 따로 뽑아 두었다.
(function (root) {
  "use strict";

  // 페이지들을 세로로 쌓았을 때 각 페이지의 윗변 위치(px).
  function pageOffsets(heights, gap) {
    var out = [];
    var y = 0;
    for (var i = 0; i < heights.length; i++) {
      out.push(y);
      y += heights[i] + gap;
    }
    return out;
  }

  // 전체 높이. 마지막 페이지 뒤에는 간격을 두지 않는다.
  function docHeight(heights, gap) {
    if (!heights.length) return 0;
    var sum = 0;
    for (var i = 0; i < heights.length; i++) sum += heights[i];
    return sum + gap * (heights.length - 1);
  }

  // 지금 화면에 걸치는 페이지 범위 [처음, 끝] (양끝 포함). overscan 만큼 넓힌다 —
  // 스크롤하는 순간 빈 칸이 보이지 않게 미리 그려 둔다.
  function visiblePages(offsets, heights, scrollTop, viewportH, overscan) {
    var top = scrollTop;
    var bottom = scrollTop + viewportH;
    var first = -1;
    var last = -1;
    for (var i = 0; i < offsets.length; i++) {
      var a = offsets[i];
      var b = a + heights[i];
      if (b > top && a < bottom) {
        if (first < 0) first = i;
        last = i;
      }
    }
    if (first < 0) { first = 0; last = 0; }   // 어디에도 안 걸치면 첫 장
    first = Math.max(0, first - overscan);
    last = Math.min(offsets.length - 1, last + overscan);
    return [first, last];
  }

  // PDF 사용자 공간 사각형 → 페이지 캔버스 안의 CSS 상자(px).
  // PDF는 왼쪽 아래가 원점이고 CSS는 왼쪽 위가 원점이라 y를 뒤집는다.
  function rectToCss(rect, pageHeightPt, scale) {
    var x0 = rect[0], y0 = rect[1], x1 = rect[2], y1 = rect[3];
    return {
      left: x0 * scale,
      top: (pageHeightPt - y1) * scale,
      width: (x1 - x0) * scale,
      height: (y1 - y0) * scale,
    };
  }

  // 대상을 화면 가운데 두는 스크롤 값. 문서 처음·끝에서는 잘린다 —
  // 안 자르면 빈 여백이 드러나고 대상이 오히려 화면 밖으로 나간다.
  function centerScrollTop(targetTop, targetH, viewportH, docH) {
    var want = targetTop + targetH / 2 - viewportH / 2;
    var max = Math.max(0, docH - viewportH);
    return Math.min(Math.max(0, want), max);
  }

  var geom = {
    pageOffsets: pageOffsets,
    docHeight: docHeight,
    visiblePages: visiblePages,
    rectToCss: rectToCss,
    centerScrollTop: centerScrollTop,
  };

  // 브라우저에서는 window.DR.geom, Node 테스트에서는 require 로 쓴다.
  if (typeof module === "object" && module.exports) module.exports = geom;
  else { root.DR = root.DR || {}; root.DR.geom = geom; }
})(typeof globalThis !== "undefined" ? globalThis : this);

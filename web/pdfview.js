// pdf.js 뷰어. 페이지를 canvas 에 직접 그린다.
//
// 왜 브라우저 기본 뷰어(<iframe>)를 안 쓰나: 그 안은 우리 JS 가 못 건드린다.
// 쪽을 옮기려면 src 에 #page=N 을 걸어야 하는데, 크롬은 같은 문서 안의
// 프래그먼트 변경을 이동으로 치지 않아서 노드를 새로 만들어야 했다 — 그게 곧
// 문서 리로드라 카드를 누를 때마다 읽던 자리가 날아갔다. 게다가 문서 크기가
// 뷰어 박스 높이에 묶여, 가로로 넓혀도 좌우 여백만 늘었다.
//
// 여기서는 우리가 픽셀을 그리므로 스크롤도 배율도 우리 것이다. 형광펜은 PDF 에
// 굽지 않고 <div> 로 얹어(setMarks) 켜고 끄기가 공짜고 클릭도 받는다.
(function () {
  "use strict";
  window.DR = window.DR || {};

  var G = null;              // pdf.js 모듈 (동적 import 로 한 번만)
  var doc = null;            // PDFDocumentProxy
  var host = null;           // 스크롤 컨테이너
  var pages = [];            // [{page, el, canvas, layer, task, width, height, rendered}]
  var scale = 1;
  var fitMode = true;        // 폭 맞춤 유지 중인가 (창 크기가 바뀌면 다시 맞춘다)
  var onError = function () {};
  var GAP = 12;              // 페이지 사이 간격(px)

  var marks = [];            // [{id, no, sev, page(1-based), rect}]
  var marksOn = true;
  var picked = null;         // 지금 고른 지적 id
  var onPick = function () {};

  // 형광펜 색. 값은 index.html 의 --sev-*-hl 이 정한다 — 여기 hex 를 박아 두었더니
  // 앱이 info 를 파랑에서 슬레이트로 옮길 때 이쪽만 파랑으로 남았다(브랜드색이
  // 파랑이라 "정보 등급"과 "강조"가 구분되지 않았다).
  var _SEV = {
    major: "var(--sev-maj-hl)",
    minor: "var(--sev-min-hl)",
    info: "var(--sev-info-hl)",
    // 반영 확인 탭. 거기서 칠해진 것은 전부 "지난 지적인데 아직 미반영" 하나라
    // 심각도로 갈라 칠할 이유가 없다 — 심각도는 카드 뱃지가 진다.
    past: "var(--sev-past-hl)",
  };

  var WORKER = "vendor/pdf.worker.min.mjs";

  // pdf.js 6.x 는 ESM 만 낸다. 빌드 단계가 없으므로 동적 import 로 불러온다.
  // file:// 로 열면 CORS 에 막힌다 — 서버로 띄워야 한다(README 참고).
  function load() {
    if (G) return Promise.resolve(G);
    return import("./vendor/pdf.min.mjs").then(function (mod) {
      G = mod;
      G.GlobalWorkerOptions.workerSrc = WORKER;
      // 워커를 못 받으면 pdf.js 는 말없이 메인 스레드로 폴백한다. 48쪽짜리 문서에서
      // 화면이 멎는데 원인이 화면 어디에도 안 뜨므로, 미리 찔러보고 없으면 알린다.
      return fetch(WORKER, { method: "HEAD" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return G; })
        .catch(function () {
          onError("PDF 워커를 불러오지 못했습니다(" + WORKER + "). 문서가 느릴 수 있습니다.");
          return G;
        });
    });
  }

  function open(mount, blob, opts) {
    close();
    onError = (opts && opts.onError) || function () {};
    mountEl = mount;
    // 검색 바가 뷰어 오른쪽 위에 절대배치로 뜬다 — 기준 좌표계가 필요하다.
    mount.style.position = "relative";
    ensureStyle();
    document.addEventListener("keydown", onKey, true);
    return load()
      .then(function (lib) {
        return blob.arrayBuffer().then(function (buf) {
          // CJK 글리프는 CMap 이 있어야 그려진다 — 한글 문서라 필수. 표준 폰트도
          // 함께 준다(임베드 안 된 폰트 대체용). 둘 다 vendor 로 서빙한다(CDN 금지).
          return lib.getDocument({
            data: buf,
            cMapUrl: "vendor/cmaps/",
            cMapPacked: true,
            standardFontDataUrl: "vendor/standard_fonts/",
          }).promise;
        });
      })
      .then(function (pdf) {
        doc = pdf;
        host = document.createElement("div");
        host.id = "pdf-scroll";
        // height:100% 로 마운트 높이에 묶는다. flex:1 을 쓰면 부모(#pdf-mount)가
        // flex 컨테이너가 아니라 안 먹어서, host 가 전체 페이지 높이로 늘어나고
        // #pdf-mount 가 첫 페이지만 남기고 잘라낸다 — 스크롤이 죽는다.
        host.style.cssText =
          "height:100%;overflow:auto;background:var(--bg);padding:" + GAP + "px 0;";
        mount.appendChild(host);
        host.addEventListener("scroll", paint, { passive: true });
        // Ctrl(⌘)+휠 = 확대·축소. 그냥 휠은 스크롤 그대로. passive:false 여야
        // preventDefault 로 브라우저의 페이지 전체 줌을 막을 수 있다.
        host.addEventListener("wheel", onWheel, { passive: false });
        return layout();
      })
      .catch(function (e) {
        onError("PDF를 열지 못했습니다: " + (e && e.message ? e.message : e));
      });
  }

  // 페이지 자리표시자를 만들고 크기를 잰다. 캔버스는 보이는 것만 그린다 —
  // 48쪽을 다 그리면 메모리가 터진다.
  function layout() {
    var jobs = [];
    for (var i = 1; i <= doc.numPages; i++) jobs.push(doc.getPage(i));
    return Promise.all(jobs).then(function (got) {
      pages = got.map(function (page) {
        var el = document.createElement("div");
        el.style.cssText =
          "position:relative;margin:0 auto " + GAP + "px;background:#fff;" +
          "box-shadow:0 1px 6px rgba(0,0,0,0.15);";
        host.appendChild(el);
        return { page: page, el: el, canvas: null, layer: null, task: null,
                 width: 0, height: 0, rendered: 0 };
      });
      fit();
    });
  }

  // 컨테이너 폭에 맞춘 배율. aspect-ratio 로 높이에 묶여 있던 예전과 달리,
  // 이제 주어진 폭을 그대로 쓴다.
  function fit() {
    if (!pages.length || !host) return;
    var vp = pages[0].page.getViewport({ scale: 1 });
    var avail = host.clientWidth - 24;      // 좌우 여백
    setScale(Math.max(0.2, avail / vp.width));
    fitMode = true;
  }

  function setScale(next) {
    hidePopup();               // 배율이 바뀌면 팝업 좌표가 어긋난다 — 닫는다
    // 줌 전 스크롤 위치를 비율로 기억했다가 복원한다 — 안 하면 배율이 바뀌며
    // 전체 높이가 달라져 읽던 자리가 튄다.
    var anchor = 0;
    if (host && host.scrollHeight > host.clientHeight) {
      anchor = host.scrollTop / (host.scrollHeight - host.clientHeight);
    }
    scale = next;
    pages.forEach(function (p) {
      var vp = p.page.getViewport({ scale: scale });
      p.width = vp.width;
      p.height = vp.height;
      p.el.style.width = vp.width + "px";
      p.el.style.height = vp.height + "px";
      p.rendered = 0;                        // 배율이 바뀌었으니 다시 그린다
      if (p.canvas) { p.canvas.remove(); p.canvas = null; }
    });
    if (host && host.scrollHeight > host.clientHeight) {
      host.scrollTop = anchor * (host.scrollHeight - host.clientHeight);
    }
    paint();
  }

  // 보이는 페이지만 캔버스로 그린다.
  function paint() {
    if (!host || !pages.length) return;
    var heights = pages.map(function (p) { return p.height; });
    var offsets = window.DR.geom.pageOffsets(heights, GAP);
    var range = window.DR.geom.visiblePages(
      offsets, heights, host.scrollTop, host.clientHeight, 1);
    for (var i = 0; i < pages.length; i++) {
      if (i >= range[0] && i <= range[1]) render(pages[i], i);
      else discard(pages[i]);
    }
    report(range[0] + 1);
  }

  // 지금 보고 있는 쪽·배율. 화면이 도구줄에 적는다 — 긴 문서에서 "몇 쪽을 보고
  // 있나"를 모르면 형광펜 번호만으로는 위치 감이 안 온다.
  //
  // 값이 바뀔 때만 알린다. 스크롤마다 부르면 화면이 쉼 없이 다시 그려진다.
  var onView = null, told = "";
  function report(page) {
    if (!onView) return;
    var now = page + "/" + pages.length + "/" + Math.round(scale * 100);
    if (now === told) return;
    told = now;
    onView({ page: page, pages: pages.length, pct: Math.round(scale * 100) });
  }

  function render(p, idx) {
    if (p.rendered === scale || p.task) return;
    var vp = p.page.getViewport({ scale: scale });
    var canvas = document.createElement("canvas");
    canvas.width = Math.floor(vp.width);
    canvas.height = Math.floor(vp.height);
    canvas.style.cssText = "display:block;width:100%;height:100%;";
    p.el.insertBefore(canvas, p.el.firstChild);
    p.task = p.page.render({ canvasContext: canvas.getContext("2d"), viewport: vp });
    p.task.promise.then(function () {
      if (p.canvas) p.canvas.remove();
      p.canvas = canvas;
      p.rendered = scale;
      p.task = null;
      renderText(p, idx);
      paintSearch(p, idx);
      paintMarks(p, idx);
    }).catch(function () { canvas.remove(); p.task = null; });
  }

  // 화면 밖 페이지의 캔버스는 버린다. 자리는 el 이 이미 잡고 있어 스크롤이 안 튄다.
  // 형광펜 층도 같이 버린다 — 캔버스만 지우면 빈 페이지 위에 형광펜만 떠 있게 된다.
  function discard(p) {
    if (p.task) { p.task.cancel(); p.task = null; }
    if (p.canvas) { p.canvas.remove(); p.canvas = null; p.rendered = 0; }
    if (p.layer) { p.layer.remove(); p.layer = null; }
    // 텍스트·검색 층도 같이 버린다(캔버스와 같은 이유). textData(PDF 좌표계
    // 원본)는 남긴다 — 배율과 무관해 다시 쓸 수 있다.
    if (p.text) { p.text.remove(); p.text = null; }
    if (p.slayer) { p.slayer.remove(); p.slayer = null; }
  }

  // 형광펜을 페이지 위에 <div> 로 얹는다. PDF 에 굽지 않으므로 켜고 끄기가 공짜고,
  // 클릭도 받을 수 있다 — 형광펜을 눌러 지적 카드를 고르는 길이 여기서 열린다.
  function paintMarks(p, idx) {
    if (p.layer) p.layer.remove();
    p.layer = document.createElement("div");
    p.layer.style.cssText =
      "position:absolute;inset:0;pointer-events:none;" + (marksOn ? "" : "display:none;");
    var vp = p.page.getViewport({ scale: 1 });
    var badged = {};       // 번호마다 배지 하나 (한 인용이 여러 줄이면 첫 줄에만)
    var atSpot = {};       // 같은 자리에 겹친 배지 수 — 옆으로 밀어 겹치지 않게
    marks.forEach(function (m) {
      if (m.page !== idx + 1) return;
      var box = window.DR.geom.rectToCss(m.rect, vp.height, scale);
      var el = document.createElement("div");
      el.setAttribute("data-mark", m.id);
      el.style.cssText =
        "position:absolute;pointer-events:auto;cursor:pointer;border-radius:2px;" +
        "left:" + box.left + "px;top:" + box.top + "px;" +
        "width:" + box.width + "px;height:" + box.height + "px;" +
        "background:" + (_SEV[m.sev] || _SEV.info) + ";" +
        "outline:" + (m.id === picked ? "2px solid var(--accent)" : "none") + ";";
      el.addEventListener("click", function (e) {
        e.stopPropagation(); onPick(m.id); showPopup(p.el, box, m);
      });
      p.layer.appendChild(el);

      // 번호 배지 — 형광펜 왼쪽에 작은 원. 형광펜과 카드가 같은 번호를 달아
      // "3번"이 서로를 가리킨다. **번호마다** 하나씩 — 한 인용이 여러 줄에 걸치면
      // 그 줄들은 같은 번호라 첫 줄에만 붙인다.
      var badgeKey = m.id + "|" + m.no;
      if (m.no && !badged[badgeKey]) {
        badged[badgeKey] = true;
        var n = document.createElement("div");
        n.textContent = String(m.no).split(",")[0].trim();
        var d = Math.max(15, Math.min(22, box.height));
        // 세 자리 번호(100+)는 지름 15~22px 원을 넘친다 — 자릿수만큼 알약으로
        // 늘린다. 한두 자리는 그대로 원이다.
        var digits = n.textContent.length;
        var w = d + (digits > 2 ? (digits - 2) * 7 : 0);
        // 한 곳에 문제가 둘 이상이면 그 자리를 여러 지적이 문다 — 실측: `운영파일`
        // 하나를 세 지적이(용어 혼용·띄어쓰기·표기) 각각 근거로 댔다. 지적마다 제
        // 번호를 주므로 배지도 여럿이다. 겹쳐 찍으면 맨 위 것만 보이니 옆으로 민다.
        var spot = Math.round(box.left) + ":" + Math.round(box.top);
        var slot = atSpot[spot] = (atSpot[spot] || 0) + 1;
        n.style.cssText =
          "position:absolute;pointer-events:auto;cursor:pointer;z-index:2;" +
          "left:" + (box.left - (w + 3) * slot) + "px;top:" + box.top + "px;" +
          "width:" + w + "px;height:" + d + "px;border-radius:" + Math.ceil(d / 2) + "px;" +
          "display:flex;align-items:center;justify-content:center;" +
          "font-size:11px;font-weight:600;color:#fff;font-family:sans-serif;" +
          "background:" + (_SEVSOLID[m.sev] || _SEVSOLID.info) + ";" +
          "box-shadow:0 1px 3px rgba(0,0,0,0.3);";
        n.addEventListener("click", function (e) {
          e.stopPropagation(); onPick(m.id); showPopup(p.el, box, m);
        });
        p.layer.appendChild(n);
      }
    });
    p.el.appendChild(p.layer);
  }

  // 번호 배지용 불투명 색(형광펜은 반투명이라 글자가 안 보인다).
  var _SEVSOLID = {
    major: "#EA580C", minor: "#CA8A04", info: "var(--sev-info-solid)",
    // 새로 드는 색은 토큰으로 든다. 앞의 둘은 먼저 있던 것이라 hex 그대로다
    // (색은 토큰만 쓴다 — test_하드코딩_hex_가_늘지_않는다).
    past: "var(--sev-past-solid)",
  };

  // 형광펜을 누르면 그 자리에 지적 문구를 띄운다. 오른쪽 카드로도 가지만, 문서에서
  // 바로 무슨 지적인지 읽히는 편이 검토 흐름을 안 끊는다. 페이지 el 안에 절대배치해
  // 스크롤을 따라간다. 한 번에 하나만 — 다른 형광펜을 누르면 이전 것은 닫힌다.
  var popup = null;
  function hidePopup() { if (popup) { popup.remove(); popup = null; } }

  function showPopup(pageEl, box, m) {
    hidePopup();
    popup = document.createElement("div");
    popup.style.cssText =
      "position:absolute;z-index:30;max-width:min(320px,80%);" +
      "left:" + box.left + "px;top:" + (box.top + box.height + 6) + "px;" +
      "background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);" +
      "box-shadow:0 8px 24px rgba(0,0,0,0.18);padding:10px 12px;" +
      "font-family:sans-serif;font-size:13px;line-height:1.6;color:var(--text);";
    var head = document.createElement("div");
    head.style.cssText =
      "display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;";
    var tag = document.createElement("span");
    tag.textContent = (m.no ? "지적 " + m.no + " · " : "") + (m.sev || "");
    tag.style.cssText = "font-size:11px;font-weight:600;color:var(--text-3);";
    var x = document.createElement("button");
    x.textContent = "✕";
    x.style.cssText =
      "border:none;background:none;cursor:pointer;color:var(--text-3);font-size:13px;padding:0;";
    x.addEventListener("click", function (e) { e.stopPropagation(); hidePopup(); });
    head.appendChild(tag); head.appendChild(x);
    var body = document.createElement("div");
    body.textContent = m.message || "(내용 없음)";   // textContent 라 HTML 주입 안전
    popup.appendChild(head); popup.appendChild(body);
    popup.addEventListener("click", function (e) { e.stopPropagation(); });
    pageEl.appendChild(popup);
  }

  function repaintLayers() {
    pages.forEach(function (p, i) { if (p.canvas) paintMarks(p, i); });
  }

  function setMarks(items, pick) {
    onPick = pick || function () {};
    hidePopup();
    marks = [];
    (items || []).forEach(function (it) {
      (it.marks || []).forEach(function (m) {
        // 번호는 **마크가 들고 온 자기 번호**를 쓴다. 지적의 `"1, 2, 3"` 을 쓰면
        // 첫 형광펜에만 `1` 이 붙고 나머지는 번호 없이 칠해진다 — 카드는 셋이라는데
        // 문서엔 하나만 보였다. 옛 좌표(마크에 번호가 없음)는 예전대로 둔다.
        marks.push({ id: it.id, no: m.no != null ? m.no : it.no, sev: it.sev,
                     message: it.message || "", page: m.page, rect: m.rect });
      });
    });
    repaintLayers();
  }

  function setMarksVisible(on) {
    marksOn = !!on;
    pages.forEach(function (p) {
      if (p.layer) p.layer.style.display = marksOn ? "" : "none";
    });
  }

  // 이 요소에 선택 링을 두를 자리인가.
  //
  // layer 의 자식에는 형광펜 rect 와 **숫자 배지**가 둘 다 있는데, 배지는
  // `data-mark` 를 안 단다. 선택을 해제하면 picked 도 null 이라, 예전에는
  // `null === null` 이 성립해 **배지 전부에 링이 켜졌다.** 아무것도 안 골랐는데
  // 문서가 전부 강조된 것처럼 보였다.
  function ringed(id, picked) {
    return !!picked && id === picked;
  }

  // 고른 지적을 강조한다. 다시 그리지 않고 테두리만 바꾼다.
  function highlight(id) {
    picked = id || null;
    pages.forEach(function (p) {
      if (!p.layer) return;
      Array.prototype.forEach.call(p.layer.children, function (el) {
        el.style.outline = ringed(el.getAttribute("data-mark"), picked)
          ? "2px solid var(--accent)" : "none";
      });
    });
  }

  // 1-based 쪽으로. rect 를 주면 그 사각형이 화면 가운데 오게 한다.
  function goTo(page, rect) {
    if (!host || !pages.length) return;
    var idx = Math.min(Math.max(0, (page || 1) - 1), pages.length - 1);
    var heights = pages.map(function (p) { return p.height; });
    var offsets = window.DR.geom.pageOffsets(heights, GAP);
    var top = offsets[idx];
    var h = 0;
    if (rect) {
      var vp = pages[idx].page.getViewport({ scale: 1 });
      var box = window.DR.geom.rectToCss(rect, vp.height, scale);
      top += box.top;
      h = box.height;
    }
    host.scrollTop = window.DR.geom.centerScrollTop(
      top, h, host.clientHeight, window.DR.geom.docHeight(heights, GAP));
    paint();
  }

  function onViewChange(fn) { onView = fn; told = ""; }

  // 지금 값. 화면을 다시 그린 뒤 도구줄 글자를 되살릴 때 쓴다 — 알림만으로는
  // 값이 안 바뀌면 다시 안 오므로 빈칸으로 남는다.
  function viewState() {
    if (!pages.length || !host) return null;
    var heights = pages.map(function (p) { return p.height; });
    var range = window.DR.geom.visiblePages(
      window.DR.geom.pageOffsets(heights, GAP), heights,
      host.scrollTop, host.clientHeight, 1);
    return { page: range[0] + 1, pages: pages.length, pct: Math.round(scale * 100) };
  }

  function zoom(step) {
    if (!pages.length) return;
    if (step === "fit") { fit(); return; }
    fitMode = false;
    setScale(Math.min(4, Math.max(0.2, scale + step)));
  }

  // Ctrl(⌘)+휠 = 확대·축소. Ctrl 없이는 브라우저 기본 스크롤에 맡긴다.
  // 배율은 곱셈으로 바꿔야(1.1×/0.9×) 배율이 커져도 한 틱 느낌이 일정하다.
  function onWheel(e) {
    if (!(e.ctrlKey || e.metaKey)) return;   // 그냥 휠은 스크롤
    e.preventDefault();
    if (!pages.length) return;
    fitMode = false;
    var factor = e.deltaY < 0 ? 1.1 : 0.9;
    setScale(Math.min(4, Math.max(0.2, scale * factor)));
  }

  // ── 텍스트 레이어 (드래그 선택·복사) ────────────────────────────────────
  //
  // 캔버스는 그림이라 글자를 긁을 수 없다. 캔버스 위에 **투명 글자**를 같은
  // 자리에 얹으면 브라우저 선택·복사가 그대로 동작한다(pdf.js 기본 뷰어와 같은
  // 방식). 스타일은 index.html 이 아니라 여기서 주입한다 — 뷰어의 자산이라
  // 뷰어가 든다(다른 화면은 이 클래스를 모른다).
  var mountEl = null;
  var styled = false;
  function ensureStyle() {
    if (styled) return;
    styled = true;
    var s = document.createElement("style");
    s.textContent =
      ".pdftext{position:absolute;inset:0;overflow:hidden;line-height:1;}" +
      ".pdftext span{position:absolute;color:transparent;white-space:pre;" +
        "cursor:text;transform-origin:0 0;}" +
      // 선택 띠는 반투명이어야 밑의 캔버스 글자가 비친다 — 토큰만 쓰려고
      // color-mix 로 섞는다(하드코딩 hex 금지 가드).
      ".pdftext span::selection{background:color-mix(in srgb,var(--accent) 30%,transparent);}";
    document.head.appendChild(s);
  }

  // 2×3 행렬 곱(pdf.js Util.transform 과 같은 규약) — 버전에 기대지 않는다.
  function mat(m, t) {
    return [m[0] * t[0] + m[2] * t[1], m[1] * t[0] + m[3] * t[1],
            m[0] * t[2] + m[2] * t[3], m[1] * t[2] + m[3] * t[3],
            m[0] * t[4] + m[2] * t[5] + m[4], m[1] * t[4] + m[3] * t[5] + m[5]];
  }

  var _measure = null;
  function measureCtx() {
    if (!_measure) _measure = document.createElement("canvas").getContext("2d");
    return _measure;
  }

  // 페이지의 텍스트 원본(문자열 색인 + 항목 좌표, PDF 좌표계 = 배율 무관).
  // 검색과 텍스트 레이어가 같이 쓴다 — 페이지당 한 번만 뽑아 페이지에 캐시.
  function pageTextData(idx) {
    var p = pages[idx];
    if (p.textData) return Promise.resolve(p.textData);
    return p.page.getTextContent().then(function (tc) {
      var geoms = tc.items.map(function (it) {
        var t = it.transform || [0, 0, 0, 0, 0, 0];
        return { x: t[4], y: t[5], w: it.width || 0,
                 h: it.height || Math.hypot(t[2], t[3]) };
      });
      p.textData = { tc: tc, index: buildIndex(tc.items), geoms: geoms };
      return p.textData;
    });
  }

  function renderText(p, idx) {
    pageTextData(idx).then(function (d) {
      if (!p.canvas) return;               // 그새 화면 밖으로 나갔다
      if (p.text) p.text.remove();
      var layer = document.createElement("div");
      layer.className = "pdftext";
      var vp = p.page.getViewport({ scale: scale });
      var ctx = measureCtx();
      d.tc.items.forEach(function (it) {
        if (!it.str || !it.str.trim() || !it.transform) return;
        var t = mat(vp.transform, it.transform);
        var fh = Math.hypot(t[2], t[3]);
        if (!fh) return;
        var span = document.createElement("span");
        span.textContent = it.str;
        var st = d.tc.styles && d.tc.styles[it.fontName];
        var fam = (st && st.fontFamily) || "sans-serif";
        span.style.left = t[4] + "px";
        span.style.top = (t[5] - fh) + "px";
        span.style.fontSize = fh + "px";
        span.style.fontFamily = fam;
        // 브라우저 글꼴과 PDF 글리프의 폭이 달라 그대로 두면 드래그 범위와
        // 눈에 보이는 글자가 어긋난다 — 실측 폭에 맞춰 가로만 늘인다.
        ctx.font = fh + "px " + fam;
        var got = ctx.measureText(it.str).width;
        var want = (it.width || 0) * scale;
        if (got && want) span.style.transform = "scaleX(" + want / got + ")";
        layer.appendChild(span);
      });
      p.el.appendChild(layer);
      if (p.layer) p.el.appendChild(p.layer);   // 형광펜은 늘 맨 위
      p.text = layer;
    });
  }

  // ── 문서 내 검색 (Ctrl+F) ───────────────────────────────────────────────
  //
  // 캔버스 안은 브라우저 Ctrl+F 가 못 본다 — 가로채서 우리 검색을 연다.
  // 대소문자 무시 부분일치. 항목 문자열을 그대로 잇는다(공백 정규화까지 하면
  // 좌표 환산이 흐트러진다) — 줄 끝(hasEOL)만 공백 하나로 잇는다.
  function buildIndex(items) {
    var text = "", spans = [];
    (items || []).forEach(function (it, i) {
      var s = it.str || "";
      if (s) {
        spans.push({ start: text.length, end: text.length + s.length, i: i });
        text += s;
      }
      if (it.hasEOL) text += " ";
    });
    return { text: text, spans: spans };
  }

  function findRanges(text, q) {
    var out = [];
    var needle = String(q || "").toLowerCase();
    if (!needle) return out;
    var hay = String(text || "").toLowerCase();
    var at = hay.indexOf(needle);
    while (at >= 0) {
      out.push([at, at + needle.length]);
      at = hay.indexOf(needle, at + needle.length);
    }
    return out;
  }

  // 일치 구간 → 형광 상자들(PDF 좌표계). 일치가 항목 여럿에 걸치면 항목마다
  // 하나씩, 항목 일부만 걸치면 글자 비율로 가로를 자른다(근사 — 고정폭이 아닌
  // 글꼴에서는 약간 어긋나지만 "어디인가"를 보여주기엔 충분하다).
  function rangeRects(range, index, geoms) {
    var rects = [];
    index.spans.forEach(function (sp) {
      var s = Math.max(range[0], sp.start), e = Math.min(range[1], sp.end);
      if (s >= e) return;
      var g = geoms[sp.i];
      if (!g || !g.w) return;
      var len = sp.end - sp.start;
      var f0 = (s - sp.start) / len, f1 = (e - sp.start) / len;
      rects.push([g.x + g.w * f0, g.y, g.x + g.w * f1, g.y + g.h]);
    });
    return rects;
  }

  var srch = { open: false, q: "", hits: [], at: -1, bar: null, input: null,
               label: null, timer: null };

  function onKey(e) {
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "f") {
      // 뷰어가 화면에 있을 때만 가로챈다 — 다른 화면에선 브라우저 찾기 그대로.
      if (!doc || !host || !document.body.contains(host)) return;
      e.preventDefault();
      openSearch();
    } else if (e.key === "Escape" && srch.open) {
      closeSearch();
    }
  }

  function openSearch() {
    if (!srch.bar) buildSearchBar();
    srch.bar.style.display = "flex";
    srch.open = true;
    srch.input.focus();
    srch.input.select();
  }

  function closeSearch() {
    srch.open = false;
    srch.q = ""; srch.hits = []; srch.at = -1;
    if (srch.bar) srch.bar.style.display = "none";
    clearSearchLayers();
  }

  function clearSearchLayers() {
    pages.forEach(function (p) {
      if (p.slayer) { p.slayer.remove(); p.slayer = null; }
    });
  }

  function runSearch(q) {
    srch.q = q; srch.hits = []; srch.at = -1;
    clearSearchLayers();
    if (!q) { setSearchLabel(""); return; }
    Promise.all(pages.map(function (_, i) { return pageTextData(i); }))
      .then(function (datas) {
        if (srch.q !== q) return;            // 그새 입력이 바뀌었다
        datas.forEach(function (d, i) {
          findRanges(d.index.text, q).forEach(function (r) {
            srch.hits.push({ page: i, rects: rangeRects(r, d.index, d.geoms) });
          });
        });
        if (srch.hits.length) goHit(0);
        else { setSearchLabel("0건"); paintSearchAll(); }
      });
  }

  function goHit(k) {
    if (!srch.hits.length) return;
    srch.at = ((k % srch.hits.length) + srch.hits.length) % srch.hits.length;
    var h = srch.hits[srch.at];
    setSearchLabel((srch.at + 1) + "/" + srch.hits.length);
    paintSearchAll();
    if (h.rects.length) goTo(h.page + 1, h.rects[0]);
  }

  function setSearchLabel(t) { if (srch.label) srch.label.textContent = t; }

  function paintSearch(p, idx) {
    if (p.slayer) { p.slayer.remove(); p.slayer = null; }
    if (!srch.q || !srch.hits.length) return;
    var vp1 = p.page.getViewport({ scale: 1 });
    var layer = document.createElement("div");
    layer.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    var drew = false;
    srch.hits.forEach(function (h, k) {
      if (h.page !== idx) return;
      h.rects.forEach(function (r) {
        var box = window.DR.geom.rectToCss(r, vp1.height, scale);
        var el = document.createElement("div");
        el.style.cssText =
          "position:absolute;border-radius:2px;" +
          "left:" + box.left + "px;top:" + box.top + "px;" +
          "width:" + box.width + "px;height:" + box.height + "px;" +
          "background:color-mix(in srgb,var(--accent) 28%,transparent);" +
          (k === srch.at ? "outline:2px solid var(--accent);" : "");
        layer.appendChild(el);
        drew = true;
      });
    });
    if (!drew) return;
    p.el.appendChild(layer);
    if (p.layer) p.el.appendChild(p.layer);   // 형광펜은 늘 맨 위
    p.slayer = layer;
  }

  function paintSearchAll() {
    pages.forEach(function (p, i) { if (p.canvas) paintSearch(p, i); });
  }

  function buildSearchBar() {
    var bar = document.createElement("div");
    bar.style.cssText =
      "position:absolute;top:10px;right:22px;z-index:40;display:flex;align-items:center;" +
      "gap:6px;background:var(--panel);border:1px solid var(--line);" +
      "border-radius:var(--r-md);box-shadow:0 8px 24px rgba(0,0,0,0.18);" +
      "padding:6px 8px;font-family:sans-serif;";
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = "문서에서 찾기";
    input.setAttribute("aria-label", "문서에서 찾기");
    input.style.cssText =
      "border:1px solid var(--line);border-radius:var(--r-sm);padding:4px 8px;" +
      "font-size:12px;width:180px;background:var(--bg);color:var(--text);outline:none;";
    input.addEventListener("input", function () {
      clearTimeout(srch.timer);
      var q = input.value.trim();
      srch.timer = setTimeout(function () { runSearch(q); }, 250);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); goHit(srch.at + (e.shiftKey ? -1 : 1)); }
      if (e.key === "Escape") { e.stopPropagation(); closeSearch(); }
    });
    var label = document.createElement("span");
    label.style.cssText =
      "font-size:11px;color:var(--text-3);min-width:34px;text-align:center;" +
      "font-variant-numeric:tabular-nums;";
    function btn(txt, title, fn) {
      var b = document.createElement("button");
      b.textContent = txt;
      b.title = title;
      b.style.cssText =
        "border:none;background:none;cursor:pointer;color:var(--text-2);" +
        "font-size:14px;padding:2px 4px;line-height:1;";
      b.addEventListener("click", fn);
      return b;
    }
    bar.appendChild(input);
    bar.appendChild(label);
    bar.appendChild(btn("‹", "이전 일치 (Shift+Enter)", function () { goHit(srch.at - 1); }));
    bar.appendChild(btn("›", "다음 일치 (Enter)", function () { goHit(srch.at + 1); }));
    bar.appendChild(btn("✕", "닫기 (Esc)", function () { closeSearch(); }));
    mountEl.appendChild(bar);
    srch.bar = bar;
    srch.input = input;
    srch.label = label;
  }

  function close() {
    hidePopup();
    document.removeEventListener("keydown", onKey, true);
    if (srch.bar) { srch.bar.remove(); }
    srch = { open: false, q: "", hits: [], at: -1, bar: null, input: null,
             label: null, timer: null };
    mountEl = null;
    if (host) { host.removeEventListener("scroll", paint); host.remove(); }
    pages.forEach(discard);
    // pdf.js 6 은 PDFDocumentProxy 에 destroy() 가 없다 — teardown 은 loadingTask 로 한다.
    // 닫기 오류가 다음 open 을 막지 않도록 감싼다.
    if (doc && doc.loadingTask) { try { doc.loadingTask.destroy(); } catch (e) { /* 무시 */ } }
    doc = null; host = null; pages = []; scale = 1; fitMode = true;
    marks = []; picked = null;
  }

  // 창 크기가 바뀌면 폭 맞춤을 유지한다. 사용자가 줌을 만졌으면 그 배율을 지킨다.
  window.addEventListener("resize", function () { if (fitMode) fit(); });

  window.DR.pdfview = {
    open: open, close: close, zoom: zoom, goTo: goTo,
    setMarks: setMarks, setMarksVisible: setMarksVisible, highlight: highlight,
    // 보고 있는 쪽·배율을 알린다(도구줄이 적는다).
    onViewChange: onViewChange, viewState: viewState,
    // 링을 두를 자리를 가르는 규칙. DOM 없이 확인한다(web/tests/).
    ringed: ringed,
    // 검색의 순수 로직(색인·일치·좌표 환산) — DOM 없이 확인한다(web/tests/).
    _search: { buildIndex: buildIndex, findRanges: findRanges, rangeRects: rangeRects },
    isOpen: function () { return !!doc; },
  };
})();

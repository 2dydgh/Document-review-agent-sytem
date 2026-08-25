(function () {
  "use strict";
  window.DR = window.DR || {};
  // 뷰 레이어: 심각도 팔레트·뷰모델(renderVals)·문서 미리보기·검토결과 HTML·
  // 화면 템플릿(view). state/props/render와 backend 일부를 주입받아 app.js와
  // 같은 상태를 그린다. 반환 함수를 app.js의 render()가 호출한다.
  window.DR.views = function (ctx) {
    var state = ctx.state, props = ctx.props, render = ctx.render;
    var ICONS = window.DR.ICONS;
    var H = window.DR.helpers;
    var esc = H.esc, rgba = H.rgba, fmtSize = H.fmtSize, download = H.download, downloadBlob = H.downloadBlob;
    var docSides = H.docSides;
    var be = ctx.backend, errorBanner = be.errorBanner, ago = be.ago, fmtElapsed = be.fmtElapsed;

  // 지적 id → 그 지적을 낸 기준 본문들. renderVals 가 매 렌더마다 채운다.
  // 수정안 호출이 기준을 함께 보내려면 화면 밖에서도 읽을 수 있어야 한다.
  var _critByFinding = {};

  // 기준 본문. 한 지적이 기준 여럿에 걸리면 줄바꿈으로 잇는다.
  function criterionTextFor(id) {
    var cs = _critByFinding[id];
    return (cs && cs.length) ? cs.join("\n") : "";
  }

  // ---- severity / type palette (one dot + soft badge) ----------------------
  //
  // dot 은 **통짜 색 조각**이고 fg 는 **연한 면 위 글자**다. 일이 다르니 값도
  // 다르다. 한 번 dot 을 fg 토큰으로 맞춰 봤는데(2026-08-12), 라이트에서
  // --sev-min-fg 가 #854D0E 라 범례 점이 갈색이 됐다 — fg 는 연한 노랑 면 위에서
  // 6.21:1 을 내려고 어둡게 고른 값이지, 그 자체로 "노랑"을 뜻하라고 고른 값이
  // 아니다. 색 토큰은 **역할이 다르면 못 돌려 쓴다.**
  // (다크에서 범례 점과 뱃지 글자의 색조가 조금 갈리는 건 남는다. 눈에 띄어서
  //  고치게 되면 --sev-*-dot 을 따로 두는 게 답이지, fg 를 빌려 오는 게 아니다.)
  var SEV = {
    major:    { dot: "#EA580C", bg: "var(--sev-maj-bg)", fg: "var(--sev-maj-fg)", bd: "var(--sev-maj-bd)", label: "Major" },
    minor:    { dot: "#EAB308", bg: "var(--sev-min-bg)", fg: "var(--sev-min-fg)", bd: "var(--sev-min-bd)", label: "Minor" },
    info:     { dot: "#64748B", bg: "var(--sev-info-bg)", fg: "var(--sev-info-fg)", bd: "var(--sev-info-bd)", label: "Info" },
    // 미검토는 심각도가 아니라 "검사를 못 했다"는 보고다. 뱃지(sevBadge)처럼
    // 면을 채우지 않는다 — 채우면 지적으로 읽힌다.
    unreviewed: { dot: "#9CA3AF", bg: "transparent", fg: "var(--text-3)", bd: "var(--line-2)", label: "미검토" },
    missing:  { dot: "#DC2626", bg: "var(--sev-crit-bg)", fg: "var(--sev-crit-fg)", bd: "var(--sev-crit-bd)" },
    mismatch: { dot: "#EA580C", bg: "var(--sev-maj-bg)", fg: "var(--sev-maj-fg)", bd: "var(--sev-maj-bd)" },
    conflict: { dot: "#EA580C", bg: "var(--sev-maj-bg)", fg: "var(--sev-maj-fg)", bd: "var(--sev-maj-bd)" },
    unknown:  { dot: "#9CA3AF", bg: "var(--neutral-weak)", fg: "var(--text-2)", bd: "var(--line)", label: "Other" }
  };
  // 검사기(checker) → 필터 분류. 필터 칩은 내부 검사기 이름이 아니라 이 분류로
  // 묶는다 — 검토자에게 "필수 항목 확인"과 "칸 값 검사"는 같은 형식 검사다.
  var CHECKER_CAT = {
    completeness: ["form", "형식 검사"],
    consistency: ["expr", "표현 검사"],
    consistency_doc: ["expr", "표현 검사"],
    traceability: ["trace", "추적 검사"],
    field_match: ["trace", "추적 검사"],
    case_wide: ["trace", "추적 검사"],
    parser: ["process", "검토 과정"],
    images: ["process", "검토 과정"]
  };
  var CAT_ORDER = ["form", "expr", "trace", "process", "etc"];
  var CAT_LABEL = { form: "형식 검사", expr: "표현 검사", trace: "추적 검사",
                    process: "검토 과정", etc: "기타" };
  var TM = {
    missing:  { dot: "#DC2626", bg: "#FEF2F2", fg: "#B91C1C", bd: "#FCA5A5" },
    mismatch: { dot: "#EA580C", bg: "#FFF7ED", fg: "#C2410C", bd: "#FDBA74" },
    extra:    { dot: "#64748B", bg: "#F1F5F9", fg: "#475569", bd: "var(--line-2)" }
  };

  // 체크리스트 아이콘. 체크리스트 화면과 홈이 같은 것을 쓴다 — 사본을 만들지 않는다.
  var glyphs = {
    generic: ICONS.list,
    prd: ICONS.fileText,
    api: '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>'
  };

  var ORDER = ["major", "minor", "info"];

  // ---- animation gating ---------------------------------------------------
  // 화면 전체를 매번 다시 그리는 구조라, 애니메이션을 그냥 붙이면 칩 하나만 눌러도
  // 목록 전체가 다시 재생된다. 직전 렌더와 비교해 "방금 바뀐 것"에만 붙인다.
  // 화면에 막 들어온 뒤에도 렌더가 한 번 더 오는 경우가 있다 (검토가 끝나면 이력을
  // 다시 불러오면서 10ms 뒤에 또 그린다). 그 렌더가 등장 연출을 지워버리므로,
  // 진입 직후 잠깐은 연출을 유지하고 지나간 만큼 딜레이를 당겨 이어붙인다.
  var ENTER_WINDOW = 250;
  // 홈의 설명 모션은 단계 네 개가 차례로 지나가 250ms보다 길다. API 응답으로
  // 중간 렌더가 와도 음수 지연으로 같은 시점부터 이어지도록 별도 창을 둔다.
  var HOME_ENTER_WINDOW = 1800;
  var prev = { key: null, at: 0, selected: null, cselected: null, stage: -1, cstage: -1 };
  function animFlags(st) {
    var key = st.mode + "/" + (st.mode === "compare" ? st.cstep : st.screen);
    var now = Date.now();
    if (key !== prev.key) { prev.key = key; prev.at = now; }
    var elapsed = now - prev.at;
    var f = {
      entered: elapsed < ENTER_WINDOW,
      enterElapsed: elapsed,
      homeEntered: st.mode === "home" && elapsed < HOME_ENTER_WINDOW,
      homeEnterElapsed: elapsed,
      openedId: st.selected && st.selected !== prev.selected ? st.selected : null,
      copenedId: st.cselected && st.cselected !== prev.cselected ? st.cselected : null,
      // 방금 완료로 넘어간 단계 (없으면 -1)
      doneStage: st.stageIndex !== prev.stage ? st.stageIndex - 1 : -1,
      cdoneStage: st.cstageIndex !== prev.cstage ? st.cstageIndex - 1 : -1
    };
    prev.selected = st.selected; prev.cselected = st.cselected;
    prev.stage = st.stageIndex; prev.cstage = st.cstageIndex;
    return f;
  }

  // 등록 전 미리보기. "무엇으로 읽었는지"를 사람 말로 만든다 —
  // 화면에 열 인덱스를 그대로 띄우면 검토자가 확인할 수 없다.
  function buildClibPreview(p) {
    if (!p) return null;
    var t = (p.tables || [])[p.picked] || {};
    var cols = t.columns || {};
    var header = t.header || [];
    var hasText = cols.text !== null && cols.text !== undefined;
    // sample·item_count는 서버가 "추측한" 열(t.guessedText, previewChecklist가
    // 응답 받을 때 찍어둔다)로 이미 골라 읽은 값이다. 사람이 열을 고쳐도 이
    // 값들은 서버가 다시 읽어주지 않는 한(등록 시점에만 재파싱) 그대로다 —
    // 원본 행을 받아 클라이언트에서 다시 세는 건 이 응답에 그 행 자체가 없어
    // 못 하고, 30장짜리 표라면 그걸 위해 원본 행을 얹는 것도 배보다 배꼽이
    // 크다. 그래서 고친 열이 추측과 다르면 낡은 값을 감추고 정직하게 만든다.
    var stale = hasText && t.guessedText != null && cols.text !== t.guessedText;
    return {
      name: p.name, picked: p.picked, tables: p.tables || [],
      header: header, columns: cols,
      sample: stale ? [] : (t.sample || []),
      itemCount: t.item_count || 0,
      stale: stale,
      textLabel: hasText
        ? ((cols.text + 1) + "번째 열 '" + (header[cols.text] || "") + "'")
        : null
    };
  }

  // 이번 검토에 **실제로 합쳐지는 층만** 추린다. /api/criteria 는 관리 화면도
  // 함께 쓰므로 업로드 기준을 전부 돌려주지만, 단일 검토는 그중 사람이 고른
  // checklist_id 하나만 쓴다. 공통 → 팀 → 업로드 순 중복 제거도 서버의
  // resolve_criteria 와 같아야 화면의 항목 수가 실제 작업량보다 부풀지 않는다.
  function reviewCriteriaInfo(clayers, uploadedId, llmEnabled, open) {
    var src = (clayers && clayers.list) || [];
    var seenText = Object.create(null), usedNo = Object.create(null);
    var counts = { rule: 0, expression: 0, whole: 0, manual: 0, disabled: 0 };
    var layers = src.filter(function (L) {
      return !L.editable || (!!uploadedId && L.id === uploadedId);
    }).map(function (L) {
      var items = (L.items || []).filter(function (it) {
        var key = String(it.text || "").trim();
        if (Object.prototype.hasOwnProperty.call(seenText, key)) return false;
        seenText[key] = true;
        return true;
      }).map(function (it) {
        var copy = {};
        Object.keys(it).forEach(function (k) { copy[k] = it[k]; });
        var no = String(copy.no || "");
        if (no && usedNo[no]) copy.no = no + "(" + L.scope + ")";
        usedNo[no] = true;

        if (copy.howChecked === "규칙 · 자동") counts.rule++;
        else if (copy.howChecked === "LLM · 자동" && !llmEnabled) {
          counts.disabled++;
          copy.howChecked = "AI 꺼짐 · 미검토";
        } else if (copy.howChecked === "LLM · 자동" && copy.mode === "LLM-문서") {
          counts.whole++;
        } else if (copy.howChecked === "LLM · 자동") counts.expression++;
        else counts.manual++;
        return copy;
      });
      return { scope: L.scope, id: L.id, name: L.name, editable: L.editable,
               error: L.error || "", items: items };
    });
    return {
      layers: layers,
      total: layers.reduce(function (n, L) { return n + L.items.length; }, 0),
      counts: counts,
      busy: !!(clayers && clayers.busy),
      error: (clayers && clayers.error) || "",
      loaded: !!(clayers && clayers.list),
      open: !!open
    };
  }

  // ---- derive view-model --------------------------------------------------
  function renderVals() {
    var D = window.DOCREVIEW, st = state, mode = st.mode;
    var anim = animFlags(st);
    var accent = props.accent;
    var meta = D.sevMeta;

    // INFO는 검토 과정 보고이고 unreviewed는 검사를 못 했다는 보고다. 둘을 모두
    // "지적 발견"으로 세면 문제 수를 부풀리고, 반대로 미검토가 있는데 "기준 통과"
    // 라고 하면 더 위험하다. 그래서 미검토는 심각도 통에 섞지 않고 따로 센다 —
    // 필터 칩도 이 넷을 그대로 쓴다(info 를 꺼도 미검토 보고는 남아야 한다).
    var counts = { major: 0, minor: 0, info: 0, unreviewed: 0 };
    var issueCount = 0, unreviewedCount = 0;
    D.findings.forEach(function (f) {
      if (f.unreviewed) { counts.unreviewed++; unreviewedCount++; return; }
      counts[f.sev]++;
      if (f.sev !== "info") issueCount++;   // counts.<등급> 직접 읽기는 가드가 막는다
    });
    var total = D.findings.length;

    // sidebar
    var featDefs = [
      { k: "home", label: "홈", icon: ICONS.home },
      // 끝을 "검토"로 맞춘다. 예전엔 축이 섞여 있었다 — "단일 검토"는 범위+동작,
      // "문서 비교"는 대상+동작, "산출물 세트"는 대상만 있고 동작이 없었다.
      // 이제 앞말이 **방식**이고 뒷말이 다 검토다: 문서 하나 안에서(단일),
      // 두 문서를 맞대어(비교), 폴더째 한 세트로(폴더).
      { k: "single", label: "단일 검토", icon: ICONS.single }, { k: "compare", label: "비교 검토", icon: ICONS.compare },
      { k: "case", label: "폴더 검토", icon: ICONS.folder },
      { k: "checklists", label: "검토 기준", icon: ICONS.list }, { k: "history", label: "검토 기록", icon: ICONS.history },
      { k: "settings", label: "설정", icon: ICONS.settings }
    ];
    var features = featDefs.map(function (d) { return { k: d.k, label: d.label, icon: d.icon, on: mode === d.k }; });

    // header + step tabs
    var heads = {
      login: ["", ""],
      signup: ["", ""],
      forgot: ["", ""],
      home: ["홈", "기능을 선택하세요"],
      single: ["단일 검토", "한 문서를 검토 기준으로 검토"],
      compare: ["비교 검토", "SRS ↔ SDD 교차검토"],
      "case": ["폴더 검토", "폴더째 올려 — 낱장마다 보고, 서로 맞춰본다"],
      checklists: ["검토 기준", "공통·팀 기준과 내가 올린 체크리스트"],
      checklistrun: ["검토 기준", "항목별 판정"],
      history: ["검토 기록", "최근 실행 내역"],
      settings: ["설정", "LLM · 청크 · 테마"]
    };
    var steps = [], hasSteps = false;
    if (mode === "single") {
      hasSteps = true;
      steps = [["upload", "업로드"], ["progress", "검토"], ["results", "지적사항"]].map(function (p) {
        return { act: "go", k: p[0], label: p[1], on: st.screen === p[0] };
      });
    } else if (mode === "compare") {
      hasSteps = true;
      // 같은 단계는 같은 이름으로 부른다. 비교의 results도 "리포트"가 아니라 지적사항 목록이다.
      steps = [["setup", "업로드"], ["progress", "비교"], ["results", "지적사항"]].map(function (p) {
        return { act: "goCStep", k: p[0], label: p[1], on: st.cstep === p[0] };
      });
    } else if (mode === "case") {
      // 산출물 세트만 단계 표시가 없어서 지금 어디쯤인지, 몇 단계가 남았는지
      // 화면에 안 나왔다. 다른 기능과 같은 이름을 쓴다 — "인식 확인"만 이
      // 기능 고유 단계다(폴더째 올리니 무엇이 무엇인지 사람이 확인해야 한다).
      hasSteps = true;
      steps = [["upload", "업로드"], ["recognize", "인식 확인"],
               ["progress", "검토"], ["results", "지적사항"]].map(function (p) {
        return { act: "goCaseStep", k: p[0], label: p[1], on: st.kase.step === p[0] };
      });
    }

    // 목록은 서버(GET /api/health)가 준 것만 쓴다. 예전엔 docreview-data.js 의
    // 목업(Generic·PRD·API Spec)을 그렸는데, 그 셋은 서버에 존재하지도 않았고
    // 골라도 전달되지 않아 "고르는 시늉"만 하는 UI였다. 서버를 아직 못 읽었으면
    // 빈 목록 — 없는 기준을 지어내느니 아무것도 안 보여주는 편이 낫다.
    var srvChecklists = (st.server && st.server.checklists) || [];
    var pickedChecklist = st.checklist || (st.server && st.server.checklist_id) || "";

    // 업로드 문서를 재본 결과. 잘못된 기준의 실패는 에러가 아니라 조용한 0건이라
    // (같은 실 문서인데 SHN34는 FR-GC_01, SKN56은 FR1-0305 — 서로 0개다),
    // 검토를 돌리기 **전에** 몇 개 걸리는지 보여줘야 한다.
    var dt = st.detect;
    var detectRow = dt && !dt.busy && !dt.error
      ? (dt.list || []).filter(function (d) { return d.id === pickedChecklist; })[0]
      : null;
    // 지금 고른 기준으로 찾은 요건 ID 개수. null이면 아직 재지 않았다 —
    // "0개"와 "모름"은 다르다. 모르는 걸 0으로 그리면 없는 경고가 뜬다.
    var detectCount = detectRow ? detectRow.matches : null;
    var detectBest = (dt && dt.best) || "";
    // id_pattern 이 없는 체크리스트(단일문서용 rvvr-standard 등)는 애초에 요건
    // ID 를 보지 않는다. 매칭 0개를 결함처럼 경고하면 정상 사용에서 붉은 띠가
    // 떠 배너 자체가 무시된다 — 경고를 무시하게 만드는 경고는 없느니만 못하다.
    var detectScored = !!(detectRow && detectRow.has_pattern);
    var detectWarn = (detectScored && detectCount === 0)
      ? ("이 기준으로는 요건 ID를 한 개도 찾지 못했습니다. 이대로 검토하면 "
         + "지적 0건이 뜨는데, 그건 통과가 아니라 검토를 못 한 것입니다."
         + (detectBest ? " 이 문서에는 '" + detectBest + "' 기준이 맞습니다." : ""))
      : "";
    var detectAuto = !!(detectBest && !st.checklistPicked && detectBest === pickedChecklist);
    var checklistCards = srvChecklists.map(function (c) {
      return { id: c.id, name: c.name, glyph: glyphs[c.id] || ICONS.list,
               sel: pickedChecklist === c.id,
               reqLabel: c.doc_type ? c.doc_type : "팀 기준" };
    });

    // AI 검토를 켤지 끌지만 고른다. 어떤 모델을 쓸지는 서버 설정이 정한다 —
    // 브라우저가 provider를 고를 수 있으면 사내 문서를 외부 API로 내보내는
    // 경로가 열린다. 모델 이름도 지어내지 않고 서버가 답한 것만 보여준다.
    var srv = st.server;
    var llmChips = [];
    var llmNote = "";
    if (!srv) {
      llmNote = "서버에 연결되지 않아 무엇으로 검토하는지 알 수 없습니다.";
    } else if (srv.llm_provider === "echo") {
      llmNote = "서버에 AI 모델이 설정되지 않았습니다. 규칙 검사만 돕니다.";
    } else {
      // 그림 해석용 모델이 붙어 있으면 그 사실을 칩에 단다. 검토자가 "그림을
      // 읽었는지"를 알아야 결과를 옳게 읽는다 — 안 읽었으면 그림 안의 표·구성도는
      // 검토되지 않은 것이다. 안 붙어 있을 때 따로 경고하지는 않는다: 검토 결과에
      // "그림 N장을 읽지 않았습니다"가 지적으로 올라오므로 그쪽이 근거다.
      llmChips = [
        { k: "off", label: "규칙만 · 빠름", on: st.llm === "off" },
        { k: "on",
          label: shortModel(srv.llm_label || srv.llm_model) + " · 사내"
                 + (srv.vlm_enabled ? " · 그림 포함" : ""),
          on: st.llm === "on" }
      ];
    }

    // 단일 검토 진행 화면. 준비 3단계는 0.1초에 끝나므로 요약 한 줄로 접고,
    // 몇 분이 걸리는 Review를 본무대로 올린다 — 레인마다 실제 작업 단위
    // (규칙·LLM 호출)의 완료 수를 센다.
    var rv = st.rev || { prep: {}, lanes: [], done: {}, active: "" };
    var prepParts = [];
    if (rv.prep.ingestion) prepParts.push(rv.prep.ingestion);
    if (rv.prep.normalize) prepParts.push(rv.prep.normalize);
    if (rv.prep.chunking) prepParts.push(rv.prep.chunking);
    var lanes = (rv.lanes || []).map(function (l) {
      // 열쇠는 label — kind("chunk")는 표현 점검과 문서 전체 점검이 공유해서
      // 유일하지 않다(api.js 의 step 처리 주석 참고).
      var done = rv.done[l.label || l.kind] || 0;
      var key = l.label || l.kind;
      return { kind: l.kind, label: key, total: l.total, doneCount: done,
        description: l.description || "", scope: l.scope || "", limited: !!l.limited,
        // 서버가 시작 이벤트에 active를 싣는다. 첫 완료 전에도 실제로 도는 레인은
        // 진행 중이고, 아직 차례가 오지 않은 레인만 대기다.
        status: l.total <= 0 ? "empty"
          : (done >= l.total ? "done" : (rv.active === key ? "run" : "wait")) };
    });
    var unitsDone = lanes.reduce(function (a, l) { return a + l.doneCount; }, 0);
    var unitsTotal = lanes.reduce(function (a, l) { return a + l.total; }, 0);
    var review = {
      prep: prepParts.join(" · "),
      prepReady: prepParts.length === 3,
      prepMs: rv.prepAt && rv.startedAt ? rv.prepAt - rv.startedAt : 0,
      lanes: lanes,
      note: rv.note || "",
      // 총량을 미리 받았을 때만 퍼센트를 말한다. 모르면 지어내지 않는다.
      pct: unitsTotal > 0 ? Math.round((unitsDone / unitsTotal) * 100) : null,
      elapsed: rv.startedAt ? fmtElapsed(Date.now() - rv.startedAt) : ""
    };
    review.criteria = reviewCriteriaInfo(st.clayers, st.reviewChecklistId,
                                         st.llm !== "off", rv.criteriaOpen);

    // pipelines
    function mkTimeline(stages, idx, justDone) {
      // 채움은 CSS 토큰으로 낸다 — JS 하드코딩(#356998)을 쓰면 다크에서 --accent 를
      // 밝게 올려도 이 점들만 라이트 톤으로 남는다. 펄스 색도 토큰 rgb 로.
      var ACC = "var(--accent)";
      return stages.map(function (s, i) {
        var done = i < idx, active = i === idx;
        // 막 완료된 단계의 체크만 튀어나온다. 전부 붙이면 매 렌더마다 다시 재생된다.
        var dotAnim = active ? ("--pc:rgba(var(--accent-rgb),0.28);animation:dvpulse 1.4s ease-in-out infinite;")
          : (done && i === justDone ? "animation:popIn .3s var(--ease-spring);" : "");
        return { label: s.label, desc: s.desc,
          // 서버가 방금 보고한 값만 그린다(state.stageDetail). 비교 stage는 key가 없어
          // 조회가 비므로 detail 줄이 그려지지 않는다 — 목업 숫자를 대신 끌어오지 않는다.
          detail: (st.stageDetail || {})[s.key] || "",
          detailColor: active ? ACC : (done ? "#6B7280" : "#9CA3AF"),
          op: (!done && !active) ? 0.6 : 1,
          lineColor: (done || active) ? ACC : "#E7E8EC", dotBg: done ? ACC : (active ? "#fff" : "#F1F2F4"),
          dotBorder: (done || active) ? ACC : "#D6D8DE", dotFg: done ? "#fff" : ACC, dotIcon: done ? ICONS.check : "",
          dotAnim: dotAnim,
          bd: active ? ACC : "#E7E8EC",
          statusLabel: done ? "DONE" : (active ? "RUNNING" : "QUEUED"),
          statusColor: active ? ACC : "#9CA3AF" };
      });
    }
    // 완료 비트 동안에는 마지막 단계도 체크로 넘긴다 — 다 끝났는데 마지막 점이
    // 계속 돌고 있으면 "완료"라는 말과 화면이 서로 다른 소리를 한다.
    var sIdx = st.done ? D.stages.length : st.stageIndex;
    var cIdx = st.cdone ? D.compare.stages.length : st.cstageIndex;
    var pipeline = mkTimeline(D.stages, sIdx, st.done ? D.stages.length - 1 : anim.doneStage);
    var progressPct = st.stageIndex < 0 ? 0 : Math.round(((st.stageIndex + 1) / D.stages.length) * 100);
    var cpipeline = mkTimeline(D.compare.stages, cIdx, st.cdone ? D.compare.stages.length - 1 : anim.cdoneStage);
    var cProgressPct = st.cstageIndex < 0 ? 0 : Math.round(((st.cstageIndex + 1) / D.compare.stages.length) * 100);

    // findings table
    var sevChips = ORDER.map(function (sev) {
      return { sev: sev, label: SEV[sev].label, count: counts[sev], on: st.sevFilter[sev] };
    });
    // 미검토 칩은 있을 때만 — 0 이면 "미검토 0" 이 헤더 자리를 먹는다.
    if (counts.unreviewed) {
      sevChips.push({ sev: "unreviewed", label: "미검토", count: counts.unreviewed, on: st.sevFilter.unreviewed });
    }
    // 검사기 필터는 내부 이름(필수 항목 확인·parser…)이 아니라 검토자가 아는
    // 분류로 묶는다 — "필수항목확인이 뭔데?"를 필터가 만들지 않는다(2026-08-14
    // 사용자 피드백). 세부 이름은 카드 뱃지(label · kind)가 계속 말한다.
    var checkerCatOf = function (c) { return (CHECKER_CAT[c] || ["etc", "기타"])[0]; };
    var seenCat = {};
    D.findings.forEach(function (f) { seenCat[checkerCatOf(f.checker)] = true; });
    var checkerOpts = [{ k: "all", label: "전체" }];
    CAT_ORDER.forEach(function (k) {
      if (seenCat[k]) checkerOpts.push({ k: k, label: CAT_LABEL[k] });
    });
    var checkerChips = checkerOpts.map(function (c) {
      return { k: c.k, label: c.label, on: st.checkerFilter === c.k };
    });
    var sortChips = [{ k: "severity", l: "심각도순" }, { k: "section", l: "위치순" }].map(function (o) {
      return { k: o.k, label: o.l, on: st.sort === o.k };
    });
    var filtered = D.findings.filter(function (f) {
      // 미검토 보고는 sev(대개 info)가 아니라 자기 칩이 가린다 — info 를 꺼도 남는다.
      var on = f.unreviewed ? st.sevFilter.unreviewed : st.sevFilter[f.sev];
      return on && (st.checkerFilter === "all" || checkerCatOf(f.checker) === st.checkerFilter);
    });
    var sortFn = st.sort === "section"
      ? function (a, b) { var pa = a.section || "", pb = b.section || ""; if (!pa && pb) return -1; if (pa && !pb) return 1; return pa.localeCompare(pb, undefined, { numeric: true }); }
      : function (a, b) { return meta[a.sev].order - meta[b.sev].order; };
    // 번호는 표시본이 지면에 찍은 것을 그대로 쓴다. 화면이 따로 매기면 "3번"이
    // 서로 다른 것을 가리켜 번호를 다는 목적이 깨진다. 표시본을 아직 안 만들었으면
    // 번호가 없다 — 번호가 형광펜에 매달려 있어 PDF를 훑기 전에는 정해지지 않는다.
    // 번호는 뷰어 오버레이(POST /api/locate)가 형광펜에 매긴 것을 그대로 쓴다.
    // 화면이 따로 매기면 "3번"이 형광펜과 카드에서 서로 다른 것을 가리킨다.
    var markNumbers = {}, markQuoteNos = {};
    ((st.marks && st.marks.items) || []).forEach(function (it) {
      if (it.no) markNumbers[it.id] = it.no;
      // 인용별 번호(evidence 순서, 못 찾은 인용은 null). 같은 절의 인용이 둘이면
      // 번호 없이는 카드에서 둘째 인용의 위치를 알 길이 없다.
      if (it.quote_nos) markQuoteNos[it.id] = it.quote_nos;
    });
    // finding.id → 그 지적을 품은 기준 라벨. payload 는 항목→지적 방향만 준다
    // (criteriaResults.items[].findings 가 평면 findings 와 같은 dict 참조) —
    // 카드·수정안에서 쓰도록 역으로 만든다. checklist는 옛 payload 호환 폴백이다.
    var critByFinding = {}, critLayerByFinding = {};
    ((((D.criteriaResults || D.checklist) || {}).items) || []).forEach(function (it) {
      (it.findings || []).forEach(function (f) {
        (critByFinding[f.id] = critByFinding[f.id] || []).push(it.text || it.no || "");
        // 층(공통/팀별/업로드)은 표시용으로만 따로 든다 — 수정안 프롬프트에
        // 보내는 기준 본문(critByFinding)에 섞으면 모델에게 잡음이다.
        (critLayerByFinding[f.id] = critLayerByFinding[f.id] || []).push(it.layer || "");
      });
    });
    // 수정안(/api/suggest)이 이 맵을 쓴다 — renderVals 안의 지역 변수라 밖에서
    // 못 읽으므로 마지막 것을 여기 둔다. 기준을 모르면 모델이 어느 방향으로
    // 고칠지 알 수 없다(SI 단위계는 "5kg" 가 아니라 "5 kg" 가 맞다).
    _critByFinding = critByFinding;
    function critLabel(id) {
      var cs = critByFinding[id];
      if (!cs || !cs.length) return "";
      // 공통·팀은 늘 도는 기준이지만 업로드는 검토자가 고른 것이다 — 어느 층의
      // 기준이 낸 지적인지 앞에 단다.
      var layer = (critLayerByFinding[id] || [])[0];
      var head = (layer ? "[" + layer + "] " : "") + cs[0];
      return cs.length === 1 ? head : (head + " 외 " + (cs.length - 1) + "건");
    }
    // 이번에만 나온 지적. 예전에는 반영 확인 패널이 이 목록을 **따로 한 번 더**
    // 그려서 같은 지적이 위아래에 두 번 보였다. 목록을 없애고 카드에 표시만 단다.
    var newIds = {};
    ((D.lineage && D.lineage.new_findings) || []).forEach(function (f) {
      if (f && f.id) newIds[f.id] = true;
    });
    // 검토자가 `해당없음` 으로 정리한 지적. **카드를 지우지는 않는다** — 기계가
    // 낸 것을 화면이 삼키면 안 되고(CLAUDE.md), 검사기는 다음에도 그 지적을 낸다.
    // 대신 "이건 이미 해당없음으로 정리됐다"를 카드가 말한다. 안 그러면 검토자가
    // "해당없다고 했는데 왜 또 뜨지" 를 매번 다시 겪는다.
    var naIds = lineageNaIds() || {};
    var tableFindings = filtered.slice().sort(sortFn).map(function (f) {
      var open = st.selected === f.id;
      // kind(모순·표기·모호)를 빠뜨리면 뱃지가 종류를 못 그린다. 이 자리는 payload
      // 를 화면용으로 **다시 짓는 곳**이라, 새 필드는 여기 적어야 살아 넘어간다.
      return { id: f.id, open: open, sev: f.sev, checker: f.checker, kind: f.kind || "",
        label: f.label || "", message: f.message, rescued: !!f.rescued,
        rescueTrace: f.rescue_trace || null,
        isNew: !!newIds[f.id], na: !!naIds[f.id],
        no: markNumbers[f.id] || null,
        quoteNos: markQuoteNos[f.id] || [],
        criteria: critLabel(f.id),
        // 체커가 단 제안. 없으면 없는 대로 둔다 — 예전엔 "위치를 확인해
        // 수정하세요."를 대신 채워 넣고 'AI 제안'이라 이름 붙였는데, 그건
        // 화면이 지어낸 문구지 AI가 만든 것이 아니다.
        // 절이 없는 지적(문서 전체를 보는 info 등)의 위치 표기. "doc" 은 디버그
        // 문자열처럼 읽혔다 — 화면·내보내기가 같은 한국어를 쓴다.
        suggestion: f.suggestion || "", loc: f.section ? "§" + f.section : "문서 전체",
        // 검증을 통과한 원문 인용. 카드가 이걸 직접 보여준다(findingCardInner).
        evidence: f.evidence || [],
        chevron: open ? "▾" : "▸" };
    });

    // 미리보기. 고른 지적이 가리키는 절과, 그 지적이 들고 온 원문 인용.
    // 규칙 체커는 근거를 안 달아 quotes가 빈다 — 그 경우 절로 스크롤만 한다.
    var selected = null;
    D.findings.forEach(function (f) { if (f.id === st.selected) selected = f; });
    var hlSection = selected ? selected.section : null;
    // 절 id → 그 절에서 칠할 인용들. 근거가 자기 위치를 들고 오므로 그대로 쓴다.
    // 절을 모르는 근거(section=null)는 지적이 가리키는 절에 붙인다.
    var hlBySection = {};
    (selected && selected.evidence || []).forEach(function (e) {
      var sid = e.section || hlSection;
      if (!sid) return;
      // 심각도 색으로 칠한다. 예전엔 앰버 한 색이라, 같은 문서를 PDF 로 보면
      // 3색(pdfview) · 텍스트 재현본으로 보면 1색 · 내보내면 다시 3색이었다.
      (hlBySection[sid] = hlBySection[sid] || []).push(
        { q: e.quote, cls: "sev-" + selected.sev });
    });

    // summary
    // ORDER 를 돌린다 — 등급을 더하거나 빼도 여기를 같이 고칠 필요가 없다.
    // (예전엔 counts.critical 을 직접 읽어서, 등급이 빠지면 undefined 로 NaN 이 됐다.)
    var maxCount = Math.max.apply(null, ORDER.map(function (k) { return counts[k]; }).concat(1));
    var statRows = ORDER.map(function (sev) {
      return { sev: sev, label: SEV[sev].label, count: counts[sev], pct: Math.round(counts[sev] / maxCount * 100) };
    });
    var chk = { completeness: 0, consistency: 0 };
    // 모르는 checker 이름이 오면 NaN이 되지 않게 막는다 (엔진에 체커가 추가될 수 있다).
    D.findings.forEach(function (f) { if (chk[f.checker] !== undefined) chk[f.checker]++; });
    var checkerCards = [{ label: "completeness", glyph: ICONS.check, count: chk.completeness }, { label: "consistency", glyph: ICONS.equal, count: chk.consistency }];
    var topFindings = D.findings.slice().sort(function (a, b) { return meta[a.sev].order - meta[b.sev].order; }).slice(0, 3).map(function (f) {
      return { sev: f.sev, sevLabel: SEV[f.sev].label, message: f.message, loc: f.section ? "§" + f.section : "문서 전체" };
    });
    // 점수(100 - 가중 감점)는 뺐다. 근거는 CLAUDE.md "기능 방침 — 점수".
    // 요약하면: 가중치도 구간도 실측 근거가 없었고, critical 항은 발동조차 하지
    // 않았으며, info 는 "못 봤다"는 보고인데 감점이었다. 눈금을 검증할 정답셋
    // (golden/)이 생기기 전에는 다시 넣지 않는다.

    // compare
    var cmp = D.compare;
    var compareFindings = cmp.findings.slice().sort(function (a, b) { return meta[a.sev].order - meta[b.sev].order; }).map(function (f) {
      var open = st.cselected === f.id;
      return { id: f.id, open: open, type: f.type, typeLabel: D.typeMeta[f.type].short,
        aLoc: f.a ? "§" + f.a : "—", bLoc: f.b ? "§" + f.b : "—", aOn: !!f.a, bOn: !!f.b,
        message: f.message, suggestion: f.suggestion, chevron: open ? "▾" : "▸" };
    });
    var coverage = cmp.stats.requirements
      ? Math.round(cmp.stats.matched / cmp.stats.requirements * 100) : 0;
    var cmpStatCards = [
      { label: "누락", count: cmp.stats.missing, color: TM.missing.dot },
      { label: "불일치", count: cmp.stats.mismatch, color: TM.mismatch.dot },
      { label: "근거 없음", count: cmp.stats.extra, color: TM.extra.dot }
    ];
    // 부모 수준에서만 검증된 세부 요건(FR-GC_01_01 → FR-GC_01). 누락은 아니지만
    // 연결과도 다르다 — 커버리지 분모에는 들어가므로 감추면 "누락 0인데 커버리지는
    // 63%"가 되어 나머지가 어디서 왔는지 화면만 봐서는 알 수 없다.
    if (cmp.stats.rolled_up) {
      cmpStatCards.push({ label: "부모 수준 검증", count: cmp.stats.rolled_up, color: "#64748B" });
    }
    // 범위 밖(부분 설계서가 담당하지 않는 상위 요건)은 누락이 아니다.
    // 그렇다고 감추지도 않는다 — 개수를 띄워 사용자가 범위를 확인하게 한다.
    if (cmp.stats.out_of_scope) {
      cmpStatCards.push({ label: "범위 밖", count: cmp.stats.out_of_scope, color: "#9CA3AF" });
    }

    // 단일 검토 셋업에서 "체크리스트로 평가"에 고를 수 있는 목록. 이건 **라이브러리에
    // 올려 등록한 체크리스트**(state.clib.list, /api/checklists)다 — 자동 검토 기준
    // (srvChecklists = YAML)이 아니다. 검토는 이 id 를 서버에서 checklists.get 으로
    // 다시 읽으므로, YAML id 를 보내면 라이브러리에 없어 404 가 난다.
    var reviewChecklistCards = (st.clib.list || []).map(function (c) {
      return { id: c.id, name: c.name, count: c.item_count || 0,
               sel: st.reviewChecklistId === c.id };
    });

    // 체크리스트가 이끈 검토의 항목별 결과(done 이벤트의 payload.checklist,
    // api.js가 window.DOCREVIEW.checklist에 보관). 안 골랐으면(null) 결과
    // 화면은 기존 평면 지적 목록을 그대로 쓴다 — singleResults가 이 값의
    // 존재로 갈린다.
    var checklistReview = (function () {
      var c = D.checklist;
      if (!c) return null;
      // 항목 안의 findings 는 payload.findings 와 같은 dict(참조)라 번호·형광펜
      // 매핑(markNumbers)이 평면 목록과 그대로 맞아떨어진다 — 여기서 새로
      // 매기지 않는다.
      function mapFinding(f) {
        var open = st.selected === f.id;
        // kind(모순·표기·모호)를 빠뜨리면 뱃지가 종류를 못 그린다. 이 자리는 payload
        // 를 화면용으로 **다시 짓는 곳**이라, 새 필드는 여기 적어야 살아 넘어간다.
        return { id: f.id, open: open, sev: f.sev, checker: f.checker, kind: f.kind || "", label: f.label || "", message: f.message,
          rescued: !!f.rescued, rescueTrace: f.rescue_trace || null,
          no: markNumbers[f.id] || null, quoteNos: markQuoteNos[f.id] || [],
          suggestion: f.suggestion || "",
          loc: f.section ? "§" + f.section : "문서 전체",
          evidence: f.evidence || [], chevron: open ? "▾" : "▸" };
      }
      var items = (c.items || []).map(function (it) {
        return { no: it.no, text: it.text, group: it.group, status: it.status,
          // 기준 자체. 본문만으로는 "이 기준이 뭐였는지"를 알 수 없다 —
          // 공통 기준 본문은 "아래 양식으로"에서 끊겨 있고 세부는 note 에 있다.
          note: it.note || "", mode: it.mode || "",
          layer: it.layer || "",   // 공통/팀별/업로드 — 항목 헤더가 출처를 단다
          findings: (it.findings || []).map(mapFinding) };
      });
      return { items: items, summary: c.summary || { flagged: 0, clean: 0, unreviewed: 0, na: 0, outofscope: 0, noanswer: 0, manual: 0, total: 0 } };
    })();

    // 회신본 반영 확인(D.lineage): 이전 지적별 상태(열림/닫힘/해당없음) + 신규 지적.
    // checklistReview 와 같은 패턴 — D 를 읽어 화면용 뷰 오브젝트를 만든다.
    var lineage = lineageView();
    var lineageCandidate = lineageCandidateOf();

    return {
      isLogin: mode === "login", isSignup: mode === "signup", isForgot: mode === "forgot", isHome: mode === "home", files: st.files,
      isSingle: mode === "single", isCompare: mode === "compare",
      isChecklists: mode === "checklists", isHistory: mode === "history", isSettings: mode === "settings",
      // 체크리스트를 채우는 독립 화면. 라이브러리 "검토 시작"과 기록에서
      // 이어서 열 때 둘 다 여기로 온다 — 자동 검토(single/results)와 무관하다.
      isChecklistRun: mode === "checklistrun",
      sUpload: mode === "single" && st.screen === "upload", sProgress: mode === "single" && st.screen === "progress",
      sResults: mode === "single" && st.screen === "results",
      cSetup: mode === "compare" && st.cstep === "setup", cProgress: mode === "compare" && st.cstep === "progress",
      kase: st.kase,
      kUpload: mode === "case" && st.kase.step === "upload",
      kRecognize: mode === "case" && st.kase.step === "recognize",
      kProgress: mode === "case" && st.kase.step === "progress",
      kResults: mode === "case" && st.kase.step === "results",
      cResults: mode === "compare" && st.cstep === "results",
      accent: accent, SEV: SEV, TM: TM, anim: anim,
      doc: D.doc, cmp: cmp, llm: st.llm, features: features, hasSteps: hasSteps, steps: steps,
      pipelinePreview: D.stages, headTitle: heads[mode][0], headSub: heads[mode][1],
      checklistCards: checklistCards, llmChips: llmChips,
      reviewChecklistCards: reviewChecklistCards, reviewChecklistId: st.reviewChecklistId,
      checklistPickReturn: st.checklistPickReturn,
      checklistReview: checklistReview,
      lineage: lineage, lineageCandidate: lineageCandidate,
      detectCount: detectCount, detectWarn: detectWarn, detectBest: detectBest,
      detectScored: detectScored,
      clib: st.clib,
      clayers: st.clayers,
      clibPreview: buildClibPreview(st.clib.preview),
      clibDetail: st.clib.detail,
      runChecklistId: st.runChecklistId,
      // 사람이 직접 채우는 체크리스트(독립 화면 checklistrun). 안 골랐으면
      // (checklist null) 화면이 안내 문구만 보여준다 — v.crun 이 그 신호다.
      crun: (function () {
        var c = st.crun.checklist;
        if (!c) return null;
        var items = (c.items || []).map(function (it, i) {
          // 결과는 no 가 아니라 배열 위치(i)로 찾는다 — no 는 선택 안 하면
          // 전부 "" 이고 구간별 재시작으로 겹칠 수 있어, no 를 키로 쓰면 같은
          // no 를 가진 다른 항목까지 판정된 것처럼 보인다.
          var r = st.crun.results[String(i)] || {};
          return { idx: i, no: it.no, text: it.text, group: it.group,
                   verdict: r.verdict || null, reason: r.reason || "" };
        });
        return { name: c.name, items: items, saving: st.crun.saving,
                 error: st.crun.error || null,
                 // 뒤로가기 대상("checklists"|"history")과 이 화면에서 적은
                 // 검토 대상 문서명 — 둘 다 checklistRunScreen 헤더가 쓴다.
                 from: st.crun.from || "checklists",
                 documentName: st.crun.documentName || "",
                 // 안 본 항목 개수. 이걸 안 보여주면 다 본 것처럼 읽힌다.
                 unjudged: items.filter(function (i) { return !i.verdict; }).length };
      })(),
      detectAuto: detectAuto, detectBusy: !!(dt && dt.busy),
      detectIdExample: detectRow ? (detectRow.id_example || "") : "",
      llmNote: llmNote,
      pipeline: pipeline, progressPct: progressPct, cpipeline: cpipeline, cProgressPct: cProgressPct,
      review: review,
      done: st.done, cdone: st.cdone, cTotalCount: (D.compare.findings || []).length,
      // 지금 펼친 카드에서 받아둔 수정안들. 인용마다 하나라 "지적id|인용순번"
      // 으로 든다 — 지적 하나에 인용이 열여덟 개인 경우가 실제로 있다.
      fixes: st.fixes,
      sevChips: sevChips, checkerChips: checkerChips, sortChips: sortChips, tableFindings: tableFindings,
      exportBtns: [{ kind: "json", label: "JSON" }, { kind: "md", label: "Markdown" }, { kind: "csv", label: "CSV" }],
      totalCount: total, issueCount: issueCount, unreviewedCount: unreviewedCount, infoCount: counts.info,
      hasFindings: tableFindings.length > 0, noFindings: tableFindings.length === 0,
      sections: D.sections || [], hlSection: hlSection, hlBySection: hlBySection,
      // 원본에 표시하는 건 PDF만 된다. hwpx는 브라우저로도 못 그리고 원본에
      // 표시할 방법도 사실상 없다 — 그 문서에는 이 버튼을 띄우지 않는다.
      isPdf: !!(D.doc && String(D.doc.type || "").toUpperCase() === "PDF"),
      annot: st.annot,
      hasOrigFile: !!(st.files.single && st.files.single.file),
      viewerMode: st.viewer.mode,
      markedReady: !!st.annot.viewUrl,
      viewerKind: String((D.doc || {}).type || "").toUpperCase(),   // PDF/DOCX/HWPX/…
      converting: st.viewer.converting,
      convertError: st.viewer.convertError,
      statRows: statRows, checkerCards: checkerCards, topFindings: topFindings,
      compareFindings: compareFindings, coverage: coverage, cmpStatCards: cmpStatCards,
      cerror: st.cerror, serror: st.serror
    };
  }

  function doAnnotate(file, then) {
    var D = window.DOCREVIEW;
    state.annot = Object.assign({}, state.annot, { busy: true, msg: "" });
    render();
    var fd = new FormData();
    // 표시본은 base PDF(원본이든 재현본이든)에 형광펜을 얹는다. 원본 파일(docx/hwpx)을
    // 그대로 보내면 /api/annotate가 PDF가 아니라고 거부한다 — 변환된 base를 보낸다.
    var base = state.viewer.baseBlob || file;
    var stem = (((window.DOCREVIEW.doc || {}).name) || "document").replace(/\.[^.]+$/, "");
    fd.append("file", base, stem + ".pdf");
    fd.append("findings", JSON.stringify(D.findings || []));
    fetch("api/annotate", { method: "POST", body: fd })
      .then(function (res) {
        if (!res.ok) {
          // 서버가 늘 JSON으로 답하지는 않는다. 500은 본문이 "Internal Server
          // Error" 평문이라 res.json()을 그냥 부르면 파싱 오류가 대신 뜬다 —
          // 사용자는 진짜 원인 대신 "Unexpected token 'I'"를 보게 된다.
          return res.text().then(function (body) {
            var detail = body;
            try { detail = JSON.parse(body).detail || body; } catch (e) { /* 평문 */ }
            throw new Error("서버 오류 " + res.status + " — " + String(detail).slice(0, 120));
          });
        }
        var mk = parseInt(res.headers.get("X-Marked-Count") || "0", 10);
        var un = parseInt(res.headers.get("X-Unmarked-Count") || "0", 10);
        var summary = res.headers.get("X-Summary") === "1";
        var sp = parseInt(res.headers.get("X-Summary-Pages") || "0", 10);
        // 지적 id → 지면에 찍힌 번호. 카드에 같은 번호를 달아 "3번 지적"이
        // 표시본과 화면에서 같은 것을 가리키게 한다. 헤더가 없거나 깨져도
        // 번호만 안 뜰 뿐 표시본 자체는 멀쩡해야 하므로 조용히 비운다.
        var numbers = {};
        try { numbers = JSON.parse(res.headers.get("X-Numbers") || "{}") || {}; }
        catch (e) { numbers = {}; }
        return res.blob().then(function (b) {
          if (state.annot.viewUrl) URL.revokeObjectURL(state.annot.viewUrl);
          var msg = "근거 " + mk + "곳에 형광펜과 번호를 붙였습니다.";
          // 요약 페이지가 지적을 지면에 직접 그린다. 크롬 기본 뷰어는 주석
          // 팝업의 한글을 못 찍고 인쇄하면 아예 사라지므로, 이게 본체다.
          msg += summary
            ? " 맨 앞에 지적 요약 페이지가 붙어 있습니다."
            : " 다만 서버에 한글 폰트가 없어 요약 페이지는 넣지 못했습니다 (sudo apt install fonts-nanum).";
          // 표시하지 못한 지적을 조용히 넘기지 않는다 — 형광펜이 없다고 해서
          // 지적이 없는 것이 아니다.
          if (un) {
            msg += " " + un + "건은 본문에서 위치를 찾지 못해 형광펜을 못 칠했습니다 — 요약 페이지에 번호 없이 실려 있습니다.";
          }
          // 다운로드하지 않고 blob을 캐시해 뷰어에 띄운다. 다운로드는 별도 버튼이
          // 이 캐시를 저장한다 — 표시본을 두 번 굽지 않게.
          state.annot = { busy: false, msg: msg, blob: b,
                          viewUrl: URL.createObjectURL(b), summaryPages: sp,
                          numbers: numbers };
          state.viewer.mode = "marked";
          render();
          if (then) then();
        });
      })
      .catch(function (e) {
        state.annot = Object.assign({}, state.annot, { busy: false, msg: "표시하지 못했습니다: " + e.message });
        state.viewer.mode = "orig";
        render();
      });
  }

  // 마지막으로 스크롤을 옮긴 지적. 선택이 바뀐 렌더에서만 뷰어를 움직이려고 둔다.

  function selectedSection() {
    var found = null;
    (window.DOCREVIEW.findings || []).forEach(function (f) {
      if (f.id === state.selected) found = f.section;
    });
    return found;
  }

  // ---- 문서 미리보기 ------------------------------------------------------
  // 엔진이 실제로 읽은 텍스트를 그린다. 원본(hwpx/pdf)을 띄우지 않는 이유는
  // docs/superpowers/specs/2026-07-14-single-review-preview-design.md 참고 —
  // hwpx는 브라우저에서 렌더할 방법이 없고(주력 포맷이 전부 hwpx다), 원본을
  // 띄우면 추출이 놓친 내용까지 "엔진이 봤다"고 오해하게 된다.

  // verify_quotes._norm 과 같은 규칙이어야 한다. 규칙이 갈라지면 백엔드가
  // "원문에 있다"고 보증한 인용을 화면이 못 찾아 하이라이트가 조용히 사라진다.
  function normQ(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }

  // marks: [{ q, cls, title }]. 화면은 고른 지적 하나만 칠하고, 내보내기는 모든
  // 지적을 심각도 색으로 칠한다 — 렌더러는 하나다.
  function markLine(line, marks) {
    if (!marks || !marks.length) return esc(line);
    function tag(m, text) {
      return '<mark class="' + (m.cls || "hl") + '"' +
        (m.title ? ' title="' + esc(m.title) + '"' : "") + '>' + esc(text) + '</mark>';
    }
    for (var i = 0; i < marks.length; i++) {
      var q = marks[i] && marks[i].q;
      if (!q) continue;
      var at = line.indexOf(q);
      // 글자까지 그대로 맞으면 그 부분만 칠한다.
      if (at >= 0) {
        return esc(line.slice(0, at)) + tag(marks[i], q) + esc(line.slice(at + q.length));
      }
    }
    var n = normQ(line);
    for (var j = 0; j < marks.length; j++) {
      // 공백만 다른 경우(verify_quotes가 허용하는 차이). 어디까지가 인용인지
      // 원문 좌표로 되짚기 어려우니 줄을 통째로 칠한다 — 못 찾은 척하는 것보다 낫다.
      if (marks[j] && marks[j].q && n.indexOf(normQ(marks[j].q)) >= 0) {
        return tag(marks[j], line);
      }
    }
    return esc(line);
  }

  function rowCells(line) {
    var parts = line.split("|");
    if (parts.length && !parts[0].trim()) parts.shift();
    if (parts.length && !parts[parts.length - 1].trim()) parts.pop();
    return parts;
  }

  var _TD = "border:1px solid var(--line);padding:8px 10px;font-size:13px;line-height:1.6;color:var(--text-2);vertical-align:top;";
  var _TH = _TD + "background:var(--bg);color:var(--text);font-weight:700;";

  function docTable(rows, quotes) {
    var head = rowCells(rows[0]).map(function (c) {
      return '<th style="' + _TH + '">' + markLine(c.trim(), quotes) + '</th>';
    }).join("");
    var body = rows.slice(1).map(function (r) {
      return '<tr>' + rowCells(r).map(function (c) {
        return '<td style="' + _TD + '">' + markLine(c.trim(), quotes) + '</td>';
      }).join("") + '</tr>';
    }).join("");
    return '<div style="overflow-x:auto;margin:0 0 18px;">' +
      '<table style="border-collapse:collapse;width:100%;">' +
      '<thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  // 추출기가 내는 모양은 세 가지뿐이다(### 제목 / | 셀 | 셀 | / 문단).
  // 마크다운 파서를 붙이지 않는다 — 파서는 우리가 안 쓰는 문법까지 해석해
  // 원문에 없는 구조를 만들어낸다.
  function docBlocks(text, quotes) {
    var lines = String(text == null ? "" : text).split("\n");
    var out = [], i = 0;
    while (i < lines.length) {
      var t = lines[i].trim();
      if (!t) { i++; continue; }
      if (t.charAt(0) === "|") {
        var rows = [];
        while (i < lines.length && lines[i].trim().charAt(0) === "|") {
          rows.push(lines[i].trim()); i++;
        }
        out.push(docTable(rows, quotes));
        continue;
      }
      var m = /^(#{1,6})\s+(.*)$/.exec(t);
      if (m) {
        var lv = Math.min(m[1].length + 2, 6);
        out.push('<h' + lv + ' style="font-size:' + (19 - m[1].length) + 'px;font-weight:700;' +
          'color:var(--text);margin:22px 0 10px;letter-spacing:-.2px;">' +
          markLine(m[2], quotes) + '</h' + lv + '>');
        i++; continue;
      }
      out.push('<p style="font-size:13px;line-height:1.6;color:var(--text-2);margin:0 0 12px;">' +
        markLine(t, quotes) + '</p>');
      i++;
    }
    return out.join("");
  }

  function docBody(v) {
    if (!v.sections.length) {
      return '<div style="padding:64px 24px;text-align:center;color:var(--text-3);font-size:14px;line-height:1.6;">' +
        '이 검토에는 문서 본문이 저장되지 않았습니다.<br>' +
        '<span style="font-size:13px;">미리보기 기능 이전에 실행된 검토입니다. 다시 검토하면 본문이 함께 저장됩니다.</span></div>';
    }
    return v.sections.map(function (s) {
      // 근거는 자기 절을 안다. 일관성 지적은 본질적으로 "여기와 저기"라서
      // 근거 둘이 서로 다른 절에 흩어진다 — 지적의 anchor 하나만 보고 칠하면
      // 나머지 근거는 영영 안 보인다. 절마다 자기 몫의 인용만 칠한다.
      var quotes = v.hlBySection[s.id] || [];
      var on = quotes.length > 0 || (v.hlSection && s.id === v.hlSection);
      var page = s.page ? '<span style="font-size:11px;color:var(--text-3);font-weight:600;">' + s.page + '쪽</span>' : "";
      return '<section id="sec-' + esc(s.id) + '" style="scroll-margin-top:24px;padding:14px 18px;margin:0 0 6px;border-radius:var(--r-md);' +
          (on ? 'background:var(--accent-weak);box-shadow:inset 3px 0 0 var(--accent);' : '') + '">' +
        '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:8px;">' +
          '<span style="font-size:11px;font-weight:600;color:var(--accent-ink);font-variant-numeric:tabular-nums;">§' + esc(s.id) + '</span>' +
          '<span style="font-size:15px;font-weight:700;color:var(--text);">' + esc(s.title) + '</span>' + page +
        '</div>' +
        docBlocks(s.text, quotes) +
      '</section>';
    }).join("");
  }

  // ---- 검토 결과 문서 (자기완결 HTML) -------------------------------------
  // 미리보기와 같은 렌더러(docBlocks/markLine)를 쓴다. 산출물이 화면과 다르게
  // 생기면 둘 중 하나는 거짓말이 된다.
  //
  // 화면과 다른 점은 둘뿐이다:
  //   1. 고른 지적 하나가 아니라 모든 지적을 심각도 색으로 한꺼번에 칠한다
  //   2. CSS 변수를 파일 안에 박는다 — 이 파일은 DocSuree 없이 혼자 열려야 한다
  //      (그래서 외부 폰트·스크립트도 안 쓴다)

  // index.html의 :root 라이트 토큰. 여기서 벗어나면 산출물 색이 화면과 달라진다.
  var EXPORT_TOKENS =
    ":root{--bg:#F2E0D4;--panel:#FFFEFC;--line:#DDCEC3;--line-2:#EEE2DA;" +
    "--text:#2B2926;--text-2:#55504A;--text-3:#6B645E;--accent:#356998;--accent-ink:#356998;" +
    "--accent-strong:#284F73;--accent-weak:rgba(53,105,152,.12);--neutral-weak:rgba(122,103,91,.11);" +
    "--sev-crit-bg:rgba(220,38,38,.1);--sev-crit-fg:#B91C1C;--sev-crit-bd:rgba(220,38,38,.2);" +
    "--sev-maj-bg:rgba(234,88,12,.1);--sev-maj-fg:#C2410C;--sev-maj-bd:rgba(234,88,12,.2);" +
    "--sev-min-bg:rgba(202,138,4,.1);--sev-min-fg:#A16207;--sev-min-bd:rgba(202,138,4,.2);" +
    "--sev-info-bg:rgba(100,116,139,.1);--sev-info-fg:#475569;--sev-info-bd:rgba(100,116,139,.2);}";

  var EXPORT_CSS = EXPORT_TOKENS +
    "*{box-sizing:border-box}" +
    "body{margin:0;background:var(--bg);color:var(--text);line-height:1.6;" +
    "font-family:system-ui,-apple-system,'Segoe UI',Roboto,'Malgun Gothic','Apple SD Gothic Neo',sans-serif}" +
    ".wrap{max-width:900px;margin:0 auto;padding:32px 20px 80px}" +
    ".card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);padding:24px 28px;margin-bottom:20px}" +
    "h1{font-size:22px;margin:0 0 6px;letter-spacing:-.4px}" +
    ".sub{color:var(--text-3);font-size:13px;margin-bottom:20px}" +
    ".warn{background:var(--sev-crit-bg);color:var(--sev-crit-fg);border:1px solid var(--sev-crit-bd);" +
    "border-radius:var(--r-sm);padding:10px 14px;font-size:12px;font-weight:600;margin-bottom:20px}" +
    ".kv{display:flex;gap:10px;font-size:13px;padding:6px 0;border-bottom:1px solid var(--line-2)}" +
    ".kv b{flex:none;width:110px;color:var(--text-3);font-weight:600}" +
    ".counts{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}" +
    ".pill{font-size:12px;font-weight:600;padding:6px 12px;border-radius:var(--r-xl);border:1px solid}" +
    ".fx{border:1px solid var(--line);border-radius:var(--r-md);padding:14px 16px;margin-bottom:10px}" +
    ".fx-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px}" +
    ".fx-msg{font-weight:700;font-size:14px}" +
    ".fx-sug{font-size:12px;color:var(--text-2);margin-top:6px}" +
    ".fx-q{font-size:12px;color:var(--text-2);border-left:3px solid var(--line);padding:2px 0 2px 10px;margin-top:6px}" +
    "mark{border-radius:3px;padding:2px 2px}" +
    "mark.sev-major{background:var(--sev-maj-bg);box-shadow:0 0 0 1px var(--sev-maj-bd)}" +
    "mark.sev-minor{background:var(--sev-min-bg);box-shadow:0 0 0 1px var(--sev-min-bd)}" +
    "mark.sev-info{background:var(--sev-info-bg);box-shadow:0 0 0 1px var(--sev-info-bd)}" +
    "section{padding:10px 14px;border-radius:var(--r-sm);margin-bottom:4px}" +
    "section.hit{background:var(--accent-weak);box-shadow:inset 3px 0 0 var(--accent)}" +
    ".sec-h{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}" +
    ".sec-n{font-size:11px;font-weight:600;color:var(--accent-ink)}" +
    ".sec-t{font-size:15px;font-weight:700}" +
    "@media print{body{background:#fff}.card{break-inside:avoid}}";

  // 반영 확인 화면과 내보내기가 함께 쓰는 뷰 모델. 두 곳이 각자 만들면
  // 화면이 말하는 판정과 회신서에 실리는 판정이 갈린다.
  // 반영 확인 한 줄 요약. 화면과 회신서가 같은 말을 하게 한 곳에 둔다.
  // 검토자가 **처리한** 건수. `해당없음` 도 처리한 것이다 — 안 세면 다섯 건을
  // 정리해도 진행률이 안 움직여 일한 티가 안 난다. 탭과 app.js 가 각자 더하면
  // 두 숫자가 갈리므로 여기 한 곳에서만 센다.
  function lineageDoneCount(L) {
    return (L.summary.closed || 0) + (L.summary.na || 0);
  }

  function lineageTabLabel(L) {
    return "반영 확인 " + lineageDoneCount(L) + "/" + L.items.length;
  }

  function lineageSummaryText(L) {
    return "반영 확인 — 반영됨 " + L.summary.closed + " · 미반영 " + L.summary.open +
      (L.summary.na ? " · 해당없음 " + L.summary.na : "") +
      " · 신규 " + L.summary.added;
  }

  // 뷰어 오버레이(POST /api/locate)가 형광펜에 매긴 번호.
  function markNumberOf(id) {
    if (!id) return null;
    var items = (state.marks && state.marks.items) || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === id) return items[i].no || null;
    }
    return null;
  }

  function lineageView() {
    var D = window.DOCREVIEW || {};
    var L = D.lineage;
    if (!L) return null;
    // 사람이 내린 판정. 기계 판정(it.status)을 **덮지 않고 따로** 온다 —
    // 덮으면 판정 근거가 사라지고, 다시 검토해 기계 판정이 새로 계산될 때
    // 사람이 한 일까지 지워진다(서버의 confirm_lineage 참고).
    var saved = D.lineageVerdicts || {};
    // 지난 검토에서 이어받은 판정 {열쇠: 값}. 검토자가 이번에 누른 것과 갈라
    // 보여준다. 값까지 보는 이유는 덮어쓰면 더 이상 이어받은 것이 아니어서다.
    var carried = D.lineageCarried || {};
    // 옛 이력은 열림·닫힘으로 저장돼 있다. 표가 없으면 그 검토들이 빈 값으로 보인다.
    var LEGACY = { "열림": "그대로 있음", "닫힘": "안 보임", "해당없음": "해당없음" };
    // 기계가 본 것 → 사람 판정의 초기값. 검토자가 안 건드리면 이 값으로 읽힌다.
    // **셋 다 미반영이다** — 기계는 고쳐졌다고 단정할 수 없다(lineage.py 참고).
    var FROM_AUTO = { "그대로 있음": "미반영", "안 보임": "미반영", "해당없음": "해당없음",
                      "판단 못 함": "미반영" };
    var items = (L.items || []).map(function (it, i) {
      var f = it.finding || {};
      var auto = LEGACY[it.status] || it.status;      // 기계가 본 것. 안 바뀐다
      // 판정은 **지적의 신원**(서버가 준 key)에 붙는다. 순번은 그 검토 안에서만
      // 뜻이 있어 다음 검토로 못 잇는다. String(i) 는 그렇게 저장된 옛 이력용이다.
      var mine = saved[it.key] || saved[String(i)];   // 사람이 고른 것(있으면)
      return { idx: String(i),
               message: f.message || "", loc: f.section ? "§" + f.section : "문서 전체",
               // 이어받은 값 그대로일 때만 `지난 판정` 이다. 검토자가
               // 덮어쓰면 그건 이번에 자기가 고른 것이다.
               auto: auto, carried: !!mine && carried[it.key] === mine,
               // 형광펜 번호. 뷰어가 매긴 것을 그대로 쓴다 — 화면이 따로 매기면
               // "3번"이 형광펜과 카드에서 서로 다른 것을 가리킨다.
               // `안 보임` 은 문서에 자리가 없어 번호도 없다.
               no: markNumberOf(it.match_id),
               // 이번 검토의 같은 지적. 누르면 문서의 그 자리로 간다.
               // 이전 지적의 좌표는 **이전 문서** 것이라 여기선 못 쓴다.
               matchId: it.match_id || "",
               // 짝이 없으면(`안 보임`) 갈 자리가 없다. 대신 지난번 인용을 보여줘
               // 검토자가 문서에서 찾을 수 있게 한다 — 목록만 있으면 어딘지 모른다.
               quote: ((f.evidence || [])[0] || {}).quote || "",
               status: mine || FROM_AUTO[auto] || "미반영" };
    });
    var newFindings = (L.new_findings || []).map(function (f) {
      return { message: f.message || "", loc: f.section ? "§" + f.section : "문서 전체",
               sev: f.sev || "info" };
    });
    // 요약은 **사람 판정** 기준이다 — 검토자가 실제로 무엇을 확인했는지가
    // "기계가 못 찾았다"보다 중요하다.
    var done = items.filter(function (i) { return i.status === "반영됨"; }).length;
    var todo = items.filter(function (i) { return i.status === "미반영"; }).length;
    var na = items.filter(function (i) { return i.status === "해당없음"; }).length;
    return { items: items, newFindings: newFindings,
             statusOpts: ["미반영", "반영됨", "해당없음"],
             newLabel: "신규 지적",
             summary: { closed: done, open: todo, na: na,
                        added: newFindings.length } };
  }

  // 회신서의 알맹이. 검토자가 지난번 지적을 하나씩 판정한 결과다 —
  // 이게 없으면 드롭다운을 누를 이유가 없다(눌러도 자기만 본다).
  // `반영 확인` 탭에서 문서에 칠할 지적의 id 들. 지난 지적 중 **아직 미반영으로
  // 둔 것**만이다 — 검토자가 판정을 바꾸면 칠이 따라 바뀐다.
  //
  // `안 보임` 은 이번 문서에 짝이 없어 칠할 자리도 없다(matchId 가 빈다).
  // 재검토가 아니면 null — 걸러낼 것이 없다는 뜻이다.
  // 지금 보고 있는 결과 탭. **기본값을 한 곳에서만 정한다** — state.reviewTab 은
  // 검토자가 탭을 직접 누르기 전까지 null 이고, 화면만 "재검토면 반영 확인부터"로
  // 기본을 잡고 있었다. 그래서 app.js 가 `state.reviewTab !== "lineage"` 로 물으면
  // 반영 확인 탭을 보고 있는데도 아니라고 답했다(형광펜이 안 바뀌었다).
  function reviewTabNow() {
    var D = window.DOCREVIEW || {};
    return D.lineage ? (state.reviewTab || "lineage") : "findings";
  }

  // 검토자가 `해당없음` 으로 정리한 지적의 id 들(이번 검토 기준).
  // 카드를 **지우지는 않는다** — 기계가 낸 것을 화면이 삼키면 안 되고(CLAUDE.md),
  // 검사기는 다음에도 그 지적을 낸다. 대신 카드가 "이미 정리됐다"를 말한다.
  // 안 그러면 검토자가 "해당없다고 했는데 왜 또 뜨지" 를 매번 다시 겪는다.
  function lineageNaIds() {
    var L = lineageView();
    if (!L) return null;
    var na = {};
    L.items.forEach(function (it) {
      if (it.matchId && it.status === "해당없음") na[it.matchId] = true;
    });
    return na;
  }

  function lineageMarkIds() {
    var L = lineageView();
    if (!L) return null;
    var keep = {};
    L.items.forEach(function (it) {
      if (it.matchId && it.status === "미반영") keep[it.matchId] = true;
    });
    return keep;
  }

  // 반영 확인 패널 전체. 좌표(POST /api/locate)는 검토가 끝난 **뒤에** 온다 —
  // 형광펜 번호가 그때 정해지므로, 도착하면 이 패널만 다시 그린다. 통째로 그리면
  // 뷰어가 PDF 를 다시 연다.
  // 이전 검토 발견 배너 — "이어서 반영 확인?"
  function lineageCandidateOf() {
    var c = (window.DOCREVIEW || {}).lineageCandidate;
    return c ? { title: c.title, at: c.at } : null;
  }

  function lineagePanelHtml() {
    var L = lineageView();
    if (!L) return "";
    return lineageHtml(L, lineageCandidateOf());
  }

  function lineageCardHtml() {
    var L = lineageView();
    if (!L || !L.items.length) return "";
    var rows = L.items.map(function (it) {
      return '<div class="fx"><div class="fx-h">' +
        '<span class="pill">' + esc(it.status) + '</span>' +
        '<span class="fx-loc">' + esc(it.loc) + '</span>' +
        '<span class="sub" style="margin-left:auto;">기계 관찰: ' + esc(it.auto) +
          // 이번에 새로 내린 판정인지, 지난 검토에서 이어온 것인지 갈라 준다.
          (it.carried ? ' · 지난 판정' : '') + '</span>' +
        '</div><div class="fx-msg">' + esc(it.message) + '</div></div>';
    }).join("");
    return '<div class="card"><h1 style="font-size:18px;">반영 확인 ' + L.items.length + '건</h1>' +
      '<div class="sub">' + esc(lineageSummaryText(L)) +
        ' — 판정은 검토자가 내린 것이고, 기계 관찰은 그 근거입니다.</div>' + rows + '</div>';
  }

  // 내보내기 본문. **화면 밖으로 나가는 글은 여기서 만든다** — 액션(app.js)은
  // 내려받기 통로만 진다. 액션 안에 두면 DOM 없이 못 돌려서, 판정이 실제로
  // 실렸는지 글자 대조로만 지킬 수 있었다(조건만 꺼도 문자열은 남는다).
  function _sortedFindings() {
    var D = window.DOCREVIEW, meta = D.sevMeta;
    return D.findings.slice().sort(function (a, b) {
      return meta[a.sev].order - meta[b.sev].order;
    });
  }

  function reviewJson() {
    var D = window.DOCREVIEW, fs = _sortedFindings(), L = lineageView();
    var obj = { source: D.doc.name, total: fs.length,
      findings: fs.map(function (f) {
        return { checker: f.checker, severity: f.sev, message: f.message,
                 anchor: { section: f.section }, suggestion: f.suggestion || null };
      }) };
    if (L && L.items.length) {
      obj.lineage = { summary: L.summary, items: L.items.map(function (it) {
        return { verdict: it.status, observed: it.auto,
                 section: it.loc, message: it.message };
      }) };
    }
    return JSON.stringify(obj, null, 2);
  }

  function reviewMd() {
    var D = window.DOCREVIEW, meta = D.sevMeta, fs = _sortedFindings(), L = lineageView();
    var s = "# 문서 검토 결과: " + D.doc.name + "\n\n총 " + fs.length + "건\n\n";
    fs.forEach(function (f) {
      s += "- **[" + meta[f.sev].label + "]** (" + f.checker + ", " +
        (f.section ? "§" + f.section : "문서 전체") + ") " + f.message + "\n";
      if (f.suggestion) s += "  - 제안: " + f.suggestion + "\n";
    });
    if (L && L.items.length) {
      s += "\n## 반영 확인 " + L.items.length + "건\n\n" + lineageSummaryText(L) + "\n\n";
      L.items.forEach(function (it) {
        s += "- **[" + it.status + "]** (" + it.loc + ") " + it.message +
          "  \n  기계 관찰: " + it.auto + "\n";
      });
    }
    return s;
  }

  function reviewCsv() {
    var fs = _sortedFindings(), L = lineageView();
    var q = function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; };
    var csv = "severity,checker,section,message,suggestion\n";
    fs.forEach(function (f) {
      csv += [q(f.sev), q(f.checker), q(f.section || ""), q(f.message),
              q(f.suggestion || "")].join(",") + "\n";
    });
    if (L && L.items.length) {
      // 엑셀에서 두 표로 읽히게 빈 줄로 끊고 머리글을 다시 낸다.
      csv += "\n" + lineageSummaryText(L) + "\n판정,기계 관찰,위치,지난번 지적\n";
      L.items.forEach(function (it) {
        csv += [q(it.status), q(it.auto), q(it.loc), q(it.message)].join(",") + "\n";
      });
    }
    return csv;
  }

  function reviewHtml() {
    var D = window.DOCREVIEW, meta = D.sevMeta, s = state.server;
    var fs = D.findings.slice().sort(function (a, b) { return meta[a.sev].order - meta[b.sev].order; });

    // 절 → 그 절에서 칠할 인용들. 지적 전부를 한꺼번에 얹는다.
    var bySec = {}, hit = {};
    fs.forEach(function (f) {
      if (f.section) hit[f.section] = true;
      (f.evidence || []).forEach(function (e) {
        var sid = e.section || f.section;
        if (!sid) return;
        hit[sid] = true;
        (bySec[sid] = bySec[sid] || []).push(
          { q: e.quote, cls: "sev-" + f.sev, title: meta[f.sev].label + " · " + f.message });
      });
    });

    var counts = { major: 0, minor: 0, info: 0 };
    fs.forEach(function (f) { counts[f.sev]++; });
    var pills = ORDER.map(function (k) {
      var p = SEV[k];
      return '<span class="pill" style="background:' + p.bg + ';color:' + p.fg + ';border-color:' + p.bd + ';">' +
        meta[k].label + ' ' + counts[k] + '</span>';
    }).join("");

    var kv = function (k, v) {
      return v ? '<div class="kv"><b>' + esc(k) + '</b><span>' + esc(v) + '</span></div>' : "";
    };
    var basis = s
      ? kv("팀 기준", s.checklist) +
        kv("담당 범위", s.scope_label || s.scope_pattern) +
        kv("검토 엔진", s.llm_provider === "echo" ? "규칙만 (LLM 미사용)" : s.llm_model)
      : '<div class="sub">검토 기준을 서버에서 읽지 못했습니다.</div>';

    // 지적 목록. 근거 인용을 함께 싣는다 — 목록만 봐도 무엇을 근거로 한 지적인지 보인다.
    var list = fs.length ? fs.map(function (f) {
      var p = SEV[f.sev];
      var qs = (f.evidence || []).map(function (e) {
        return '<div class="fx-q">' + esc(e.quote) + '</div>';
      }).join("");
      return '<div class="fx" id="' + esc(f.id) + '">' +
        '<div class="fx-head">' +
          '<span class="pill" style="background:' + p.bg + ';color:' + p.fg + ';border-color:' + p.bd + ';">' +
            meta[f.sev].label + '</span>' +
          '<span style="font-size:11px;font-weight:600;color:var(--text-3);">' +
            (f.section ? '§' + esc(f.section) : '문서 전체') +
            (f.page ? ' · ' + f.page + '쪽' : '') + ' · ' + esc(f.checker) + '</span>' +
        '</div>' +
        '<div class="fx-msg">' + esc(f.message) + '</div>' + qs +
        (f.suggestion ? '<div class="fx-sug">제안: ' + esc(f.suggestion) + '</div>' : '') +
      '</div>';
    }).join("") : '<div class="sub">지적사항이 없습니다.</div>';

    var body = (D.sections || []).length
      ? (D.sections).map(function (sec) {
          var marks = bySec[sec.id] || [];
          return '<section class="' + (hit[sec.id] ? "hit" : "") + '">' +
            '<div class="sec-h"><span class="sec-n">§' + esc(sec.id) + '</span>' +
              '<span class="sec-t">' + esc(sec.title) + '</span>' +
              (sec.page ? '<span style="font-size:11px;color:var(--text-3);font-weight:600;">' + sec.page + '쪽</span>' : '') +
            '</div>' + docBlocks(sec.text, marks) +
          '</section>';
        }).join("")
      : '<div class="sub">이 검토에는 문서 본문이 저장되지 않았습니다.</div>';

    var name = (D.doc && D.doc.name) || "문서";
    // 파일 안에 문서 본문이 통째로 들어간다. 이 파일 하나가 사내 문서 사본이다.
    return "<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">" +
      "<title>" + esc(name) + " — DocSuree 검토 결과</title><style>" + EXPORT_CSS + "</style></head><body>" +
      '<div class="wrap">' +
        '<div class="card">' +
          '<h1>' + esc(name) + '</h1>' +
          '<div class="sub">DocSuree · 문서 일관성·추적성 검토 Agent — 검토 결과 ' +
            esc(new Date().toLocaleString("ko-KR")) + '</div>' +
          '<div class="warn">사내 문서 — 이 파일에는 문서 본문 전체가 포함됩니다. 외부 반출 금지.</div>' +
          basis +
          '<div class="counts">' + pills + '</div>' +
        '</div>' +
        lineageCardHtml() +
        '<div class="card"><h1 style="font-size:18px;">지적사항 ' + fs.length + '건</h1>' +
          '<div class="sub">LLM이 낸 지적에는 원문 근거가 함께 실려 있습니다. 근거 없는 지적은 리포트에 오르지 않습니다.</div>' +
          list +
        '</div>' +
        '<div class="card"><h1 style="font-size:18px;">문서 본문</h1>' +
          '<div class="sub">엔진이 읽은 텍스트입니다. 지적의 근거가 본문 위에 표시되어 있습니다.</div>' +
          body +
        '</div>' +
      '</div></body></html>';
  }

  // ---- small template helpers --------------------------------------------
  function docShapeIcon(title, size, colorBase) {
    // 2글자 확장자까지 받는다 — `.md` 가 3글자 규칙에 안 걸려 혼자 일반 아이콘으로
    // 떨어졌다. 지원 형식이 .md·.txt·.pdf·.hwpx·.docx 이므로 2~4 면 전부 덮는다.
    var extMatch = title ? title.match(/\.([a-zA-Z0-9]{2,4})$/) : null;

    // 확장자가 없으면 폴더다(폴더 검토가 세트째 하나로 뜨는 자리). 문서 아이콘과
    // 같은 시각 언어로 그린다 — 같은 viewBox·같은 두 겹 투명도라 나란히 놓아도
    // 크기와 색이 어긋나지 않는다. 종이의 접힌 모서리 자리를 폴더의 탭이 맡는다.
    if (!extMatch) {
      if (size < 40) {
        return '<span style="color:var(--'+colorBase+');display:inline-flex;align-items:center;font-size:'+size+'px;">' + ICONS.folder + '</span>';
      }
      // 폴더는 가로가 넓다. 문서의 세로 비율(28×36)에 맞추려 들면 억지스러워지므로
      // 자기 viewBox(30×26)를 쓴다. 같은 것은 비율이 아니라 **시각 언어**다 —
      // 같은 색, 같은 두 겹 투명도(몸통 0.15 · 탭 0.3), 같은 얇은 윤곽과 여백.
      // 폭은 문서(size×0.8)와 비슷하게 맞춘다 — 더 넓히면 옆의 문서 아이콘을 누른다.
      return '<svg viewBox="0 0 30 26" style="width:'+Math.round(size * 0.85)+'px;height:'+Math.round(size * 0.737)+'px;color:var(--'+colorBase+');flex:none;margin:0 4px;">' +
        '<path d="M0 4a2 2 0 0 1 2-2h8.5l3 3.5H28a2 2 0 0 1 2 2v14.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2z" fill="currentColor" opacity="0.15"/>' +
        '<path d="M0 4a2 2 0 0 1 2-2h8.5l3 3.5H0z" fill="currentColor" opacity="0.3"/>' +
        '<path d="M0 4a2 2 0 0 1 2-2h8.5l3 3.5H28a2 2 0 0 1 2 2v14.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2z" fill="none" stroke="currentColor" stroke-width="0.7" stroke-linejoin="round" opacity="0.38"/>' +
        '<path d="M0 4a2 2 0 0 1 2-2h8.5l3 3.5H0" fill="none" stroke="currentColor" stroke-width="0.7" stroke-linejoin="round" opacity="0.38"/>' +
        // 서류 두 줄. 문서 아이콘은 확장자 글자가 안을 채우는데 폴더는 빈 도형이라
        // 나란히 놓으면 혼자 허전했다. 개수를 적는 편이 정보로는 낫지만 이 함수는
        // 개수를 받지 않는다 — 그건 인자를 늘리는 일이라 따로 한다.
        '<line x1="8" y1="13" x2="22" y2="13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity="0.55"/>' +
        '<line x1="8" y1="17" x2="18" y2="17" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity="0.55"/></svg>';
    }

    var ext = extMatch[1].toUpperCase();
    // 2글자(MD)는 같은 크기로 두면 허전하다. 글자 수에 맞춰 셋으로 나눈다.
    var fSize = ext.length > 3 ? "6.5" : (ext.length < 3 ? "9" : "7.5");

    // For small inline icons, return a simpler mini badge
    if (size < 40) {
      return '<span style="display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;background:var(--'+colorBase+'-weak);color:var(--'+colorBase+');padding:2px 4px;border-radius:4px;line-height:1;vertical-align:middle;margin-right:6px;">' + ext + '</span>';
    }

    var w = Math.round(size * 0.8);
    var h = size;

    /* 40px 이상에서는 업로드 삽화와 같은 윤곽 언어를 쓴다. viewBox 기준 .7은
       실제 40~52px 렌더에서 약 1px이고, 작은 인라인 배지는 위에서 이미 별도
       마크업으로 빠졌으므로 좁은 곳에 선이 뭉치지 않는다. */
    return '<svg viewBox="0 0 28 36" style="width:'+w+'px;height:'+h+'px;color:var(--'+colorBase+');flex:none;margin:0 4px;">' +
      '<path d="M4 0h13l11 11v21a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4V4a4 4 0 0 1 4-4z" fill="currentColor" opacity="0.15"/>' +
      '<path d="M17 0v11h11" fill="currentColor" opacity="0.3"/>' +
      '<path d="M4 0h13l11 11v21a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4V4a4 4 0 0 1 4-4z" fill="none" stroke="currentColor" stroke-width="0.7" stroke-linejoin="round" opacity="0.38"/>' +
      '<path d="M17 0v11h11" fill="none" stroke="currentColor" stroke-width="0.7" stroke-linejoin="round" opacity="0.38"/>' +
      '<text x="14" y="26" font-size="' + fSize + '" font-weight="900" style="font-family:var(--font-body);" fill="currentColor" text-anchor="middle" letter-spacing="-0.3px">' + ext + '</text></svg>';
  }

  function iconTile(glyph, size, sel) {
    var s = size || 34;
    var bg = sel ? "var(--accent)" : "var(--accent-weak)", fg = sel ? "#fff" : "var(--accent-ink)";
    return '<div style="width:' + s + 'px;height:' + s + 'px;flex:none;border-radius:' + Math.round(s * 0.28) + 'px;background:' + bg + ';display:flex;align-items:center;justify-content:center;color:' + fg + ';font-weight:700;font-size:' + Math.round(s * 0.42) + 'px;">' + glyph + '</div>';
  }
  // 심각도 점을 여기 따로 달지 않는다. 면·테두리·글자색이 이미 그 색이라
  // 같은 말을 두 번 하는 것이고, 카드 머리줄(번호 칩·뱃지·신규·위치)은 폭이
  // 빠듯하다. 위쪽 범례와 안 맞아 보이던 건 뱃지 탓이 아니라 **범례 점이
  // 테마를 안 따라가서**였다 — SEV.dot 주석 참고.
  function badge(pal, label) {
    return '<span style="display:inline-flex;align-items:center;font-size:11px;font-weight:600;letter-spacing:.01em;padding:4px 8px;border-radius:5px;background:' + pal.bg + ';color:' + pal.fg + ';border:1px solid ' + pal.bd + ';">' + esc(label) + '</span>';
  }

  // 솔리드 심각도 배지(색 채운 알약). 밝은 색(노랑 Minor)은 흰 글자 대비가 낮아 어두운
  // 글자를 쓴다 — light=true면 진한 갈색 글자.
  function solidBadge(color, label, light) {
    return '<span style="display:inline-flex;align-items:center;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;padding:4px 10px;border-radius:var(--r-sm);background:' + color + ';color:' + (light ? "#4A3806" : "#fff") + ';">' + esc(label) + '</span>';
  }

  // 표시본이 지면에 찍은 번호. 화면과 PDF가 같은 번호를 가리키게 하는 표식이라
  // 화면이 임의로 매기지 않는다 — 번호가 없으면(표시본 전이거나 못 칠한 지적)
  // 자리를 비운다. 지어낸 번호는 지면에 없는 곳을 가리킨다.
  // 근거가 여럿이면 "1, 2"로 온다.
  // 지적 하나의 심각도 뱃지. **단일 검토와 폴더 검토가 같은 것을 쓴다.**
  //
  // 예전엔 폴더 쪽이 `<span class="mono">major</span>` 맨 글자였다. 같은 심각도가
  // 한쪽에서는 색 채운 알약, 한쪽에서는 회색 소문자로 보여 두 화면이 다른 도구처럼
  // 읽혔다. 뱃지 함수(solidBadge)는 이미 있었는데 폴더 쪽만 안 쓰고 있었다.
  //
  // 미검토는 심각도가 아니다 — "문제를 찾았다"가 아니라 "검사를 못 했다"는 보고라
  // 색을 안 채우고 테두리만 있는 뱃지(badge)로 낸다. 채우면 지적으로 읽힌다.
  function sevBadge(f) {
    if (f.unreviewed) return badge(SEV.unknown, "미검토");
    var pal = SEV[f.sev] || SEV.unknown;
    // **뱃지 글자는 무엇이 잡았나(label)다.** `MAJOR` 만 줄줄이 뜨면 무엇을 봐야
    // 하는지 안 보이지만 `약어 목록 대조` · `파일명 규칙 검사` 는 바로 읽힌다.
    //
    // 색은 그대로 심각도다 — PDF 형광펜이 심각도 색으로 칠해지므로(pdfview.js
    // _SEV) 색까지 종류로 바꾸면 형광펜과 카드가 끊긴다. 종류는 아홉인데 구분되는
    // 반투명 색은 셋이 한계라 색으로는 못 가른다.
    //
    // 종류(kind)가 있으면 label 뒤에 붙인다 — `표현 점검 · 모순`. 표현 점검 하나가
    // 스물몇 건을 내는데 오타와 앞뒤 모순이 같은 뱃지를 달고 있었다. 갈리는 것은
    // 색뿐이었는데(주황=major 노랑=minor) 검토자가 그 뜻을 알 리 없다.
    //
    // label 이 없으면(옛 payload · 조립 계층이 안 찍은 지적) 심각도 이름으로
    // 되돌아간다 — 빈 뱃지를 내느니 예전 모습이 낫다.
    var text = f.label || pal.label || f.sev;
    if (f.kind) text += " · " + f.kind;
    // 재질의 왕복 끝에 근거를 찾은 지적(rescue). 근거는 원문 대조를 통과했지만
    // 한 번에 근거를 댄 지적과는 온 길이 다르다 — 출처를 숨기지 않는다. 심각도
    // 뱃지에 섞지 않고 미검토처럼 테두리 뱃지를 **나란히** 단다. 색을 채우면
    // 또 하나의 지적으로 읽힌다.
    if (f.rescued) return badge(pal, text) + badge(SEV.info, "근거 재확인됨");
    // **모양은 하나로 간다.** 색만 심각도를 말한다.
    //
    // 예전에는 색을 채운 알약이었는데, 노랑(minor)만 흰 글자 대비가 안 나와
    // 어두운 글자를 썼다 — 같은 굵기인데도 minor 만 굵어 보였다. 게다가 바로
    // 옆 `미검토` 는 연한 뱃지라 한 목록에 두 모양이 섞여 있었다.
    //
    // 연한 뱃지는 대비도 낫다: 채운 알약은 흰 글자로 major 3.56:1 · minor 1.92:1
    // 이었고, 이쪽은 4.58~9.03:1 이다(작은 글자라 4.5:1 을 넘겨야 한다).
    return badge(pal, text);
  }

  // title 을 안 주면 형광펜 번호로 본다(단일 검토의 기본 용도). 폴더 검토는 같은
  // 칩에 기준 번호를 담으므로 제목을 갈아 끼운다 — 안 그러면 "표시본 PDF의
  // W-작성일자-순서번 형광펜" 같은 툴팁이 뜬다.
  function numberChip(no, title, id, showAll) {
    if (!no) return "";
    var one = function (n, act) {
      // 모양은 index.html 의 .nchip 이 갖는다 — 인라인로 두면 :hover 를 못 써서
      // 누를 수 있다는 것이 보이지 않았다(실제로 몰라서 못 눌렀다).
      return '<span class="nchip"' + act + ' title="' +
        esc(title || (act ? n + "번 형광펜 위치로 이동" : "표시본 PDF의 " + n + "번 형광펜")) +
        '">' + esc(n) + '</span>';
    };
    // 한 지적이 여러 곳을 물면 번호도 여럿이다("3, 4, 5, 6"). **칩을 쪼개 각각
    // 누를 수 있게 한다** — 예전에는 한 덩어리라 카드를 눌러도 늘 첫 번호(3번)로만
    // 갔고, 나머지 셋으로 갈 길이 없었다.
    //
    // 카드를 다시 누르는 것으로는 못 돈다 — 그건 선택 해제다(select 는 토글).
    var parts = id ? String(no).split(",").map(function (n) { return n.trim(); }) : [];
    if (parts.length < 2) {
      return one(no, id ? ' data-act="goMark" data-arg="' + esc(id + "|" + no) + '"' : "");
    }
    // 접힌 카드에서는 앞 몇 개 + "+N" 으로 줄인다. 한 지적이 17곳을 물면
    // (실측: §21.1 수일치 지적) 칩 18개가 카드 폭을 뚫고 나가 헤더가 깨졌다.
    // 펼치면(showAll) 전부 — 컨테이너가 flex-wrap 이라 줄바꿈으로 들어간다.
    var MAX = 6;
    var shown = (showAll || parts.length <= MAX) ? parts : parts.slice(0, MAX - 1);
    var html = shown.map(function (n) {
      return one(n, ' data-act="goMark" data-arg="' + esc(id + "|" + n) + '"');
    }).join("");
    if (shown.length < parts.length) {
      html += '<span class="nchip" title="카드를 펼치면 번호 전체가 보입니다">+' +
        (parts.length - shown.length) + '</span>';
    }
    return html;
  }

  // 지적 카드의 겉·속을 따로 만든다. 카드를 고를 때 화면 전체를 다시 그리면
  // PDF iframe이 DOM에서 떨어졌다 붙으며 리로드된다(=새로고침처럼 보인다).
  // 그래서 app.js의 select는 이 둘로 해당 카드만 갈아끼운다 — 뷰어는 안 건드린다.
  // 모양은 index.html 의 .fcard 규칙이 갖는다 — 인라인으로 두면 :hover 가
  // 인라인에 밀려 안 먹는다. 여기선 상태(펼침)만 클래스로 얹는다.
  function findingCardClass(f) {
    return "fcard" + (f.open ? " on" : "");
  }

  function lineageHtml(L, cand) {
    if (!L) return '';
    // 어느 검토와 대조했는지. 두 번 고친 자리다 — 처음엔 강조 테두리 +
    // "이어서 반영 확인?" 물음이라 눌러야 하는 것처럼 보였고(누를 것이 없다 —
    // 서버가 이미 대조를 끝낸 뒤다), 평서문 한 줄로 바꾸니 이번엔 맨몸 글자가
    // 허공에 떠 보였다. 이 앱에서 문서는 늘 아이콘 + 파일명이다(뷰어 헤더·
    // 업로드·이력) — 대조 대상도 문서니 같은 관용구로, 아래 안내 상자의
    // 머리행으로 넣는다. 알림 셋(대조 대상·요약·안내)이 상자 하나로 모인다.
    var srcRow = cand
      ? '<div style="display:flex;align-items:center;gap:6px;padding-bottom:8px;' +
          'margin-bottom:8px;border-bottom:1px solid var(--line-2);">' +
          '<span style="flex:none;display:flex;">' + docShapeIcon(cand.title, 16, "accent") + '</span>' +
          '<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
            'font-size:12px;font-weight:600;color:var(--text);">' + esc(cand.title) + '</span>' +
          (cand.at ? '<span class="mono" style="flex:none;font-size:11px;color:var(--text-3);">' +
            esc(cand.at) + '</span>' : '') +
        '</div>'
      : '';
    var items = L.items.map(function (it) {
      // 지적 카드와 같은 관용구(fcard)를 쓴다. 두 탭을 오갈 때 눈이 같은 곳을 보게 —
      // 목록형으로 두었더니 나란히 놓았을 때 딴 화면처럼 보였다.
      //
      // 누르면 문서의 그 자리로 간다. 짝이 없으면(`안 보임`) 갈 데가 없어 안 건다.
      return '<div' + (it.matchId ? ' data-act="select" data-arg="' + esc(it.matchId) + '" tabindex="0" role="button"' : '') +
        ' class="fcard"' + (it.matchId ? '' : ' style="cursor:default;"') + '>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
          '<span style="display:flex;align-items:center;gap:4px;">' + numberChip(it.no, null, it.matchId) +
            // **기계가 본 것.** 판정의 근거다 — `안 보임` 은 "고쳐졌다"가 아니라
            // "같은 인용을 못 찾았다"일 뿐이라, 검토자가 그 차이를 알아야 한다.
            '<span style="flex:none;font-size:11px;font-weight:600;padding:2px 8px;' +
              'border-radius:var(--r-sm);background:var(--neutral-weak);color:var(--text-3);' +
              'white-space:nowrap;">' + esc(it.auto) + '</span>' +
            // 기계가 정한 것이 아니라 **지난번에 검토자가** 내린 판정이다.
            (it.carried ? '<span style="flex:none;font-size:11px;font-weight:600;' +
              'padding:2px 8px;border-radius:var(--r-sm);background:var(--accent-weak);' +
              'color:var(--accent-ink);">지난 판정</span>' : '') +
          '</span>' +
          '<span style="font-variant-numeric:tabular-nums;font-size:11px;font-weight:600;' +
            'color:var(--text-3);">' + esc(it.loc) + '</span>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end;gap:12px;">' +
          '<span style="flex:1;min-width:0;">' +
            '<div style="font-size:14px;line-height:1.6;color:var(--text);font-weight:600;">' +
              esc(it.message) + '</div>' +
            // 짝이 없으면 이번 문서에 가리킬 자리가 없다. 지난번 인용을 보여줘
            // 검토자가 직접 찾게 한다 — "어딘지 모르겠다"가 그래서 나온다.
            (!it.matchId && it.quote
              ? '<div style="margin-top:6px;font-size:11px;color:var(--text-3);' +
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">지난 근거: ' +
                esc(it.quote) + '</div>' : '') +
          '</span>' +
          // 앱이 그리는 셀렉트를 쓴다. 네이티브 <select> 는 펼친 목록을 OS 가
          // 그려서 화면의 다른 목록과 안 어울린다(index.html 의 .sel 참고).
          // id 앞머리 `lnv-` 로 app.js 의 selPick 이 판정 저장으로 잇는다.
          selectField('lnv-' + it.idx, '판정', L.statusOpts,
                      { value: it.status, cls: 'sel-sm' }) +
        '</div>' +
      '</div>';
    }).join('');
    // 신규 지적 목록은 여기서 그리지 않는다. 같은 지적이 아래 카드에도 나와
    // 위아래로 두 번 보였다 — 카드의 `신규` 뱃지가 그 자리를 대신한다.
    // 이 화면을 **어떻게 봐야 하는지**를 화면이 말해야 한다. 어휘를 아무리 골라도
    // 처음 보는 사람은 `그대로 있음`·`안 보임` 이 무엇의 결과인지 모른다 —
    // 기계가 본 것인지 자기가 해야 할 일인지부터 안 갈린다.
    // 용어는 **카드에 실제로 붙는 상태 칩 그대로** 보여주고 옆에 뜻을 단다.
    // 산문에 볼드를 섞어 쓰던 이전 판은 강조 볼드와 용어 볼드가 구별되지 않아
    // "볼드가 무슨 뜻인지"부터 헷갈렸다 — 칩과 같은 생김새면 설명이 필요 없다.
    // 볼드는 딱 하나, 검토자가 바꿔야 할 값(반영됨)에만 남긴다.
    var term = function (t, desc) {
      return '<div style="display:flex;align-items:flex-start;gap:8px;">' +
        '<span style="flex:none;font-size:11px;font-weight:600;padding:2px 8px;' +
          'border-radius:var(--r-sm);background:var(--neutral-weak);color:var(--text-3);' +
          'white-space:nowrap;">' + t + '</span>' +
        '<span style="padding-top:2px;min-width:0;">' + desc + '</span>' +
      '</div>';
    };
    // 상자는 이 패널의 노트 관용구(--bg 면 + --line 테두리 — issuesShell 의
    // annot 노트와 동일)를 쓴다. --neutral-weak 채움이던 때는 안에 넣을 상태
    // 칩(같은 --neutral-weak)이 바닥과 한 색이 돼 사라졌다.
    var legend = '<div style="font-size:11px;line-height:1.6;color:var(--text-3);' +
      'margin-bottom:10px;padding:10px 12px;background:var(--bg);' +
      'border:1px solid var(--line);border-radius:var(--r-sm);">' +
      srcRow +
      '<div style="margin-bottom:8px;color:var(--text-2);">' +
        (cand ? '지난 검토의 지적을 이번 문서에서 다시 찾아본 결과입니다. '
              : '지난 지적을 이번 문서에서 다시 찾아본 결과입니다. ') +
        '고쳐졌다고 단정하지는 않으니 직접 확인하고, 확인했으면 판정을 ' +
        '<b>반영됨</b>으로 바꿔 주세요. 확인 전까지 판정은 모두 미반영입니다.</div>' +
      '<div style="display:flex;flex-direction:column;gap:6px;">' +
        term('그대로 있음', '지적된 문장이 문서에 아직 그대로 있습니다') +
        term('안 보임', '같은 문장을 못 찾았습니다 — 고친 건지 표현만 바뀐 건지는 직접 봐야 합니다') +
        term('판단 못 함', '이번 검사가 불완전해서 알 수 없습니다') +
        term('해당없음', '지난 검토에서 내린 판정입니다 — 다음 검토에도 이어집니다') +
      '</div>' +
      '</div>';
    return '<div id="lineagePanel" style="margin-bottom:16px;">' +
      '<div id="lineageSummary" style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px;">' + esc(lineageSummaryText(L)) + '</div>' +
      legend + items + '</div>';
  }

  // 카드 안의 원문 인용 줄. verify_quotes 를 통과한 근거만 여기 온다 —
  // 규칙 체커는 근거를 안 달아 빈다(그때는 줄 자체가 없다).
  function evidenceQuotes(f, v) {
    var evs = f.evidence || [];
    if (!evs.length) return "";
    if (!f.open) {
      // 접힌 카드는 한 줄로 자른다. 목록에서는 "어느 문장인지"의 첫 조각이면
      // 충분하고, 전문은 펼치거나 문서에서 본다.
      return '<div style="margin-top:8px;font-size:12px;line-height:1.6;color:var(--text-2);' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
        '<mark class="sev-' + esc(f.sev) + '">' + esc(evs[0].quote || "") + '</mark>' +
        (evs.length > 1 ? ' <span style="font-size:11px;color:var(--text-3);">외 ' + (evs.length - 1) + '곳</span>' : '') +
      '</div>';
    }
    return evs.map(function (e, i) {
      // 이 인용의 형광펜 번호. 같은 절의 인용이 둘이면("운영권 조정"/"운영권조정")
      // 번호가 없을 때 둘째 인용이 문서 어디인지 알 길이 없었다 — 눌러서 간다.
      var no = (f.quoteNos || [])[i];
      var chip = no
        ? '<span class="nchip" data-act="goMark" data-arg="' + esc(f.id + "|" + no) +
          '" title="' + no + '번 형광펜 위치로 이동" style="margin-right:6px;">' + no + '</span>'
        : '';
      return '<div style="margin-top:8px;font-size:12px;line-height:1.6;color:var(--text-2);">' +
        chip +
        '<mark class="sev-' + esc(f.sev) + '">' + esc(e.quote || "") + '</mark>' +
        (e.section ? ' <span class="mono" style="font-size:11px;color:var(--text-3);">§' + esc(e.section) + '</span>' : '') +
        fixLine(f, v, i) +
      '</div>';
    }).join("");
  }

  // 인용 하나의 수정안. **인용마다 따로 만든다.** 예전엔 지적당 하나였고 대상은
  // 언제나 첫 인용이었다 — 지적 하나가 문장 여럿을 근거로 들면(실측: 수일치 오류
  // 지적 하나에 인용 18개) 나머지 문장은 검토자가 손으로 옮겨 적어야 했다.
  //
  // 겸해서 이 줄이 **잘못 끌려온 인용을 드러내는 자리**다. 인용이 문서에 실재하는지는
  // 코드가 대조하지만(verify_quotes) 그 인용에 지적이 해당하는지는 대조할 방법이
  // 없다. 모델이 "고칠 곳이 없다"고 답하면 그 사실을 그대로 보여준다 — 화면이
  // 대신 판정하지 않는다.
  function fixLine(f, v, i) {
    var key = f.id + "|" + i;
    var fx = (v.fixes || {})[key];
    var out = "";
    if (fx && fx.busy) {
      out = '<div style="font-size:12px;color:var(--text-3);display:flex;align-items:center;gap:6px;">' +
        '<span style="display:inline-block;animation:spin 1s linear infinite;">' + ICONS.refresh + '</span>수정안을 만드는 중…</div>';
    } else if (fx && fx.ok) {
      // 갈아끼우는 건 사람이 한다(원본이 PDF·HWPX라 도구가 직접 못 고친다) —
      // 그래서 복사 버튼까지가 이 기능의 끝이다.
      out = '<div class="eyebrow" style="color:var(--accent-ink);margin-bottom:4px;">수정안</div>' +
        '<div style="font-size:12px;line-height:1.6;color:var(--text);font-weight:600;background:var(--accent-weak);padding:8px 10px;border-radius:var(--r-sm);">' + esc(fx.revised) + '</div>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:6px;">' +
        '<button data-act="copyFix" data-arg="' + esc(key) + '" class="linkbtn" style="font-size:11px;">수정안 복사</button></div>';
    } else if (fx) {
      // 못 만든 경우. 이유를 그대로 보여준다 — 조용히 비워두면 버튼이 고장난
      // 줄 안다.
      out = '<div style="font-size:12px;line-height:1.6;color:var(--text-2);">' + esc(fx.reason) + '</div>';
    }
    var btn = (fx && fx.busy) ? "" :
      '<button data-act="suggestFix" data-arg="' + esc(key) + '" class="linkbtn" ' +
      'style="font-size:11px;">' + (fx ? "수정안 다시 만들기 →" : "수정안 만들기 →") + '</button>';
    return '<div style="margin:6px 0 2px 0;padding-left:10px;border-left:1px solid var(--line-2);">' +
      out + btn + '</div>';
  }

  // 복원 지적의 "재확인 여정" — 처음 인용(대조 실패) → 검색 → 확정 근거.
  // 에이전트가 도구를 들고 문서를 뒤진 과정이다. 결과만 남기면 그 과정이
  // 사라져, 복원 지적이 어디서 왔는지 검토자가 알 길이 없다. 펼친 카드에서만
  // 보인다 — 목록에서는 "근거 재확인됨" 뱃지가 그 역할을 한다.
  function rescueJourney(f) {
    if (!f.open || !f.rescued || !f.rescueTrace) return "";
    var t = f.rescueTrace;
    var rows = [];
    (t.failed_quotes || []).forEach(function (q) {
      rows.push('처음 인용 <span style="text-decoration:line-through;">“' + esc(q) + '”</span> — 문서에 없음');
    });
    (t.searched || []).forEach(function (s) {
      rows.push('문서 검색: <span class="mono">' + esc(s) + '</span>');
    });
    rows.push('다시 인용한 근거가 원문 대조를 통과 — 위 형광펜 문장');
    return '<div style="margin-top:8px;padding:8px 10px;border:1px solid var(--line-2);' +
      'border-radius:var(--r-sm);font-size:11px;line-height:1.6;color:var(--text-3);">' +
      '<div style="font-weight:600;margin-bottom:2px;">근거 재확인 여정</div>' +
      rows.map(function (r) { return '<div>→ ' + r + '</div>'; }).join("") +
    '</div>';
  }

  function findingCardInner(f, v) {
    return '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
        // 뱃지는 sevBadge 하나로 낸다. 여기서 solidBadge 를 따로 부르고 있어서
        // 단일 검토만 `MAJOR` 글자가 남아 있었다 — 폴더 검토는 종류 이름인데
        // 같은 카드 관용구가 화면마다 다른 말을 했다.
        '<span style="display:flex;flex-wrap:wrap;align-items:center;gap:4px;">' + numberChip(f.no, null, f.id, f.open) +
        sevBadge(f) +
        // 재검토에서 이번에만 나온 지적. 반영 확인 패널이 같은 목록을 한 번 더
        // 그리던 것을 이 표시로 대신한다.
        (f.isNew ? '<span style="flex:none;font-size:11px;font-weight:600;padding:2px 8px;' +
          'border-radius:var(--r-sm);background:var(--accent-weak);color:var(--accent-ink);">신규</span>' : '') +
        // 검토자가 반영 확인에서 "우리 문서엔 해당 안 된다"고 정리한 지적이다.
        (f.na ? '<span style="flex:none;font-size:11px;font-weight:600;padding:2px 8px;' +
          'border-radius:var(--r-sm);background:var(--neutral-weak);color:var(--text-3);">해당없음</span>' : '') +
        '</span>' +
        '<span style="font-variant-numeric:tabular-nums;font-size:11px;font-weight:600;color:var(--text-3);">' + esc(f.loc) + '</span>' +
      '</div>' +
      // 모양은 CSS 의 .fmsg 가 정한다 — 접힘/펼침에 따라 줄 수와 두께가 달라지는데,
      // 인라인으로 두면 그 규칙이 인라인에 밀려 안 먹는다(.fcard 주석과 같은 이유).
      //
      // 문장마다 줄을 바꾼다. 한두 문장짜리(정상)에는 티가 안 나고, 길게 나온
      // 것에서만 벽이 목록으로 바뀐다. 자르는 규칙은 helpers.sentences 에 있다 —
      // `500.00 GB` 같은 마침표를 문장 끝으로 오해하지 않는 게 핵심이다.
      '<div class="fmsg">' + H.sentences(f.message).map(esc).join("<br>") + '</div>' +
      // **원문 근거를 카드가 직접 보여준다.** 인용 대조를 통과한 문장(이 제품의
      // 계약)이 문서 안에만 칠해져 있어서, 카드에서는 "무엇이 문제인지"만 읽고
      // "어느 문장이 문제인지"는 문서로 눈을 옮겨야 했다. 문서·내보내기와 같은
      // mark.sev-* 형광펜을 그대로 쓴다 — 왼쪽 문서와 오른쪽 카드가 같은 색으로
      // 같은 문장을 가리킨다. 접힌 카드는 첫 인용 한 줄만, 펼치면 전부.
      evidenceQuotes(f, v) +
      rescueJourney(f) +
      (f.criteria ? '<div style="margin-top:6px;font-size:11px;font-weight:600;color:var(--text-3);">기준: ' + esc(f.criteria) + '</div>' : '') +
      (f.open && f.suggestion ? expand(v.anim.openedId === f.id, suggestBox(f)) : '');
  }

  // 카드 겉껍질(data-act·data-card 속성 포함)을 만드는 **유일한** 자리. 평면
  // 지적 목록과 체크리스트 항목별 목록 둘 다 이 함수로 카드를 그린다 —
  // 각자 따로 카드 껍질을 찍으면 부분 갱신(app.js의 select)이 찾는 앵커가
  // 두 곳으로 갈라져, 한쪽 모양만 고치고 잊는 사고가 난다
  // (test_card_markup_is_shared_between_full_render_and_partial_update 가
  // 그 속성이 소스에 한 번만 나오는지를 지킨다).
  function findingCardHtml(f, v, extraStyle) {
    // tabindex/role: 카드는 div 라 포커스를 못 받는다 — 클릭 위임(app.js)이
    // 키보드에선 Enter/Space 브리지로 이어지므로, 포커스만 받게 하면 된다.
    return '<div data-act="select" data-arg="' + f.id + '" data-card="' + f.id +
      '" tabindex="0" role="button" class="' + findingCardClass(f) + '" style="' + (extraStyle || "") + '">' +
      findingCardInner(f, v) + '</div>';
  }

  // 펼친 카드 아래쪽. 체커가 단 지침이다 — "무엇을 확인하라"는 말이지
  // "이 문장을 이렇게 고쳐라"가 아니다. 구체적 수정안은 인용마다 붙는다(fixLine):
  // 지적 하나가 여러 문장을 근거로 들 때 첫 문장 하나만 고쳐 줄 수는 없다.
  function suggestBox(f) {
    if (!f.suggestion) return "";
    return '<div style="margin-top:14px;padding:14px;background:var(--panel);border:1px solid var(--line-2);border-radius:var(--r-sm);animation:fadeIn .2s ease-out;">' +
      '<div class="eyebrow" style="color:var(--accent-ink);margin-bottom:8px;">검토 지침</div>' +
      '<div style="font-size:13px;color:var(--text-2);line-height:1.6;">' + esc(f.suggestion) + '</div>' +
    '</div>';
  }

  // 오른쪽 패널 접기/펼치기 아이콘(Lucide panel-right-close/open). 홑화살(›)보다
  // "패널을 닫는다"는 직관이 커 접힘↔펼침이 짝으로 읽힌다.
  var ICON_PANEL_CLOSE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/><path d="m8 9 3 3-3 3"/></svg>';
  var ICON_PANEL_OPEN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/><path d="m10 15-3-3 3-3"/></svg>';

  // 범례 한 줄: 색 점 + 이름 + 한 줄 설명.
  function legendRow(dotColor, label, desc) {
    return '<div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:10px;">' +
        '<span style="flex:none;width:8px;height:8px;border-radius:50%;background:' + dotColor + ';margin-top:6px;"></span>' +
        '<div>' +
          '<div style="font-size:13px;font-weight:600;color:var(--text);">' + esc(label) + '</div>' +
          '<div style="font-size:12px;color:var(--text-3);line-height:1.6;">' + esc(desc) + '</div>' +
        '</div>' +
      '</div>';
  }
  function card(inner, pad) {
    return '<div style="background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);padding:' + (pad || "20px") + ';">' + inner + '</div>';
  }
  // 뒤로가기 링크. 화면마다 붙여넣지 않는다 — 문구도 간격도 한 곳에서 정한다.
  // "목록으로 돌아가기" 맞은편. 홈을 거쳐 돌아오는 길은 검토가 끝난 화면을
  // 다시 보여줄 뿐이라(screen이 results에 머문다), 다음 문서로 가려면 별도의
  // 길이 필요하다.
  //
  // 아이콘은 문서+플러스다. 새로고침 화살표를 쓰면 "같은 문서를 다시 돌린다"로
  // 읽히는데, 이건 다른 문서를 새로 올리는 길이다.
  var ICON_DOC_PLUS = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h6"/><polyline points="14 2 14 8 20 8"/><line x1="18" y1="14" x2="18" y2="20"/><line x1="15" y1="17" x2="21" y2="17"/></svg>';

  function newReviewLink(which) {
    return '<div class="hover-accent" data-act="newReview" data-arg="' + (which || "single") + '" tabindex="0" role="button" ' +
      'title="다른 문서를 새로 올려 검토합니다" ' +
      'style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;' +
      'color:var(--text-3);cursor:pointer;padding:8px;">' + ICON_DOC_PLUS + ' 새 문서 검토</div>';
  }

  function backLink(mode, label) {
    return '<div class="hover-accent" data-act="setMode" data-arg="' + mode + '" tabindex="0" role="button" style="display:inline-flex;align-self:flex-start;align-items:center;gap:6px;font-size:14px;font-weight:600;color:var(--text-3);cursor:pointer;padding:8px;margin-left:-8px;">' + ICONS.arrowLeft + ' ' + esc(label) + '</div>';
  }

  // 페이지 헤더 — 화면당 하나, **카드 밖**에 선다. 제목은 브랜드 서체
  // (.headline = Gmarket Sans Bold), 밑에 한 줄 부제와 얇은 구분선.
  // 예전엔 제목이 큰 흰 카드 **안**에 있어서, 페이지 제목인지 카드 제목인지
  // 위계가 섞여 보였다 — 판단 규칙: 사이드바 메뉴에서 고른 화면의 이름이면
  // 페이지 제목(여기), 아니면 섹션·카드 제목(본문 서체 600~700)이다.
  function pageHead(title, sub) {
    return '<div style="padding-bottom:14px;border-bottom:1px solid var(--line);">' +
      '<h1 class="headline" style="margin:0;font-size:22px;font-weight:700;' +
        'letter-spacing:-.4px;color:var(--text);">' + esc(title) + '</h1>' +
      (sub ? '<p style="margin:6px 0 0;font-size:13px;color:var(--text-3);">' +
        esc(sub) + '</p>' : '') +
    '</div>';
  }
  // Drag-and-drop file picker. opts: { slot, file, nav? }. `file` is
  // {name,size} from state or null. Wired via data-drop / data-slot in boot().
  function dropzone(opts) {
    var f = opts.file, id = "file-" + opts.slot;
    var navAttr = opts.nav ? ' data-nav="' + opts.nav + '"' : "";
    var input = '<input id="' + id + '" type="file" data-slot="' + opts.slot + '"' + navAttr +
      ' accept=".md,.txt,.pdf,.hwpx,.docx" style="display:none;">';
    var big = !!opts.big;
    var body;
    if (f) {
      if (big) {
        body = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;padding:20px 0;">' +
          docShapeIcon(f.name, 52, 'accent') +
          '<div style="text-align:center;width:100%;">' +
            '<div style="font-weight:700;font-size:15px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%;margin:0 auto 6px;">' + esc(f.name) + '</div>' +
            '<div class="mono" style="font-size:13px;color:var(--text-3);">' + esc(fmtSize(f.size)) + '</div>' +
          '</div>' +
          '<div style="display:flex;gap:16px;align-items:center;margin-top:20px;">' +
            '<span style="display:flex;align-items:center;gap:4px;font-size:12px;font-weight:600;color:var(--accent-ink);background:var(--accent-weak);padding:6px 12px;border-radius:var(--r-xl);">' + ICONS.check + ' 첨부 완료</span>' +
            '<button class="btn btn-ghost btn-ghost-accent" data-act="clearFile" data-arg="' + opts.slot + '">제거</button>' +
          '</div>' +
        '</div>';
      } else {
        body = '<div style="display:flex;align-items:center;gap:16px;">' + docShapeIcon(f.name, 52, 'accent') +
          '<div style="min-width:0;flex:1;">' +
            '<div style="font-weight:700;font-size:15px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(f.name) + '</div>' +
            '<div class="mono" style="font-size:12px;color:var(--text-3);margin-top:4px;">' + esc(fmtSize(f.size)) + '</div>' +
          '</div>' +
          '<span style="flex:none;display:flex;align-items:center;gap:4px;font-size:12px;font-weight:600;color:var(--accent-ink);background:var(--accent-weak);padding:6px 12px;border-radius:var(--r-xl);">' + ICONS.check + ' 첨부 완료</span>' +
          '<button class="btn btn-ghost btn-ghost-accent" data-act="clearFile" data-arg="' + opts.slot + '" style="flex:none;">제거</button>' +
        '</div>';
      }
    } else {
      body = '<div data-act="openFile" data-arg="' + opts.slot + '" style="cursor:pointer;text-align:center;padding:' + (big ? "40px 20px" : "28px 20px") + ';">' +
        // 폴더 검토 드롭존의 폴더 그림과 같은 계열 — 연한 채움 위에 같은
        // 그라디언트로 윤곽선을 얹는다. 채움만 있으면(opacity .15) 형태가
        // 흐려서, 윤곽선이 있는 폴더 그림 옆에 두면 이쪽만 덜 그려진 것처럼 보인다.
        //
        // 그라디언트 id 에 slot 을 붙인다 — 비교 검토는 이 함수를 A·B 두 번
        // 부르므로 고정 id 를 쓰면 한 화면에 같은 id 가 둘이 된다. 지금은 두
        // 그라디언트 값이 같아 눈에 안 띄지만, 값이 갈리는 순간 조용히 한쪽을
        // 따라간다(id 는 문서에서 유일해야 한다).
        '<svg viewBox="0 0 100 100" style="width:52px;height:52px;margin-bottom:12px;"><defs><linearGradient id="upDocGrad-' + opts.slot + '" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="var(--accent-strong)" /><stop offset="100%" stop-color="var(--accent)" /></linearGradient></defs><path d="M24 18 L57 18 L76 37 L76 78 A 4 4 0 0 1 72 82 L28 82 A 4 4 0 0 1 24 78 Z" fill="url(#upDocGrad-' + opts.slot + ')" opacity="0.15" /><path d="M57 18 L57 32 A 5 5 0 0 0 62 37 L76 37 Z" fill="url(#upDocGrad-' + opts.slot + ')" opacity="0.25" /><path d="M24 18 L57 18 L76 37 L76 78 A 4 4 0 0 1 72 82 L28 82 A 4 4 0 0 1 24 78 Z" fill="none" stroke="url(#upDocGrad-' + opts.slot + ')" stroke-width="2" stroke-linejoin="round" opacity="0.40" /><path d="M57 18 L57 32 A 5 5 0 0 0 62 37 L76 37 Z" fill="none" stroke="url(#upDocGrad-' + opts.slot + ')" stroke-width="2" stroke-linejoin="round" opacity="0.40" /><path d="M50 44 L50 64 M41 53 L50 44 L59 53" stroke="var(--accent)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" /></svg>' +
        '<div style="font-size:15px;font-weight:700;color:var(--text);">파일을 끌어다 놓거나 <span style="color:var(--accent-ink);text-decoration:underline;">클릭하여 업로드</span></div>' +
        '<div style="font-size:13px;color:var(--text-3);margin-top:10px;">지원 형식: .hwpx, .docx, .pdf, .md, .txt (최대 30MB)</div>' +
      '</div>';
    }
    return '<div class="dropzone" data-drop="' + opts.slot + '"' + navAttr +
      // 점선은 전용 토큰(--line-dashed). --line-2 는 표·행을 가르는 경계선이라
      // 흰 배경에서 거의 안 보였고, 같은 앱의 폴더 검토·체크리스트 드롭존은
      // 처음부터 --line-dashed 를 써서 여기만 점선이 없는 것처럼 보였다.
      ' style="min-width:0;height:100%;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;overflow:hidden;border:2px dashed ' + (f ? "transparent" : "var(--line-dashed)") + ';border-radius:var(--r-lg);background:' + (f ? "var(--panel)" : "var(--bg)") + ';transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);' + (f ? "padding:20px;box-shadow:var(--sh-2);border:1px solid var(--line);" : "") + '" ' +
      // hover 채움은 --state-hover-brand. 중립 hover 면은 목록·메뉴용이라 이곳에
      // 쓰면 테두리만 신호를 지고 배경 반응은 약해진다. 점선 카드는 어느 표면에
      // 놓이든(흰 패널 위든 회색 페이지 위든)
      // 같은 값으로 읽히도록 검토 기준 카드와 맞춘다.
      //
      // ponytail: hover 를 인라인으로 칠한다 — 빈 상태의 바탕이 인라인이라
      // :hover 클래스가 못 이기고, 파일이 붙은 상태는 배경·테두리가 통째로
      // 달라 한 클래스로 안 묶인다. CSS 로 옮기려면 두 상태를 클래스로 가른다.
      'onmouseover="' + (!f ? "this.style.borderColor='var(--accent)';this.style.background='var(--state-hover-brand)'" : "") + '" onmouseout="' + (!f ? "this.style.borderColor='var(--line-dashed)';this.style.background='var(--bg)'" : "") + '">' +
      input + body + '</div>';
  }

  // ---- templates ----------------------------------------------------------
  // 결과 목록에 막 들어왔을 때만 카드가 순차적으로 올라온다 (필터/선택 렌더에는 안 붙는다).
  function enterAnim(v, i) {
    if (!v.anim.entered) return "";
    var delay = Math.max(0, Math.min(i * 30, 300) - v.anim.enterElapsed);
    return "animation:listIn .3s var(--ease-out) backwards;animation-delay:" + delay + "ms;";
  }
  // 상세 영역. 방금 펼친 카드만 높이 전환을 재생한다.
  function expand(justOpened, inner) {
    return '<div class="expand"' + (justOpened ? ' style="animation:expandIn .2s var(--ease-out);"' : "") +
      '><div>' + inner + '</div></div>';
  }

  function timelineItem(s) {
    return '<div style="display:flex;gap:16px;align-items:stretch;">' +
        '<div style="width:20px;flex:none;position:relative;display:flex;justify-content:center;">' +
          '<div style="position:absolute;top:0;bottom:0;width:2px;background:' + s.lineColor + ';"></div>' +
          '<div style="position:relative;z-index:1;margin-top:14px;width:20px;height:20px;border-radius:50%;background:' + s.dotBg + ';border:2px solid ' + s.dotBorder + ';display:flex;align-items:center;justify-content:center;color:' + s.dotFg + ';font-size:11px;font-weight:600;' + s.dotAnim + '">' + s.dotIcon + '</div>' +
        '</div>' +
        '<div style="flex:1;min-width:0;margin-bottom:10px;padding:16px;border:1px solid ' + s.bd + ';background:var(--panel);border-radius:var(--r-sm);opacity:' + s.op + ';transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);">' +
          '<div style="display:flex;align-items:baseline;gap:10px;">' +
            '<span style="font-size:14px;font-weight:600;flex:none;">' + esc(s.label) + '</span>' +
            '<span style="font-size:13px;color:var(--text-2);min-width:0;">' + esc(s.desc) + '</span>' +
            '<span class="mono eyebrow" style="margin-left:auto;flex:none;font-weight:600;color:' + s.statusColor + ';">' + s.statusLabel + '</span>' +
          '</div>' +
          (s.detail ? '<div class="mono" style="font-size:11px;color:' + s.detailColor + ';margin-top:6px;">' + esc(s.detail) + '</div>' : '') +
        '</div>' +
      '</div>';
  }

  function sidebar(v) {
    var items = v.features.map(function (f) {
      return '<div class="nav' + (f.on ? " on" : "") + '" data-act="setMode" data-arg="' + f.k + '">' +
        '<span style="width:18px;text-align:center;font-size:14px;">' + f.icon + '</span>' +
        '<span>' + esc(f.label) + '</span></div>';
    }).join("");
    // 브랜드 머리와 오른쪽 전역 헤더는 60px 한 줄로 정확히 잇는다. 별도의 선은
    // 두 경계를 겹쳐 보이게 하므로, 오른쪽은 app-sidebar의 옅은 음영으로만 나눈다.
    return '<aside class="app-sidebar" style="width:216px;flex:none;background:var(--panel);display:flex;flex-direction:column;">' +
      '<div class="sidebar-brand">' +
        // 마크 30 → 34. 워드마크를 키우자 글자 덩어리가 두 줄 합쳐 36.8px 이 되어
        // 마크가 혼자 작아 보였다. 34 면 덩어리 높이와 맞아 셋이 한 묶음으로 읽힌다.
        // (로그인 계열의 32px 마크는 그대로 둔다 — 거기는 22px 제목 한 줄이라 비율이 다르다.)
        '<div style="width:34px;height:34px;flex:none;display:flex;align-items:center;justify-content:center;color:var(--accent-ink);">' + ICONS.logoMark + '</div>' +
        // 워드마크 15 → 18. 15/11 은 네 단 차이뿐이라 제품 이름과 부제가 거의
        // 같은 무게로 붙어 있었다. 18 은 크기 사다리의 바로 다음 칸이다(15 다음이
        // 18 · 16·17 은 없다 — index.html 서체 주석).
        // 부제는 11 에 둔다. 더 줄여 달라는 요구였지만 11 이 사다리의 바닥이고,
        // --text-3 로 이미 5.38:1 이라 여기서 더 내리면 대비가 기준에 걸린다.
        // 위계는 부제를 깎아서가 아니라 이름을 키워서 벌린다(차이 4 → 7).
        '<div style="line-height:1.2;min-width:0;">' +
          '<div class="brand-wordmark" style="font-size:18px;">Doc<span style="color:var(--accent-ink);">Suree</span></div>' +
          '<div style="margin-top:2px;font-size:11px;font-weight:500;color:var(--text-3);">문서검토 agent 서비스</div>' +
        '</div>' +
      '</div>' +
      '<div style="padding:12px;display:flex;flex-direction:column;gap:2px;">' + items + '</div>' +
      // margin-top:auto 를 구분선이 지므로 아래 구획 전체가 바닥에 붙는다.
      '<div style="margin-top:auto;height:1px;margin-left:16px;margin-right:16px;flex:none;background:var(--line);"></div>' +
      '<div style="padding:16px 20px;display:flex;flex-direction:column;gap:12px;">' +
        (teamLabel(state.user && state.user.team) ? 
          '<div style="margin-left:-4px;margin-right:-4px;padding:10px 12px;background:var(--bg);border:1px solid var(--line);border-radius:var(--r-md);display:flex;flex-direction:column;gap:4px;box-shadow:inset 0 2px 4px rgba(0,0,0,0.02);">' +
            '<div style="font-size:11px;font-weight:600;color:var(--text-3);display:flex;align-items:center;gap:4px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>소속 팀</div>' +
            '<div style="font-size:13px;font-weight:600;color:var(--text);">' + esc(teamLabel(state.user.team)) + '</div>' +
          '</div>' 
        : '') +
        '<div class="nav" style="margin-left:-10px;margin-right:-10px;color:var(--text-2);cursor:pointer;"><span style="width:18px;text-align:center;font-size:14px;">' + ICONS.search + '</span><span style="font-size:13px;">도움말 및 지원</span></div>' +
      '</div>' +
    '</aside>';
  }

  // ---- 검색 --------------------------------------------------------------
  // 뒤지는 것은 **이미 받아 둔 목록** 둘뿐이다: 검토 기록(제목)과 등록된
  // 체크리스트(이름). 서버에 새로 물을 것이 없어서 색인도 엔드포인트도 없다.
  //
  // 공백을 다 지우고 맞춘다. 한글은 "사업 계획서"와 "사업계획서"가 같은 말인데
  // 띄어쓰기만 다른 경우가 흔해서, 공백을 남기면 사람이 친 대로만 걸린다.
  function searchNorm(s) {
    return String(s == null ? "" : s).replace(/\s+/g, "").toLowerCase();
  }

  // 한 줄. 왼쪽 아이콘 · 제목 · 그 아래 부연, 오른쪽 꼬리표.
  function searchRow(act, arg, iconHtml, title, sub, tail) {
    return '<div class="pick" data-act="' + act + '" data-arg="' + esc(arg) + '" ' +
      'style="padding:12px 14px;background:var(--panel);border:1px solid var(--line);' +
      'border-radius:var(--r-sm);display:flex;align-items:center;gap:12px;cursor:pointer;">' +
      '<span style="flex:none;display:flex;color:var(--text-2);">' + iconHtml + '</span>' +
      '<span style="flex:1;min-width:0;">' +
        '<span style="display:block;font-size:14px;font-weight:600;color:var(--text);' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(title) + '</span>' +
        (sub ? '<span style="display:block;font-size:11px;color:var(--text-3);' +
               'margin-top:2px;">' + esc(sub) + '</span>' : "") +
      '</span>' +
      (tail || "") +
    '</div>';
  }

  function searchGroup(label, rows, hidden) {
    if (!rows.length) return "";
    return '<div style="margin-bottom:18px;">' +
      '<div class="eyebrow" style="color:var(--text-3);margin-bottom:8px;">' + esc(label) + '</div>' +
      '<div style="display:flex;flex-direction:column;gap:6px;">' + rows.join("") + '</div>' +
      // **자른 건수를 드러낸다.** 조용히 8건만 보이면 "그게 전부"로 읽힌다.
      (hidden > 0
        ? '<div style="margin-top:8px;font-size:11px;color:var(--text-3);">' +
          '맞는 것이 ' + hidden + '건 더 있습니다 — 더 적어서 좁혀 보세요.</div>'
        : "") +
    '</div>';
  }

  var SEARCH_MAX = 8;

  function searchResultsHtml() {
    var q = searchNorm(state.searchQ);
    var hist = state.history || [];
    var lists = (state.clib && state.clib.list) || [];

    var histIcon = ICONS.fileText, listIcon = ICONS.list;
    var histRow = function (h) {
      var n = h.findings || 0;
      var tail = '<span style="flex:none;font-size:11px;font-weight:600;padding:4px 10px;' +
        'border-radius:999px;font-variant-numeric:tabular-nums;background:' +
        (n ? "var(--accent-weak)" : "var(--band-good-bg)") + ';color:' +
        (n ? "var(--accent-ink)" : "var(--band-good-fg)") + ';">' +
        (n ? n + "건" : "이상 없음") + '</span>';
      var kind = h.kind === "compare" ? "비교 검토"
               : h.kind === "case" ? "폴더 검토"
               : h.kind === "checklist" ? "체크리스트" : "단일 검토";
      return searchRow("openHistory", h.id, histIcon, h.title,
                       kind + " · " + ago(h.at), tail);
    };
    var listRow = function (c) {
      return searchRow("openChecklist", c.id, listIcon, c.name,
                       (c.item_count || 0) + "개 항목", "");
    };

    // 아직 안 친 상태. 빈 화면을 두느니 최근 것을 낸다 — 진짜 이력이라 지어낸
    // "최근 검색 항목"과 다르다(우리는 검색어를 저장하지 않는다).
    if (!q) {
      if (state.history === null) {
        return '<div style="padding:36px 0;text-align:center;font-size:13px;' +
          'color:var(--text-3);">검토 기록을 불러오는 중…</div>';
      }
      if (!hist.length && !lists.length) {
        return '<div style="padding:36px 0;text-align:center;font-size:13px;' +
          'color:var(--text-3);">아직 검토한 문서도 등록된 체크리스트도 없습니다.</div>';
      }
      return searchGroup("최근 검토", hist.slice(0, 5).map(histRow), 0);
    }

    var mh = hist.filter(function (h) { return searchNorm(h.title).indexOf(q) >= 0; });
    var ml = lists.filter(function (c) { return searchNorm(c.name).indexOf(q) >= 0; });

    if (!mh.length && !ml.length) {
      return '<div style="padding:36px 0;text-align:center;">' +
        '<div style="font-size:14px;font-weight:600;color:var(--text-2);">맞는 것이 없습니다</div>' +
        '<div style="margin-top:6px;font-size:12px;color:var(--text-3);line-height:1.6;">' +
          '검토 기록 ' + hist.length + '건과 체크리스트 ' + lists.length + '건의 ' +
          '이름을 찾았습니다.</div></div>';
    }
    return searchGroup("검토 기록", mh.slice(0, SEARCH_MAX).map(histRow),
                       mh.length - SEARCH_MAX) +
           searchGroup("체크리스트", ml.slice(0, SEARCH_MAX).map(listRow),
                       ml.length - SEARCH_MAX);
  }

  function header(v) {
    var leftContent = "";
    if (v.hasSteps) {
      leftContent = '<nav style="display:flex;gap:20px;align-items:center;">' + v.steps.map(function (s) {
        return '<span class="tab' + (s.on ? " on" : "") + '" data-act="' + s.act + '" data-arg="' + s.k + '" tabindex="0" role="button">' + esc(s.label) + '</span>';
      }).join("") + '</nav>';
    } else {
      // 날짜·아이콘의 회색은 토큰이어야 한다. #6B7280 을 박아 두면 다크에서
      // 어두운 헤더 위에 어두운 회색이 남아 안 읽힌다(--text-2 는 테마마다 뒤집힌다).
      leftContent = '<div style="color:var(--text-2);font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px;">' + ICONS.calendar + ' ' + new Date().toLocaleDateString('ko-KR', {year:'numeric', month:'long', day:'numeric', weekday:'long'}) + '</div>';
    }
    var uName = state.user ? state.user.name : "홍길동";
    var uEmail = state.user ? state.user.email : "user@surereview.ai";
    var dropMenu = "";
    if (state.profileMenuOpen) {
      // 소속 팀이 곧 검사 기준이다 — 로그인할 때 이 팀의 기준을 걸어놓고 돈다
      // (app.js doLogin). 그런데 정작 "내가 어느 팀으로 로그인해 있는지"를
      // 확인할 자리가 어디에도 없었다. 팀이 비어 있으면 팀 기준 수십 건이
      // 조용히 빠지므로, 비었다는 사실도 눈에 띄어야 한다.
      var uTeam = teamLabel(state.user && state.user.team);
      var teamRow = '<div style="padding:12px 16px;border-bottom:1px solid var(--line-2);display:flex;align-items:center;gap:8px;">' +
        '<span style="font-size:12px;color:var(--text-3);flex:none;">소속 팀</span>' +
        (uTeam
          ? '<span style="margin-left:auto;min-width:0;font-size:12px;font-weight:600;color:var(--accent-ink);background:var(--accent-weak);padding:4px 10px;border-radius:999px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(uTeam) + '</span>'
          // 칩을 안 씌운다 — 값이 있는 것처럼 보이면 안 된다.
          : '<span style="margin-left:auto;font-size:12px;color:var(--text-3);">미지정 · 팀 기준이 안 걸립니다</span>') +
      '</div>';
      dropMenu = '<div id="profileMenu" style="position:absolute;top:60px;right:48px;width:240px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);z-index:100;animation:fadeUp .15s ease-out forwards;overflow:hidden;">' +
        '<div style="padding:16px;border-bottom:1px solid var(--line-2);display:flex;align-items:center;gap:12px;">' +
          '<div class="profile-menu-avatar">' + esc(uName.charAt(0)) + '</div>' +
          '<div style="min-width:0;flex:1;">' +
            '<div style="font-size:14px;font-weight:700;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(uName) + '</div>' +
            '<div style="font-size:11px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(uEmail) + '</div>' +
          '</div>' +
        '</div>' +
        teamRow +
        '<div style="padding:8px;">' +
          // "요금제 관리 / Pro Plan" 은 뺐다 — 사내망 도구라 요금제가 없다.
          // 있지도 않은 것을 흉내내면 나머지 항목까지 목업으로 읽힌다.
          '<div class="pick" data-act="openProfileSettings" style="padding:10px 12px;font-size:13px;font-weight:500;color:var(--text-2);border-radius:var(--r-sm);cursor:pointer;" onmouseover="this.style.background=\'var(--bg)\'" onmouseout="this.style.background=\'var(--panel)\'">내 프로필 설정</div>' +
        '</div>' +
        '<div style="padding:8px;border-top:1px solid var(--line-2);">' +
          // setMode("login") 이 아니다 — 그건 화면만 바꾸고 앞사람의 검토 상태를 그대로 둔다.
          '<div class="pick" data-act="doLogout" style="padding:10px 12px;font-size:13px;font-weight:500;color:var(--sev-crit-fg);border-radius:var(--r-sm);cursor:pointer;display:flex;align-items:center;gap:8px;" onmouseover="this.style.background=\'rgba(239,68,68,0.05)\'" onmouseout="this.style.background=\'var(--panel)\'">' + ICONS.logout + ' 로그아웃</div>' +
        '</div>' +
      '</div>';
    }

    // 알림. **이 세션에서 앱이 직접 본 사건만** 담는다(api.js 의 notify).
    //
    // 예전에는 여기 목업 둘("결제 모듈 명세서의 정밀 검토가 완료되었습니다" ·
    // "김개발님이 보안 심의 요청서를 공유했습니다")이 박혀 있었고, 종에는 안 읽은
    // 알림이 있다는 빨간 점이 늘 떠 있었다. 그건 지웠다.
    //
    // 대신 진짜 사건이 있다: 검사를 걸어놓고 다른 화면으로 옮겨도 스트림은 계속
    // 돌아서(setMode 가 안 끊는다) **끝나도 그 화면에 없으면 조용히 끝난다.**
    // 그때만 쌓인다 — 진행 화면을 지켜본 사람에게는 안 쌓는다.
    //
    // 서버 알림함이 아니라는 것을 화면이 말해야 한다. 새로고침하면 비워지는데
    // 그걸 안 밝히면 "알림이 사라졌다"가 고장으로 읽힌다.
    var notis = state.notis || [];
    var dropNoti = "";
    if (state.notiOpen) {
      var notiRows = notis.length
        ? notis.map(function (n) {
            // 이력 id 가 없으면(저장 실패) 갈 데가 없다 — 누르는 시늉을 안 한다.
            var go = n.id ? ' data-act="openHistory" data-arg="' + esc(n.id) + '"' : '';
            return '<div' + go + ' style="padding:12px 16px;border-bottom:1px solid var(--line-2);' +
              (n.id ? 'cursor:pointer;' : '') + '">' +
              '<div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:4px;">' +
                '<span style="font-size:12px;font-weight:600;color:var(--accent-ink);">검토 완료</span>' +
                '<span style="flex:none;font-size:11px;color:var(--text-3);">' + esc(ago(n.at)) + '</span>' +
              '</div>' +
              '<div style="font-size:13px;color:var(--text);line-height:1.4;overflow:hidden;' +
                'text-overflow:ellipsis;white-space:nowrap;">' + esc(n.title) + '</div>' +
              (n.id ? '' : '<div style="margin-top:4px;font-size:11px;color:var(--text-3);">' +
                          '이력에 저장되지 않아 다시 열 수 없습니다</div>') +
            '</div>';
          }).join("")
        : '<div style="padding:28px 16px;text-align:center;font-size:13px;color:var(--text-3);">' +
          '아직 알릴 일이 없습니다.</div>';
      dropNoti = '<div id="notiMenu" style="position:absolute;top:52px;right:92px;width:320px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);z-index:100;animation:fadeUp .15s ease-out forwards;overflow:hidden;">' +
        '<div style="padding:14px 16px;border-bottom:1px solid var(--line-2);display:flex;justify-content:space-between;align-items:center;">' +
          '<div style="font-size:13px;font-weight:600;color:var(--text);">알림</div>' +
          '<div data-act="toggleNoti" class="hover-accent" style="color:var(--text-3);cursor:pointer;display:flex;font-size:15px;">' + ICONS.x + '</div>' +
        '</div>' +
        '<div data-scroll="notiList" style="max-height:300px;overflow-y:auto;">' + notiRows + '</div>' +
        '<div style="padding:10px 16px;border-top:1px solid var(--line-2);font-size:11px;' +
          'line-height:1.6;color:var(--text-3);">' +
          '검토를 걸어두고 다른 화면을 보는 동안 끝난 것만 모읍니다. ' +
          '새로고침하면 비워집니다.</div>' +
      '</div>';
    }

    // 탭을 닫으면 검사가 죽는 것은 그대로다(SSE). 그래서 이 목록은 세션을
    // 못 넘는다 — 작업 큐가 생기면 그때 서버 알림함으로 옮긴다(CLAUDE.md 성능 스펙).

    var searchModal = "";
    if (state.searchOpen) {
      searchModal = '<div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.2);backdrop-filter:blur(2px);z-index:999;display:flex;align-items:flex-start;justify-content:center;padding-top:12vh;animation:fadeIn .15s ease-out forwards;" onclick="if(event.target===this) document.getElementById(\'searchCloseBtn\').click();">' +
        '<div style="width:600px;max-width:92vw;background:var(--panel);border-radius:var(--r-lg);box-shadow:var(--sh-3);overflow:hidden;">' +
          '<div style="padding:16px 24px;border-bottom:1px solid var(--line-2);display:flex;align-items:center;gap:12px;">' +
            '<span style="font-size:20px;color:var(--text-2);">' + ICONS.search + '</span>' +
            // data-search-q 가 app.js 의 input 리스너와 짝이다. 그쪽은 render()를
            // 부르지 않고 결과 목록만 갈아끼운다 — 여기서 다시 그리면 입력 중
            // 포커스와 한글 조합이 날아간다(data-reason 입력과 같은 수법).
            '<input type="text" data-search-q autocomplete="off" ' +
              'placeholder="검토한 문서 이름 · 체크리스트 이름" ' +
              'value="' + esc(state.searchQ || "") + '" ' +
              'style="flex:1;border:none;outline:none;font-size:15px;color:var(--text);font-family:inherit;background:transparent;" autofocus>' +
            '<div id="searchCloseBtn" data-act="toggleSearch" style="font-size:18px;color:var(--text-3);cursor:pointer;display:flex;transition:color .2s;" onmouseover="this.style.color=\'var(--text)\'" onmouseout="this.style.color=\'var(--text-3)\'">' + ICONS.x + '</div>' +
          '</div>' +
          '<div id="searchResults" data-scroll="search" style="padding:20px 24px;background:var(--bg);min-height:200px;max-height:52vh;overflow-y:auto;">' +
            searchResultsHtml() +
          '</div>' +
          // **무엇을 안 뒤지는지도 말한다.** 문서 본문은 안 뒤진다 — 원본은 서버에
          // 있고 전문 검색 색인이 없다. 안 밝히면 "본문에 있는 말인데 안 나온다"를
          // 검색 고장으로 읽는다.
          '<div style="padding:10px 24px;border-top:1px solid var(--line-2);font-size:11px;' +
            'color:var(--text-3);line-height:1.6;">' +
            '검토 기록과 체크리스트의 <b style="font-weight:700;">이름</b>을 찾습니다. ' +
            '문서 본문은 찾지 않습니다.</div>' +
        '</div>' +
      '</div>';
    }

    var profileSettingsModal = "";
    if (state.profileSettingsOpen) {
      var sEmail = state.user ? state.user.email : "";
      var sName = state.user ? state.user.name : "";
      
      profileSettingsModal = '<div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.2);backdrop-filter:blur(2px);z-index:999;display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease-out forwards;" onclick="if(event.target===this) document.getElementById(\'closeProfileBtn\').click();">' +
        '<div style="width:400px;background:var(--panel);border-radius:var(--r-lg);box-shadow:var(--sh-3);padding:24px;">' +
          '<div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:20px;">내 프로필 설정</div>' +
          '<div style="margin-bottom:16px;">' +
            '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">이메일 (변경 불가)</div>' +
            '<input type="text" value="' + esc(sEmail) + '" disabled style="width:100%;padding:10px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--bg);color:var(--text-3);font-size:14px;box-sizing:border-box;">' +
          '</div>' +
          '<div style="margin-bottom:16px;">' +
            '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">이름</div>' +
            '<input id="psName" type="text" value="' + esc(sName) + '" style="width:100%;padding:10px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--panel);color:var(--text);font-size:14px;box-sizing:border-box;">' +
          '</div>' +
          '<div style="display:flex;gap:12px;margin-bottom:24px;">' +
            '<div style="flex:1;">' +
              '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">부서</div>' +
              selectField("psDept", "소속 부서", DEPTS) +
            '</div>' +
            '<div style="flex:1;" id="psTeamWrapper">' +
              '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">팀 (검사 기준)</div>' +
              selectField("psTeam", "소속 팀", teamOptions()) +
            '</div>' +
          '</div>' +
          '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
            '<button id="closeProfileBtn" class="btn" style="padding:10px 16px;border-radius:var(--r-sm);background:var(--bg);color:var(--text-2);font-weight:600;border:none;cursor:pointer;" data-act="closeProfileSettings">취소</button>' +
            '<button class="btn" style="padding:10px 16px;border-radius:var(--r-sm);background:var(--accent-surface);color:#fff;font-weight:600;border:none;cursor:pointer;" data-act="saveProfileSettings">저장</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    }

    return '<header class="app-header">' +
      leftContent +
      '<div style="display:flex;align-items:center;gap:18px;position:relative;">' +
        '<span data-act="toggleSearch" style="cursor:pointer;font-size:18px;color:' + (state.searchOpen ? 'var(--accent-ink)' : 'var(--text-2)') + ';display:flex;transition:color .2s;" onmouseover="this.style.color=\'var(--accent-ink)\'" onmouseout="this.style.color=\'' + (state.searchOpen ? 'var(--accent-ink)' : 'var(--text-2)') + '\'">' + ICONS.search + '</span>' +
        '<span data-act="toggleNoti" style="cursor:pointer;font-size:18px;color:' + (state.notiOpen ? 'var(--accent-ink)' : 'var(--text-2)') + ';display:flex;position:relative;transition:color .2s;" onmouseover="this.style.color=\'var(--accent-ink)\'" onmouseout="this.style.color=\'' + (state.notiOpen ? 'var(--accent-ink)' : 'var(--text-2)') + '\'">' +
          ICONS.bell +
          // 점은 **안 읽은 것이 있을 때만.** 늘 떠 있으면 아무 뜻도 없다.
          (notis.some(function (n) { return n.unread; })
            ? '<span style="position:absolute;top:0;right:2px;width:6px;height:6px;border-radius:50%;background:var(--sev-crit-fg);border:1px solid var(--bg);"></span>'
            : '') +
        '</span>' +
        '<div style="width:1px;height:24px;background:var(--line);"></div>' +
        // hover와 열린 상태는 index.html의 중립 클릭 면 계약이 함께 맡는다.
        // 인라인 이벤트로 색을 칠하면 사이드바·최근 검토와 규칙이 다시 갈라진다.
        '<div class="header-profile' + (state.profileMenuOpen ? ' on' : '') + '" data-act="toggleProfile">' +
          '<div class="header-avatar">' + esc(uName.charAt(0)) + '</div>' +
          '<span style="font-size:13px;font-weight:600;color:var(--text);user-select:none;">' + esc(uName) + '님 ▾</span>' +
        '</div>' +
      '</div>' +
      dropMenu + dropNoti + searchModal + profileSettingsModal +
    '</header>';
  }

  function singleUpload(v) {
    var steps = v.pipelinePreview.map(function (s, i) {
      var n = (i + 1 < 10 ? "0" : "") + (i + 1);
      return '<div style="display:flex;align-items:baseline;gap:10px;padding:8px 0;' + (i ? "border-top:1px solid var(--line-2);" : "") + '">' +
        '<span class="mono" style="font-size:11px;color:var(--accent-ink);width:16px;flex:none;">' + n + '</span>' +
        '<div style="min-width:0;">' +
          '<div style="font-size:13px;font-weight:500;">' + esc(s.label) + '</div>' +
          '<div style="font-size:11px;color:var(--text-3);margin-top:2px;line-height:1.4;">' + esc(s.desc) + '</div>' +
        '</div>' +
      '</div>';
    }).join("");
    // 자동 검토 기준(YAML: id_pattern·required_sections) picker 는 여기 없다 —
    // 그건 2문서 비교(compareSetup/checklistChips)에서만 쓴다. 단일 검토는
    // 이제 서버가 늘 돌리는 기본 검토(용어 일관성·미작성 TBD)와, 사용자가
    // 고르는 라이브러리 체크리스트("체크리스트로 평가") 두 갈래뿐이다.
    // 체크리스트를 평가 기준으로 고르는 카드. "안 씀"을 늘 첫 자리에 둬 고른
    // 적 없는 상태(reviewChecklistId === "")도 명시적으로 고를 수 있게 한다 —
    // 그래야 한 번 골랐다가 되돌리는 길이 생긴다.
    var reviewChips = [{ id: "", name: "안 씀", sel: v.reviewChecklistId === "", glyph: ICONS.x }]
      .concat(v.reviewChecklistCards).map(function (c) {
        var iconHtml = '<div style="width:24px;height:24px;border-radius:var(--r-sm);background:' + (c.sel ? 'var(--accent)' : 'var(--bg)') + ';color:' + (c.sel ? '#fff' : 'var(--text-3)') + ';display:flex;align-items:center;justify-content:center;flex:none;">' + (c.glyph || ICONS.list) + '</div>';
        return '<button data-act="pickReviewChecklist" data-arg="' + esc(c.id) + '" style="padding:6px 14px 6px 6px;display:inline-flex;align-items:center;gap:8px;font-size:13px;' +
          'font-weight:600;border-radius:var(--r-md);cursor:pointer;border:1px solid ' +
          (c.sel ? "var(--accent)" : "var(--line)") + ';background:' +
          (c.sel ? "var(--accent-weak)" : "var(--panel)") + ';color:var(--text);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);"' +
          ' onmouseover="if(!' + c.sel + ')this.style.background=\'var(--state-hover-neutral)\'"' +
          ' onmouseout="if(!' + c.sel + ')this.style.background=\'var(--panel)\'">' + 
          iconHtml + esc(c.name) +
          (c.count ? ' <span style="color:var(--text-3);font-weight:500;">' + esc(c.count) + '</span>' : '') +
          '</button>';
      }).join("");
    // 라이브러리에 등록한 게 없으면 그 사실을 말한다 — 빈 목록만 보이면 왜 없는지 모른다.
    var reviewChecklistEmpty = (v.reviewChecklistCards.length === 0)
      ? '<div style="font-size:12px;color:var(--text-3);margin-top:8px;">등록된 체크리스트가 없습니다. 파일을 올리거나 ' +
        '<span data-act="goPickChecklist" style="color:var(--accent-ink);cursor:pointer;text-decoration:underline;transition:opacity .15s;" onmouseover="this.style.opacity=\'0.65\'" onmouseout="this.style.opacity=\'1\'">검토 기준</span>에서 직접 작성할 수 있습니다.</div>'
      : '';
    return '<div class="page-shell page-shell-primary" data-scroll="setup">' +
      '<div class="page-container page-stack">' +
        errorBanner(v.serror) +
        pageHead("단일 문서 검토", "검토할 문서와 적용 기준을 선택합니다.") +
        '<div class="setup-panel">' +
          '<div style="display:flex;gap:24px;align-items:stretch;">' +
            '<div style="flex:1;min-width:0;">' + dropzone({ slot: "single", file: v.files.single, big: true }) + '</div>' +
            '<div style="width:320px;flex:none;background:var(--bg);border-radius:var(--r-lg);padding:20px 24px;border:1px solid var(--line);">' +
              '<div class="eyebrow" style="color:var(--text-2);margin-bottom:10px;font-size:13px;">AI 분석 파이프라인</div>' + steps +
            '</div>' +
          '</div>' +
          // 체크리스트는 별도 대형 카드가 아니라 이 작업의 보조 설정이다. 업로드와
          // 같은 무게로 경쟁하지 않게 패널 아래 컨텍스트 행으로 붙인다.
          '<div class="setup-context">' +
            '<div class="setup-context-row">' +
              '<div>' +
                '<h3 class="setup-section-title">추가 검토 기준</h3>' +
                '<p class="setup-section-sub">기본 검토는 항상 적용됩니다.</p>' +
              '</div>' +
              '<div style="min-width:0;">' +
                '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' + reviewChips +
                  '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="uploadChecklistForReview" style="white-space:nowrap;">+ 체크리스트 업로드</button>' +
                '</div>' +
                reviewChecklistEmpty +
              '</div>' +
              '<button class="btn btn-lg btn-primary" data-act="startReview" style="white-space:nowrap;">검토 시작 ' + ICONS.arrowRight + '</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // 진행 화면 머리말. 끝나면 같은 자리에서 완료를 말하고 넘어간다 — 화면을
  // 하나 더 띄우지 않는다. 0건일 때 "발견 0건"은 실패처럼 읽히므로 달리 말한다.
  function progressHead(done, count, running, pct, unreviewed) {
    if (!done) {
      return '<div class="review-running-head">' +
          '<span class="review-hourglass" aria-hidden="true">' + ICONS.hourglass + '</span>' +
          '<h2 style="margin:0;font-size:18px;font-weight:700;letter-spacing:-.01em;">' + esc(running[0]) + '</h2>' +
        '</div>' +
        '<p style="margin:6px 0 0;color:var(--text-3);font-size:13px;">' + esc(running[1]) +
        ' · <span style="color:var(--text-2);font-weight:600;">' + pct + '%</span></p>';
    }
    // 5분을 기다린 끝의 한 번이다. 여기가 이 화면에서 delight 를 써도 되는
    // 유일한 자리 — 검토당 한 번 돌고, 돌고 나면 결과 화면으로 넘어간다.
    return '<div class="review-complete-head" style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">' +
        '<div class="review-complete-check" style="width:32px;height:32px;border-radius:50%;background:var(--accent);color:white;display:flex;align-items:center;justify-content:center;box-shadow:0 0 16px var(--accent-weak);">' + ICONS.check + '</div>' +
        '<h2 style="margin:0;font-size:22px;font-weight:700;letter-spacing:-.01em;color:var(--text);">검토 완료</h2>' +
      '</div>' +
      '<p class="review-complete-copy" style="margin:0;color:var(--text-3);font-size:13px;padding-left:44px;">' +
        (count > 0
          ? '<span style="color:var(--text-2);font-weight:700;">지적 ' + count + '건</span>' +
            (unreviewed ? ' · 미검토 ' + unreviewed + '건' : '')
          : (unreviewed ? '지적 없음 · 일부 기준 미검토'
                        : '지적 없음 · 모든 자동 검사 완료')) +
        // "정리하고 있습니다…"였는데, 완료 뒤 진행 탭에 돌아와도 이 화면이 그대로
        // 살아 있다(done 유지) — 진행형 문구는 재방문에서 거짓말이 된다.
        ' · 결과는 지적사항 탭에 있습니다</p>';
  }

  // 작업 레인. 카운터 하나가 실제 규칙 검사 또는 LLM 호출 하나다.
  // 레인의 순수 지표(폭·카운터). laneMosaic 와 app.js 부분 갱신이 함께 쓴다 —
  // step 마다 폭·카운터만 제자리로 고쳐 shimmer·width 트랜지션을 안 끊는다.
  function laneMetrics(lane) {
    var pct = lane.total > 0 ? (lane.doneCount / lane.total * 100) : 0;
    var counter = lane.status === "empty" ? "항목 없음"
      : (lane.status === "wait" ? (lane.doneCount ? lane.doneCount + "/" + lane.total + " · 대기" : "대기")
      : (lane.status === "done" ? "완료" : lane.doneCount + "/" + lane.total + " · 검사 중"));
    return { pct: pct, counter: counter, status: lane.status };
  }

  // 레인 알맹이. app.js 의 updateLanesInPlace 가 상태 전환 때 겉wrapper 는 살려두고
  // 이것만 갈아끼운다 — wrapper 가 살아 있어야 opacity 전환(.5→1)이 실제로 돈다.
  // justChanged 는 "방금 이 상태가 됐다": 완료 표시가 그때만 튀어나온다. 정적
  // 렌더에서까지 튀면 다른 레인이 끝날 때마다 이미 끝난 것들이 같이 팔짝인다.
  function laneInner(lane, justChanged) {
    var m = laneMetrics(lane);
    var pct = m.pct, counter = m.counter;
    var head = lane.status === "run" ? "var(--accent-ink)" : (lane.status === "done" ? "var(--text-2)" : "var(--text-3)");
    var mark = lane.status === "done"
      ? '<span class="review-lane-check' + (justChanged ? " is-new" : "") + '" style="color:var(--neutral);display:flex;">' + ICONS.check + '</span>'
      : "";

    // data-lane-* 훅: app.js repaintProgress 가 이 안의 폭·카운터만 갈아끼운다.
    // 바 DOM 을 통째로 다시 만들면 shimmer 가 매 step 처음으로 튀어 흰빛이 번쩍인다.
    // 색은 지금 일하는 레인 하나만 쓴다. 완료된 레인은 체크 아이콘과 같은
    // neutral 회색으로 고정해 시선이 다음 활성 레인으로 넘어가게 한다. 대기 중
    // 일부 채워진 바도 회색이다 — 활성 상태가 아닌데 브랜드색이면 두 레인이
    // 동시에 도는 것처럼 보인다.
    var bar = '<div style="width:100%;height:6px;background:var(--line-2);border-radius:var(--r-sm);overflow:hidden;position:relative;">' +
        // 폭이 아니라 scaleX 로 찬다 — width 전환은 매 프레임 레이아웃을 다시
        // 계산한다(transform 은 GPU 에서 끝난다). 그라데이션·라운드는 100% 폭
        // 상자를 눌러 그리는 것이라 보이는 결과는 같다.
        '<div data-lane-fill class="review-lane-fill' + (justChanged && lane.status === "done" ? " is-completing" : "") + '" style="height:100%;width:100%;transform:scaleX(' + (pct / 100) + ');transform-origin:left;background:' + (lane.status === "run" ? "linear-gradient(90deg, var(--accent), var(--brand-highlight))" : "var(--neutral)") + ';border-radius:var(--r-sm);transition:transform .3s var(--ease-out);' + (lane.status === "run" ? "box-shadow:0 0 10px var(--accent-weak);" : "") + '"></div>' +
        (lane.status === "run" ? '<div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(90deg, transparent, var(--shimmer), transparent);transform:translateX(-100%);animation:shimmer 2s infinite;"></div>' : "") +
      '</div>';

    var scope = lane.scope
      ? '<span style="font-size:11px;color:' + (lane.limited ? "var(--sev-min-fg)" : "var(--text-3)") + ';">' +
        esc(lane.scope) + '</span>' : "";
    return '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:10px;">' +
        mark +
        // 색 전환은 안 건다 — 이 노드는 상태가 바뀔 때 통째로 새로 만들어져
        // transition 이 볼 이전 값이 없다. 살아남는 건 겉 wrapper 의 opacity 뿐이다.
        '<div style="min-width:0;display:flex;flex-direction:column;gap:4px;">' +
          '<span style="font-size:15px;font-weight:700;color:' + head + ';">' + esc(lane.label) + '</span>' +
          (lane.description ? '<span style="font-size:12px;color:var(--text-3);line-height:1.4;">' + esc(lane.description) + '</span>' : '') +
          scope +
        '</div>' +
        '<span data-lane-counter class="mono" style="margin-left:auto;padding-top:2px;font-size:12px;color:var(--text-3);white-space:nowrap;">' + esc(counter) + '</span>' +
      '</div>' +
      bar;
  }

  function laneMosaic(lane, i) {
    return '<div data-lane-idx="' + i + '" data-lane-status="' + lane.status + '" style="margin-bottom:26px;opacity:' +
      (lane.status === "wait" ? ".5" : "1") + ';transition:opacity .3s var(--ease-out);">' +
      laneInner(lane, false) +
    '</div>';
  }

  // 진행 중에는 잣대를 바꿀 수 없다. 이 패널은 선택기가 아니라 이번 요청에
  // 고정된 설정의 영수증이다. 바꾸는 UI를 두면 이미 시작된 서버 작업까지
  // 바뀌는 것처럼 보이므로, 적용 층과 실행 방식만 읽기 전용으로 보여준다.
  function criteriaPanel(review) {
    var s = state.server;
    var c = review.criteria || { layers: [], counts: {}, total: 0 };
    var row = function (k, v) {
      return '<div style="display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line-2);">' +
        '<span style="font-size:12px;font-weight:600;color:var(--text-2);flex:none;width:74px;">' + esc(k) + '</span>' +
        '<span style="font-size:12px;color:var(--text-2);line-height:1.4;word-break:break-word;">' + esc(v) + '</span>' +
      '</div>';
    };
    var layers = (c.layers || []).map(function (L) {
      return '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;">' +
        '<span style="font-size:11px;font-weight:700;padding:4px 6px;border-radius:var(--r-xl);' +
          'background:var(--accent-weak);color:var(--accent-ink);">' + esc(L.scope) + '</span>' +
        '<span style="flex:1;min-width:0;font-size:12px;color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(L.name) + '</span>' +
        '<span class="mono" style="font-size:11px;color:var(--text-3);">' + L.items.length + '개</span>' +
      '</div>';
    }).join("");
    var countLine = function (label, n) {
      return '<div style="display:flex;justify-content:space-between;gap:8px;padding:4px 0;font-size:12px;">' +
        '<span style="color:var(--text-3);">' + esc(label) + '</span>' +
        '<span class="mono" style="color:var(--text-2);">' + n + '개</span></div>';
    };
    var whole = (review.lanes || []).filter(function (l) { return l.label === "문서 전체 점검"; })[0];
    var criteriaBody = c.busy && !c.loaded
      ? '<div style="font-size:12px;color:var(--text-3);padding:8px 0;">적용 기준을 읽는 중…</div>'
      : (c.error
        ? '<div style="font-size:12px;color:var(--sev-crit-fg);padding:8px 0;line-height:1.4;">기준을 불러오지 못했습니다.<br>' + esc(c.error) + '</div>'
        : (layers || '<div style="font-size:12px;color:var(--text-3);padding:8px 0;">공통 또는 팀 기준이 없습니다.</div>'));

    return '<div style="width:286px;flex:none;background:var(--bg);' +
      'border:1px solid var(--line);border-radius:var(--r-md);padding:24px;">' +
      '<div style="color:var(--accent-ink);font-size:15px;line-height:1.4;margin-bottom:6px;font-weight:750;letter-spacing:-.01em;">이번 검토 설정</div>' +
      '<div style="font-size:11px;color:var(--text-3);line-height:1.6;margin-bottom:12px;">시작할 때 확정된 읽기 전용 설정입니다.</div>' +
      '<div style="padding:10px 0;border-top:1px solid var(--line-2);">' +
        '<div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px;">적용 기준</div>' + criteriaBody +
        ((!c.busy && !c.error && c.loaded) ?
          '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="openReviewCriteria" style="width:100%;justify-content:center;margin-top:8px;">적용 기준 ' + c.total + '개 보기</button>' : '') +
      '</div>' +
      '<div style="padding:10px 0;border-top:1px solid var(--line-2);">' +
        '<div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px;">검사 방식</div>' +
        countLine("규칙 자동 검사", c.counts.rule || 0) +
        countLine("표현 점검", c.counts.expression || 0) +
        countLine("문서 전체 점검", c.counts.whole || 0) +
        countLine("직접 확인", c.counts.manual || 0) +
        (c.counts.disabled ? countLine("AI 꺼짐 · 미검토", c.counts.disabled) : "") +
      '</div>' +
      row("모델", state.llm === "off" ? "사용 안 함" : shortModel(s && s.llm_model)) +
      row("이미지", state.llm !== "off" && s && s.vlm_enabled ? "해석 포함" : "해석 안 함") +
      (whole && whole.scope ? row("전체 범위", whole.scope) : "") +
      '<div style="font-size:11px;color:var(--text-3);line-height:1.6;padding-top:10px;border-top:1px solid var(--line-2);">기준을 바꾸려면 검토를 취소하고 시작 화면에서 변경하세요.</div>' +
    '</div>';
  }

  function reviewCriteriaDialog(review) {
    var c = review.criteria || {};
    if (!c.open) return "";
    var body = c.busy && !c.loaded
      ? '<div style="padding:36px;text-align:center;color:var(--text-3);font-size:13px;">적용 기준을 읽는 중…</div>'
      : (c.error ? errorBanner(c.error)
        : ((c.layers || []).length
          ? '<div style="display:flex;flex-direction:column;gap:10px;">' +
              c.layers.map(function (L) { return criteriaLayerCard(L, !!state.clayers.open[L.id]); }).join("") +
            '</div>'
          : '<div style="padding:36px;text-align:center;color:var(--text-3);font-size:13px;">적용된 기준이 없습니다.</div>'));
    return '<div style="position:fixed;inset:0;z-index:90;display:flex;align-items:center;justify-content:center;padding:28px;">' +
      '<button data-act="closeReviewCriteria" aria-label="적용 기준 닫기" style="position:absolute;inset:0;border:0;background:rgba(15,23,42,.45);cursor:default;"></button>' +
      '<div role="dialog" aria-modal="true" aria-label="이번 검토에 적용된 기준" style="position:relative;z-index:1;width:min(820px,100%);max-height:min(760px,88vh);display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--sh-3);">' +
        '<div style="display:flex;align-items:flex-start;gap:16px;padding:22px 24px;border-bottom:1px solid var(--line);">' +
          '<div style="flex:1;min-width:0;"><div style="font-size:18px;font-weight:750;color:var(--text);">이번 검토에 적용된 기준</div>' +
            '<div style="font-size:12px;color:var(--text-3);margin-top:6px;">공통 → 팀별 → 선택한 업로드 기준 순으로 합쳐진 ' + (c.total || 0) + '개 항목 · 진행 중 변경 불가</div></div>' +
          '<button class="btn btn-sm btn-ghost" data-act="closeReviewCriteria" aria-label="닫기">닫기</button>' +
        '</div>' +
        (c.counts && c.counts.disabled ? '<div style="margin:16px 24px 0;padding:10px 12px;border-radius:var(--r-sm);background:var(--sev-min-bg);color:var(--sev-min-fg);font-size:12px;">AI 검토를 꺼서 LLM 기준 ' + c.counts.disabled + '개는 이번 검토에서 실행되지 않습니다.</div>' : '') +
        '<div data-scroll="review-criteria" style="padding:18px 24px 24px;overflow:auto;">' + body + '</div>' +
      '</div>' +
    '</div>';
  }

  // 진행 화면에서 step 마다 바뀌는 조각들(레인·노트·퍼센트·경과). 전체 렌더
  // 없이 이 조각만 교체하려고 따로 뽑았다 — app.js repaintProgress 와 아래
  // singleProgress 가 함께 쓴다. 전체를 다시 그리면 '검토 취소' 버튼 DOM 이
  // step 마다 재생성돼 hover(:hover)가 깜빡인다.
  function progressFragments(v) {
    var r = v.review;
    var lanes = r.lanes.map(laneMosaic).join("");
    // 아직 작업량을 못 받았거나(체커가 아직 신고 전) 단위 없는 체커가 도는 중.
    var note = !lanes
      ? '<div class="review-warmup" role="status">' +
          '<span class="review-warmup-orbit" aria-hidden="true"><i></i></span>' +
          '<span>' + esc(r.note || "검토 기준과 검사 순서를 준비하고 있습니다") + '</span>' +
          '<span class="review-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
        '</div>'
      : (r.note ? '<div style="font-size:12px;color:var(--text-3);margin-bottom:18px;">' + esc(r.note) + '</div>' : "");
    var pct = r.pct === null
      ? '<span class="review-live"><i aria-hidden="true"></i>진행 중' +
          '<span class="review-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></span>'
      : '전체 <span style="color:var(--text);font-weight:700;">' + r.pct + '%</span>';
    return { lanes: lanes, note: note, pct: pct, elapsed: esc(r.elapsed) + ' 경과' };
  }

  function singleProgress(v) {
    var r = v.review;
    var labels = r.lanes.map(function (l) { return l.label; });
    var hasExpression = labels.indexOf("표현 점검") >= 0;
    var hasWhole = labels.indexOf("문서 전체 점검") >= 0;
    var progressCopy = hasExpression && hasWhole
      ? "표현은 문서 조각별로, 일관성은 문서 전체를 비교하여 확인합니다"
      : (labels.length === 1 && labels[0] === "규칙 검사"
        ? "필수 항목과 서식을 자동 규칙으로 확인합니다"
        : "선택된 기준에 따라 문서를 확인합니다");

    // 준비 단계는 0.1초에 끝난다. 진행이 아니라 결과다 — 한 줄로 접는다.
    var prep = r.prepReady
      ? '<div style="display:flex;align-items:center;gap:10px;padding:14px 18px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);margin-bottom:24px;">' +
          '<span style="color:var(--neutral);display:flex;">' + ICONS.check + '</span>' +
          '<span style="font-size:13px;font-weight:600;color:var(--text-2);">문서 준비 · ' + esc(r.prep) + '</span>' +
          (r.prepMs ? '<span class="mono" style="margin-left:auto;font-size:11px;color:var(--text-3);">' + (r.prepMs / 1000).toFixed(1) + '초</span>' : "") +
        '</div>'
      : '<div class="review-document-loading" role="status">' +
          '<span class="review-document-scan" aria-hidden="true">' + ICONS.fileText + '<i></i></span>' +
          '<span style="min-width:0;">' +
            '<strong>문서를 읽는 중</strong>' +
            '<small>페이지와 문단 구조를 정리하고 있습니다</small>' +
          '</span>' +
          '<span class="review-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
        '</div>';

    // 자주 바뀌는 조각은 id 로 감싸 둔다 — api.js가 step 마다 이 안쪽만 갈아끼우고
    // 전체(특히 '검토 취소' 버튼)는 그대로 둔다. 그래야 버튼이 재생성 안 돼 hover 유지.
    var frag = progressFragments(v);
    var note = '<div id="pg-note">' + frag.note + '</div>';
    var lanes = '<div id="pg-lanes">' + frag.lanes + '</div>';

    // 끝나도 이 줄은 **남긴다**. 통째로 지우면 방금까지 100% 를 말하던 자리가
    // 빈칸이 되어 진행이 되감긴 것처럼 보인다 — 실제로 그렇게 읽혔다.
    // 사라지는 건 취소 단추뿐이다(끝난 일을 취소할 수는 없다).
    var foot = '<div style="display:flex;align-items:center;justify-content:space-between;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--text-3);">' +
          '<span id="pg-pct">' + frag.pct + '</span>' +
          '<div style="display:flex;align-items:center;gap:16px;">' +
            '<span id="pg-elapsed" class="mono">' + frag.elapsed + '</span>' +
            (v.done ? "" :
              '<button data-act="cancelReview" class="btn btn-sm btn-ghost btn-ghost-accent">검토 취소</button>') +
          '</div>' +
        '</div>';

    // 여기는 홈·결과와 **같은 불투명 패널**이다. 유리 + 떠다니는 오브는
    // 로그인 계열, 곧 작업을 시작하기 **전** 화면에만 남긴다.
    //
    // 이유는 통일감만이 아니다. 검토는 최대 5분이고 그동안 사용자는 이 화면을
    // 본다 — 600·500px 짜리 흐린 원이 15초·12초 주기로 떠다니는 배경을 5분
    // 보는 것은 장식이 아니라 피로다(느린 전면 반복은 어지럼을 부른다).
    // 3초 스치는 로그인 화면과 같은 장식이 아니다.
    // 오브가 사라져서 overflow-x:hidden·position:relative 도 같이 지웠다 —
    // 오른쪽으로 삐져나가 가로 스크롤을 만들던 것이 그 오브들이었다.
    return '<div data-scroll="progress" style="padding:36px 32px;height:100%;overflow-y:auto;">' +
      '<div style="max-width:1040px;margin:0 auto;background:var(--panel);' +
        'border:1px solid var(--line);border-radius:var(--r-lg);padding:32px;box-shadow:var(--sh-2);">' +
        '<div style="margin-bottom:24px;">' +
          progressHead(v.done, v.issueCount, ["검토 중…", progressCopy], r.pct === null ? 0 : r.pct, v.unreviewedCount) +
        '</div>' +
        '<div style="display:flex;gap:32px;align-items:flex-start;flex-wrap:wrap;">' +
          '<div style="flex:1;min-width:320px;">' + prep + note + lanes + foot + '</div>' +
          criteriaPanel(r) +
        '</div>' +
      '</div>' +
    '</div>' + reviewCriteriaDialog(r);
  }

  // AI 검토 켜고 끄기. 검토를 시작하는 자리에 둔다 — 설정 화면 깊숙이 두면
  // 검토자는 자기가 무엇으로 검토하는지 모른 채 버튼을 누른다.
  // 고를 수 있는 건 켜고 끄는 것뿐이다. 어떤 모델을 쓸지는 서버가 정한다.
  function aiToggle(v) {
    if (!v.llmChips.length) {
      return '<div style="font-size:12px;color:var(--text-3);">' + esc(v.llmNote) + '</div>';
    }
    var chips = v.llmChips.map(function (l) {
      return toolbarChip("setLlm", l.k, l.label, l.on);
    }).join("");
    var hint = v.llm === "on"
      ? "표현 불일치·모순까지 봅니다 · 1분 남짓"
      : "규칙 검사만 — 몇 초면 끝납니다";
    return '<div>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
        '<span style="font-size:13px;font-weight:600;color:var(--text);">AI 검토</span>' + chips +
      '</div>' +
      '<div style="font-size:12px;color:var(--text-3);">' + hint + '</div>' +
    '</div>';
  }

  // 서버가 답한 모델 이름을 그대로 쓰되 벤더 접두어만 뗀다.
  function shortModel(m) {
    if (!m) return "AI 모델";
    var parts = String(m).split("/");
    return parts[parts.length - 1];
  }

  function toolbarChip(act, arg, label, on, extra) {
    var st = on
      ? "background:var(--accent-weak);color:var(--accent-ink);"
      : "background:transparent;color:var(--text-2);";
    return '<span class="chip" data-act="' + act + '" data-arg="' + arg + '" style="' + st + 'font-size:12px;font-weight:600;padding:6px 12px;border-radius:var(--r-sm);">' + esc(label) + (extra || "") + '</span>';
  }

  // 체크리스트 기준 검토의 상단 완료 현황. 101개 중 몇 개가 지적/이상없음/사람
  // 확인필요로 갈렸는지 — 이게 없으면 항목별 목록만 보고는 몇 개가 아직
  // 사람 손을 기다리는지 알 수 없다.
  function checklistCompletenessLine(summary) {
    return '<div style="padding:2px 0 16px;font-size:12px;font-weight:600;color:var(--text-2);">' +
      '자동 판정 ' + esc(summary.flagged) + ' · 이상 없음 ' + esc(summary.clean) +
      // "응답 없음"은 서버가 안 붙었거나 죽은 것이라 고칠 곳이 설정·장비다.
      // "검사 안 됨"은 기준값이 비었거나(규칙) 그 기준 판정만 안 온 것(LLM)이라
      // 고칠 곳이 다르다. 왜인지는 항목 안에 붙는다 — 규칙은 INFO 지적으로,
      // LLM 은 note 로. 뭉치면 검토자가 무엇을 해야 하는지 알 수 없다.
      (summary.noanswer ? ' · 응답 없음 ' + esc(summary.noanswer) : '') +
      (summary.unreviewed ? ' · 검사 안 됨 ' + esc(summary.unreviewed) : '') +
      // "해당 없음"은 고칠 것이 없다 — 있을 때만 보여주고, "검사 안 됨"과 가른다.
      // 뭉치면 검토자가 정상인 것을 보고 장비·설정을 뒤진다.
      (summary.na ? ' · 해당 없음 ' + esc(summary.na) : '') +
      // 생성 기능·이력 관리는 이 문서를 볼 항목이 아니다. "사람 확인 필요" 에
      // 섞으면 검토자가 자기 일이 아닌 것까지 떠안은 줄 안다.
      (summary.outofscope ? ' · 검토 대상 아님 ' + esc(summary.outofscope) : '') +
      ' · 사람 확인 필요 ' + esc(summary.manual) + '</div>';
  }

  // 항목 하나: [번호 · 항목 텍스트] 뒤에 상태를 붙이고, flagged면 그 항목에서
  // 나온 지적을 findingCardInner로 그대로 그린다(평면 목록과 같은 카드 —
  // 같은 finding dict 를 참조하므로 번호·형광펜도 같다).
  function checklistItemGroup(it, v) {
    // 분류(IS22 의 Consistency·Correctness 등)를 항목 앞에 옅게 단다 — 이 항목이
    // 왜 그 검사에 걸렸는지 검토자가 알아보게. 없으면(무분류) 생략한다.
    var groupTag = it.group
      ? '<span style="flex:none;font-size:11px;font-weight:600;color:var(--accent-ink);background:var(--accent-weak);padding:2px 8px;border-radius:var(--r-sm);margin-right:6px;">' + esc(it.group) + '</span>'
      : '';
    // 층(공통/팀별/업로드). 공통·팀은 늘 돌지만 업로드는 검토자가 고른 체크리스트다 —
    // 항목이 어느 층에서 왔는지 헤더가 말한다. 채우지 않은 테두리 칩(미검토 뱃지와
    // 같은 문법) — 분류(groupTag)와 급이 달라 보이게.
    var layerTag = it.layer
      ? '<span style="flex:none;font-size:11px;font-weight:600;color:var(--text-3);box-shadow:inset 0 0 0 1px var(--line-2);padding:2px 8px;border-radius:var(--r-sm);margin-right:6px;">' + esc(it.layer) + '</span>'
      : '';
    // 번호는 검토자가 **원본 체크리스트와 대조하는 길**이다(엑셀 1~4, 올린
    // 파일의 No.1~2). 그래서 출처가 있는 번호만 보여준다 — "C-" 로 시작하는
    // 것은 우리가 지어낸 것이라 대조할 원본이 없고, 사용자에겐 뜻이 없다.
    var showNo = it.no && it.no.indexOf("C-") !== 0;
    var label = (showNo ? esc(it.no) + ' · ' : '') + esc(it.text);
    // 상태 아이콘은 인라인 SVG로 낸다. 이모지(⚠️·👤·✅)는 컬러 이모지 폰트가 없는
    // 환경에서 네모 상자로 깨져 "창 아이콘"처럼 보였다.
    var statusIco = function (name, color) {
      return '<span style="color:' + color + ';margin-right:4px;">' + ICONS[name] + '</span>';
    };
    var head = it.status === "flagged"
        ? (statusIco("alert", "var(--sev-maj-fg)") + esc(it.findings.length) + '건')
      : it.status === "manual"
        ? (statusIco("user", "var(--text-3)") + '사람 확인 필요')
      : it.status === "noanswer"
        ? (statusIco("alert", "var(--text-3)") + '응답 없음')
      : it.status === "unreviewed"
        ? (statusIco("user", "var(--text-3)") + '검사 안 됨')
      : it.status === "na"
        ? (statusIco("check", "var(--text-3)") + '해당 없음')
      : it.status === "outofscope"
        ? (statusIco("check", "var(--text-3)") + '검토 대상 아님')
        : (statusIco("check", "var(--band-good-fg)") + '이상 없음');
    // 확인 방법(세부 기준). 본문이 "아래 양식으로"에서 끊겨 있어도 여기 있다 —
    // 원본 엑셀은 사내 파일이라 앱에 없어서, 이걸 안 보여주면 검토자가 무엇을
    // 확인하라는 건지 알 길이 없다.
    var noteHtml = it.note
      ? '<div style="margin-top:4px;font-size:12px;color:var(--text-3);line-height:1.6;white-space:pre-wrap;">' +
          esc(it.note) + '</div>'
      : '';
    // "왜 사람 확인 필요인가"의 답. 도구가 검사한 것과 애초에 검사할 수 없는
    // 것은 다른 말인데, 상태만 보면 둘이 같아 보인다.
    var why = (it.status === "outofscope")
      // 생성 기능(수식 도출·이미지·표 그리기)과 이력 관리다. 문서를 보는
      // 검사가 아니라서 이 화면에 판정이 있을 수 없다.
      ? '<div style="margin-top:4px;font-size:11px;color:var(--text-3);">' +
          '이 기준은 문서를 검토하는 항목이 아닙니다 — 산출물을 만들거나 이력을 관리하는 기능입니다.</div>'
      : (it.status === "na")
      // 고칠 것이 없다는 뜻이다. "검사 안 됨"으로 읽히면 검토자가 장비·설정을
      // 뒤지게 되므로 여기서 분명히 말한다.
      ? '<div style="margin-top:4px;font-size:11px;color:var(--text-3);">' +
          '이 기준이 이 문서를 대상으로 하지 않습니다 — 고칠 것이 없습니다.</div>'
      // 사람 몫인 이유는 둘이고 검토자가 할 일이 다르다.
      //   기준이 mode: 사람 이라고 **적었다** → 문서만으로는 못 본다(스캔 품질·
      //     책갈피 동작처럼). 검사기를 만들 일이 아니라 사람이 볼 일이다.
      //   아무도 안 적었다 → 그냥 아직 검사기가 없는 것이다. 업로드 체크리스트는
      //     엑셀에 mode 칸이 없어 **전부** 이쪽인데, 예전에는 화면이 그것들까지
      //     "문서만으로 판정할 수 없다"고 말했다 — "PDF 필드오류 문자열이 있는가"
      //     처럼 기계가 그대로 볼 수 있는 항목에도 그렇게 말했으니 거짓말이다.
      // mode 가 규칙인데 manual 인 항목은 note 가 이미 이유를 말한다(orchestrator
      // 의 note_suffix) — 여기서 또 말하면 같은 문장이 두 번 뜬다.
      : (it.status === "manual" && it.mode === "사람")
      ? '<div style="margin-top:4px;font-size:11px;color:var(--text-3);">' +
          (it.mode_declared
            ? '이 기준은 문서만으로 판정할 수 없어 사람이 확인합니다.'
            : '이 기준에 붙은 검사기가 아직 없어 사람이 확인합니다.') + '</div>'
      : '';
    // 지적 카드는 기준 아래에 **들여쓰고 왼쪽 레일**을 세운다. 그냥 나열하면
    // 이 카드가 위 기준의 결과인지, 다음 기준의 것인지 읽히지 않는다.
    var findingsHtml = it.findings.length
      ? '<div style="margin-top:10px;padding-left:12px;border-left:2px solid var(--line);">' +
          it.findings.map(function (f) {
            return findingCardHtml(f, v, "margin-bottom:8px;");
          }).join("") +
        '</div>'
      : '';
    return '<div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid var(--line-2);">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;">' +
        '<span style="font-size:13px;font-weight:600;color:var(--text);min-width:0;">' + layerTag + groupTag + label + '</span>' +
        '<span style="flex:none;font-size:12px;font-weight:600;color:var(--text-2);">' + head + '</span>' +
      '</div>' +
      noteHtml + why +
      findingsHtml +
    '</div>';
  }

  function singleResults(v) {

    // 문서 미리보기. pdf(브라우저 blob) 또는 docx/hwpx(서버 변환)면 PDF iframe으로,
    // 이력·미지원·변환 실패는 엔진이 읽은 텍스트로. hwpx는 재현본이라 라벨로 구분한다.
    var kind = v.viewerKind;
    // docx·hwp·hwpx 는 LibreOffice로 원본을 직접 변환해 레이아웃이 살아 있다
    // (hwp/hwpx는 H2Orestart 필터). 그래서 pdf.js 뷰어로 연다. 변환 안 되는 포맷·
    // 이력·변환 실패만 엔진이 읽은 텍스트 폴백으로 간다.
    var convertible = (kind === "DOCX" || kind === "HWPX" || kind === "HWP");
    var showPdf = v.hasOrigFile && (kind === "PDF" || convertible) && !v.convertError;
    var baseLabel = "원본";
    var headMeta = showPdf
      ? (kind === "PDF" ? "원본 PDF" : "원본 PDF (docx 변환)")
      : (v.convertError ? "변환 실패 — 텍스트로 표시"
         : (v.isPdf ? "이력에는 원본이 없어 텍스트로 표시"
            : (v.sections.length ? v.sections.length + "개 절 · 엔진이 읽은 본문" : "본문 없음")));
    // 헤더(문서명·쪽수·형광펜·줌·전체화면)는 공용 viewerHeadHtml — 폴더
    // 검토(caseDocView)와 같은 것을 쓴다. 복사하면 한쪽만 고쳐진다.
    var docName = (v.doc && v.doc.name) ? v.doc.name : "Document";
    var viewerHead = viewerHeadHtml(docName, showPdf, headMeta);
    var docViewer = '<div style="flex:1;background:var(--bg);display:flex;flex-direction:column;position:relative;overflow:hidden;">' +
      (v.converting
        ? viewerHead +
          '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);font-size:14px;font-weight:600;gap:10px;">' +
            '<span style="display:inline-block;animation:spin 1s linear infinite;">' + ICONS.refresh + '</span>원본을 PDF로 준비하는 중…</div>'
        // 표시본을 굽는 동안은 원본을 대신 띄우지 않는다. 화면 전환이 곧 iframe
        // 재로드라, 원본을 잠깐 띄웠다 바꾸면 로드를 두 번 하며 깜빡인다.
        // 실제 문서에서 0.2초대라 기다리는 편이 눈에 편하다.
        : (v.viewerMode === "marked" && v.annot.busy && !v.annot.viewUrl && showPdf)
          ? viewerHead +
            '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);font-size:14px;font-weight:600;gap:10px;">' +
              '<span style="display:inline-block;animation:spin 1s linear infinite;">' + ICONS.refresh + '</span>지적을 문서에 표시하는 중…</div>'
        : showPdf
          // 제목·토글·PDF를 하나의 세로 카드로 묶어 회색 캔버스에 크게(viewerWrap).
          ? viewerWrap(true, viewerHead +
              '<div id="pdf-mount" style="flex:1;overflow:hidden;"></div>')
          // 재현본(hwpx·텍스트 폴백)도 PDF와 같은 카드 구조(viewerWrap)를 쓴다 —
          // 예전엔 헤더를 카드 위에 깔고 스크롤 컨테이너에 padding:32px 을 줘서,
          // 문서 시작이 오른쪽 "검토 결과" 패널(margin-top:4px)보다 ~65px 아래에서
          // 시작했다. hwpx 는 늘 이 분기라(docx만 PDF로 변환된다) 주력 포맷에서
          // 항상 어긋나 보였다. 헤더가 카드 안에 있으니 스크롤도 PDF와 같다 —
          // 헤더는 고정되고 본문만 흐른다. 문서 여백(40/44px)은 스크롤 컨테이너가 갖는다.
          : viewerWrap(false, viewerHead +
              '<div id="doc-scroll" data-scroll="doc" style="flex:1;overflow:auto;padding:40px 44px;">' +
                docBody(v) +
              '</div>')) +
    '</div>';

    // 분포 바·범례는 issuesShell 이 그린다 — 폴더 검토도 같은 것을 쓴다.

    // 내보내기 아이콘(Lucide download)과 헤더 드롭다운. 항목을 고르면 handler가 닫는다.
    var dlIcon = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    var exportMenu = state.exportMenuOpen
      ? '<div id="exportMenu" style="position:absolute;top:44px;right:0;width:248px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);z-index:120;overflow:hidden;animation:fadeUp .15s ease-out forwards;">' +
          // PDF면 원본에 형광펜을 얹어 돌려줄 수 있다. 그 밖의 포맷은 HTML 산출물뿐.
          // 색으로 서열을 매기지 않는다. 글자색은 하나로 두고 아이콘 칩과
          // 한 줄 설명으로 무엇을 받는지 구분한다.
          (v.isPdf
            ? '<button data-act="downloadMarked" class="mi"' + (v.annot.busy ? ' disabled' : '') + ' style="border-bottom:1px solid var(--line-2);">' +
                '<span class="mi-ico">' + dlIcon + '</span>' +
                '<span><span>' + (v.annot.busy ? '표시본 만드는 중…' : '표시본 PDF') + '</span>' +
                '<span class="mi-sub" style="display:block;">지적을 형광펜·번호로 얹은 원본</span></span>' +
              '</button>'
            : '') +
          '<button data-act="exportAs" data-arg="html" class="mi">' +
            '<span class="mi-ico">' + dlIcon + '</span>' +
            '<span><span>검토 결과 문서</span>' +
            '<span class="mi-sub" style="display:block;">지적 전체를 담은 HTML</span></span>' +
          '</button>' +
          '<div style="display:flex;gap:4px;padding:6px;border-top:1px solid var(--line-2);">' +
            [["json", "JSON"], ["md", "Markdown"], ["csv", "CSV"]].map(function (e) {
              return '<button data-act="exportAs" data-arg="' + e[0] + '" class="mi-mini">' + e[1] + '</button>';
            }).join("") +
          '</div>' +
        '</div>'
      : "";

    // 우측 패널은 이제 "검토 결과"(자동 검사) 하나만 보여준다. 사람이 직접
    // 채우는 체크리스트는 독립 화면(checklistRunScreen)으로 떨어져 나갔다 —
    // 예전엔 여기 탭(findings/checklist)으로 얹혀 있었지만, 자동 검토와
    // 상관없는 기능이 결과 화면에 있으면 "왜 검토 결과에서 체크리스트를
    // 채우냐"는 혼란만 남는다.
    // 재검토(이력 있음)면 패널을 탭 둘로 나눈다. 예전에는 반영 확인 패널과 지적
    // 카드가 한 열에 세로로 이어져, 지난번 지적 27건을 지나야 이번 결과가 나왔다.
    //
    // 뷰어는 안 줄어든다 — 결과 화면은 좌우 2단이고 탭은 오른쪽 패널 안에만 든다.
    //
    // 기본은 반영 확인이다. 재검토에서 검토자가 먼저 보고 싶은 것은 "지난번 지적이
    // 고쳐졌나" 이고, 이번 결과 전체는 그다음이다.
    var hasLineage = !!v.lineage;
    var reviewTab = reviewTabNow();
    var reviewTabBar = "";
    if (hasLineage) {
      var lg = v.lineage.summary || {};
      var tabsR = [["lineage", lineageTabLabel(v.lineage)],
                   ["findings", "이번 검토 " + v.issueCount + "건"]];
      // issuesShell 의 tabs 자리로 들어간다(스크롤 밖 고정) — margin 은 스크롤
      // body 의 자체 padding 이 대신한다.
      reviewTabBar = '<div style="display:flex;gap:18px;">' +
        tabsR.map(function (t) {
          return '<span id="tab-' + t[0] + '" class="tab' + (reviewTab === t[0] ? " on" : "") +
            '" data-act="setReviewTab" data-arg="' + t[0] + '" tabindex="0" role="button">' + esc(t[1]) + '</span>';
        }).join("") + '</div>';
    }

    // 정렬·검사기 필터. 뷰모델(sortChips/checkerChips)과 핸들러(setSort/setChecker)는
    // 진작 있었는데 화면에 붙는 건 여기가 처음이다. 체크리스트 묶음 보기에는 안
    // 붙인다 — 거기는 항목 순서가 체크리스트 등록 순서라 필터·정렬이 적용되지 않는다.
    function fchip(act, arg, label, on) {
      return '<span data-act="' + act + '" data-arg="' + arg + '" tabindex="0" role="button"' +
        ' style="padding:4px 10px;font-size:11px;font-weight:600;border-radius:var(--r-xl);cursor:pointer;' +
        'background:' + (on ? "var(--accent-weak)" : "var(--bg)") + ';color:' + (on ? "var(--accent)" : "var(--text-3)") + ';' +
        'box-shadow:inset 0 0 0 1px ' + (on ? "var(--accent)" : "var(--line)") + ';">' + esc(label) + '</span>';
    }
    var filterBar = "";
    if (!v.checklistReview && v.totalCount > 0) {
      filterBar = '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;">' +
        v.sortChips.map(function (o) { return fchip("setSort", o.k, o.label, o.on); }).join("") +
        // 검사기가 하나뿐이면 "전체/그 하나" 두 칩이 같은 목록을 가리킨다 — 안 그린다.
        (v.checkerChips.length > 2
          ? '<span style="width:1px;height:14px;background:var(--line);margin:0 2px;"></span>' +
            v.checkerChips.map(function (c) { return fchip("setChecker", c.k, c.label, c.on); }).join("")
          : "") +
      '</div>';
    }
    // 헤드라인 옆 부제. info(검토 과정 보고)와 미검토는 "지적"이 아니라서 큰
    // 숫자에 섞지 않되, 숨기지도 않는다 — 조용히 지우면 "지적이 없다"는 거짓말이 된다.
    var subParts = [];
    if (v.infoCount) subParts.push("참고 " + v.infoCount);
    if (v.unreviewedCount) subParts.push("미검토 " + v.unreviewedCount);
    var issuesPanel = issuesShell({
      id: "issuesPanel",
      title: "검토 결과",
      count: v.issueCount,
      sub: subParts.join(" · "),
      // 미검토가 남아 있으면 0건이어도 "이상 없음"이라 말하지 않는다 —
      // "0건 통과"와 "검토를 못 했다"를 섞지 않는다(CLAUDE.md).
      noClean: v.unreviewedCount > 0,
      filters: filterBar,
      chips: v.sevChips,
      hidden: state.issuesCollapsed,
      actions:
        '<button class="hover-accent" data-act="toggleExportMenu" title="내보내기" style="flex:none;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:1px solid ' + (state.exportMenuOpen ? "var(--accent)" : "var(--line)") + ';background:' + (state.exportMenuOpen ? "var(--accent-weak)" : "var(--bg)") + ';border-radius:var(--r-sm);cursor:pointer;color:' + (state.exportMenuOpen ? "var(--accent)" : "var(--text-3)") + ';">' + dlIcon + '</button>' +
        '<button class="hover-accent" data-act="toggleIssues" title="패널 접기" style="flex:none;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:1px solid var(--line);background:var(--bg);border-radius:var(--r-sm);cursor:pointer;color:var(--text-3);">' + ICON_PANEL_CLOSE + '</button>',
      overlay: exportMenu,
      note: v.annot.msg
        ? '<div style="margin-top:12px;font-size:12px;line-height:1.6;color:var(--text-2);background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);padding:8px 10px;">' + esc(v.annot.msg) + '</div>'
        : "",
      tabs: reviewTabBar,
      body: (reviewTab === "lineage"
        ? lineageHtml(v.lineage, v.lineageCandidate)
        : (v.checklistReview
          // 체크리스트 기준으로 검토했으면 지적을 항목별로 묶어 보인다 — 필터·정렬은
          // 여기 적용하지 않는다(항목 순서 자체가 체크리스트가 등록된 순서다).
          ? checklistCompletenessLine(v.checklistReview.summary) +
            v.checklistReview.items.map(function (it) { return checklistItemGroup(it, v); }).join("")
          : (v.hasFindings ? v.tableFindings.map(function(f, i) {
               return findingCardHtml(f, v, enterAnim(v, i));
            }).join("") : '<div style="padding:40px 20px;text-align:center;color:var(--text-3);font-size:14px;font-weight:500;">선택한 조건에 해당하는 지적이 없습니다.</div>')))
    });

    // 접었을 때 오른쪽 끝에 남는 얇은 레일. 클릭하면 다시 펼친다 — 몇 건인지도 세로로 보여준다.
    var issuesRail = '<div id="issuesRail" class="rail" data-act="toggleIssues" tabindex="0" role="button" title="검토 결과 펼치기" style="margin:4px 0 12px 0;display:' + (state.issuesCollapsed ? "flex" : "none") + ';">' +
      '<div class="rail-ico">' + ICON_PANEL_OPEN + '</div>' +
      '<div class="rail-label">검토 결과 ' + v.issueCount + '건</div>' +
    '</div>';

    // 백링크는 비교 화면처럼 전체 폭 상단 바로. 그래야 그 아래에서 문서 뷰어와
    // "검토 결과" 패널이 같은 높이에서 시작한다(예전엔 백링크가 왼쪽 컬럼에만 있어
    // 문서를 밀어, 패널 헤더가 문서보다 위에서 시작했다).
    // 패널·레일을 둘 다 DOM에 두고 display만 토글한다 — 접기 때 render()로 문서 뷰어를
    // 다시 그리면 PDF iframe이 리로드되므로(=새로고침), 뷰어는 건드리지 않는다.
    return '<div style="display:flex;flex-direction:column;height:100%;width:100%;">' +
      '<div style="flex:none;padding:10px 32px 4px;display:flex;align-items:center;justify-content:space-between;gap:12px;">' +
        backLink("history", "목록으로 돌아가기") + newReviewLink() + '</div>' +
      '<div id="results-row" style="' + resultsRowCss(state.viewerFull) + '">' +
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">' + docViewer + '</div>' +
        issuesPanel + issuesRail +
      '</div>' +
    '</div>';
  }

  // 문서 카드(뷰어 헤더 + PDF/재현본)의 스타일. 전체화면이어도 카드 자체는 그대로다
  // — 화면을 덮는 건 카드가 아니라 아래 resultsRowCss가 맡는다.
  function viewerCardCss(isPdf) {
    return "display:flex;flex-direction:column;overflow:hidden;background:var(--panel);" +
      "border:1px solid var(--line);border-radius:var(--r-md);" +
      // PDF: 주어진 자리를 폭·높이 모두 꽉 채운다. 페이지 배율은 pdfview 가 폭에
      // 맞춰 정한다. 예전에는 aspect-ratio 로 높이에서 폭을 파생시켜, 오른쪽 패널을
      // 접어도 좌우 여백만 늘고 문서는 안 커졌다.
      // 그림자는 토큰으로. 인라인 rgba(0,0,0,.04) 는 어두운 캔버스 위에서 사실상
      // 안 보여서, 다크에서는 문서 카드가 배경에 붙어 있었다.
      (isPdf ? "height:100%;width:100%;box-shadow:var(--sh-3);"
             : "width:100%;max-width:820px;box-shadow:var(--sh-3);");
  }

  // 뷰어 카드 공용 래퍼 — 회색 캔버스 위 카드. 시작 높이(padding-top 4px)가
  // 오른쪽 issuesShell(margin-top 4px)과 맞는다. 단일 PDF·재현본·폴더 검토
  // 셋이 같은 것을 써야 화면마다 문서 시작 높이가 안 갈라진다.
  function viewerWrap(isPdf, inner) {
    return '<div style="flex:1;overflow:hidden;display:flex;justify-content:center;padding:4px 32px 12px;">' +
      '<div style="' + viewerCardCss(isPdf) + '">' + inner + '</div>' +
    '</div>';
  }

  // 뷰어 카드의 슬림 헤더 — 단일 검토와 폴더 검토가 같은 것을 쓴다.
  // showPdf 면 쪽수(#pdf-where)·형광펜·줌·전체화면 단추가 붙고, 아니면
  // 상태 문구(headMeta)만 남는다. 단추들은 전역 id(#pdf-mount 의 pdfview,
  // #results-row)에 붙으므로 어느 화면에서든 같은 액션으로 동작한다.
  function viewerHeadHtml(docName, showPdf, headMeta) {
    var _zbtn = "padding:4px 12px;font-size:13px;font-weight:600;border:none;cursor:pointer;" +
      "background:transparent;color:var(--text-2);";
    // 보고 있는 쪽·배율. 뷰어가 스크롤·확대 때마다 이 자리 글자만 갈아끼운다
    // (app.js 의 onViewChange) — 긴 문서에서 몇 쪽인지 모르면 위치 감이 안 온다.
    var viewerWhere = showPdf
      ? '<span id="pdf-where" class="mono" style="flex:none;font-size:11px;font-weight:600;' +
        'color:var(--text-3);white-space:nowrap;"></span>'
      : "";
    // 형광펜을 끄면 문서 자체를 읽을 수 있다. 지적이 수십 건이면 색이 겹쳐
    // 원문이 안 보인다 — 끄고 읽다가 다시 켠다.
    var markBtn = showPdf
      ? '<button data-act="toggleMarks" class="viewer-tool viewer-mark-tool" aria-pressed="' +
        (state.marksOn === false ? "false" : "true") + '" title="' +
        (state.marksOn === false ? "형광펜 켜기" : "형광펜 끄기") + '" ' +
        'style="flex:none;height:28px;padding:0 10px;display:flex;align-items:center;gap:6px;' +
        'border:1px solid var(--line);border-radius:var(--r-sm);cursor:pointer;font-size:11px;font-weight:600;' +
        'background:' + (state.marksOn === false ? "var(--bg)" : "var(--accent-weak)") + ';' +
        'color:' + (state.marksOn === false ? "var(--text-3)" : "var(--accent-ink)") + ';">형광펜</button>'
      : "";
    var viewerToggle = showPdf
      ? '<span class="viewer-tool-group" style="flex:none;display:inline-flex;background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);overflow:hidden;">' +
          '<button class="viewer-tool" data-act="zoom" data-arg="-0.2" title="축소" style="' + _zbtn + '">−</button>' +
          '<button class="viewer-tool" data-act="zoom" data-arg="fit" title="폭 맞춤" style="' + _zbtn + 'font-size:12px;border-left:1px solid var(--line);border-right:1px solid var(--line);">맞춤</button>' +
          '<button class="viewer-tool" data-act="zoom" data-arg="0.2" title="확대" style="' + _zbtn + '">+</button>' +
        '</span>'
      : '<span style="flex:none;font-size:11px;font-weight:600;color:var(--text-3);">' + headMeta + '</span>';
    // 문서를 화면 전체로. 카드가 폭에 맞춰 배율을 정하는 탓에 오른쪽 패널을
    // 접어도 문서는 안 커진다 — 크게 보는 유일한 길이라 전체화면을 따로 둔다.
    var fullBtn = '<button id="viewerFullBtn" class="viewer-tool" data-act="toggleViewerFull" ' +
      'title="' + (state.viewerFull ? "원래 크기로 (Esc)" : "전체화면") + '" ' +
      'style="flex:none;width:28px;height:28px;display:flex;align-items:center;justify-content:center;' +
      'border:1px solid var(--line);background:var(--bg);border-radius:var(--r-sm);cursor:pointer;color:var(--text-3);">' +
      (state.viewerFull ? ICONS.minimize : ICONS.maximize) + '</button>';
    return '<div style="flex:none;padding:10px 16px;display:flex;justify-content:space-between;align-items:center;gap:10px;border-bottom:1px solid var(--line);">' +
      '<span style="display:flex;align-items:center;gap:4px;min-width:0;font-size:12px;font-weight:600;color:var(--text-2);"><span style="flex:none;">' + docShapeIcon(docName, 16, "accent") + '</span>' +
        '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(docName) + '</span></span>' +
      '<span style="flex:none;display:flex;align-items:center;gap:8px;">' +
        viewerWhere + markBtn + viewerToggle + fullBtn + '</span>' +
    '</div>';
  }

  // 결과 화면의 2단 행(문서 뷰어 + "검토 결과" 패널). 전체화면이면 이 **행**을
  // 화면 전체로 덮어 사이드바·상단 헤더·백링크 바를 가린다.
  //
  // 덮는 대상이 문서 카드가 아니라 행인 게 핵심이다. 카드만 덮으면 문서는 커지지만
  // 지적 목록이 사라져, 정작 "지적이 문서 어디냐"를 보려던 사람이 둘을 번갈아 봐야
  // 한다. 행을 덮으면 패널이 남는데도 문서는 거의 안 작아진다 — PDF 카드는
  // aspect-ratio로 높이에서 폭을 정하므로, 오른쪽 400px은 어차피 남던 좌우 여백에서
  // 빠질 뿐이다.
  //
  // 전체화면을 **제자리 스타일 변경**으로만 구현하는 것도 핵심이다. 노드를 body 밑으로
  // 옮겨 띄우는 흔한 방법을 쓰면 안 된다 — iframe은 DOM에서 옮기는 순간 브라우저가
  // 문서를 다시 읽어서(app.js makePdfFrame 위 주석) 읽던 쪽을 잃는다. position:fixed는
  // 시각적으로만 흐름에서 빼내므로 리로드가 없고, 조상에 걸어도 마찬가지다.
  //
  // app.js의 toggleViewerFull도 이 함수로 cssText를 통째로 갈아끼운다. 개별 속성을
  // 지웠다 폈다 하면(style.position = "") 원래 인라인 값까지 날아간다.
  function resultsRowCss(full) {
    // z-index는 "검토 결과" 패널(10)·내보내기 메뉴(120)보다 위여야 셸을 다 덮는다.
    // 배경을 깔지 않으면 가린 사이드바·헤더가 비쳐 보인다.
    if (full) return "display:flex;position:fixed;inset:0;z-index:300;background:var(--bg);";
    return "display:flex;flex:1;min-height:0;width:100%;";
  }

  // 지금 고른 기준이 이 문서에 맞는지 알려주는 띠.
  //
  // 잘못된 기준의 실패는 에러가 아니라 조용한 0건이다 — "지적 없음"이 떠서
  // 검토를 통과한 것처럼 보인다. 같은 실에서 온 문서인데도 ID 체계가 달라
  // (SHN34: FR-GC_01, SKN56: FR1-0305) 서로의 기준으로는 0개다.
  // 그래서 검토를 돌리기 전에 개수를 지면에 띄운다.
  function detectBanner(v) {
    if (v.detectBusy) {
      return '<div style="margin-top:16px;padding:12px 16px;border-radius:var(--r-md);background:var(--bg);' +
        'border:1px solid var(--line);font-size:13px;color:var(--text-3);">문서에서 요건 ID를 찾는 중…</div>';
    }
    if (v.detectCount === null || v.detectCount === undefined) return "";
    // 요건 ID 를 세지 않는 기준이면 띠 자체를 띄우지 않는다 — 셀 것이 없는데
    // "0개 찾았습니다"라고 말하면 그 자체가 거짓말이다.
    if (!v.detectScored) return "";
    var bad = v.detectCount === 0;
    var bg = bad ? "rgba(239,68,68,0.08)" : "rgba(16,185,129,0.08)";
    var bd = bad ? "#EF4444" : "#10B981";
    var body = bad
      ? esc(v.detectWarn)
      : ('이 문서에서 요건 ID <b>' + v.detectCount + '개</b>를 찾았습니다.'
         + (v.detectIdExample ? ' (예: <code>' + esc(v.detectIdExample) + '</code>)' : '')
         + (v.detectAuto ? ' <span style="color:var(--text-3);">— 기준이 자동으로 선택되었습니다.</span>' : ''));
    return '<div style="margin-top:16px;padding:12px 16px;border-radius:var(--r-md);background:' + bg +
      ';border-left:3px solid ' + bd + ';font-size:13px;line-height:1.6;color:var(--text);">' + body + '</div>';
  }

  // 기준 고르기(칩). 비교 화면에는 이게 아예 없어서 서버 기본값에 갇혀 있었다 —
  // 추적성은 체크리스트의 id_pattern에 전부 기대므로 가장 위험한 구멍이었다.
  function checklistChips(v) {
    if (!v.checklistCards.length) return "";
    var chips = v.checklistCards.map(function (c) {
      return '<button data-act="setChecklist" data-arg="' + c.id + '" style="padding:6px 14px 6px 6px;display:inline-flex;align-items:center;gap:8px;font-size:13px;' +
        'font-weight:600;border-radius:var(--r-md);cursor:pointer;border:1px solid ' +
        (c.sel ? "var(--accent)" : "var(--line)") + ';background:' +
        (c.sel ? "var(--accent-weak)" : "var(--panel)") + ';color:var(--text);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);">' +
        '<div style="width:24px;height:24px;border-radius:var(--r-sm);background:' + (c.sel ? 'var(--accent)' : 'var(--bg)') + ';color:' + (c.sel ? '#fff' : 'var(--text-3)') + ';display:flex;align-items:center;justify-content:center;flex:none;">' + c.glyph + '</div>' +
        esc(c.name) + '</button>';
    }).join("");
    return '<div class="setup-context">' +
      '<div class="setup-context-row" style="grid-template-columns:176px minmax(0,1fr);">' +
        '<div>' +
          '<h3 class="setup-section-title">검토 기준</h3>' +
          '<p class="setup-section-sub">문서군에 맞는 기준을 선택하세요.</p>' +
        '</div>' +
        '<div style="min-width:0;">' +
          '<div style="display:flex;gap:8px;flex-wrap:wrap;">' + chips + '</div>' +
          detectBanner(v) +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function compareSetup(v) {
    function docSlot(label, slot, file) {
      return '<div style="flex:1;min-width:0;">' +
        '<div class="eyebrow" style="color:var(--text-2);margin-bottom:12px;">' + label + '</div>' +
        dropzone({ slot: slot, file: file }) +
      '</div>';
    }
    return '<div class="page-shell page-shell-primary" data-scroll="csetup">' +
      '<div class="page-container page-stack">' +
        errorBanner(v.cerror) +
        pageHead("문서 비교", "기준 문서와 비교 문서를 맞대어 어긋난 곳과 누락을 찾습니다.") +
        '<div class="setup-panel">' +
          '<div style="display:flex;gap:32px;align-items:center;">' +
            docSlot("기준 문서 (Document A)", "compareA", v.files.compareA) +
            '<div style="flex:none;width:56px;height:56px;border-radius:50%;background:var(--bg);border:2px solid var(--line);display:flex;align-items:center;justify-content:center;color:var(--accent-ink);font-size:24px;box-shadow:var(--sh-2);">' + ICONS.arrowLeftRight + '</div>' +
            docSlot("비교 대상 문서 (Document B)", "compareB", v.files.compareB) +
          '</div>' +
          checklistChips(v) +
          '<div style="display:flex;justify-content:flex-end;margin-top:18px;">' +
            '<button class="btn btn-lg btn-primary" data-act="startCompare">비교 시작 ' + ICONS.arrowRight + '</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function compareProgress(v) {
    return '<div style="padding:40px;">' +
      '<div style="max-width:600px;margin:0 auto;">' +
        '<svg viewBox="0 0 100 100" style="width:60px;height:60px;margin:0 auto 16px;display:block;"><defs><linearGradient id="laserGradComp" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="var(--neutral)" stop-opacity="0" /><stop offset="50%" stop-color="var(--neutral)" stop-opacity="1" /><stop offset="100%" stop-color="var(--neutral)" stop-opacity="0" /></linearGradient><filter id="laserGlowComp" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="2.5" result="blur" /><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><g transform="translate(-10, -6)"><path d="M28 18 L56 18 L72 34 L72 78 A 4 4 0 0 1 68 82 L32 82 A 4 4 0 0 1 28 78 Z" fill="var(--bg)" /><path d="M28 18 L56 18 L72 34 L72 78 A 4 4 0 0 1 68 82 L32 82 A 4 4 0 0 1 28 78 Z" fill="var(--accent-weak)" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" /><path d="M56 18 L56 30 A 4 4 0 0 0 60 34 L72 34 Z" fill="var(--bg)" stroke="none" /><path d="M56 18 L56 30 A 4 4 0 0 0 60 34 L72 34 Z" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" /><line x1="36" y1="48" x2="64" y2="48" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /><line x1="36" y1="60" x2="52" y2="60" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /><line x1="36" y1="72" x2="60" y2="72" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /></g><g transform="translate(10, 6)"><path d="M28 18 L56 18 L72 34 L72 78 A 4 4 0 0 1 68 82 L32 82 A 4 4 0 0 1 28 78 Z" fill="var(--bg)" /><path d="M28 18 L56 18 L72 34 L72 78 A 4 4 0 0 1 68 82 L32 82 A 4 4 0 0 1 28 78 Z" fill="var(--accent-weak)" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" /><path d="M56 18 L56 30 A 4 4 0 0 0 60 34 L72 34 Z" fill="var(--bg)" stroke="none" /><path d="M56 18 L56 30 A 4 4 0 0 0 60 34 L72 34 Z" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" /><line x1="36" y1="48" x2="64" y2="48" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /><line x1="36" y1="60" x2="52" y2="60" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /><line x1="36" y1="72" x2="60" y2="72" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" /></g><rect x="12" y="20" width="76" height="6" rx="3" fill="url(#laserGradComp)" filter="url(#laserGlowComp)"><animate attributeName="y" values="10;90;10" dur="2s" repeatCount="indefinite" /></rect></svg><div style="margin-bottom:22px;">' +
          progressHead(v.cdone, v.cTotalCount, ["Comparing…", "두 문서를 매칭하고 교차검토합니다"], v.cProgressPct) +
        '</div>' + v.cpipeline.map(timelineItem).join("") +
      '</div>' +
    '</div>';
  }

  function compareResults(v) {
    var dashboard = '<div style="padding:16px 32px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:16px;box-shadow:var(--sh-1);z-index:20;position:relative;">' +
      '<div style="display:flex;gap:40px;align-items:center;">' +
      '<div style="flex:none;display:flex;align-items:center;gap:20px;">' +
        '<div style="width:68px;height:68px;border-radius:50%;background:var(--bg);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;position:relative;box-shadow:inset 0 2px 4px rgba(0,0,0,0.02);">' +
          '<svg viewBox="0 0 36 36" style="position:absolute;top:-2px;left:-2px;width:72px;height:72px;transform:rotate(-90deg);"><circle stroke="var(--accent)" stroke-dasharray="' + v.coverage + ', 100" stroke-linecap="round" stroke-width="2.5" fill="none" cx="18" cy="18" r="16"/></svg>' +
          '<span style="font-size:18px;font-weight:700;color:var(--accent-ink);">' + v.coverage + '<span style="font-size:12px;font-weight:600;">%</span></span>' +
        '</div>' +
        '<div>' +
          '<div class="eyebrow" style="color:var(--text-3);margin-bottom:6px;">Total Match</div>' +
          '<div style="font-size:14px;color:var(--text);font-weight:600;">' + v.cmp.stats.matched + ' / ' + v.cmp.stats.requirements + ' 건 완벽 일치</div>' +
        '</div>' +
      '</div>' +
      '<div style="width:1px;height:48px;background:var(--line);"></div>' +
      '<div style="display:flex;gap:16px;flex:1;">' +
        v.cmpStatCards.map(function(s) {
          return '<div style="display:flex;align-items:center;gap:16px;padding:14px 20px;background:var(--panel);border-radius:var(--r-md);border:1px solid var(--line);flex:1;max-width:220px;box-shadow:var(--sh-1);">' +
            '<span style="width:12px;height:12px;border-radius:50%;background:' + s.color + ';box-shadow:0 0 10px ' + s.color + '60;"></span>' +
            '<div>' +
              '<div class="mono" style="font-size:22px;font-weight:800;color:var(--text);line-height:1.2;margin-bottom:2px;">' + s.count + '</div>' +
              '<div style="font-size:12px;color:var(--text-2);font-weight:600;">' + esc(s.label) + '</div>' +
            '</div>' +
          '</div>';
        }).join("") +
      '</div>' +
    '</div>';


    // 원문 미리보기는 아직 구현되지 않았다. 예전에는 여기에 가짜 요건([A-2] 카카오
    // 로그인, [B-2] MD5 적용 등)이 하드코딩돼 있어서, 진짜 분석 결과 옆에 지어낸
    // 지적이 나란히 보였다. 없는 것을 그럴듯하게 보여주느니 없다고 말하는 편이 낫다.
    // 문서 뷰어를 회색 캔버스 위에 뜬 카드로(단일 화면과 같은 톤). 간격은 행의 padding·gap이 준다.
    function comparePane(label, name, last) {
      return '<div style="flex:1;min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);display:flex;flex-direction:column;overflow:hidden;">' +
        '<div style="padding:14px 24px;background:var(--panel);border-bottom:1px solid var(--line);font-size:13px;font-weight:600;color:var(--text);display:flex;align-items:center;gap:10px;min-width:0;">' +
          ICONS.fileText + '<span style="flex:none;">' + esc(label) + '</span>' +
          '<span class="mono" style="font-weight:500;color:var(--text-3);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(name || "\u2014") + '</span>' +
        '</div>' +
        '<div style="flex:1;overflow:auto;padding:32px;display:flex;justify-content:center;align-items:center;">' +
          '<div style="max-width:300px;text-align:center;color:var(--text-3);font-size:13px;line-height:1.6;">' +
            '원문 미리보기는 아직 구현되지 않았습니다.<br>' +
            '분석 결과는 오른쪽 <b>비교 결과 내역</b>에 있습니다.' +
          '</div>' +
        '</div>' +
      '</div>';
    }

    var docAViewer = comparePane("기준 문서", v.cmp.docA && v.cmp.docA.name, false);
    var docBViewer = comparePane("비교 대상 문서", v.cmp.docB && v.cmp.docB.name, true);

    var issuesSidebar = '<div id="cIssuesPanel" style="width:380px;flex:none;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);display:' + (state.cIssuesCollapsed ? "none" : "flex") + ';flex-direction:column;overflow:hidden;z-index:10;">' +
      '<div style="padding:24px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">' +
        '<div style="font-weight:700;font-size:15px;color:var(--text);">불일치 내역 분석</div>' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="background:var(--bg);padding:4px 12px;border-radius:var(--r-xl);font-size:12px;font-weight:600;color:var(--text-3);">' + v.compareFindings.length + '건 발견</span>' +
          '<button class="hover-accent" data-act="toggleCIssues" title="패널 접기" style="flex:none;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:1px solid var(--line);background:var(--bg);border-radius:var(--r-sm);cursor:pointer;color:var(--text-3);">' + ICON_PANEL_CLOSE + '</button>' +
        '</div>' +
      '</div>' +
      '<div data-scroll="compareFindings" style="flex:1;overflow-y:auto;"><div style="padding:14px 16px;">' +
        v.compareFindings.map(function(f, i) {
           var pal = v.TM[f.type];
           return '<div data-act="cselect" data-arg="' + f.id + '" class="' + findingCardClass(f) +
             '" style="' + enterAnim(v, i) + '">' +
             '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
               solidBadge(pal.dot, f.typeLabel, false) +
               '<span style="font-variant-numeric:tabular-nums;font-size:11px;font-weight:600;color:var(--text-3);">' + esc(f.aLoc) + ' ↔ ' + esc(f.bLoc) + '</span>' +
             '</div>' +
             '<div style="font-size:14px;color:var(--text);line-height:1.6;font-weight:600;">' + esc(f.message) + '</div>' +
             // 단일 검토와 달리 여기엔 "수정안 만들기"를 두지 않는다. 비교 지적은
             // 두 문서 사이의 불일치라 어느 쪽 문장을 고쳐야 하는지가 정해지지
             // 않는다 — 한쪽을 골라 고쳐 쓰면 그게 곧 판단을 대신하는 것이다.
             // (예전엔 아무 동작도 없는 "제안 반영하기" 버튼이 놓여 있었다.)
             (f.open && f.suggestion ? expand(v.anim.copenedId === f.id,
                '<div style="margin-top:14px;padding:14px;background:var(--panel);border:1px solid var(--line-2);border-radius:var(--r-sm);"><div class="eyebrow" style="color:var(--accent-ink);margin-bottom:8px;">검토 지침</div><div style="font-size:13px;color:var(--text-2);line-height:1.6;">' + esc(f.suggestion) + '</div></div>') : '') +
           '</div>';
        }).join("") +
      '</div></div>' +
      '</div>' +
    '</div>';

    // 접었을 때 오른쪽 끝에 남는 얇은 레일. 클릭하면 다시 펼친다.
    var issuesRailC = '<div id="cIssuesRail" class="rail" data-act="toggleCIssues" title="불일치 내역 펼치기" style="z-index:10;display:' + (state.cIssuesCollapsed ? "flex" : "none") + ';">' +
      '<div class="rail-ico">' + ICON_PANEL_OPEN + '</div>' +
      '<div class="rail-label">불일치 ' + v.cTotalCount + '건</div>' +
    '</div>';

    // 단일과 동일하게 "목록으로 돌아가기"만 회색 캔버스에. 대시보드(커버리지·통계)는 유지.
    // 접으면 두 문서 뷰어가 그만큼 넓어진다.
    return '<div style="display:flex;flex-direction:column;height:100%;">' +
      '<div style="flex:none;padding:16px 32px 12px;display:flex;align-items:center;justify-content:space-between;gap:12px;">' +
        backLink("history", "목록으로 돌아가기") + newReviewLink("compare") + '</div>' +
      dashboard +
      '<div style="display:flex;flex:1;min-height:0;background:var(--bg);padding:4px 32px 12px;gap:24px;">' + docAViewer + docBViewer + issuesSidebar + issuesRailC + '</div>' +
    '</div>';
  }

  // 검토 기준 3층. 검토는 공통 ∪ 팀 ∪ 업로드를 합쳐 돌지만(resolve_criteria),
  // 화면에는 어디서 온 기준인지 갈라 보여야 한다 — 팀에 "이건 우리 기준이고
  // 저건 전사 공통"이라고 말할 수 있어야 하고, 고칠 수 있는 층도 업로드뿐이다.
  //
  // 항목마다 howChecked 를 단다. 기준은 수십 건인데 검사기가 실제로 받는 것은
  // 그중 일부다. 그 차이가 안 보이면 검토자는 "기준에 있으니 검사됐겠지"라고
  // 읽는다 — 이 도구가 낼 수 있는 최악의 거짓말이다.
  // [배경, 글자, 테두리]. 셋째 칸이 있는 이유는 **색만으로는 안 갈렸기** 때문이다 —
  // 웜 뉴트럴(규칙 · 자동)과 회색(사람이 확인)이 11px 칩에서 거의 같은 회색으로
  // 보였다. 그래서 색이 아니라 **꼴**로 가른다: 자동으로 도는 것은 면이 차고,
  // 사람 몫은 테두리만 남은 빈 칩이다(아직 아무도 안 채운 칸). 남은 색차도 같이
  // 벌렸다 — 규칙은 웜 브라운, 사람은 쿨 슬레이트다.
  // 글자는 --neutral-ink 다. --neutral-strong(Slate 200)은 **면** 색이라
  // 흰 바탕에서 1.14:1 로 사실상 안 보였다(팔레트 주석도 쓰지 말라고 적어 뒀다).
  var HOW_TONE = {
    "규칙 · 자동": ["var(--neutral-weak)", "var(--neutral-ink)", "transparent"],
    "LLM · 자동": ["var(--accent-weak)", "var(--accent-ink)", "transparent"],
    "사람이 확인": ["transparent", "var(--sev-info-fg)", "var(--sev-info-bd)"],
    "AI 꺼짐 · 미검토": ["var(--sev-min-bg)", "var(--sev-min-fg)", "transparent"]
  };

  var HOW_ORDER = ["규칙 · 자동", "LLM · 자동", "사람이 확인", "AI 꺼짐 · 미검토"];
  var ICON_CHEV = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';

  function howChip(label, n) {
    var t = HOW_TONE[label] || HOW_TONE["사람이 확인"];
    return '<span class="clay-chip" style="background:' + t[0] + ';color:' + t[1] +
        ';border-color:' + t[2] + ';">' +
      esc(label) + (n == null ? "" : '<b>' + n + '</b>') + '</span>';
  }

  // 항목 한 줄. 접히면 제목 + 상세 두 줄, 펼치면 상세 전문이다.
  // 담당 Agent·검사기 이름·출처(요구사항 xlsx 행 번호)는 여기 없다 — 셋 다 이
  // 화면을 보는 사람의 것이 아니었다(앞 둘은 코드 안 이름이고 오른쪽 칩이 이미
  // "자동인가 사람 몫인가"를 말한다, 출처는 기준을 **관리하는** 쪽이 되짚는
  // 값이다). 검증 대상은 줄마다 되풀이하는 대신 소제목이 진다(itemsHtml).
  // 값은 전부 yaml 에 그대로 있다.
  // 예전에는 note 의 **첫 줄만** 그렸다 — 기준 본문이 번호 매긴 여러 줄인데
  // 화면에는 1번만 보이고 나머지는 아무 데도 없었다. 검토자가 "이 기준이 무엇을
  // 요구하나"를 알 수 없으면 이 화면은 목록 흉내만 내는 셈이다.
  function criteriaItemRow(it, key, open) {
    var head = (it.text || "").trim();
    var note = (it.note || "").trim();
    // 접힌 줄은 **제목 한 줄**이다. 그래야 203 건이 한눈에 훑히는 체크리스트가
    // 되고, 기준 본문은 필요할 때 편다.
    //
    // "왜 어떤 줄은 눌리고 어떤 줄은 안 눌리나" — 실측(2026-08-20) 203 건 중
    // 114 건은 note 가 아예 없어 펼 것이 없다. 그 차이를 **화살표로 드러낸다**:
    // 화살표가 있으면 더 있는 것, 없으면 그게 전부다. 눌림 여부가 데이터에
    // 숨어 있으면 변덕으로 보이지만, 손잡이가 보이면 규칙으로 읽힌다.
    // (한때 본문 두 줄을 미리 보여주고 접었는데, 짧은 본문은 접어도 다 보여서
    //  누르면 줄만 바뀌었다. 제목만 남기면 그 어중간함이 사라진다.)
    var open = !!note && open;
    return '<div class="clay-row' + (note ? " is-fold" : "") + '"' +
        (note
          ? ' data-act="toggleCriteriaItem" data-arg="' + esc(key) + '"' +
            ' role="button" tabindex="0" aria-expanded="' + (open ? "true" : "false") + '"'
          : "") + '>' +
      // 번호는 팀마다 자릿수가 다르고, 층이 겹치면 "3(팀별)" 처럼 늘어난다 —
      // 고정 34px 에서는 두 줄로 접히거나 제목 위로 넘쳤다. 폭은 내용이 정하고
      // 34px 은 줄 맞춤을 위한 최소값으로만 남긴다(.clay-no).
      '<span class="clay-no">' + esc(it.no) + '</span>' +
      '<div style="flex:1;min-width:0;">' +
        (head ? '<div class="clay-title">' + esc(head) + '</div>' : "") +
        (open ? '<div class="clay-note">' + esc(note) + '</div>' : "") +
      '</div>' +
      // 검사 방식은 **글자로** 붙는다. 한때 왼쪽에 글리프(✓·사람·대시)만 두고
      // 이 칩을 뺐는데, 규칙 · 자동과 LLM · 자동이 둘 다 ✓ 로 같아져서 "규칙이
      // 확실히 잡는가, 모델 판단인가"가 화면에서 사라졌다 — 이 목록에서 제일
      // 알아야 하는 구분이다. 그림 하나로 못 가르는 것은 글자로 적는다.
      '<span class="clay-how">' + howChip(it.howChecked) + '</span>' +
      (note ? '<span class="clay-rowchev">' + ICON_CHEV + '</span>' : "") +
    '</div>';
  }



  // 검증 대상(yaml 의 group)으로 묶어 소제목을 세운다. 줄마다 "검증 대상 형식"
  // 을 되풀이하면 서른 줄에 같은 말이 서른 번 붙는데, 묶으면 그 자리가 목차가
  // 된다 — 체크리스트를 종이로 받으면 원래 이렇게 생겼다.
  // 순서는 yaml 에 나온 차례를 따른다(정렬하지 않는다 — 기준 파일의 순서가 곧
  // 팀이 정한 순서다). group 이 빈 항목(업로드 체크리스트가 그렇다)은 소제목
  // 없이 그 자리에 그대로 놓는다.
  function itemsHtml(L, items) {
    var order = [], bucket = Object.create(null);
    items.forEach(function (it) {
      var g = (it.group || "").trim();
      if (!bucket[g]) { bucket[g] = []; order.push(g); }
      var key = L.id + "|" + (it.no || "") + "|" + bucket[g].length;
      bucket[g].push(criteriaItemRow(it, key, !!state.clayers.openItem[key]));
    });
    return order.map(function (g) {
      return (g ? '<div class="clay-group">' + esc(g) +
                    '<span>' + bucket[g].length + '개</span></div>' : "") +
        bucket[g].join("");
    }).join("");
  }

  // how: 고른 검사 방식 필터("" = 전체). 검토 진행 중 모달도 이 카드를 쓰는데,
  // 거기엔 필터가 없어 인자를 안 넘긴다.
  function criteriaLayerCard(L, open, how) {
    var counts = {};
    L.items.forEach(function (i) { counts[i.howChecked] = (counts[i.howChecked] || 0) + 1; });
    var chips = HOW_ORDER.filter(function (k) { return counts[k]; })
      .map(function (k) { return howChip(k, counts[k]); }).join("");
    var items = how ? L.items.filter(function (i) { return i.howChecked === how; }) : L.items;
    var body = items.length
      ? itemsHtml(L, items)
      : '<div style="font-size:12px;color:var(--text-3);padding:10px 0;border-top:1px solid var(--line);">' +
          '이 층에는 ‘' + esc(how) + '’ 항목이 없습니다.</div>';
    return '<div class="clay-card">' +
      '<div class="clay-head" data-act="toggleCriteriaLayer" data-arg="' + esc(L.id) + '"' +
          ' role="button" tabindex="0" aria-expanded="' + (open ? "true" : "false") + '">' +
        '<span class="clay-scope">' + esc(L.scope) + '</span>' +
        '<div style="flex:1;min-width:0;">' +
          '<div class="clay-name">' + esc(L.name) + '</div>' +
          '<div class="clay-metarow">' +
            '<span class="clay-meta">항목 <b>' + L.items.length + '</b>개' +
              (L.editable ? "" : " · 읽기 전용") + '</span>' + chips +
          '</div>' +
        '</div>' +
        '<span class="clay-chev">' + ICON_CHEV + '</span>' +
      '</div>' +
      (open ? '<div class="clay-items">' + body + '</div>' : "") +
    '</div>';
  }

  function criteriaLayersSection(v) {
    var s = v.clayers;
    if (s.busy) return '<div style="font-size:13px;color:var(--text-3);padding:8px 0;">검토 기준을 읽는 중…</div>';
    if (s.error) return errorBanner(s.error);
    if (!s.list) return "";
    var readOnly = s.list.filter(function (L) { return !L.editable; });
    if (!readOnly.length) {
      return '<div style="font-size:12px;color:var(--text-3);padding:4px 0;">' +
        '고른 팀이 없어 팀 기준을 못 보여줍니다. 로그인하면 소속 팀 기준이 자동으로 걸립니다.</div>';
    }
    // 층을 가로지르는 합계. "공통 12 + 팀 30" 을 사람이 더하게 두지 않는다.
    var counts = {}, total = 0;
    readOnly.forEach(function (L) {
      L.items.forEach(function (i) { counts[i.howChecked] = (counts[i.howChecked] || 0) + 1; total++; });
    });
    var filters = '<button class="clay-fchip' + (s.how ? "" : " on") + '" data-act="setCriteriaHow" data-arg="">' +
        '전체 <b>' + total + '</b></button>' +
      HOW_ORDER.filter(function (k) { return counts[k]; }).map(function (k) {
        var t = HOW_TONE[k];
        return '<button class="clay-fchip' + (s.how === k ? " on" : "") + '" data-act="setCriteriaHow" data-arg="' + esc(k) + '">' +
          '<span class="dot" style="background:' + t[1] + ';"></span>' + esc(k) +
          ' <b>' + counts[k] + '</b></button>';
      }).join("");
    // 필터를 걸면 층을 **자동으로 편다**. 접힌 채로 두면 칩을 눌러도 화면이
    // 그대로라 필터가 죽은 것처럼 보인다.
    return '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 12px;">' + filters + '</div>' +
      '<div style="display:flex;flex-direction:column;gap:10px;">' +
        readOnly.map(function (L) {
          return criteriaLayerCard(L, !!s.open[L.id] || !!s.how, s.how);
        }).join("") +
      '</div>';
  }

  function checklistsView(v) {
    var header = pageHead("검토 기준", "검토는 공통 기준 + 소속 팀 기준 + 내가 올린 체크리스트를 합쳐 돕니다. 앞의 둘은 읽기 전용입니다.");

    // 단일 검토에서 "고르러" 왔으면 그 사실과 돌아가는 길을 위에 띄운다.
    // 고르면 곧장 돌아가지 않고 여기서 "선택됨"을 확인시킨 뒤, 돌아가기는
    // 사람이 누른다 — 버튼 누르자마자 화면이 튀면 순간이동처럼 어색하다.
    var pickedChecklist = (v.clib.list || []).filter(function (c) {
      return c.id === v.reviewChecklistId; })[0];
    var pickBanner = v.checklistPickReturn
      ? (pickedChecklist
          // 골랐을 때만 강조색을 칠한다 — 선택이 됐다는 신호다.
          ? '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;' +
              'padding:12px 16px;border-radius:var(--r-md);background:var(--accent-weak);border:1px solid var(--accent);">' +
              '<span style="font-size:13px;color:var(--accent-ink);font-weight:600;min-width:0;">' +
                '‘' + esc(pickedChecklist.name) + '’ 선택됨 — 이 기준으로 검토합니다.</span>' +
              '<button data-act="backToReviewFromChecklist" style="font-size:13px;background:var(--accent-surface);' +
                'color:#fff;border:none;border-radius:var(--r-sm);padding:8px 16px;cursor:pointer;font-weight:700;' +
                'white-space:nowrap;">검토로 돌아가기 →</button>' +
            '</div>'
          // 아직 안 골랐으면 색 없이 담백한 안내만 — 강조는 선택 신호로 아껴 둔다.
          : '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;' +
              'padding:12px 16px;border-radius:var(--r-md);background:transparent;border:1px solid var(--line);">' +
              '<span style="font-size:13px;color:var(--text-3);">' +
                '체크리스트를 고르면 단일 검토 화면으로 돌아갑니다.</span>' +
              '<span data-act="backToReviewFromChecklist" style="font-size:13px;color:var(--text-2);' +
                'cursor:pointer;font-weight:600;text-decoration:underline;white-space:nowrap;">← 검토로 돌아가기</span>' +
            '</div>')
      : '';

    // 올린 체크리스트도 **같은 카드**다 — 공통·팀별 층과 나란히 놓이는 것이라
    // 껍데기(.clay-card/.clay-head)와 글자 사다리를 그대로 쓴다. 예전에는 44px
    // 아이콘 칩에 15px 제목이라 혼자 다른 물건처럼 보였고, 높이도 층 카드와
    // 몇 px 씩 어긋나 목록이 흔들렸다.
    var rows = (v.clib.list || []).map(function (c) {
      return '<div class="clay-card">' +
        '<div class="clay-head" data-act="openChecklist" data-arg="' + esc(c.id) + '"' +
            ' role="button" tabindex="0">' +
          '<span class="clay-scope">업로드</span>' +
          '<div style="flex:1;min-width:0;">' +
            '<div class="clay-name">' + esc(c.name) + '</div>' +
            '<div class="clay-metarow">' +
              '<span class="clay-meta">' + esc(c.source_filename) +
                ' · 항목 <b>' + c.item_count + '</b>개</span>' +
            '</div>' +
          '</div>' +
          // 행 전체 클릭은 openChecklist(상세 보기)로 그대로 남긴다. 이 버튼들은
          // data-act 델리게이션이 closest("[data-act]")라 안쪽 버튼이 이겨 행
          // 클릭으로 새지 않는다.
          // 고르기 모드면 주 버튼은 "선택"(고르기만 하고 머문다 — 돌아가기는 위
          // 배너로). 고른 항목은 "✓ 선택됨"으로 표시한다. 그 외엔 "검토 시작"
          // (사람이 직접 채우는 독립 화면으로 간다).
          (v.checklistPickReturn
            ? (c.id === v.reviewChecklistId
                ? '<button class="btn btn-sm btn-primary" data-act="selectChecklistForReview" data-arg="' + esc(c.id) + '">✓ 선택됨</button>'
                : '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="selectChecklistForReview" data-arg="' + esc(c.id) + '">선택</button>')
            : '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="startChecklistRun" data-arg="' + esc(c.id) + '">검토 시작</button>') +
          '<button class="btn btn-sm btn-ghost" data-act="deleteChecklist" data-arg="' + esc(c.id) + '">삭제</button>' +
        '</div>' +
      '</div>';
    }).join("");

    // 업로드 드롭존의 그림들과 같은 계열 — 연한 채움 위에 같은 그라디언트로
    // 윤곽선을 얹는다(dropzone() 참고). 문서 폭·52px 상자·채움·윤곽·내부 선을
    // 일반 업로드와 같게 두어 체크리스트만 별도 아이콘 세트처럼 보이지 않게 한다.
    //
    // 그라디언트 id 는 그림마다 다르다 — 같은 id 를 두 번 쓰면 나중 것이 이기고,
    // 한 화면에 둘 다 있으므로 조용히 하나가 사라진다.
    function docGlyph(gradId, glyph) {
      var shape = 'M24 18 L57 18 L76 37 L76 78 A 4 4 0 0 1 72 82 L28 82 A 4 4 0 0 1 24 78 Z';
      var fold = 'M57 18 L57 32 A 5 5 0 0 0 62 37 L76 37 Z';
      return '<svg viewBox="0 0 100 100" style="width:52px;height:52px;margin:0 auto 12px;display:block;">' +
        '<defs><linearGradient id="' + gradId + '" x1="0%" y1="0%" x2="100%" y2="100%">' +
          '<stop offset="0%" stop-color="var(--accent-strong)" /><stop offset="100%" stop-color="var(--accent)" />' +
        '</linearGradient></defs>' +
        '<path d="' + shape + '" fill="url(#' + gradId + ')" opacity="0.15" />' +
        '<path d="' + fold + '" fill="url(#' + gradId + ')" opacity="0.25" />' +
        '<path d="' + shape + '" fill="none" stroke="url(#' + gradId + ')" stroke-width="2" stroke-linejoin="round" opacity="0.40" />' +
        '<path d="' + fold + '" fill="none" stroke="url(#' + gradId + ')" stroke-width="2" stroke-linejoin="round" opacity="0.40" />' +
        '<path d="' + glyph + '" stroke="var(--accent)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" />' +
      '</svg>';
    }
    // 올리는 것은 위 화살표, 직접 쓰는 것은 더하기 — 문서 모양은 같이 쓴다.
    var attachIcon = docGlyph("upDocGrad2", "M50 44 L50 64 M41 53 L50 44 L59 53");
    var writeIcon = docGlyph("writeDocGrad", "M50 44 L50 64 M41 54 L59 54");

    var actionCards = '<div style="display:flex;gap:16px;margin-top:8px;">' +
      '<div data-act="openChecklistFile" style="flex:1;border:2px dashed var(--line-dashed);border-radius:var(--r-lg);background:var(--panel);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);padding:28px 20px;text-align:center;cursor:pointer;" onmouseover="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--state-hover-brand)\'" onmouseout="this.style.borderColor=\'var(--line-dashed)\';this.style.background=\'var(--panel)\'">' +
        attachIcon +
        '<div style="font-weight:700;font-size:15px;color:var(--text);">파일 첨부</div>' +
        '<div style="font-size:12px;color:var(--text-3);margin-top:6px;">.pdf, .xlsx, .csv 업로드</div>' +
        '<input type="file" id="file-checklist" accept=".pdf,.xlsx,.csv" style="display:none;">' +
      '</div>' +
      '<div data-act="writeChecklist" style="flex:1;border:2px dashed var(--line-dashed);border-radius:var(--r-lg);background:var(--panel);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);padding:28px 20px;text-align:center;cursor:pointer;" onmouseover="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--state-hover-brand)\'" onmouseout="this.style.borderColor=\'var(--line-dashed)\';this.style.background=\'var(--panel)\'">' +
        writeIcon +
        '<div style="font-weight:700;font-size:15px;color:var(--text);">직접 작성</div>' +
        '<div style="font-size:12px;color:var(--text-3);margin-top:6px;">웹에서 새 체크리스트 작성</div>' +
      '</div>' +
    '</div>';

    return '<div class="page-shell page-shell-primary" data-scroll="clib">' +
      '<div class="page-container page-stack">' +
        pickBanner + header + errorBanner(v.clib.error) +
        (v.clibPreview ? clibPreviewCard(v)
          : v.clibDetail ? clibDetailCard(v)
          : (criteriaLayersSection(v) +
             '<div class="eyebrow" style="color:var(--text-3);margin:18px 0 2px;">내가 올린 체크리스트</div>' +
             rows + actionCards)) +
      '</div>' +
    '</div>';
  }

  // 등록 전 확인 카드. 추측을 조용히 채택하지 않는다.
  function clibPreviewCard(v) {
    var p = v.clibPreview;
    var tabs = p.tables.length > 1
      ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;">' +
          p.tables.map(function (t, i) {
            return '<button data-act="pickChecklistTable" data-arg="' + i + '" style="padding:6px 10px;font-size:12px;border-radius:var(--r-sm);cursor:pointer;border:1px solid ' +
              (i === p.picked ? "var(--accent)" : "var(--line)") + ';background:' +
              (i === p.picked ? "var(--accent-weak)" : "var(--panel)") + ';">' +
              esc(t.label || ("표 " + (i + 1))) + '</button>';
          }).join("") +
        '</div>'
      : "";

    var picker = '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0;">' +
      '<span style="font-size:13px;color:var(--text-3);">항목 내용 열:</span>' +
      p.header.map(function (h, i) {
        var on = p.columns.text === i;
        return '<button data-act="setChecklistColumn" data-arg="text:' + i + '" style="padding:6px 10px;font-size:12px;border-radius:var(--r-sm);cursor:pointer;border:1px solid ' +
          (on ? "var(--accent)" : "var(--line)") + ';background:' + (on ? "var(--accent-weak)" : "var(--panel)") + ';">' +
          (i + 1) + '. ' + esc(h || "(빈 제목)") + '</button>';
      }).join("") +
    '</div>';

    var verdictLine = p.textLabel
      ? '<div style="padding:10px 14px;border-radius:var(--r-sm);background:rgba(16,185,129,0.08);border-left:3px solid #10B981;font-size:13px;">' +
          esc(p.textLabel) + ' 을 <b>항목 내용</b>으로 읽었습니다.' +
          (p.stale ? '' : ' 항목 ' + p.itemCount + '개.') +
        '</div>'
      : '<div style="padding:10px 14px;border-radius:var(--r-sm);background:rgba(239,68,68,0.08);border-left:3px solid #EF4444;font-size:13px;">' +
          '어느 열이 항목 내용인지 알아내지 못했습니다. 아래에서 골라주세요.' +
        '</div>';

    // 고른 열이 서버의 처음 추측과 달라졌으면, 그 추측대로 읽은 옛 표본을
    // 새로 고른 열의 것처럼 보여주지 않는다 — 등록을 누르면 이 열로 다시
    // 읽는다는 사실만 정직하게 알린다.
    var sample = p.stale
      ? '<div style="font-size:13px;color:var(--text-3);padding:8px 0;">' +
          '고른 열로 다시 읽으면 등록 시 반영됩니다.' +
        '</div>'
      : p.sample.map(function (s) {
          return '<div style="font-size:13px;padding:6px 0;border-bottom:1px solid var(--line);">' +
            '<span style="color:var(--text-3);margin-right:8px;">' + esc(s.no || "-") + '</span>' + esc(s.text) + '</div>';
        }).join("");

    return '<div class="surface-work" style="padding:22px;">' +
      '<div style="font-weight:700;font-size:15px;margin-bottom:12px;">' + esc(p.name) + '</div>' +
      tabs + verdictLine + picker +
      '<div style="margin:10px 0 16px;">' + sample + '</div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
        '<button class="btn btn-ghost btn-ghost-accent" data-act="cancelChecklist">취소</button>' +
        '<button class="btn btn-primary" data-act="registerChecklist">등록</button>' +
      '</div>' +
    '</div>';
  }

  // 등록된 체크리스트 상세. 이름과 개수만으로는 무엇이 등록됐는지 알 수 없고,
  // 열을 틀리게 골라 등록한 것도 열어봐야 드러난다.
  function clibDetailCard(v) {
    var c = v.clibDetail;
    var rows = (c.items || []).map(function (it) {
      return '<div style="padding:10px 0;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:10px;">' +
        '<span class="mono" style="color:var(--text-3);min-width:34px;white-space:nowrap;">' + esc(it.no || "-") + '</span>' +
        (it.group ? '<span style="color:var(--accent-ink);min-width:70px;">' + esc(it.group) + '</span>' : '') +
        '<span style="flex:1;">' + esc(it.text) + '</span>' +
      '</div>';
    }).join("");
    return '<div class="surface-work" style="padding:22px;">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">' +
        '<div style="font-weight:700;font-size:15px;">' + esc(c.name) + '</div>' +
        '<div style="font-size:12px;color:var(--text-3);">항목 ' + (c.items || []).length + '개</div>' +
        '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="closeChecklist" style="margin-left:auto;">닫기</button>' +
      '</div>' + rows +
    '</div>';
  }

  var VERDICT_CHOICES = ["Satisfied", "Modification Required", "Not Satisfied", "N/A"];

  // 검토 전에 고르는 자리. **이름을 분명히 갈라야 한다** — 같은 화면에 이미
  // "자동 검토 기준"(엔진이 쓰는 id_pattern·required_sections)이 있다.
  // 이건 사람이 직접 항목을 채우는 것이라 "직접 확인할 체크리스트"로 부른다.
  // 항목 목록 렌더(독립 체크리스트 화면 checklistRunScreen 안에서 쓴다).
  // 자동 검토(rev)와 독립이라 LLM 을 기다리지 않는다 — 등록된 체크리스트를
  // 라이브러리에서 "검토 시작"한 순간 바로 항목이 뜬다.
  function checklistRunView(v) {
    if (!v.crun) return '<div style="padding:24px;color:var(--text-3);">검토 기준을 고르면 항목이 나옵니다.</div>';
    var head = '<div style="display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line);">' +
      '<div style="font-weight:700;">' + esc(v.crun.name) + '</div>' +
      '<div style="font-size:13px;color:' + (v.crun.unjudged ? "#EF4444" : "var(--text-3)") + ';">' +
        (v.crun.unjudged ? ('미판정 ' + v.crun.unjudged + '개 남음') : '전부 판정함') + '</div>' +
      '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="saveChecklistRun" style="margin-left:auto;">' +
        (v.crun.saving ? '저장 중…' : '저장') + '</button>' +
      '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="exportChecklistCsv">CSV 내보내기</button>' +
    '</div>';

    var rows = v.crun.items.map(function (it) {
      // data-arg/data-reason 은 it.no 가 아니라 it.idx(배열 위치)를 싣는다 —
      // no 는 비어 있거나(전부 "") 겹칠 수 있고 "|" 를 포함할 수도 있어 식별자로
      // 쓸 수 없다. 화면에 보이는 번호(it.no)는 그대로 둔다.
      var choices = VERDICT_CHOICES.map(function (w) {
        var on = it.verdict === w;
        return '<button data-act="setVerdict" data-arg="v|' + esc(it.idx) + '|' + esc(w) + '" style="padding:4px 10px;font-size:11px;font-weight:600;border-radius:var(--r-sm);cursor:pointer;border:1px solid ' +
          (on ? "var(--accent)" : "var(--line)") + ';background:' + (on ? "var(--accent-weak)" : "var(--panel)") + ';">' + esc(w) + '</button>';
      }).join("");
      return '<div style="padding:12px 20px;border-bottom:1px solid var(--line);">' +
        '<div style="font-size:13px;margin-bottom:6px;">' +
          '<span style="color:var(--text-3);margin-right:8px;">' + esc(it.no || "-") + '</span>' + esc(it.text) + '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">' + choices + '</div>' +
        '<input data-reason="' + esc(it.idx) + '" value="' + esc(it.reason) + '" placeholder="이유 (결론과 근거를 함께 적습니다)" ' +
          'style="width:100%;padding:6px 10px;font-size:12px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--bg);color:var(--text);">' +
      '</div>';
    }).join("");

    return '<div data-scroll="crun" style="height:100%;overflow:auto;background:var(--panel);">' + head + rows + '</div>';
  }

  // 체크리스트를 채우는 독립 화면. 라이브러리 "검토 시작"(startChecklistRun)
  // 또는 기록에서 이어서(openHistory, kind==="checklist") 열 때 둘 다 여기로
  // 온다 — 자동 검토(단일 검토 결과 화면)와 완전히 분리했다. checklistRunView가
  // 저장·CSV·미판정개수를 이미 갖춘 자기 완결형이라 여기선 뒤로가기와 헤더만
  // 얹는다.
  function checklistRunScreen(v) {
    var c = v.crun;
    // 라이브러리에서 왔으면 라이브러리로, 기록에서 이어서 열었으면 기록으로
    // — 다른 곳으로 돌아가면 "뒤로"라는 말이 거짓말이 된다.
    var fromHistory = !!(c && c.from === "history");
    var docName = c && c.documentName;
    return '<div class="page-shell" data-scroll="checklistrun">' +
      '<div class="page-container page-stack" style="max-width:820px;min-height:0;">' +
        backLink(fromHistory ? "history" : "checklists", fromHistory ? "기록으로" : "라이브러리로") +
        errorBanner(c && c.error) +
        '<div style="background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg);padding:20px 24px;flex:none;">' +
          '<div style="font-weight:700;font-size:18px;margin-bottom:6px;">' + esc(c ? c.name : "") + '</div>' +
          '<div style="font-size:13px;color:var(--text-3);margin-bottom:12px;">검토 대상 문서: ' + (docName ? esc(docName) : "(지정 안 함)") + '</div>' +
          '<input data-checklist-doc value="' + esc(docName || "") + '" placeholder="검토 대상 문서명 (선택)" ' +
            'style="width:100%;padding:8px 12px;font-size:13px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--bg);color:var(--text);box-sizing:border-box;">' +
        '</div>' +
        '<div style="flex:1;min-height:0;border:1px solid var(--line);border-radius:var(--r-lg);overflow:hidden;">' + checklistRunView(v) + '</div>' +
      '</div>' +
    '</div>';
  }

  function historyView(v) {
    // 페이지 헤더 관용구(pageHead)와 같은 꼴인데, 오른쪽에 동작 버튼이 붙어
    // 구분선까지 한 판으로 두른다 — 제목 서체·크기·부제·선은 같은 규격.
    var header = '<div style="display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid var(--line);padding-bottom:14px;">' +
      '<div>' +
        '<h1 class="headline" style="font-size:22px;font-weight:700;color:var(--text);margin:0;letter-spacing:-.4px;">최근 검토 기록</h1>' +
        '<p style="font-size:13px;color:var(--text-3);margin:6px 0 0;">과거에 분석한 문서들의 요약 및 상세 결과를 언제든 다시 확인하세요.</p>' +
      '</div>' +
      '<div style="display:flex;gap:8px;">' +
        '<button class="btn btn-ghost btn-ghost-accent" data-act="reloadHistory">새로고침 ⟳</button>' +
        // 기록이 있을 때만 낸다 — 비어 있는데 "전체 삭제"가 있으면 누를 것이 없다.
        // 하나씩 지우면 스무 건에 스무 번을 눌러야 한다.
        ((state.history || []).length
          ? '<button class="btn btn-ghost btn-danger-ghost" data-act="askDeleteAll">전체 삭제</button>' : "") +
      '</div>' +
    '</div>';

    // 서버에 저장된 진짜 이력. 목업 목록은 지웠다 — 검토한 적 없는 문서가 "완료"로
    // 떠 있으면, 진짜 결과와 구별할 방법이 없다.
    var rows = (function () {
      var empty = function (msg) {
        return '<div style="padding:56px 24px;text-align:center;color:var(--text-3);' +
          'font-size:14px;background:var(--panel);"><svg viewBox="0 0 100 100" style="width:100px;height:100px;margin:0 auto 16px;display:block;opacity:0.8;">  <defs>    <linearGradient id="emGrad" x1="0%" y1="0%" x2="100%" y2="100%">      <stop offset="0%" stop-color="var(--line-2)" />      <stop offset="100%" stop-color="var(--line)" />    </linearGradient>  </defs>  <rect x="25" y="20" width="50" height="60" rx="6" fill="url(#emGrad)" opacity="0.3"/>  <rect x="25" y="20" width="50" height="60" rx="6" fill="none" stroke="var(--text-3)" stroke-width="3" stroke-dasharray="6 4"/>  <circle cx="50" cy="45" r="14" fill="none" stroke="var(--text-3)" stroke-width="3" />  <line x1="60" y1="55" x2="68" y2="63" stroke="var(--text-3)" stroke-width="4" stroke-linecap="round" /></svg>' + msg + '</div>';
      };
      if (state.history === null) return empty("불러오는 중…");
      // 홈과 같은 구분이다(appHomeView). 못 읽은 것을 빈 목록으로 그리면 이 화면은
      // 존재하는 기록을 "없다"고 말한다 — 여기는 기록이 전부인 화면이라 더 나쁘다.
      if (state.historyError) {
        return empty('검토 기록을 불러오지 못했습니다.<br>' +
          '<span style="font-size:13px;">기록이 없는 것이 아니라, 지금 읽지 못한 것입니다.</span>' +
          '<br><button class="btn btn-ghost btn-ghost-accent" data-act="reloadHistory" ' +
            'style="margin-top:14px;font-size:13px;padding:8px 16px;">다시 시도</button>');
      }
      if (!state.history.length) {
        return empty("아직 검토한 문서가 없습니다.<br>" +
          '<span style="font-size:13px;">단일 검토나 비교 검토를 실행하면 결과가 여기에 남습니다.</span>');
      }
      return state.history.map(function (h) {
        var isCompare = h.kind === "compare";
        var kind = isCompare ? "다중 문서 교차 비교" : "단일 정밀 검토";
        var n = h.findings || 0;
        var dot = n ? "#CA8A04" : "#16A34A";
        // 행 전체가 결과로 가는 클릭 대상이다 — 홈의 최근 검토 행(.hrow)과 같은 규칙.
        // 예전엔 삭제 버튼 오클릭이 걱정돼 행 클릭을 뺐는데, 그러면 홈에서 행을 눌러
        // 들어오던 사용자가 여기선 클릭이 씹혀 "모두 보기"가 막다른 길이 됐다.
        // 핸들러가 closest("[data-act]")로 누른 지점부터 위로 올라가므로(app.js:780)
        // 결과 보기/삭제 버튼은 행보다 먼저 잡힌다 — 오클릭 걱정은 구조가 이미 막는다.
        //
        // background 를 인라인으로 두지 않는다 — 인라인이 :hover 클래스를 이기므로
        // 호버 배경이 죽는다. 배경은 index.html의 .hrow-flush:hover가 칠한다.
        var iconHtml = isCompare
          ? '<div style="width:44px;height:44px;border-radius:var(--r-md);background:var(--neutral-weak);color:var(--neutral);display:flex;align-items:center;justify-content:center;flex:none;font-size:22px;">' + ICONS.compare + '</div>'
          : docShapeIcon(h.title, 44, 'accent');

        return '<div class="hrow-flush" data-act="openHistory" data-arg="' + esc(h.id) + '" ' +
            'style="display:flex;align-items:center;gap:20px;padding:20px 24px;' +
            'border-bottom:1px solid var(--line-2);">' +
          iconHtml +
          '<div style="flex:1;min-width:0;">' +
            '<div class="history-doc-title" style="margin-bottom:6px;overflow:hidden;' +
              'text-overflow:ellipsis;white-space:nowrap;">' + esc(h.title) + '</div>' +
            '<div style="display:flex;align-items:center;gap:12px;">' +
              '<span class="history-doc-meta" style="font-weight:600;background:var(--bg);padding:4px 10px;' +
                'border-radius:var(--r-sm);border:1px solid var(--line);">' + kind + '</span>' +
              '<span style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--text-2);">' +
                '<span style="width:8px;height:8px;border-radius:50%;background:' + dot + ';"></span>' +
                (n ? n + "건 지적" : "지적 없음") + '</span>' +
            '</div>' +
          '</div>' +
          '<div style="text-align:right;flex:none;">' +
            '<div class="history-doc-meta" style="font-weight:600;margin-bottom:8px;">' + esc(ago(h.at)) + '</div>' +
            // 두 버튼 모두 자기 data-act를 갖는다. 클릭 핸들러가 closest("[data-act]")로
            // 눌린 버튼을 고르므로 결과 보기/삭제가 각각 제 동작을 한다.
            '<button class="btn btn-sm btn-ghost btn-ghost-accent" data-act="openHistory" data-arg="' + esc(h.id) + '">결과 보기 ' + ICONS.arrowRight + '</button>' +
            '<button class="btn btn-sm btn-ghost btn-danger-ghost" data-act="askDeleteHistory" data-arg="' + esc(h.id) + '" style="margin-left:6px;">삭제</button>' +
          '</div>' +
        '</div>';
      }).join("");
    })();

    // 삭제 확인 모달. 행의 삭제 버튼(askDeleteHistory)이 state.confirmDelete를 채우면 뜬다.
    // searchModal과 같은 오버레이 방식 — 바깥 클릭이나 취소로 닫고, "삭제"가 실제로 지운다.
    var confirmModal = "";
    if (state.confirmDelete) {
      var cd = state.confirmDelete;
      confirmModal =
        '<div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.28);' +
          'backdrop-filter:blur(2px);z-index:1000;display:flex;align-items:center;justify-content:center;' +
          'animation:fadeIn .15s ease-out forwards;" ' +
          'onclick="if(event.target===this){var b=document.getElementById(\'cancelDeleteBtn\');if(b)b.click();}">' +
          '<div style="background:var(--panel);border:1px solid var(--line);border-radius:var(--r-lg);' +
            'box-shadow:0 24px 60px rgba(0,0,0,0.24);width:400px;max-width:90vw;padding:26px 28px;' +
            'animation:fadeUp .2s var(--ease-out) forwards;">' +
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">' +
              '<span style="display:flex;align-items:center;justify-content:center;width:40px;height:40px;' +
                'border-radius:var(--r-md);background:var(--sev-crit-bg);color:var(--sev-crit-fg);font-size:20px;flex:none;">' + ICONS.alert + '</span>' +
              '<h3 style="margin:0;font-size:18px;font-weight:700;color:var(--text);letter-spacing:-0.3px;">검토 기록 삭제</h3>' +
            '</div>' +
            '<p style="margin:0 0 22px;font-size:14px;line-height:1.6;color:var(--text-2);">' +
              '<b style="color:var(--text);">' + esc(cd.title) + '</b>' +
              (cd.all ? '을 모두 삭제할까요?' : ' 기록을 삭제할까요?') + '<br>' +
              '삭제한 기록은 복구할 수 없습니다.</p>' +
            '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
              '<button id="cancelDeleteBtn" data-act="cancelDelete" class="btn btn-lg btn-ghost btn-ghost-accent">취소</button>' +
              '<button class="btn btn-lg btn-danger" data-act="deleteHistory" data-arg="' + esc(cd.id) + '">삭제</button>' +
            '</div>' +
          '</div>' +
        '</div>';
    }

    return '<div class="page-shell page-shell-primary" data-scroll="history"><div class="page-container page-stack">' +
      header +
      '<div class="surface-list">' +
        '<div style="background:var(--bg);padding:14px 24px;border-bottom:1px solid var(--line);display:flex;font-size:12px;font-weight:600;color:var(--text-3);">' +
          '<div style="flex:1;">문서 및 결과 요약</div>' +
          '<div style="width:140px;text-align:right;padding-right:8px;">분석 일시</div>' +
        '</div>' +
        rows +
      '</div>' +
      confirmModal +
    '</div></div>';
  }
  function settingsView(v) {
    var header = pageHead("환경 설정", "기본 동작 방식, AI 엔진 옵션 및 외부 연동을 설정합니다.");

    var toggleOn = '<div style="width:40px;height:24px;background:var(--accent);border-radius:var(--r-md);position:relative;cursor:pointer;"><div style="width:18px;height:18px;background:#FFF;border-radius:50%;position:absolute;top:3px;right:3px;box-shadow:0 2px 4px rgba(0,0,0,0.2);"></div></div>';
    var toggleOff = '<div style="width:40px;height:24px;background:var(--line-2);border-radius:var(--r-md);position:relative;cursor:pointer;"><div style="width:18px;height:18px;background:#FFF;border-radius:50%;position:absolute;top:3px;left:3px;box-shadow:0 2px 4px rgba(0,0,0,0.1);"></div></div>';

    var llm = "";
    if (!v.llmChips.length) {
      llm = '<span style="font-size:12px;color:var(--text-3);">' + esc(v.llmNote) + '</span>';
    } else {
      var aiOn = false;
      var modelName = "";
      for (var i = 0; i < v.llmChips.length; i++) {
        if (v.llmChips[i].k === "on") {
          aiOn = v.llmChips[i].on;
          modelName = v.llmChips[i].label;
        }
      }
      var toggleHtml = aiOn ? toggleOn : toggleOff;
      var nextState = aiOn ? "off" : "on";
      llm = '<div style="display:flex;align-items:center;gap:12px;cursor:pointer;" data-act="setLlm" data-arg="' + nextState + '">' + toggleHtml + '<span style="font-size:13px;font-weight:600;color:var(--text-2);">' + esc(modelName) + '</span></div>';
    }

    function sectionGroup(title, rows) {
      return '<div>' +
        '<div class="eyebrow" style="color:var(--text-3);margin-bottom:12px;padding-left:4px;">' + esc(title) + '</div>' +
        '<div class="surface-list">' + rows.join('<div style="height:1px;background:var(--line-2);"></div>') + '</div>' +
      '</div>';
    }

    function settingRow(label, desc, control) {
      return '<div style="display:flex;align-items:center;padding:20px 24px;">' +
        '<div style="flex:1;">' +
          '<div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:4px;">' + esc(label) + '</div>' +
          '<div style="font-size:13px;color:var(--text-3);">' + esc(desc) + '</div>' +
        '</div>' +
        '<div style="flex:none;margin-left:24px;">' + control + '</div>' +
      '</div>';
    }

    var lchip = state.theme === "light" ? "background:var(--accent-weak);color:var(--accent-ink);" : "background:var(--bg);color:var(--text-3);";
    var dchip = state.theme === "dark" ? "background:var(--accent-weak);color:var(--accent-ink);" : "background:var(--bg);color:var(--text-3);";
    
    var generalRows = [
      settingRow('테마 모드', '화면의 기본 밝기 테마를 설정합니다.', '<div style="display:flex;gap:4px;"><span class="chip" data-act="setTheme" data-arg="light" style="' + lchip + 'font-size:13px;font-weight:600;padding:6px 12px;border-radius:var(--r-sm);cursor:pointer;">라이트</span><span class="chip" data-act="setTheme" data-arg="dark" style="' + dchip + 'font-size:13px;font-weight:600;padding:6px 12px;border-radius:var(--r-sm);cursor:pointer;">다크</span></div>'),
      settingRow('언어 (Language)', '인터페이스의 기본 언어를 변경합니다.', '<select style="padding:8px 12px;border-radius:var(--r-sm);border:1px solid var(--line);background:var(--bg);color:var(--text);font-size:13px;font-weight:600;cursor:pointer;"><option>한국어</option><option>English</option></select>')
    ];

    var aiRows = [
      settingRow('AI 검토', '끄면 규칙 검사만 돌아 훨씬 빠릅니다. 켜면 표현 불일치·모순까지 봅니다. 모델은 서버가 정합니다.', '<div style="display:flex;gap:6px;align-items:center;">' + llm + '</div>'),
      settingRow('문서 파싱 청크 크기', '한 번에 분석할 텍스트 덩어리의 크기입니다.', '<div style="display:flex;align-items:center;gap:8px;"><input type="text" value="4000" style="width:60px;padding:6px;text-align:center;border-radius:var(--r-sm);border:1px solid var(--line);background:var(--bg);font-family:inherit;font-size:13px;color:var(--text);font-weight:600;"><span style="font-size:12px;color:var(--text-3);">chars</span></div>')
    ];

    var intRows = [
      settingRow('이메일 리포트 수신', '검토가 완료되면 계정 이메일로 결과를 전송합니다.', toggleOn),
      settingRow('Slack 알림 연동', 'Workspace의 지정된 슬랙 채널로 상태 알림을 보냅니다.', toggleOff)
    ];

    return '<div class="page-shell page-shell-primary" data-scroll="settings"><div class="page-container page-stack">' +
      header +
      sectionGroup('일반 설정 (General)', generalRows) +
      sectionGroup('AI 검토 엔진 (AI Engine)', aiRows) +
      sectionGroup('알림 및 연동 (Integrations)', intRows) +
    '</div></div>';
  }


  function appHomeView(v) {
    // 홈 진입 — 벤토 타일 여섯이 한꺼번에 튀어나오면 무엇부터 볼지가 안 잡힌다.
    // 50ms 씩 어긋내면 격자가 읽히는 순서대로 앉는다. 결과 목록의 enterAnim 과
    // **같은 기계에 같은 관용구**다(listIn: 10px 올라오며 나타남) — 화면에 들어올
    // 때만 돌고, 음수 지연으로 재렌더에서 안 되감긴다.
    // 3D 로 꺾어 봤다가 물렸다: 타일에서는 몰라도 화면 전체가 같이 돌면 과했다.
    var tileEnter = function (i) {
      if (!v.anim.entered) return "";
      var delay = Math.max(0, Math.min(i * 50, 250) - v.anim.enterElapsed);
      return "animation:listIn .3s var(--ease-out) backwards;animation-delay:" + delay + "ms;";
    };

    // 최근 검토: 서버에 저장된 진짜 이력이다.
    //
    // 예전에는 여기에 그럴듯한 목업 4건(B2B 플랫폼 요구사항 정의서.pdf 등)이 박혀
    // 있었다. 한 번도 검토한 적 없는 문서들이 "완료"로 떠 있었던 셈이다. 없는 것을
    // 지어내 보여주느니 "아직 없다"고 말하는 편이 낫다.
    var recentItems = (function () {
      var empty = function (msg) {
        // 아이콘이 옅은 브랜드 면 위에 앉는다. 예전엔 회색 아이콘을 opacity .3 으로
        // 흐려 놨는데, 그러면 "아직 안 했다"가 아니라 "고장났다"로 읽힌다 —
        // 빈 화면은 죽은 화면과 구별되어야 한다.
        // 초록(이상 없음)이나 주황을 쓰면 빈 목록이 판정처럼 보인다 — 아무것도
        // 안 한 상태는 판정이 아니다. 그래서 상태색이 아니라 브랜드색을 옅게 쓴다.
        return '<div class="home-empty">' +
          '<div class="home-empty-icon">' +
            ICONS.fileText.replace('width="1em" height="1em"', 'width="26" height="26"') + '</div>' +
          '<div class="home-empty-copy">' + msg + '</div>' +
          '</div>';
      };
      if (state.history === null) return empty("불러오는 중…");
      // **못 읽은 것과 없는 것은 다른 말이다.** 실패를 빈 목록으로 그리면, 검토를
      // 스무 건 한 사람에게 화면이 "아직 없습니다"라고 거짓말한다. 다시 시도할
      // 길도 같이 준다 — 상태만 말하고 손잡이가 없으면 새로고침밖에 답이 없다.
      if (state.historyError) {
        return '<div style="padding:40px 0;text-align:center;">' +
          '<div style="font-size:14px;font-weight:600;color:var(--text-2);">' +
            '검토 기록을 불러오지 못했습니다</div>' +
          '<div style="margin-top:6px;font-size:12px;color:var(--text-3);">' +
            '기록이 없는 것이 아니라, 지금 읽지 못한 것입니다.</div>' +
          '<button class="btn btn-ghost btn-ghost-accent" data-act="reloadHistory" ' +
            'style="margin-top:14px;font-size:12px;padding:8px 14px;">다시 시도</button>' +
        '</div>';
      }
      if (!state.history.length) {
        return empty("아직 검토한 문서가 없습니다.") +
          // 빈 화면은 "무엇을 하면 채워지는가"를 말해야 한다(위 시작 타일로 잇는다).
          '<div style="margin-top:-32px;text-align:center;font-size:12px;' +
            'color:var(--text-3);padding-bottom:12px;">위에서 검토를 시작하면 여기에 남습니다.</div>';
      }

      return state.history.slice(0, 6).map(function (h) {
        var isCompare = h.kind === "compare";
        var kind = isCompare ? "다중 문서 교차 비교" : "단일 정밀 검토";
        var n = h.findings || 0;
        // 글자는 --accent-ink(다크에서 밝아짐), 배경 틴트는 별도 토큰.
        // 예전엔 background 에 col+"22" 로 알파를 붙였는데, 그 hex 접미사 수법은
        // 리터럴(#10B98122)에만 통하고 var() 뒤에 붙으면 값이 무효가 돼 배경이 통째로
        // 사라진다 — "N건 지적" 칩만 배경 없이 뜨던 원인이었다.
        var col = n ? "var(--accent-ink)" : "var(--band-good-fg)";
        var colBg = n ? "var(--accent-weak)" : "var(--band-good-bg)";
        var label = n ? (n + "건 지적") : "지적 없음";
        // 호버 배경은 index.html의 .hrow:hover에 맡긴다 — 인라인 background 는
        // :hover 를 이겨 버린다.
        var iconHtml = isCompare
          ? '<div style="width:40px;height:40px;border-radius:var(--r-md);background:var(--neutral-weak);color:var(--neutral);display:flex;align-items:center;justify-content:center;flex:none;font-size:20px;">' + ICONS.compare + '</div>'
          : docShapeIcon(h.title, 40, 'accent');

        return '<div class="hrow" data-act="openHistory" data-arg="' + esc(h.id) + '" ' +
            'style="display:flex;align-items:center;justify-content:space-between;">' +
          '<div class="history-row-main">' +
            iconHtml +
            '<div style="min-width:0;">' +
              '<div class="history-doc-title" style="overflow:hidden;' +
                'text-overflow:ellipsis;white-space:nowrap;">' + esc(h.title) + '</div>' +
              '<div class="history-doc-meta" style="margin-top:4px;">' +
                kind + ' · ' + esc(ago(h.at)) + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="history-row-tail">' +
            '<div class="history-count" style="flex:none;' +
              'background:' + colBg + ';color:' + col + ';">' + label + '</div>' +
            '<div class="history-row-arrow">' + ICONS.arrowRight + '</div>' +
          '</div>' +
        '</div>';
      }).join("");
    })();

    // "모두 보기"는 홈이 못 보여준 게 실제로 있을 때만 낸다. 홈은 slice(0,6)으로 6건을
    // 그리므로 이력이 6건 이하면 기록 화면은 같은 목록이다 — 눌러도 새 정보가 없는
    // 헛걸음이라, 없는 "더"를 약속하지 않는다.
    var seeAllLink = (state.history && state.history.length > 6)
      ? '<button type="button" class="btn btn-sm btn-primary home-see-all" data-act="setMode" data-arg="history">모두 보기 ' + ICONS.arrowRight + '</button>'
      : '';

    // 검토 기준: 서버가 "지금 적용 중"이라고 답한 값만 보여준다.
    //
    // 예전에는 여기에 목업 3종(Generic / PRD / API Spec)이 박혀 있었다. 서버가
    // 실제로는 데모용 체크리스트(id_pattern: SR-\d+)를 쓰고 있어도 화면은 그럴듯한
    // 카드를 띄웠고, 결과는 조용히 0건이 나왔다. 무슨 잣대로 재는 중인지 화면에서
    // 확인할 방법이 없었던 것이 문제의 핵심이었다.

    // 벤토 격자 — 크기와 자리가 곧 우선순위다. 위 한 줄은 **시작하는 것** 셋,
    // 아래는 매번 보는 최근 검토가 두 줄을 먹고 그 옆에 기준·흐름이 쌓인다.
    // 높이가 다 같으면 그건 격자가 아니라 줄이다.
    //
    // 예전에는 큰 흰 카드 넷이 세로로 쌓여 있어 무엇부터 봐야 하는지 안 보였다.
    // 검토 셋은 **같은 크기**다. 무엇을 고를지는 문서가 몇 개냐일 뿐이라
    // 하나만 크게 두면 나머지가 곁다리로 보인다.
    // 시작 타일은 **가로형**으로 낮게 깐다 — 홈의 주인은 매번 보는 최근 검토라,
    // 시작 셋이 세로로 크면 홈이 대시보드가 아니라 기능 선택 화면으로 읽힌다.
    // (.tile 의 flex-direction:column 을 인라인 row 로 뒤집는다.)
    var startTile = function (act, arg, title, desc, icon, st) {
      return '<button type="button" class="tile act qs grow b2" data-act="' + act + '"' +
        (arg ? ' data-arg="' + arg + '"' : "") +
        ' style="' + (st || "") + '">' +
        '<span class="qs-icon">' + icon + '</span>' +
        '<span class="qs-copy">' +
          '<span class="tile-h" style="display:block;">' + esc(title) + '</span>' +
          '<span class="tile-sub" style="display:block;margin-top:2px;">' + esc(desc) + '</span>' +
        '</span>' +
        '<span class="qs-arrow">' + ICONS.arrowRight + '</span>' +
      '</button>';
    };

    // 기준 세 겹. **홈에서는 건수를 말하지 않는다.**
    //
    // 여기까지 세 번 돌아왔다. 층을 6초짜리 슬라이드로 돌렸고(도는 글은 읽는
    // 물건이 아니라 뺐다), items 의 `agent` 로 종류를 갈라 세웠고(실측해 보니
    // 일곱 팀 중 여섯이 공통과 3~4종을 공유해 거의 같은 목록이 반복됐다),
    // 묶음 이름 + 건수 목록으로 줄였다. 마지막까지 남아 있던 것이 **숫자**인데,
    // 홈에 선 사람에게 "공통 7건 · 팀 13건"은 아무 결정도 바꾸지 않는다.
    // 건수가 궁금해지는 순간은 기준 화면에 들어간 뒤다.
    //
    // 그래서 홈은 **어느 겹이 걸리는가** 하나만 그림으로 말한다.
    //   공통    씨앗. 늘 걸린다.
    //   팀별    씨앗. 소속 팀이 있으면 걸린다.
    //   체크리스트  검사를 시작할 때 고른 것만 걸린다
    //              (server.py 의 compose_review_preset(seed, picked, team) 중 picked).
    // 걸리지 않은 층은 흐리게 두고 상태 글자를 붙인다. 색만으로 상태를 말하지 않는다.
    var layers = (state.homeCriteria && state.homeCriteria.layers) || null;
    var uTeam = teamLabel(state.user && state.user.team);

    // 기준 타일. 홈에서 "이 문서는 무엇으로 재는가"를 말하는 자리다.
    // 세 입력층이 하나의 문서 검토로 모이는 관계만 그리고, 기준 항목 건수는 안 낸다.
    //
    // 브랜드 면 타일(흰 면 규칙의 유일한 예외 — index.html .tile.crit 주석).
    //
    // 이 타일은 **읽는 타일**이다. 문은 `모두 보기` 버튼 하나뿐이다.
    // 예전에는 타일 전체가 문이었는데(act + data-act), 어느 줄을 눌러도 전부
    // 같은 목록으로 갔다 — 줄을 눌렀는데 그 줄 것만 안 나오면 그건 누를 수
    // 있는 것이 아니라 함정이다.
    //
    // 최근 검토와 같은 두 행을 차지하므로 grow까지 붙여 세로 끝선을 맞춘다.
    // 편집형 인포그래픽은 남는 높이를 큰 숫자와 목록 사이의 여백으로 쓴다.
    // 기준 입력 하나. 전체 이름은 title에 남기고, 좁은 도식 안에는 짧은 층 이름과
    // 적용 상태만 둔다. 없는 층도 점선으로 자리를 지켜 구조 자체를 감추지 않는다.
    function critSource(name, state, on, fullName, optional) {
      return '<div class="crit-source-node' + (on ? "" : " is-off") +
        (optional ? " is-optional" : "") + '" title="' +
        esc(fullName || name) + (on ? "" : " · 이번 검토에는 안 걸립니다") + '">' +
        // 앞 칸의 점이 상태를 진다 — 채우면 걸리고, 빈 링이면 안 걸린다
        // (index.html .crit-source-dot).
        '<span class="crit-source-dot" aria-hidden="true"></span>' +
        '<b>' + esc(name) + '</b><span>' + esc(state) + '</span></div>';
    }

    var critTile = (function () {
      var ls = layers || [];
      var find = function (sc) {
        return ls.filter(function (L) { return L.scope === sc; })[0] || null;
      };
      var common = find("공통"), team = find("팀별");
      var ups = ls.filter(function (L) { return L.scope === "업로드"; });
      var head = '<div class="tile crit grow b2 r2 stat" data-glow style="' + tileEnter(4) + '">' +
        // 평소에는 보이지 않고 커서 조명 안에서만 드러나는 전신 마스코트.
        // 작은 이스터에그인 만큼 정보보다 먼저 보이지 않도록 웹용으로 줄여 쓴다.
        '<span class="crit-secret-mark" aria-hidden="true">' +
          '<img src="public/mascot-investigator-192.png?v=20260820" alt="">' +
        '</span>' +
        '<div class="home-tile-head">' +
          '<span class="tile-h">검토 기준</span>' +
          '<button type="button" class="btn btn-sm btn-invert home-see-all"' +
            ' data-act="setMode" data-arg="checklists">모두 보기 ' +
            ICONS.arrowRight + '</button>' +
        '</div>';
      if (!ls.length) {
        // 큰 0 을 띄우지 않는다. 기준이 0건인 것과 아직 못 불러온 것은 다른 말이다.
        return head + '<div class="crit-loading">' +
          (uTeam ? "기준을 불러오는 중…" : "로그인하면 소속 팀 기준이 함께 걸립니다") +
          '</div></div>';
      }
      // 셋은 **늘 셋이다.** 없는 겹도 자리를 지키고 흐린 상태로 선다. 감추면
      // "우리 팀 기준이 안 걸렸다"와 "그런 겹이 원래 없다"가 구별되지 않고,
      // 체크리스트를 올려 쓸 수 있다는 것 자체를 모른 채로 남는다.
      return head +
        '<div class="crit-editorial">' +
          // 세 기준 입력이 한 문서로 모인다. 진입 때 입력이 차례로 앉고 합류선과
          // 문서가 뒤따른다. 재렌더 재생
          // 방지는 flow-enter 와 같은 음수 지연 수법이다.
          '<div class="crit-figure" role="img" aria-label="공통 기준과 팀 기준, 검토할 때 선택한 체크리스트를 모아 한 문서에 적용합니다">' +
            '<div class="crit-scope' + (v.anim.homeEntered ? " scope-enter" : "") + '"' +
              (v.anim.homeEntered
                ? ' style="--plane-delay:' + (420 - v.anim.homeEnterElapsed) + 'ms;"' : "") +
              '>' +
              '<div class="crit-sources">' +
                critSource("공통", common ? "상시" : "못 읽음", !!common, "공통 기준") +
                critSource("팀 기준", team ? "적용" : "미적용", !!team,
                           team ? team.name : "소속 팀 기준") +
                critSource("체크리스트", ups.length ? "선택 가능 " + ups.length + "개" : "검토할 때 선택",
                           ups.length > 0, "올린 체크리스트", true) +
              '</div>' +
              '<svg class="crit-flow-lines" viewBox="0 0 48 150" preserveAspectRatio="none" aria-hidden="true">' +
                '<path class="crit-flow-path' + (common ? "" : " is-off") + '" d="M0 21 C18 21 14 75 28 75"/>' +
                '<path class="crit-flow-path' + (team ? "" : " is-off") + '" d="M0 75 H28"/>' +
                '<path class="crit-flow-path' + (ups.length ? " is-optional" : " is-off") + '" d="M0 129 C18 129 14 75 28 75"/>' +
                '<path class="crit-flow-out" d="M28 75 H44"/>' +
                // 구조선과 별개의 짧은 하이라이트가 제 갈래에서 문서까지 흐른다.
                // pathLength를 정규화해 곡선·직선 모두 같은 속도로 보이게 한다.
                '<path pathLength="100" class="crit-flow-pulse' + (common ? "" : " is-off") + '" d="M0 21 C18 21 14 75 28 75 H44"/>' +
                '<path pathLength="100" class="crit-flow-pulse is-second' + (team ? "" : " is-off") + '" d="M0 75 H44"/>' +
                '<path pathLength="100" class="crit-flow-pulse is-third' + (ups.length ? " is-optional" : " is-off") + '" d="M0 129 C18 129 14 75 28 75 H44"/>' +
              '</svg>' +
              '<div class="crit-document-node">' +
                '<span class="crit-document-icon" aria-hidden="true">' + ICONS.fileText + '</span>' +
                '<b>검토 문서</b><small>기준 통합 적용</small>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="crit-statement">' +
            '<div class="crit-statement-title">세 기준을 모아 한 문서를 검토합니다</div>' +
            // 이름표에서 줄인 팀 이름이 여기서 온전히 나온다. 로그인 안 한
            // 사람에게는 팀 기준이 왜 비었는지가 이 화면에서 제일 중요한 말이다.
            '<div class="crit-note">' +
              '<span>' +
                (team ? esc(team.name) + " 기준이 공통 기준과 함께 걸립니다"
                      : "로그인하면 소속 팀 기준이 함께 걸립니다") +
              '</span>' +
              '<span>체크리스트는 검토를 시작할 때 고릅니다</span>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    })();

    // 최근 검토 — 두 줄을 먹는 제일 큰 타일. 매번 보는 것이 제일 커야 한다.
    // 머리줄은 지금 목록에 실제로 담긴 것만 센다. "총 148건 지적" 같은 말은
    // 못 한다 — 서버가 주는 목록은 최근 20건까지이고, 그 밖은 우리가 모른다.
    var loaded = state.history || [];
    var sumFindings = loaded.reduce(function (a, h) { return a + (h.findings || 0); }, 0);
    var recentMeta = loaded.length
      ? '<span class="home-tile-meta">' + loaded.length + '건에서 ' +
        sumFindings + '건 지적</span>'
      : '';
    var recentTile = '<div class="tile grow b4 r2" style="' + tileEnter(3) + '">' +
      '<div class="home-tile-head">' +
        '<span class="tile-h">최근 검토</span>' +
        '<span class="home-tile-actions">' +
          recentMeta + seeAllLink + '</span>' +
      '</div>' +
      '<div class="home-recent-list">' + recentItems + '</div>' +
    '</div>';

    // 단계는 1→2→3→4 **순서대로** 한 번만 들어온다. 흐름에서는 순서가 곧
    // 내용이므로 짧은 시차 자체가 "이 순서로 검토한다"를 말한다.
    //
    // 타일 껍질에는 연출을 안 건다(아래 flowTile 에 tileEnter 가 없다). 껍질과
    // 단계가 둘 다 움직이면 translate 가 겹쳐 두 배로 뛴다 — 껍질은 화면 전체가
    // 들어올 때 같이 오고(body 의 fadeIn), 그 위에서 단계만 차례로 앉는다.
    var flowStep = function (n, title, desc, i) {
      var st = "";
      var cls = "flow-step";
      if (v.anim.homeEntered) {
        // API 응답으로 홈이 다시 그려져도 처음부터 재생하지 않는다. 이미 흐른
        // 시간만큼 음수 지연을 주어 같은 프레임부터 이어진다.
        // 벤토 카드가 먼저 앉은 다음 시작하되, 단계마다 60ms만 어긋나 업무
        // 화면에서 지나치게 연출처럼 보이지 않게 한다.
        var delay = 360 + i * 60 - v.anim.homeEnterElapsed;
        cls += " flow-enter";
        st = ' style="--flow-delay:' + delay + 'ms;"';
      }
      // 아이콘 칩은 달았다가 뺐다 — 같은 아이콘이 나브·다른 화면에서 다른 뜻으로
      // 쓰여 겹쳤다(index.html .flow-n 주석). 점·번호·레일만 남긴다.
      return '<div class="' + cls + '" role="listitem"' + st + '>' +
        '<span class="flow-n">' + (n < 10 ? "0" + n : n) + '</span>' +
        '<div class="flow-title">' + esc(title) + '</div>' +
        '<div class="flow-desc">' + esc(desc) + '</div>' +
      '</div>';
    };
    // 흐름은 **제 줄을 갖는다**(b6 한 줄). 예전에는 기준 타일과 오른쪽 2열을
    // 나눠 써서 하나가 나오면 하나가 빠지는 구조였고, 그래서 "처음 몇 번만 읽는
    // 설명"이라는 이유로 기록이 생기면 통째로 물러났다. 그런데 홈은 이 서비스가
    // 무엇을 하는지 알게 되는 곳이고, 그걸 문장으로 말하는 타일은 이것 하나다 —
    // 검토를 한 번 해본 사람에게만 안 보이는 자기소개는 앞뒤가 안 맞는다.
    //
    // 큰 숫자와 짧은 문장, 가는 구분선만 쓰는 편집형 정보 구조로 기준 타일과
    // 같은 시각 언어를 공유한다. 데스크톱은 4열, 중간 폭은 2열, 모바일은 1열로
    // 접혀 어느 너비에서도 1→2→3→4 읽는 순서를 유지한다.
    var flowTile = '<div class="tile b6">' +
      '<div class="home-tile-head"><div class="tile-h">검토 방법</div></div>' +
      '<div class="flow-editorial">' +
        '<div class="flow-figure" aria-hidden="true">' +
          '<span class="flow-figure-number">4</span>' +
          '<span class="flow-figure-label">단계로<br>문서를 검토</span>' +
        '</div>' +
        '<div class="flow" role="list" aria-label="문서를 올리고, 글자를 읽고, 기준으로 잰 뒤 지적을 짚습니다">' +
          flowStep(1, "문서를 올린다", "PDF · Word · HWP", 0) +
          flowStep(2, "글자를 읽는다", "표와 그림 속 글자까지", 1) +
          flowStep(3, "기준으로 잰다", "공통 + 소속 팀 기준", 2) +
          flowStep(4, "지적을 짚는다", "문서의 그 자리에 형광펜", 3) +
        '</div>' +
      '</div>' +
    '</div>';

    // 홈에서 사용자 이름과 `님`만 브랜드색·700으로 묶는다. 쉼표와 환영 문구는
    // 차콜로 남겨 전부 링크처럼 보이지 않게 하고, hover·밑줄은 붙이지 않는다.
    var uName = esc(state.user ? state.user.name : "");
    var greeting = uName
      ? '<span class="home-greeting-name">' + uName + ' 님</span>, 환영합니다'
      : '환영합니다';

    return '<div class="home-scroll" data-scroll="home">' +
      '<div class="home-layout">' +
        '<div class="home-greeting">' +
          '<div class="home-greeting-copy">' +
            '<h1 class="headline home-greeting-title"><span>' + greeting + '</span>' +
              // 인사 손짓은 진입 때 한 번만 흔든다. 재렌더에서 처음부터 다시 돌지
              // 않도록 흐른 시간만큼 음수 지연을 준다(flow-enter 와 같은 수법).
              '<span class="home-greeting-wave' + (v.anim.homeEntered ? " wave-enter" : "") +
                '" aria-hidden="true"' +
                (v.anim.homeEntered
                  ? ' style="--wave-delay:' + (400 - v.anim.homeEnterElapsed) + 'ms;"' : "") +
                '>' + ICONS.wave + '</span></h1>' +
            '<p class="home-greeting-sub">' +
              '검토 기준에 따라 문서의 문제를 찾습니다.</p>' +
          '</div>' +
        '</div>' +
        '<div class="bento">' +
          startTile("newReview", "", "단일 문서 검토",
                    "문서 하나를 기준에 따라 검토합니다", ICONS.single, tileEnter(0)) +
          startTile("setMode", "compare", "문서 비교 검토",
                    "두 문서 사이의 차이와 누락을 찾습니다", ICONS.compare, tileEnter(1)) +
          startTile("setMode", "case", "폴더 검토",
                    "산출물 묶음의 일관성을 함께 검토합니다", ICONS.folder, tileEnter(2)) +
          recentTile +
          critTile +
          flowTile +
        '</div>' +
      '</div>' +
    '</div>';
  }


  // ── 산출물 세트 검토 ────────────────────────────────────────────────────────────
  // 검사 1건이 문서 하나가 아니라 산출물 세트다. 폴더째 올리고, 무엇이 무엇인지
  // 확인받은 뒤 검사한다.
  //
  // 고른 값은 전부 state(kase)에 있다 — DOM 에 들고 있으면 render() 한 번에
  // 날아간다(회원가입 폼이 그렇게 아팠다).

  // 카드는 앱 공용 card() 를 그대로 쓴다. 예전에 radius 만 14px 로 따로 잡아
  // 놓아서 같은 화면에 8px 카드와 14px 카드가 섞여 있었다.
  var caseCard = card;

  // 폴더 드롭존. dropzone() 과 같은 두 상태를 갖는다 — 비었을 때는 안내, 담겼을
  // 때는 **담긴 것**과 "첨부 완료".
  //
  // 예전에는 상태가 하나뿐이라 폴더를 놓아도 드롭존이 "폴더를 끌어다 놓거나..."
  // 그대로였다. 단일 검토는 같은 자리가 문서 카드로 바뀌는데 여기만 안 바뀌니,
  // 파일 목록이 아래 붙는 것을 못 본 사람은 업로드가 안 된 줄 알고 다시 놓았다.
  //
  // dropzone() 함수 자체는 못 쓴다 — 그쪽은 파일 하나에 slot 이 있고 여기는
  // 폴더 통째다. 겉모습(52px 그림 · 15px 제목 · 13px 보조줄 · 칩 + 버튼)만 맞춘다.
  function caseDropzone(k) {
    var n = k.files.length;
    // 세로 가운데 정렬은 여기(공유 스타일)서 진다 — 옆의 "검사 단계" 패널이 더
    // 클 때 드롭존이 stretch 로 늘어나는데, 빈 상태에만 정렬이 빠져 있어 그림과
    // 안내가 위에 붙어 있었다(단일 검토 dropzone() 은 처음부터 갖고 있던 정렬).
    var box = 'flex:1;min-width:0;border-radius:var(--r-lg);box-sizing:border-box;' +
      'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
      'transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);text-align:center;';
    // 폴더 그림. 담겼을 때는 채움을 올려 "빈 자리"가 아니라 "든 것"으로 읽히게 한다.
    function folder(fill, stroke) {
      return '<svg viewBox="0 0 100 100" style="width:52px;height:52px;margin-bottom:12px;">' +
        '<defs><linearGradient id="upFolderGrad" x1="0%" y1="0%" x2="100%" y2="100%">' +
        '<stop offset="0%" stop-color="var(--accent-strong)" /><stop offset="100%" stop-color="var(--accent)" /></linearGradient></defs>' +
        '<path d="M18 30 A4 4 0 0 1 22 26 L40 26 L47 34 L78 34 A4 4 0 0 1 82 38 L82 74 A4 4 0 0 1 78 78 L22 78 A4 4 0 0 1 18 74 Z" fill="url(#upFolderGrad)" opacity="' + fill + '" />' +
        '<path d="M18 30 A4 4 0 0 1 22 26 L40 26 L47 34 L78 34 A4 4 0 0 1 82 38 L82 74 A4 4 0 0 1 78 78 L22 78 A4 4 0 0 1 18 74 Z" fill="none" stroke="url(#upFolderGrad)" stroke-width="2" opacity="' + stroke + '" />' +
        // 담겼으면 화살표(=올려라) 대신 문서 세 장(=들었다).
        (n
          ? '<path d="M35 46 H65 M35 56 H65 M35 66 H54" stroke="var(--accent)" stroke-width="4" stroke-linecap="round" fill="none" />'
          : '<path d="M50 45 L50 65 M41 54 L50 45 L59 54" stroke="var(--accent)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" />') +
        '</svg>';
    }
    if (!n) {
      // 문서가 아니라 폴더를 받는다 — dropzone() 의 문서 그림에 폴더 탭을
      // 붙이고 같은 화살표를 넣는다. 그라디언트 id 는 이 화면에만 있다.
      return '<div data-casedrop style="' + box + 'border:2px dashed var(--line-dashed);background:var(--bg);padding:40px 20px;cursor:pointer;" data-act="pickCaseFolder"' +
        ' onmouseover="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--state-hover-brand)\'"' +
        ' onmouseout="this.style.borderColor=\'var(--line-dashed)\';this.style.background=\'var(--bg)\'">' +
        folder("0.15", "0.40") +
        '<div style="font-size:15px;font-weight:700;color:var(--text);">폴더를 끌어다 놓거나 <span style="color:var(--accent-ink);text-decoration:underline;">클릭하여 선택</span></div>' +
        '<div style="font-size:13px;color:var(--text-3);margin-top:10px;">하위 폴더까지 모읍니다 · 지원 형식: .hwpx, .docx, .pdf, .md, .txt</div>' +
      '</div>';
    }
    var bytes = k.files.reduce(function (sum, f) { return sum + (f.size || 0); }, 0);
    // 담긴 뒤에도 data-casedrop 은 남긴다 — 더 놓으면 이어서 담는다(addCaseFiles
    // 가 이름으로 중복을 거른다). 다만 클릭으로 창을 다시 여는 것은 뺀다.
    // dropzone() 도 파일이 붙으면 클릭을 안 받는다 — 아래 "파일만 고르기" 가 그 몫이다.
    return '<div data-casedrop style="' + box + 'border:1px solid var(--line);background:var(--panel);padding:28px 20px;box-shadow:var(--sh-2);">' +
      folder("0.15", "0.40") +
      '<div style="font-weight:700;font-size:15px;color:var(--text);">문서 ' + n + '개</div>' +
      '<div class="mono" style="font-size:13px;color:var(--text-3);margin-top:6px;">' + esc(fmtSize(bytes)) + '</div>' +
      '<div style="display:flex;gap:16px;align-items:center;margin-top:20px;">' +
        '<span style="display:flex;align-items:center;gap:4px;font-size:12px;font-weight:600;color:var(--accent-ink);background:var(--accent-weak);padding:6px 12px;border-radius:var(--r-xl);">' + ICONS.check + ' 첨부 완료</span>' +
        '<button class="btn btn-ghost btn-ghost-accent" data-act="clearCaseFiles">제거</button>' +
      '</div>' +
    '</div>';
  }

  function caseUpload(v) {
    var k = v.kase;
    // 단일 검토 업로드의 "AI 분석 파이프라인" 패널과 같은 자리·같은 규격. 예전엔
    // 이 화면만 오른쪽이 비어 있어서, 같은 폭에 드롭존 하나만 떠 있었다 —
    // 무엇을 검사하는지도 검사 시작 전에는 어디에도 안 적혀 있었다.
    var steps = CASE_STAGES.map(function (s, i) {
      var n = "0" + (i + 1);
      return '<div style="display:flex;align-items:baseline;gap:10px;padding:8px 0;' + (i ? "border-top:1px solid var(--line-2);" : "") + '">' +
        '<span class="mono" style="font-size:11px;color:var(--accent-ink);width:16px;flex:none;">' + n + '</span>' +
        '<div style="min-width:0;">' +
          '<div style="font-size:13px;font-weight:500;">' + esc(s.label) + '</div>' +
          '<div style="font-size:11px;color:var(--text-3);margin-top:2px;line-height:1.4;">' + esc(s.desc) + '</div>' +
        '</div>' +
      '</div>';
    }).join("");
    var list = k.files.length
      ? '<div data-scroll="caseUploadFiles" style="margin-top:14px;max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:var(--r-md);">' +
          k.files.map(function (f, i) {
            return '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;' +
              (i ? "border-top:1px solid var(--line-2);" : "") + 'font-size:12px;">' +
              '<span style="color:var(--text-3);width:22px;">' + (i + 1) + '</span>' +
              '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(f.name) + '</span>' +
              '<span class="mono" style="color:var(--text-3);">' + Math.max(1, Math.round(f.size / 1024)) + ' KB</span>' +
              '</div>';
          }).join("") + '</div>'
      : "";
    var err = k.error
      ? '<div style="margin-top:14px;padding:12px 14px;background:var(--sev-crit-bg);border:1px solid var(--sev-crit-bd);border-radius:var(--r-sm);color:var(--sev-crit-fg);font-size:13px;">' + esc(k.error) + '</div>'
      : "";
    return '<div class="page-shell page-shell-primary" data-scroll="case-upload">' +
      '<div class="page-container page-stack">' +
      // 단일 검토·문서 비교와 같은 관용구 — 카드 밖 pageHead + 카드 안 작업 영역.
      pageHead("폴더 검토", "한 의뢰의 산출물 폴더를 통째로 올려 함께 검토합니다.") +
      '<div class="setup-panel">' +
        '<div style="margin-bottom:16px;">' +
          '<h2 class="setup-section-title">산출물 폴더</h2>' +
          '<p style="margin:4px 0 0;color:var(--text-3);font-size:13px;line-height:1.6;">' +
            '같은 의뢰번호의 산출물이 담긴 폴더를 올리세요. 하위 폴더까지 모아 문서 안의 값과 문서 간 일관성을 확인합니다. 문서 두 개만 대조하려면 비교 검토를 사용하세요.</p>' +
        '</div>' +
        // 단일·비교 업로드와 같은 2열 — 왼쪽 드롭존, 오른쪽 단계 패널. 드롭존
        // 속도 dropzone() 의 빈 상태와 같은 관용구다(80px 그림 + 18px 안내 +
        // 13px 형식 줄). 폴더 통째 업로드라 dropzone() 함수 자체는 못 쓰지만
        // (파일 목록이 아래 붙고 slot 이 없다) 겉모습은 맞춘다. 예전엔 여기만
        // 그림도 형식 안내도 없이 작은 글씨 두 줄이라, 같은 앱으로 안 보였다.
        '<div style="display:flex;gap:24px;align-items:stretch;">' +
        caseDropzone(k) +
          '<div style="width:320px;flex:none;background:var(--bg);border-radius:var(--r-lg);padding:20px 24px;border:1px solid var(--line);">' +
            '<div class="eyebrow" style="color:var(--text-2);margin-bottom:10px;font-size:13px;">검사 단계</div>' + steps +
          '</div>' +
        '</div>' +
        // "비우기" 는 뺐다 — 드롭존 안의 "제거" 와 같은 일을 한다. 둘을 나란히
        // 두면 어느 쪽이 무엇을 지우는지(고른 파일? 인식 결과?) 읽히지 않는다.
        list + err +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;">' +
          '<button class="btn btn-ghost" data-act="pickCaseFiles">파일만 고르기</button>' +
          (k.files.length
            ? '<button class="btn btn-lg btn-primary" data-act="classifyCase">' +
                k.files.length + '개 파일 인식하기</button>'
            : "") +
        '</div>' +
      '</div>' +
      '</div>' +
    '</div>';
  }

  function caseRecognize(v) {
    var k = v.kase, r = k.recog || { recognized: [], unclassified: [], ignored: [], missing: [], outputKeys: [] };
    function row(cells, warn) {
      return '<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:1px solid var(--line-2);font-size:13px;' +
        (warn ? "" : "") + '">' + cells + '</div>';
    }
    var recognized = r.recognized.map(function (x) {
      var stale = x.formNo && x.formNo.stale;
      return row(
        '<span style="width:170px;flex:none;font-weight:600;">' + esc(x.key) + '</span>' +
        '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-2);">' + esc(x.file) + '</span>' +
        (stale
          ? '<span class="mono" style="color:var(--text-2);font-weight:600;font-size:11px;flex:none;">구 양식 ' + esc(x.formNo.found) + ' → ' + esc(x.formNo.expected) + '</span>'
          : '<span style="color:var(--text-3);font-size:11px;flex:none;">최신</span>'), stale);
    }).join("");

    // 미분류는 사람이 지정하거나 뺀다. 추측해 배정하면 엉뚱한 필드맵으로 검사해
    // 거짓 지적이 난다 — 그래서 여기서 멈춰 묻는다.
    var unclassified = r.unclassified.map(function (name) {
      var picked = k.assign[name] || "";
      var excluded = !!k.exclude[name];
      var opts = ['<option value="">— 지정 안 함 —</option>'].concat(
        r.outputKeys.map(function (key) {
          return '<option value="' + esc(key) + '"' + (picked === key ? " selected" : "") + '>' + esc(key) + '</option>';
        })).join("");
      return row(
        '<span style="width:170px;flex:none;color:var(--text-3);">미분류</span>' +
        '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
          (excluded ? "text-decoration:line-through;color:var(--text-3);" : "") + '">' + esc(name) + '</span>' +
        '<select data-act="assignOutput" data-arg="' + esc(name) + '"' + (excluded ? " disabled" : "") +
          ' style="flex:none;padding:4px 8px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:12px;background:var(--panel);color:var(--text);">' + opts + '</select>' +
        '<button class="btn btn-sm btn-ghost" data-act="toggleExclude" data-arg="' + esc(name) + '" style="flex:none;">' +
          (excluded ? "되돌리기" : "제외") + '</button>', !excluded && !picked);
    }).join("");

    var ignored = r.ignored.map(function (x) {
      return row('<span style="width:170px;flex:none;color:var(--text-3);">건너뜀</span>' +
        '<span style="flex:1;color:var(--text-3);">' + esc(x.file) + '</span>' +
        '<span style="color:var(--text-3);font-size:11px;flex:none;">' + esc(x.reason || "") + '</span>');
    }).join("");

    // 업로드 화면과 같은 껍데기(24px 패널). 예전엔 이 화면만 공용 card() 8px 를
    // 써서, 한 흐름의 2단계인데 앞뒤 화면과 카드 모양이 갈렸다.
    function panel(inner, pad) {
      // 앞뒤 화면(업로드 히어로 카드)과 같은 --r-lg — 이 화면만 24px 였다.
      return '<div class="surface-work" style="padding:' + (pad || "24px") + ';border-radius:var(--r-lg);">' + inner + '</div>';
    }
    var missing = r.missing.length
      ? panel('<div style="font-size:13px;font-weight:600;margin-bottom:8px;">안 올라온 산출물 ' + r.missing.length + '종</div>' +
          '<div style="font-size:13px;color:var(--text-3);line-height:1.6;">' + r.missing.map(esc).join(" · ") + '</div>' +
          '<div style="font-size:12px;color:var(--text-3);margin-top:8px;">없는 문서가 필요한 대조는 <b>미검토</b>로 남습니다 — 지적 0건과 다릅니다.</div>', "24px 32px")
      : "";

    return '<div class="page-shell page-shell-primary" data-scroll="case-recognize">' +
      '<div class="page-container page-stack">' +
      // 페이지 제목은 여전히 "폴더 검토"다 — 인식 확인은 그 안의 한 단계라서,
      // 단계 이름(인식 결과 N/M종)은 카드 안 섹션 제목(본문 서체 700)으로 내린다.
      pageHead("폴더 검토", "검사 전에 문서 유형 인식 결과를 확인합니다.") +
      panel(
        '<div style="font-size:18px;font-weight:700;letter-spacing:-.3px;color:var(--text);margin-bottom:6px;">인식 결과 — 산출물 ' + r.recognized.length + '/' + r.outputKeys.length + '종</div>' +
        '<p style="margin:0 0 20px 0;color:var(--text-3);font-size:14px;line-height:1.6;">잘못 배정되면 엉뚱한 기준으로 검사합니다.</p>' +
        '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' +
          recognized + unclassified + ignored +
        '</div>') +
      missing +
      '<div style="display:flex;gap:8px;">' +
        '<button class="btn btn-ghost" data-act="backToCaseUpload">뒤로</button>' +
        '<button class="btn btn-lg btn-primary" data-act="runCase" style="flex:1;">검사 시작</button>' +
      '</div>' +
      '</div>' +
    '</div>';
  }



  // ── 산출물 세트 검토 리포트 ──────────────────────────────────────────────────────────
  // 네 부분이다: 요약(+산출물 인식표) · 산출물별 값 · 산출물 간 대조 · 기타.
  //
  // 인식표가 지적보다 앞에 온다. 산출물 하나가 안 올라온 걸 모르고 "지적 없음"을
  // 보면 검토자가 통과로 읽는다.

  // 검토를 막는 숫자와 참고용 숫자를 크기로 가른다. 일곱을 같은 크기로 늘어놓으면
  // "지적 3"과 "건너뜀 1"이 같은 무게로 읽혀 무엇을 먼저 볼지가 사라진다.
  // (큰 숫자는 800 — Wanted 의 ExtraBold. Gmarket 자리가 아니라서 실제로 있다.
  //  작은 숫자(18px)는 700 — 800 은 20px 넘는 숫자 전용이다.)
  function caseStat(n, label, tone, small) {
    return '<div style="' + (small ? "flex:0 0 92px;" : "flex:1;") + 'text-align:center;padding:14px 8px;">' +
      '<div class="mono" style="font-size:' + (small ? "18px;font-weight:700" : "24px;font-weight:800") + ';color:' +
        (tone || "var(--text)") + ';">' + n + '</div>' +
      '<div style="font-size:' + (small ? "11px" : "12px") + ';color:var(--text-3);margin-top:2px;">' + esc(label) + '</div></div>';
  }

  // 누를 수 있는 행에는 앱 공용 .row 를 붙인다 — cursor 만 바뀌고 hover 가
  // 없으면 눌리는 줄인지 대 보기 전에는 모른다(다른 표는 전부 .row 다).
  function caseRow(cells, act, arg) {
    return '<div' + (act ? ' class="row" data-act="' + esc(act) + '" data-arg="' + esc(arg || "") +
        '" tabindex="0" role="button"' : "") +
      ' style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:1px solid var(--line-2);font-size:13px;">' +
      cells + '</div>';
  }

  // 전체 지적을 어느 검사 층이 냈는지. 상단의 숫자 하나만 보여주면 사용자는
  // 산출물 표의 "지적 3건"과 전체 "지적 8건"이 왜 다른지 알 수 없다.
  function caseFindingCounts(p) {
    var out = { output: 0, case_wide: 0, pair: 0, manual_input: 0,
                unreviewed: 0, total: 0 };
    (p.findings || []).forEach(function (f) {
      if (f.unreviewed) { out.unreviewed++; return; }
      out[f.kind] = (out[f.kind] || 0) + 1;
      out.total++;
    });
    return out;
  }

  function caseFindingBadge(f) {
    var labels = {
      output: "문서 단독 검사",
      case_wide: "전체 필드 대조",
      pair: "두 문서 대조",
      manual_input: "외부 기준값 대조"
    };
    return sevBadge({
      unreviewed: !!f.unreviewed,
      sev: f.sev,
      label: labels[f.kind] || f.label || "검토 결과"
    });
  }

  function caseFindingSummary(p) {
    var c = caseFindingCounts(p);
    return '<div' +
      ' style="display:flex;align-items:center;gap:16px;padding:12px 14px;margin-bottom:14px;' +
      'border:1px solid var(--line);border-radius:var(--r-md);background:var(--panel);">' +
        '<div style="flex:none;">' +
          '<div class="mono" style="font-size:22px;font-weight:800;color:var(--text);">' + c.total + '</div>' +
          '<div style="font-size:11px;color:var(--text-3);">전체 지적</div>' +
        '</div>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:13px;font-weight:600;color:var(--text);">' +
            '문서 단독 검사 ' + c.output + ' · 문서 간 불일치 ' + (c.case_wide + c.pair) +
            (c.manual_input ? ' · 외부 기준값 불일치 ' + c.manual_input : '') +
          '</div>' +
          '<div style="font-size:12px;color:var(--text-3);margin-top:4px;">' +
            (c.unreviewed ? '별도로 미검토 ' + c.unreviewed + '건이 남아 있습니다. ' : '') +
            '수정하거나 확인할 문제를 한 목록에서 봅니다.</div>' +
        '</div>' +
        '<button class="btn btn-sm btn-ghost" data-act="setCaseTab" data-arg="compare" style="flex:none;">' +
          '전체 지적 보기 ' + ICONS.arrowRight + '</button>' +
      '</div>';
  }

  function caseMatrixSummary(p) {
    var rows = p.matrix || [];
    var counts = { "일치": 0, "불일치": 0, "미검토": 0 };
    rows.forEach(function (m) { counts[m.status] = (counts[m.status] || 0) + 1; });
    return '<div style="display:flex;align-items:center;gap:16px;padding:12px 14px;margin-bottom:14px;' +
      'border:1px solid var(--line);border-radius:var(--r-md);background:var(--panel);">' +
        '<div style="flex:none;">' +
          '<div class="mono" style="font-size:22px;font-weight:800;color:var(--text);">' +
            (counts["일치"] + counts["불일치"]) + '/' + rows.length + '</div>' +
          '<div style="font-size:11px;color:var(--text-3);">전체 필드 대조</div>' +
        '</div>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:13px;font-weight:600;color:var(--text);">' +
            '불일치 ' + counts["불일치"] + ' · 일치 ' + counts["일치"] +
            ' · 미검토 ' + counts["미검토"] + '</div>' +
          '<div style="font-size:12px;color:var(--text-3);margin-top:4px;">' +
            '여러 문서에서 같은 필드 값을 맞대본 결과입니다.</div>' +
        '</div>' +
        '<button class="btn btn-sm btn-ghost" data-act="setCaseTab" data-arg="matrix" style="flex:none;">' +
          '대조표 보기 ' + ICONS.arrowRight + '</button>' +
      '</div>';
  }

  function caseOutputTable(p) {
    var rows = (p.outputs || []).map(function (o) {
      var stale = o.formNo && o.formNo.stale;
      // 구 양식은 고쳐야 하는 것 — minor 틴트를 입는다. 회색 글자이던 때는
      // "최신"과 같은 무게라 훑어서는 안 걸렸다.
      var badge = stale
        ? '<span class="mono" style="font-size:11px;font-weight:600;flex:none;padding:2px 8px;' +
          'border-radius:var(--r-sm);background:var(--sev-min-bg);color:var(--sev-min-fg);' +
          'box-shadow:inset 0 0 0 1px var(--sev-min-bd);">구 양식 ' + esc(o.formNo.found) + ' → ' + esc(o.formNo.expected) + '</span>'
        : '<span style="font-size:11px;color:var(--text-3);flex:none;">최신</span>';
      // 이 행은 문서 단독 검사뿐 아니라 이 문서가 걸린 문서 간 지적도 말한다.
      // 예전에는 시험기록서에 온도 불일치가 있어도 자체 지적이 0이라 정상으로
      // 표시했다. 전체 숫자와 문서 행이 서로 반대말을 한 셈이다.
      var chip = function (text, bg, fg) {
        return '<span style="font-size:11px;font-weight:600;flex:none;padding:2px 8px;' +
          'border-radius:var(--r-sm);background:' + bg + ';color:' + fg + ';">' + text + '</span>';
      };
      var related = (p.findings || []).filter(function (f) {
        return docSides(f.document).indexOf(o.key) >= 0;
      });
      var cross = related.filter(function (f) {
        return !f.unreviewed && (f.kind === "case_wide" || f.kind === "pair");
      }).length;
      var manualInput = related.filter(function (f) {
        return !f.unreviewed && f.kind === "manual_input";
      }).length;
      var pending = related.filter(function (f) { return !!f.unreviewed; }).length;
      var marks = [];
      if (o.status !== "reviewed") {
        marks.push(chip("검사 안 됨", "var(--neutral-weak)", "var(--text-3)"));
      } else {
        if (o.findings) marks.push(chip("문서 단독 검사 " + esc(o.findings),
          "var(--accent-weak)", "var(--accent-ink)"));
        if (cross) marks.push(chip("문서 간 불일치 " + esc(cross),
          "var(--sev-maj-bg)", "var(--sev-maj-fg)"));
        if (manualInput) marks.push(chip("외부 기준값 불일치 " + esc(manualInput),
          "var(--sev-maj-bg)", "var(--sev-maj-fg)"));
        if (pending) marks.push(chip("관련 미검토 " + esc(pending),
          "var(--neutral-weak)", "var(--text-3)"));
        if (!o.findings && !cross && !manualInput && !pending) marks.push(chip(
          "관련 지적 없음", "var(--band-good-bg)", "var(--band-good-fg)"));
      }
      return caseRow(
        '<span style="width:150px;flex:none;font-weight:600;">' + esc(o.key) + '</span>' +
        '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-2);">' + esc(o.file) + '</span>' +
        '<span style="flex:none;display:inline-flex;gap:6px;justify-content:flex-end;">' + marks.join("") + '</span>' +
        badge +
        '<button class="btn btn-sm btn-ghost" data-act="openCaseDoc" data-arg="' + esc(o.key) + '" style="flex:none;">' +
          '문서에서 보기</button>');
    }).join("");
    var missing = (p.missing || []).map(function (key) {
      return caseRow(
        '<span style="width:150px;flex:none;font-weight:600;color:var(--text-2);">' + esc(key) + '</span>' +
        '<span style="flex:1;color:var(--text-3);">올라오지 않았습니다 — 이 문서가 필요한 대조는 미검토로 남습니다</span>');
    }).join("");
    return '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + rows + missing + '</div>';
  }

  function caseFieldsPanel(p, sel) {
    var out = (p.outputs || []).filter(function (o) { return o.key === sel; })[0]
      || (p.outputs || [])[0];
    if (!out) return '<div style="font-size:13px;color:var(--text-3);">산출물이 없습니다.</div>';
    var chips = (p.outputs || []).map(function (o) {
      var on = o.key === out.key;
      return '<button class="chip" data-act="pickCaseOutput" data-arg="' + esc(o.key) + '" style="padding:6px 12px;border-radius:var(--r-sm);font-size:12px;font-weight:600;border:1px solid ' +
        (on ? "var(--accent)" : "var(--line)") + ';background:' + (on ? "var(--accent-weak)" : "var(--panel)") +
        ';color:' + (on ? "var(--accent-ink)" : "var(--text)") + ';">' +
        esc(o.key) + '</button>';
    }).join("");
    var fields = (out.fields || []).length
      ? (out.fields || []).map(function (f) {
          var val = f.selected && f.selected.length
            ? f.selected.join(" · ")
            : (f.found ? (f.value === "" ? "(빈 값)" : f.value) : "");
          return caseRow(
            '<span style="width:150px;flex:none;color:var(--text-2);">' + esc(f.name) + '</span>' +
            // 못 찾은 값은 대조표의 ? 와 같은 minor 톤이다 — 회색이던 때는
            // 정상 값과 같은 무게라 문제로 안 읽혔다.
            '<span class="mono" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
              (f.found ? esc(val)
                : '<span style="font-weight:600;color:var(--sev-min-fg);">찾지 못했습니다</span>' +
                  '<span style="color:var(--text-3);"> — 필드맵을 확인하십시오</span>') + '</span>' +
            '<span class="mono" style="flex:none;font-size:11px;color:var(--text-3);">' + esc(f.at || "") + '</span>',
            );
        }).join("")
      : caseRow('<span style="color:var(--text-3);">' + esc(out.reason || "값이 없습니다") + '</span>');
    return '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">' + chips + '</div>' +
      '<div style="font-size:12px;color:var(--text-3);margin-bottom:8px;">' + esc(out.reason || "") + '</div>' +
      '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + fields + '</div>';
  }


  // 필드 × 산출물 매트릭스. 팀이 xlsx No.13 에서 "비교용 엑셀"이라고 부른 것이다.
  //
  // **격자로 그린다** — 가로가 산출물, 세로가 항목. 어디서 틀어졌는지 교차점 하나로
  // 보인다. 지적 목록만으로는 맞은 곳이 안 보여서 "6곳 다 봤고 1곳이 틀렸다"를
  // 말할 수 없다.
  //
  // 어느 칸이 틀렸나는 **서버가 정한다**(cell.ok). 버전 무시 같은 정규화가 거기
  // 있어서, 화면이 다시 계산하면 두 곳의 판정이 어긋난다.
  function caseMatrix(p, focus) {
    var rows = p.matrix || [];
    if (!rows.length) return '<div style="font-size:13px;color:var(--text-3);">전 산출물 대조 기준이 없습니다.</div>';

    // 열은 기준에 나온 산출물 전부. 기준 파일에 적힌 순서를 지킨다(작성 순서다).
    var cols = [], seen = {};
    rows.forEach(function (m) {
      (m.cells || []).forEach(function (c) {
        if (!seen[c.output]) { seen[c.output] = 1; cols.push(c.output); }
      });
    });

    // 셀 상태 중 **문제만 색을 받는다** — 검토자는 붉은 칩만 훑으면 된다.
    // 다른 값은 값 자체를 칩에 싣는다. "다르다(⚠)"만 찍고 값을 툴팁에 숨기면
    // 무엇이 어떻게 다른지 보러 문서를 또 열어야 했다. 같음 표시는 유니코드
    // ✔ 대신 다른 화면과 같은 선형 체크 아이콘을 쓴다.
    function mark(c) {
      if (!c) return { h: '<span style="color:var(--line);">–</span>',
                       tip: "이 항목의 대조 대상이 아닙니다" };
      if (!c.present) return { h: '<span style="color:var(--text-3);">·</span>',
                               tip: "올라오지 않았습니다" };
      if (c.configured === false) return {
        h: '<span style="font-size:11px;color:var(--text-3);">설정 없음</span>',
        tip: "이 문서의 필드 추출 규칙이 없습니다" };
      if (!c.found) return { h: '<span style="font-weight:700;color:var(--sev-min-fg);">?</span>',
                             tip: "값을 찾지 못했습니다" };
      if (c.ok === false) return {
        h: '<span class="mono" style="display:inline-block;max-width:100%;overflow:hidden;' +
           'text-overflow:ellipsis;white-space:nowrap;vertical-align:middle;font-size:11px;' +
           'font-weight:600;padding:2px 8px;border-radius:var(--r-sm);background:var(--sev-crit-bg);' +
           'color:var(--sev-crit-fg);box-shadow:inset 0 0 0 1px var(--sev-crit-bd);">' +
           esc(c.value || "다름") + '</span>',
        tip: c.value || "값이 다릅니다" };
      return { h: '<span style="display:inline-flex;vertical-align:middle;color:var(--text-2);">' +
                  ICONS.check + '</span>', tip: c.value || "" };
    }

    var head = '<div style="display:flex;border-bottom:1px solid var(--line);">' +
      '<div style="width:150px;flex:none;padding:8px 10px;font-size:12px;color:var(--text-3);">항목</div>' +
      cols.map(function (k) {
        return '<div style="flex:1;min-width:0;padding:8px 4px;font-size:11px;color:var(--text-3);text-align:center;' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(k) + '">' + esc(k) + '</div>';
      }).join("") +
      '<div style="width:96px;flex:none;padding:8px 10px;font-size:12px;color:var(--text-3);text-align:right;">확인</div>' +
    '</div>';

    var body = rows.map(function (m) {
      var byOut = {};
      (m.cells || []).forEach(function (c) { byOut[c.output] = c; });
      var tone = m.status === "불일치" ? "var(--sev-crit-fg)"
               : (m.status === "일치" ? "var(--text)" : "var(--text-3)");
      var related = (p.findings || []).filter(function (f) { return f.ruleId === m.id; })[0];
      var open = focus === m.id;
      // 행 전체가 같은 상세를 여는 한 동작이다. 체크·값 칸은 상태 표시일 뿐이라
      // 별도 클릭 대상으로 만들지 않는다. 원문 이동은 펼친 상세의 명시적인
      // "문서에서 보기" 버튼이 맡는다.
      var row = '<div class="case-matrix-row' + (open ? ' is-open' : '') + '"' +
          ' data-matrix-row="' + esc(m.id) + '" data-act="openMatrixDetail" data-arg="' + esc(m.id) + '"' +
          ' tabindex="0" role="button" aria-expanded="' + (open ? 'true' : 'false') + '"' +
          ' title="' + esc(m.field + " 대조 상세 보기") + '">' +
        '<div class="case-matrix-field"' +
          ' style="width:150px;flex:none;padding:8px 10px;font-size:13px;font-weight:600;color:' + tone + ';' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"' +
          '>' +
          '<span style="display:inline-flex;align-items:center;gap:6px;">' +
            '<span class="case-matrix-disclosure">' + (open ? '▾' : '▸') + '</span>' +
            esc(m.field) + '</span></div>' +
        cols.map(function (k) {
          var c = byOut[k], mk = mark(c);
          return '<div style="flex:1;min-width:0;padding:8px 6px;text-align:center;font-size:13px;"' +
            ' title="' + esc(k + " — " + mk.tip) + '">' + mk.h + '</div>';
        }).join("") +
        '<div style="width:96px;flex:none;padding:8px 10px;font-size:11px;color:var(--text-3);text-align:right;">' +
          m.seen + '/' + m.total + '</div>' +
      '</div>';

      if (!open) return row;
      var details = (m.cells || []).map(function (c) {
        var stateText = !c.present ? "문서가 올라오지 않음"
          : c.configured === false ? "추출 규칙 없음"
          : !c.found ? "값을 찾지 못함"
          : c.ok === false ? "불일치 값"
          : "확인한 값";
        return '<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line-2);">' +
          '<span style="width:150px;flex:none;font-weight:600;color:var(--text-2);">' + esc(c.output) + '</span>' +
          '<span class="mono" style="flex:1;min-width:0;color:' +
            (c.ok === false ? 'var(--sev-crit-fg)' : 'var(--text-2)') + ';">' +
            esc(c.found ? (c.value || "(빈 값)") : stateText) + '</span>' +
          '<span style="flex:none;font-size:11px;color:var(--text-3);">' + esc(stateText) + '</span>' +
          (c.found
            ? '<button class="btn btn-sm btn-ghost" data-act="openCaseDoc" data-arg="' +
              esc(c.output + (related ? "|" + related.id : "")) + '">문서에서 보기</button>'
            : '') +
        '</div>';
      }).join("");
      var reason = m.status === "불일치"
        ? "문서에서 읽은 값이 서로 다릅니다. 어느 값이 맞는지는 원문과 기준을 확인해야 합니다."
        : m.status === "미검토"
          ? "필요한 문서값을 모두 확보하지 못해 대조를 끝내지 못했습니다."
          : "대상 문서에서 읽은 값이 모두 일치합니다.";
      return row + '<div class="case-matrix-detail" data-matrix-detail="' + esc(m.id) + '"' +
          ' role="region" aria-label="' + esc(m.field + " 대조 상세") + '">' +
          '<div class="case-matrix-detail-head">' +
            '<span class="case-matrix-detail-title">' + esc(m.field) + ' 대조 상세</span>' +
            '<span class="case-matrix-detail-reason">' + esc(reason) + '</span>' +
            '<button class="btn btn-sm btn-ghost" data-act="openCriteria" data-arg="' + esc(m.id) +
              '" style="margin-left:auto;flex:none;">이 기준 보기</button>' +
          '</div>' + details +
        '</div>';
    }).join("");

    return '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + head + body + '</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:10px;font-size:11px;color:var(--text-3);align-items:center;">' +
        '<span style="display:inline-flex;align-items:center;gap:4px;">' +
          '<span style="display:inline-flex;color:var(--text-2);">' + ICONS.check + '</span> 같음</span>' +
        '<span style="display:inline-flex;align-items:center;gap:4px;">' +
          '<span class="mono" style="font-weight:600;padding:2px 6px;border-radius:var(--r-sm);' +
          'background:var(--sev-crit-bg);color:var(--sev-crit-fg);box-shadow:inset 0 0 0 1px var(--sev-crit-bd);">값</span>' +
          ' 다름 — 그 문서의 값</span>' +
        '<span><b style="color:var(--sev-min-fg);">?</b> 값을 못 찾음</span>' +
        '<span>설정 없음 — 추출 규칙 없음</span>' +
        '<span><b>·</b> 안 올라옴</span>' +
        '<span><b style="color:var(--line);">–</b> 대조 대상 아님</span>' +
        '<span>행을 누르면 대조 상세가 열리고, 상세의 버튼으로 원문을 봅니다</span>' +
      '</div>';
  }

  function caseFindingList(p) {
    if (!(p.findings || []).length) {
      return '<div style="font-size:13px;color:var(--text-3);">대조에서 나온 것이 없습니다.</div>';
    }
    return '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' +
      p.findings.map(function (f) {
        // 심각도 색은 그 지적의 등급을 따른다 — 주황을 박아 두면 minor·info 도
        // "주의"로 읽힌다(caseDocView 도 같은 자리를 고쳤다).
        // 인용은 단일 검토 카드와 같은 형광펜(mark.sev-*)으로 칠한다 — 회색
        // mono 만이던 때는 같은 근거가 화면마다 다른 옷을 입었다. 등급이 없는
        // 줄(미검토)은 심각도 색을 빌리지 않는다.
        var ev = (f.evidence || []).map(function (e) {
          return '<div style="display:flex;gap:8px;font-size:12px;color:var(--text-3);margin-top:4px;">' +
            '<span class="mono" style="flex:none;width:74px;">' + esc(e.at) + '</span>' +
            '<span class="mono" style="min-width:0;">' +
              (f.sev && !f.unreviewed
                ? '<mark class="sev-' + esc(f.sev) + '">' + esc(e.quote) + '</mark>'
                : esc(e.quote)) + '</span></div>';
        }).join("");
        return '<div style="padding:12px 14px;border-top:1px solid var(--line-2);">' +
          '<div style="display:flex;gap:8px;align-items:center;">' +
            // 단일 검토와 같은 뱃지. 기준 id 는 안 낸다 — 뱃지가 무엇이 잡았는지를
            // 이미 사람 말로 말한다(caseDocView 도 같은 자리를 뺐다).
            caseFindingBadge(f) +
            '<span style="font-size:11px;color:var(--text-3);margin-left:auto;flex:none;">' + esc(f.document || "") + '</span>' +
          '</div>' +
          '<div style="font-size:13px;margin-top:4px;">' + esc(f.message) + '</div>' + ev +
          (f.unreviewed ? "" : '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">' +
            docSides(f.document).map(function (side) {
              return '<button class="btn btn-sm btn-ghost" data-act="openCaseDoc" data-arg="' + esc(side + "|" + f.id) + '">' +
                esc(side) + ' 문서에서 보기</button>';
            }).join("") +
            (f.kind === "case_wide"
              ? '<button class="btn btn-sm btn-ghost" data-act="openMatrixDetail" data-arg="' +
                esc(f.ruleId || "") + '">대조표에서 보기</button>'
              : '') +
            (f.ruleId
              ? '<button class="btn btn-sm btn-ghost" data-act="openCriteria" data-arg="' +
                esc(f.ruleId) + '">기준 보기</button>'
              : '') + '</div>') +
        '</div>';
      }).join("") + '</div>';
  }

  function caseOtherPanel(p) {
    function block(title, items, note) {
      if (!items.length) return "";
      return '<div style="margin-bottom:14px;">' +
        '<div style="font-size:13px;font-weight:600;margin-bottom:6px;">' + esc(title) + ' ' + items.length + '건</div>' +
        (note ? '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">' + esc(note) + '</div>' : "") +
        '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' +
          items.map(function (x) {
            return caseRow('<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(x.file) + '</span>' +
              (x.reason ? '<span style="flex:none;font-size:11px;color:var(--text-3);">' + esc(x.reason) + '</span>' : ""));
          }).join("") + '</div></div>';
    }
    var body = block("분류가 필요한 파일", p.unclassified || [],
        "양식번호가 없어 산출물을 정하지 못했습니다. 추측해 배정하면 엉뚱한 기준으로 검사합니다.") +
      block("참고자료 제외", p.ignored || [], "검토 대상이 아닌 참고자료로 분류되어 검사에서 제외했습니다.");
    return body || '<div style="font-size:13px;color:var(--text-3);">분류가 필요한 파일이나 제외된 참고자료가 없습니다.</div>';
  }


  // 지적을 누르면 그 산출물을 뷰어로 연다. 단일 검토와 같은 부품을 쓴다 —
  // render-pdf 로 PDF 를 만들고 locate 로 인용문 위치를 받아 형광펜을 얹는다.
  //
  // 대조 지적은 문서 **둘**을 가리킨다. 여기서는 연 문서 쪽 근거만 짚고, 반대쪽은
  // 오른쪽 목록에 값으로 보여 준다 — 나란히 띄우는 것은 그다음이다.
  // 검토 결과 패널의 껍데기. **단일 검토와 폴더 검토가 같은 것을 쓴다.**
  //
  // 예전엔 둘이 따로였다 — 단일은 400px 에 그림자·40px 큰 숫자·분포 바·범례,
  // 폴더는 340px 에 13px 한 줄("이 문서의 지적 3건")이었다. 같은 일을 하는 자리가
  // 이만큼 다르면 두 화면이 다른 도구처럼 읽힌다.
  //
  // 카드까지 합치지는 않는다 — 폴더 검토 카드는 지적이 걸친 문서 여럿과
  // "저 문서에서 보기" 버튼을 진다. 단일 검토에는 그 개념 자체가 없어서, 합치면
  // 분기투성이 함수가 되고 한쪽을 고칠 때마다 다른 쪽을 깨뜨린다.
  //
  // opts: {id, title, count, sub, noClean, filters, chips, actions, overlay, note, body, hidden}
  //   chips  [{sev,label,count,on}] — on 이 있으면 눌러서 거르는 범례, 없으면 그냥 범례
  //   actions 헤더 오른쪽 버튼들(내보내기·접기). 없으면 자리도 안 만든다
  function issuesShell(opts) {
    var total = opts.count || 0;
    var chips = opts.chips || [];
    var legend = chips.map(function (c) {
      // 거를 수 있으면 누를 수 있게, 아니면 글자만. 폴더 검토에는 필터 상태가
      // 없으므로(state.kase 에 sevFilter 가 없다) 누르는 시늉을 하지 않는다.
      //
      // 생김새는 카드의 심각도 뱃지와 같은 틴트다(SEV bg/fg/bd) — 점 범례이던
      // 때는 원색 점과 회색 글자가 카드 뱃지·형광펜과 다른 세 번째 어휘였다.
      // 같은 색이 같은 등급을 말해야 필터와 목록이 한 언어로 읽힌다.
      var pal = SEV[c.sev] || SEV.unknown;
      var act = c.on === undefined ? "" : ' data-act="toggleSev" data-arg="' + c.sev + '" tabindex="0" role="button"';
      var dim = c.on === undefined || c.on ? 1 : 0.35;
      return '<span' + act + (act ? ' title="' + esc(c.label) + ' 지적 보이기/숨기기"' : '') +
        ' style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;' +
        'font-size:12px;font-weight:600;border-radius:var(--r-sm);' +
        'background:' + pal.bg + ';color:' + pal.fg + ';box-shadow:inset 0 0 0 1px ' + pal.bd + ';' +
        'opacity:' + dim + ';transition:opacity .15s;' +
        (act ? "cursor:pointer;" : "") + '">' + esc(c.label) +
        '<span style="font-variant-numeric:tabular-nums;">' + c.count + '</span></span>';
    }).join("");

    // 폭은 화면을 따라간다. 400px 고정이면 27인치에서는 지적 문장이 서너 글자마다
    // 꺾이고, 13인치에서는 같은 400px 이 문서를 절반 가까이 먹는다 — 둘 다 400 이
    // "적당했던" 한 화면 크기에서만 맞는 값이었다. 아래위 한계는 두어야 한다:
    // 360 아래로는 뱃지 줄이 두 줄로 접히고, 480 위로는 문서가 밀린다.
    return '<div' + (opts.id ? ' id="' + opts.id + '"' : "") +
      ' style="width:clamp(360px, 26vw, 480px);flex:none;margin:4px 32px 12px 0;background:var(--panel);' +
      'border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--sh-3);' +
      'display:' + (opts.hidden ? "none" : "flex") + ';flex-direction:column;overflow:hidden;z-index:10;">' +
      '<div style="position:relative;padding:18px 24px 16px;background:var(--panel);border-bottom:1px solid var(--line);">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
          '<span style="font-weight:700;font-size:15px;color:var(--text);letter-spacing:-.01em;">' + esc(opts.title) + '</span>' +
          (opts.actions ? '<div style="display:flex;align-items:center;gap:6px;">' + opts.actions + '</div>' : "") +
        '</div>' +
        (opts.overlay || "") +
        // 큰 자리에는 **실제로 센 것**만 둔다 — 지적 건수. 예전에는 점수가 있었으나
        // 눈금에 근거가 없어 뺐다(CLAUDE.md "기능 방침 — 점수").
        //
        // 0건일 때만 판정 칩을 붙인다. "지적 없음"은 검사 결과로 말할 수 있지만
        // "위험"은 말할 근거가 없다 — 그래서 --band-warn/bad 는 같이 지웠다.
        '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px;">' +
          '<span style="font-size:40px;font-weight:800;line-height:1;letter-spacing:-.03em;color:var(--text);font-variant-numeric:tabular-nums;">' + total + '</span>' +
          '<span style="font-size:13px;font-weight:600;color:var(--text-3);">건 지적</span>' +
          // sub: 큰 숫자에 안 섞은 것들(참고·미검토)의 건수. 지적이 아니라서
          // 따로 말하되, 숨기지는 않는다.
          (opts.sub ? '<span style="font-size:12px;font-weight:600;color:var(--text-3);">· ' + esc(opts.sub) + '</span>' : '') +
          // noClean: 0건이어도 미검토가 남았으면 "이상 없음"이라 말하지 않는다.
          (total === 0 && !opts.noClean
            ? '<span style="margin-left:auto;font-size:12px;font-weight:600;color:var(--band-good-fg);background:var(--band-good-bg);padding:6px 12px;border-radius:var(--r-xl);">이상 없음</span>'
            : '') +
        '</div>' +
        // **한 가지 등급뿐이면 범례를 안 그린다.** `Major 12` 칩 하나는 위의 큰
        // 숫자 12 를 한 번 더 말하는 것뿐이다. 폴더 검토가 그렇다 — 규칙만
        // 돌아서 지적이 전부 MAJOR 다. CRITICAL 을 지운 것과 같은 이유다
        // (shared/models.py Severity). 이 판단은 chips.length > 1 가 진다.
        //
        // 분포 바는 지웠다 — 칩의 건수들이 이미 다 말하는 비율을 채도 높은
        // 원색 띠로 한 번 더 그렸고, 패널에서 제일 시끄러운 색이 정보가 아니라
        // 장식이었다. 색은 의미가 실리는 자리(칩·형광펜)에만 남긴다.
        (chips.length > 1
          ? '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;">' + legend + '</div>'
          : "") +
        // filters: 정렬·검사기 칩(단일 검토만 넘긴다). 범례 아래 한 줄.
        (opts.filters ? '<div style="margin-top:8px;">' + opts.filters + '</div>' : "") +
        (opts.note || "") +
        // 탭은 스크롤 밖, **헤더의 마지막 줄**에 산다. body 안에 넣으면 카드를
        // 내리는 순간 "지금 어느 탭을 보고 있는지"가 함께 사라지고, 헤더 밖에
        // 따로 줄을 두면 헤더 경계선과 탭 경계선이 이중으로 생겨 다른 화면의
        // 탭(전역 헤더의 스텝 탭 — 경계선 하나 위에 앉는다)과 어긋난다.
        // 음수 마진이 헤더의 아래 패딩(16px)을 지워 밑줄이 경계선에 붙는다.
        (opts.tabs ? '<div style="margin:14px 0 -16px;">' + opts.tabs + '</div>' : "") +
      '</div>' +
      // 스크롤은 바깥(패딩 0)에서 → 스크롤바가 카드 가장자리에 붙는다. 안쪽 래퍼가
      // 좌우 대칭 여백(바깥에 padding-right 를 주면 스크롤바 오른쪽에 빈 채널이 생긴다).
      '<div style="flex:1;overflow-y:auto;"><div style="padding:14px 16px;">' + opts.body + '</div></div>' +
    '</div>';
  }

  // 지적 목록 → 범례용 칩. on 을 안 주면 거르기 없는 범례가 된다.
  function sevChipsOf(findings, sevFilter) {
    var counts = {};
    (findings || []).forEach(function (f) { counts[f.sev] = (counts[f.sev] || 0) + 1; });
    return ORDER.filter(function (k) { return counts[k]; }).map(function (k) {
      var c = { sev: k, label: SEV[k].label, count: counts[k] };
      if (sevFilter) c.on = sevFilter[k];
      return c;
    });
  }

  function caseDocView(v) {
    var k = v.kase, view = k.view, p = k.payload;
    var out = (p.outputs || []).filter(function (o) { return o.key === view.key; })[0] || {};
    var mine = (p.findings || []).filter(function (f) {
      return !f.unreviewed && (f.document || "").indexOf(view.key) >= 0;
    });
    var markNos = {};
    (((state.marks || {}).items) || []).forEach(function (it) {
      if (it.no) markNos[it.id] = it.no;
    });

    // 단일 검토와 같은 뷰어 크롬(viewerHeadHtml) — 문서명·쪽수·형광펜·줌·
    // 전체화면. 준비 중·실패 상태에서도 헤더는 남긴다(단일 검토와 같은 짜임).
    var head = viewerHeadHtml(out.file || view.key, true, "");
    var body;
    if (v.convertError) {
      body = head + '<div style="flex:1;display:flex;align-items:center;justify-content:center;padding:20px;font-size:13px;color:var(--sev-crit-fg);">' + esc(v.convertError) + '</div>';
    } else if (v.converting || !k.view) {
      body = head + '<div style="flex:1;display:flex;align-items:center;justify-content:center;gap:10px;font-size:14px;font-weight:600;color:var(--text-3);">' +
        '<span style="display:inline-block;animation:spin 1s linear infinite;">' + ICONS.refresh + '</span>문서를 PDF로 준비하는 중…</div>';
    } else {
      body = head + '<div id="pdf-mount" style="flex:1;overflow:hidden;"></div>';
    }

    var cards = mine.length
      ? mine.map(function (f, ci) {
          var sides = docSides(f.document);
          // 근거 줄과 문서를 짝지을 수 있을 때만 이름을 단다. 개수가 다르면
          // i 번째 근거가 i 번째 문서의 것이라는 보장이 없다 — 억지로 맞추면
          // 남의 문서 이름이 붙은 인용이 나온다.
          var paired = sides.length > 1 && (f.evidence || []).length === sides.length;
          var ev = (f.evidence || []).map(function (e, i) {
            var side = e.document || (paired ? sides[i] : "");
            var here = side === view.key;
            // 인용은 단일 검토 카드와 같은 형광펜(mark.sev-*) — PDF 위 형광펜과
            // 카드 근거가 같은 색으로 같은 문장을 가리킨다. 다른 문서의 인용은
            // 칠하지 않는다(이 화면의 형광펜은 지금 보는 문서 것이다).
            return '<div style="display:flex;gap:8px;font-size:12px;margin-top:4px;' +
              (here || !paired ? "" : "color:var(--text-3);") + '">' +
              '<span style="flex:none;width:52px;">' + esc(side) + '</span>' +
              '<span class="mono" style="flex:none;width:70px;color:var(--text-3);">' + esc(e.at) + '</span>' +
              '<span class="mono" style="min-width:0;">' +
                (f.sev && (here || !paired)
                  ? '<mark class="sev-' + esc(f.sev) + '">' + esc(e.quote) + '</mark>'
                  : esc(e.quote)) + '</span></div>';
          }).join("");
          // 이 지적이 걸친 **나머지 문서 전부**. 하나만 가정하면 전체 대조
          // (문서 3~4개)에서 세 이름이 붙은 버튼 하나가 나오고, 그 이름의
          // 산출물이 없어 눌러도 아무 일이 없었다.
          var others = sides.filter(function (x) { return x && x !== view.key; });
          // 첫 칸에는 구분선을 안 얹는다 — 패널 안쪽 여백 위에 선이 떠 보인다.
          return '<div data-case-finding="' + esc(f.id) + '" style="padding:12px 2px;' +
            (ci ? "border-top:1px solid var(--line-2);" : "") + '">' +
            '<div style="display:flex;gap:8px;align-items:center;">' +
              '<span data-case-number="' + esc(f.id) + '" style="display:inline-flex;align-items:center;gap:4px;">' +
                numberChip(markNos[f.id] || "", null, f.id, true) + '</span>' +
              // 심각도 뱃지는 **형광펜과 짝이다.** PDF 위 형광펜이 심각도 색으로
              // 칠해지므로(pdfview.js _SEV), 카드에서 등급을 빼면 노란 형광펜을
              // 보고도 왜 노란지 알 길이 없어진다.
              //
              // 폴더 검토는 규칙만 돌아 지금은 전부 MAJOR 라 뱃지가 늘 같다. 그래도
              // 남긴다 — 여기서 뱃지가 하는 일은 "등급을 가른다"가 아니라 "형광펜
              // 색이 무엇을 뜻하는지 말한다"이다. 분포 바·범례는 그 짝이 없으므로
              // 한 등급뿐일 때 그리지 않는다(issuesShell).
              caseFindingBadge(f) +
              // 기준 id(`F-성적서번호` · `W-작성일자-순서` · `1-7/대표자`)는 **화면에
              // 안 낸다.** 셋이 규칙도 출처도 달라(코드 생성 · 팀 yaml 의 case_wide ·
              // 팀 yaml 의 pairs) 검토자가 읽을 값이 아니다. 뱃지가 무엇이 잡았는지를
              // 이미 사람 말로 말한다 — id 는 그 옆에서 자리만 차지했다.
              //
              // 값 자체는 payload 에 남는다(ruleId) — CSV·리포트가 되짚을 때 쓴다.
            '</div>' +
            '<div style="font-size:13px;margin-top:4px;">' + esc(f.message) + '</div>' + ev +
            (others.length
              ? '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">' +
                others.map(function (o) {
                  return '<button class="btn btn-ghost" data-act="openCaseDoc" data-arg="' + esc(o + "|" + f.id) +
                    '" style="padding:4px 10px;font-size:12px;">' + esc(o) + ' 에서 보기</button>';
                }).join("") + '</div>'
              : "") +
          '</div>';
        }).join("")
      : '<div style="padding:14px;font-size:13px;color:var(--text-3);">이 문서를 가리키는 지적이 없습니다.</div>';

    // 단일 검토 결과와 같은 행 구조 — id(results-row)와 스타일이 같아야
    // 전체화면(toggleViewerFull)·Esc 가 이 화면에서도 같은 손잡이로 동작한다.
    // 파일명은 상단 바가 아니라 뷰어 헤더가 말한다(단일 검토와 같은 자리).
    return '<div style="height:100%;box-sizing:border-box;display:flex;flex-direction:column;">' +
      // 돌아가기는 단일 검토의 백링크와 같은 관용구(hover-accent + 화살표) —
      // 여기만 ghost 버튼이면 같은 동작이 화면마다 다른 손잡이로 보인다.
      '<div style="display:flex;align-items:center;gap:10px;flex:none;padding:10px 32px 4px;">' +
        '<div class="hover-accent" data-act="closeCaseDoc" tabindex="0" role="button" ' +
          'style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;' +
          'color:var(--text-3);cursor:pointer;padding:8px;margin-left:-8px;">' +
          ICONS.arrowLeft + ' 리포트로 돌아가기</div>' +
        '<span style="font-size:14px;font-weight:700;">' + esc(view.key) + '</span>' +
      '</div>' +
      '<div id="results-row" style="' + resultsRowCss(state.viewerFull) + '">' +
        viewerWrap(true, body) +
        // 단일 검토와 같은 껍데기(issuesShell). 제목만 다르다 — 여기서는 폴더 안
        // 문서 하나를 보는 중이라 "이 문서의" 를 붙여야 무엇을 센 숫자인지 읽힌다.
        // chips 를 안 넘긴다 — 이 목록은 지적만 담고(미검토는 걸러진다) 폴더
        // 검토는 규칙만 돌아 전부 MAJOR 다. 한 칸짜리 분포 바와 `● Major 3`
        // 한 줄은 위의 큰 숫자를 두 번 더 말하는 것뿐이다.
        issuesShell({
          title: "이 문서의 검토 결과",
          count: mine.length,
          body: cards
        }) +
      '</div>' +
    '</div>';
  }


  function caseManual(v, p) {
    var k = v.kase, manual = p.manual || [];
    if (!manual.length) return "";
    var savedResults = p.manualResults || [];
    var rows = manual.map(function (m) {
      var on = !!k.checked[m.id];
      var value = (k.manualInputs || {})[m.id] || "";
      var result = savedResults.filter(function (r) { return r.id === m.id; })[0];
      var status = result && result.status;
      var statusTone = status === "일치" ? "color:var(--band-good-fg);background:var(--band-good-bg);"
        : status === "수정 필요" ? "color:var(--sev-maj-fg);background:var(--sev-maj-bg);"
        : "color:var(--text-3);background:var(--neutral-weak);";
      var compared = result && result.input
        ? (result.cells || []).map(function (c) {
            return '<span style="font-size:11px;color:' +
              (c.ok === true ? 'var(--band-good-fg)' : c.ok === false ? 'var(--sev-maj-fg)' : 'var(--text-3)') +
              ';">' + esc(c.output) + ': ' + esc(c.found ? c.value : '값 못 찾음') + '</span>';
          }).join('<span style="color:var(--line);"> · </span>')
        : "";
      var affected = result && result.affectedCount
        ? '<div data-manual-result style="margin:8px 0 0 28px;padding:10px 12px;border-radius:var(--r-sm);' +
            'background:var(--sev-maj-bg);color:var(--sev-maj-fg);font-size:12px;">' +
            '<div style="font-weight:700;">일괄 수정 필요 · 올바른 값 ' +
              '<span class="mono">' + esc(result.correctValue) + '</span> · 대상 ' +
              esc(result.affectedCount) + '개 문서</div>' +
            '<div style="display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:6px;">' +
              (result.affected || []).map(function (a) {
                return '<span>' + esc(a.output) + ': <span class="mono">' +
                  esc(a.currentValue) + '</span> → <span class="mono">' +
                  esc(a.correctValue) + '</span></span>';
              }).join('') +
            '</div></div>'
        : "";
      return '<div data-manual-row="' + esc(m.id) + '" style="padding:12px;border-top:1px solid var(--line-2);font-size:13px;">' +
        '<div style="display:flex;align-items:center;gap:10px;">' +
        '<button type="button" aria-label="' + esc(m.text) + ' 확인" data-act="toggleManual" data-arg="' + esc(m.id) + '" ' +
          (v.kase.confirming ? "disabled " : "") +
          'style="width:18px;height:18px;padding:0;flex:none;border-radius:4px;border:1px solid ' +
          (on ? "var(--accent)" : "var(--line)") + ';background:' + (on ? "var(--accent)" : "var(--panel)") +
          ';color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;">' + (on ? ICONS.check : "") + '</button>' +
        '<span style="flex:1;' + (on ? "" : "color:var(--text-2);") + '">' + esc(m.text) + '</span>' +
        '<span style="flex:none;font-size:11px;color:var(--text-3);">대조 원천: ' + esc(m.against || "") + '</span>' +
        (status ? '<span data-manual-result style="flex:none;font-size:11px;font-weight:600;padding:4px 8px;border-radius:var(--r-sm);' +
          statusTone + '">' + esc(status) + '</span>' : '') +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:10px;margin:8px 0 0 28px;">' +
          '<input type="text" data-manual-input="' + esc(m.id) + '" value="' + esc(value) + '" ' +
            (v.kase.confirming ? "disabled " : "") +
            'placeholder="' + esc((m.against || "외부 원천") + '의 기준값 입력') + '" ' +
            'style="flex:1;min-width:180px;padding:8px 10px;border:1px solid var(--line);border-radius:var(--r-sm);' +
            'background:var(--panel);color:var(--text);font-size:12px;">' +
          '<span style="font-size:11px;color:var(--text-3);">입력값과 문서의 ' + esc((result && result.field) || String(m.id).replace(/^M-/, "")) + ' 값을 대조합니다.</span>' +
        '</div>' +
        affected +
        (compared ? '<div data-manual-result style="display:flex;flex-wrap:wrap;gap:4px;margin:8px 0 0 28px;">' + compared + '</div>' : '') +
      '</div>';
    }).join("");
    var done = manual.filter(function (m) { return k.checked[m.id]; }).length;
    return caseCard(
      '<div style="display:flex;align-items:baseline;gap:8px;">' +
        '<span style="font-size:13px;font-weight:600;">직접 확인 ' + done + '/' + manual.length + '</span>' +
        '<span style="font-size:12px;color:var(--text-3);">외부 원천을 확인해 체크하고 값을 입력하면, 저장된 문서값과 추가 대조합니다.</span>' +
      '</div>' +
      '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;margin-top:10px;">' + rows + '</div>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-top:12px;">' +
        '<button class="btn btn-primary" data-act="confirmCase"' + (v.kase.confirming ? " disabled" : "") +
          ' style="flex:1;padding:10px;font-size:13px;font-weight:600;">' +
          (v.kase.confirming ? "추가 대조·저장 중…" : "추가 대조 후 점검 확정 · 이력 저장") + '</button>' +
        // 누른 결과는 누르는 자리 옆에 둔다. 떨어져 있으면 눌렸는지 확인하러
        // 다른 데를 봐야 한다.
        (k.confirmedAt ? '<span id="case-confirmed-at" style="flex:none;font-size:12px;color:var(--text-3);">확정 ' +
          esc(String(k.confirmedAt).replace("T", " ").replace("+00:00", " UTC")) + '</span>' : "") +
      '</div>', "20px");
  }

  function caseReport(v) {
    var k = v.kase, p = k.payload, st = p.stats || {};
    if (k.view) return caseDocView(v);
    var tab = k.tab || "summary";
    var manual = p.manual || [];
    var done = manual.filter(function (m) { return k.checked[m.id]; }).length;
    var excluded = (st.unclassified || 0) + (st.ignored || 0);
    var tabs = [["summary", "요약"], ["compare", "지적 " + (st.findings || 0)],
                ["matrix", "필드 대조 " + (st.wideTotal || 0)], ["outputs", "추출된 값"],
                ["manual", "직접 확인 " + done + "/" + manual.length],
                ["other", "검토 제외 " + excluded], ["criteria", "검토 기준"]];
    // 앱 공용 .tab — 밑줄·글자 모두 --accent-ink 다. 여기만 --accent(채움색)로
    // 밑줄을 그으면 다른 화면 탭과 색이 갈린다.
    //
    // 탭은 카드의 고정 머리줄이다 — 스크롤은 탭 아래 내용만 한다(아래 return
    // 참고). 한때 sticky 로 붙였는데, 화면 상단에 걸리는 순간 카드 테두리에서
    // 떨어져 나온 흰 띠처럼 보였다(좌우 1px 테두리는 스크롤되는데 띠는 테두리
    // 없이 남는다). 구조로 고정하면 그런 이음새 자체가 없다.
    var tabBar = '<div style="display:flex;flex-wrap:wrap;gap:18px;border-bottom:1px solid var(--line);">' +
      tabs.map(function (t) {
        return '<span class="tab' + (tab === t[0] ? " on" : "") + '" data-act="setCaseTab" data-arg="' + t[0] + '" tabindex="0" role="button">' +
          esc(t[1]) + '</span>';
      }).join("") + '</div>';

    var panel = "";
    if (tab === "summary") {
      panel = caseFindingSummary(p) + caseMatrixSummary(p) +
        '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">문서별 결과</div>' +
        '<div style="font-size:12px;color:var(--text-3);margin-bottom:10px;">' +
          '문서 행은 상태 요약입니다. 원문은 각 행의 ‘문서에서 보기’ 버튼으로 엽니다.</div>' +
        caseOutputTable(p);
    } else if (tab === "matrix") {
      panel = '<div style="font-size:12px;color:var(--text-3);margin-bottom:10px;">' +
        '항목 이름을 누르면 비교한 값과 판정 이유가 이 화면에서 펼쳐집니다. ' +
        '검토 기준은 상세 안의 ‘이 기준 보기’ 버튼으로 확인합니다.</div>' +
        caseMatrix(p, k.matrixFocus || "");
    } else if (tab === "outputs") {
      panel = caseFieldsPanel(p, k.selOutput);
    } else if (tab === "compare") {
      panel = '<div style="font-size:12px;color:var(--text-3);margin-bottom:10px;">' +
        '수정하거나 확인할 문제 목록입니다. 문서 위치·대조표·검토 기준은 각 버튼으로 구분해 엽니다.</div>' +
        caseFindingList(p);
    } else if (tab === "manual") {
      panel = caseManual(v, p);
    } else if (tab === "criteria") {
      panel = caseCriteria(v);
    } else {
      panel = caseOtherPanel(p);
    }
    if (k.error) {
      panel = '<div role="alert" style="margin-bottom:12px;padding:10px 12px;border-radius:var(--r-sm);' +
        'background:var(--sev-maj-bg);color:var(--sev-maj-fg);font-size:13px;">' +
        esc(k.error) + '</div>' + panel;
    }

    // 페이지 전체가 아니라 **탭 아래만** 스크롤한다 — 단일 검토의 결과 패널과
    // 같은 구조다(머리줄·탭 고정, 내용만 흐른다). 스크롤 위치 복원(data-scroll)
    // 은 실제로 스크롤하는 안쪽 칸이 진다.
    return '<div class="page-shell" style="display:flex;overflow:hidden;">' +
      '<div class="page-container page-stack" style="display:flex;flex-direction:column;min-height:0;">' +
      caseCard(
        '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px;">' +
          '<h1 style="margin:0;font-size:22px;font-weight:700;letter-spacing:-.01em;color:var(--text);">' + esc(p.caseId || "점검") + '</h1>' +
          '<div style="font-size:13px;color:var(--text-3);">' + esc(p.team || "") + '</div>' +
          '<div style="margin-left:auto;display:flex;gap:8px;">' +
            '<button class="btn btn-ghost" data-act="caseCsv"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>CSV 내려받기</button>' +
            '<button class="btn btn-ghost" data-act="clearCaseFiles"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"></path><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M3 22v-6h6"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path></svg>새 점검</button>' +
          '</div>' +
        '</div>' +
        // 결과와 검토 범위를 가른다. 전에는 산출물·대조율·지적·미검토·합산값을
        // 같은 크기로 일곱 칸에 늘어놓아 무엇이 문제 수인지 알 수 없었다.
        '<div style="display:flex;align-items:stretch;margin-top:12px;border:1px solid var(--line);border-radius:var(--r-md);">' +
          caseStat(st.findings || 0, "전체 지적") +
          caseStat(st.unreviewed || 0, "미검토", "var(--text-3)") +
          caseStat(done + "/" + manual.length, "직접 확인", "var(--text-3)") +
          '<div style="flex:none;align-self:stretch;width:1px;background:var(--line);margin:10px 0;"></div>' +
          '<div style="flex:1.5;display:flex;flex-direction:column;justify-content:center;padding:10px 16px;">' +
            '<div style="font-size:11px;font-weight:600;color:var(--text-3);margin-bottom:6px;">검토 범위</div>' +
            '<div style="display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--text-2);">' +
              '<span>산출물 인식 <b>' + (st.outputs || 0) + "/" + ((st.outputs || 0) + (st.missing || 0)) + '</b></span>' +
              '<span>전체 필드 대조 판정 <b>' + (st.wideChecked || 0) + "/" + (st.wideTotal || 0) + '</b></span>' +
              '<span>분류가 필요한 파일 <b>' + (st.unclassified || 0) + '</b></span>' +
              '<span>참고자료 제외 <b>' + (st.ignored || 0) + '</b></span>' +
            '</div>' +
          '</div>' +
        '</div>', "20px") +
      // 탭 카드만은 caseCard 를 안 쓴다 — 껍데기는 같은 값(패널면·선·모서리)
      // 이지만 안이 머리줄(고정)과 스크롤 칸으로 갈라져야 한다.
      '<div style="flex:1;min-height:0;display:flex;flex-direction:column;' +
        'background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);">' +
        '<div style="flex:none;padding:20px 20px 0;">' + tabBar + '</div>' +
        '<div data-scroll="case-results" style="flex:1;overflow-y:auto;padding:16px 20px 20px;">' + panel + '</div>' +
      '</div>' +
      '</div>' +
    '</div>';
  }

  // 검토 기준 — **판정에 쓰이는 그대로** 보여준다. 요약하면 실제로 도는 규칙과
  // 화면이 갈리고, 검토자가 "왜 이게 지적이지?"를 물었을 때 답이 안 된다.
  //
  // 필드로 묶는다. 산출물별로 늘어놓으면 같은 필드가 반복된다 — 실측: 48줄인데
  // 실제 필드는 20개고 의뢰번호 하나가 7번 나온다. 리포트에서 넘어오는 것도
  // "시험항목명 0/4" 라는 **필드**다.
  function caseCriteria(v) {
    var k = v.kase, c = k.criteria;
    if (!c) {
      // 셋을 구분한다 — 부르는 중 · 실패(사유와 다시 시도) · 아직 안 부름.
      // 하나로 뭉치면 검토자가 뭘 해야 할지 모른다.
      if (k.criteriaError) {
        return '<div style="font-size:13px;color:var(--sev-maj-fg);">' +
          esc(k.criteriaError) + '</div>' +
          '<button class="btn btn-ghost" data-act="loadCriteria" style="margin-top:10px;">다시 불러오기</button>';
      }
      return '<div style="font-size:13px;color:var(--text-3);">검토 기준을 불러오는 중…</div>';
    }
    var focus = k.criteriaFocus || "";
    var fieldFocus = focus.indexOf("F-") === 0 ? focus.slice(2) : "";
    var wideById = {};
    (c.caseWide || []).forEach(function (w) { wideById[w.id] = w; });
    var pairById = {};
    (c.pairs || []).forEach(function (pr) { pairById[pr.id] = pr; });

    function chip(text, tone) {
      return '<span class="mono" style="flex:none;font-size:11px;padding:2px 6px;border-radius:5px;' +
        'background:' + (tone || "var(--accent-weak)") + ';color:var(--text-2);">' + esc(text) + '</span>';
    }

    // 이 산출물에서 값을 어떻게 집는지. 이름만 보여주면 산출물 탭과 다를 게 없다.
    function how(w) {
      if (w.from === "table_rows") return "표에서 열 " + (w.columns || []).join(" · ") + " 을(를) 찾습니다";
      if (w.from === "checkbox_group") return "선택지 " + (w.options || []).join(" · ");
      if (w.from === "header" || w.from === "footer") return "머릿말/꼬리말 — 아직 못 읽습니다";
      return "라벨 " + (w.labels || []).map(function (l) { return '"' + l + '"'; }).join(" 또는 ") +
             " 의 " + (w.at === "below" ? "아래" : "오른쪽") + " 칸";
    }

    function rules(w) {
      var out = [];
      if (w.required) out.push(chip("필수"));
      if (w.pattern) out.push(chip("형식 " + w.pattern));
      if (w.format) out.push(chip(w.format === "date_range" ? "기간" : "날짜"));
      if (w.equals) out.push(chip("고정 " + w.equals));
      if (w.select === "one") out.push(chip("하나만"));
      (w.requiredColumns || []).forEach(function (col) { out.push(chip(col + " 필수")); });
      return out.join("");
    }

    var fields = (c.fields || []).map(function (f) {
      var wide = wideById[f.caseWide];
      var on = (f.caseWide && f.caseWide === focus) ||
        (fieldFocus && f.name === fieldFocus) ||
        ((f.pairs || []).indexOf(focus) >= 0);
      // 이 필드가 어느 대조에 쓰이나. "라벨은 이것"(추출)과 "N곳에서 같아야
      // 한다"(대조)가 한 자리에 있어야 왜 미검토인지 짚을 수 있다.
      var note = wide
        ? wide.outputs.length + "곳에서 같아야 합니다 — " + wide.outputs.join(" · ")
        : (f.pairs.length
            ? f.pairs.map(function (id) {
                var pr = pairById[id];
                return pr ? (pr.left + " ↔ " + pr.right + " (쌍 " + id + ")") : id;
              }).join(" · ")
            : "이 산출물 안에서만 봅니다");

      var body = f.where.length
        ? f.where.map(function (w) {
            return caseRow(
              '<span style="width:150px;flex:none;color:var(--text-2);">' + esc(w.output) + '</span>' +
              '<span style="flex:1;min-width:0;color:var(--text-2);">' + esc(how(w)) + '</span>' +
              '<span style="flex:none;display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;">' +
                rules(w) + '</span>');
          }).join("")
        : caseRow('<span style="color:var(--text-2);">어느 산출물에서도 이 값을 뽑는 기준이 없습니다 — ' +
                  '그래서 늘 미검토로 남습니다</span>');

      return '<div' + (on ? ' data-criteria-focused="true"' : '') +
        ' style="margin-bottom:14px;' + (on ? "outline:2px solid var(--accent);outline-offset:4px;border-radius:var(--r-sm);" : "") + '">' +
        '<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px;">' +
          '<span style="font-size:13px;font-weight:600;">' + esc(f.name) + '</span>' +
          '<span style="font-size:12px;color:var(--text-3);">' + esc(note) + '</span>' +
          '<span style="margin-left:auto;flex:none;font-size:11px;color:var(--text-3);">' +
            esc(f.where.length + "곳") + '</span>' +
        '</div>' +
        '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + body + '</div>' +
      '</div>';
    }).join("");

    // 산출물별로만 있는 기준 — 고정 문구와 서명란. 필드가 아니라 문서 단위다.
    var perOutput = (c.outputs || []).map(function (o) {
      var lines = "";
      if ((o.fixedText || []).length) {
        lines += caseRow('<span style="width:150px;flex:none;color:var(--text-2);">고정 문구</span>' +
          '<span style="flex:1;min-width:0;color:var(--text-2);">' +
          esc(o.fixedText.length + "개 — " + o.fixedText[0].slice(0, 44) + "…") + '</span>');
      }
      (o.signatures || []).forEach(function (s) {
        lines += caseRow('<span style="width:150px;flex:none;color:var(--text-2);">서명 ' + esc(s.role) + '</span>' +
          '<span style="flex:1;min-width:0;color:var(--text-2);">' +
          esc('"' + s.placeholder + '" 가 그대로면 미작성 (' + (s.at === "below" ? "아래" : "오른쪽") + ' 칸)') + '</span>');
      });
      if (!lines) return "";
      return '<div style="margin-bottom:14px;">' +
        '<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px;">' +
          '<span style="font-size:13px;font-weight:600;">' + esc(o.key) + '</span>' +
          '<span class="mono" style="font-size:11px;color:var(--text-3);">' + esc(o.formNo) + '</span>' +
        '</div>' +
        '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + lines + '</div>' +
      '</div>';
    }).join("");

    var skips = (c.ignore || []).map(function (i) {
      return caseRow(
        '<span style="width:150px;flex:none;" class="mono">' + esc(i.pattern) + '</span>' +
        '<span style="flex:1;color:var(--text-2);">' + esc(i.reason) + '</span>');
    }).join("");

    function block(title, note, body) {
      if (!body) return "";
      return '<div style="margin-bottom:20px;">' +
        '<div style="font-size:13px;font-weight:600;margin-bottom:4px;">' + esc(title) + '</div>' +
        (note ? '<div style="font-size:12px;color:var(--text-3);margin-bottom:10px;">' + esc(note) + '</div>' : "") +
        body + '</div>';
    }

    return '<div style="font-size:12px;color:var(--text-3);margin-bottom:16px;">' +
        esc(c.team + " 검토 기준입니다. 지금 판정에 쓰이는 규칙 그대로입니다. " +
            "팀이 준 요구사항 " + c.itemCount + "항목 중 검사로 옮긴 부분입니다.") +
      '</div>' +
      block("값 " + (c.fields || []).length + "개 — 어디서 어떻게 뽑고, 어디끼리 맞추나", "", fields) +
      block("문서 단위 기준", "필드가 아니라 문서 전체에 걸리는 것입니다.", perOutput) +
      block("건너뛰는 파일", "이 규칙에 걸리는 파일은 검사하지 않습니다.",
            skips ? '<div style="border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden;">' + skips + '</div>' : "");
  }

  // CSV — **전 항목을 내보낸다.** 판정한 것만 내보내면 받아 본 사람은 그게 전부라고
  // 읽는다(preset/export.py 와 같은 원칙). 판정 못 한 것은 "미판정"으로 남긴다.
  function caseCsvText(p) {
    function cell(x) {
      var s = String(x == null ? "" : x);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    var rows = [["번호", "분류", "항목", "판정", "이유", "문서", "위치", "값"]];
    (p.outputs || []).forEach(function (o) {
      var stale = o.formNo && o.formNo.stale;
      rows.push([o.key, "산출물 인식", "양식번호가 최신 개정본인가",
                 o.formNo && o.formNo.found ? (stale ? "불일치" : "일치") : "미판정",
                 stale ? o.formNo.found + " ≠ " + o.formNo.expected
                       : (o.formNo && o.formNo.found ? "" : "파일명에 양식번호가 없습니다"),
                 o.file, ""]);
      rows.push([o.key, "산출물 검사", "단일 문서 검사", "미판정", o.reason || "", o.file, ""]);
    });
    (p.missing || []).forEach(function (key) {
      rows.push([key, "산출물 인식", "산출물이 제출되었는가", "불일치",
                 "올라오지 않았습니다", "", ""]);
    });
    (p.matrix || []).forEach(function (m) {
      (m.cells || []).forEach(function (c) {
        rows.push([m.id, "전 산출물 대조", m.field,
                   m.status === "미검토" ? "미판정" : m.status,
                   c.present
                     ? (c.configured === false ? "필드 추출 규칙이 없습니다"
                        : (c.found ? "" : "값을 찾지 못했습니다"))
                     : "올라오지 않았습니다",
                   c.output, c.at || "", c.found ? c.value : ""]);
      });
    });
    (p.manualResults || []).forEach(function (r) {
      var unresolved = ["확인 전", "입력 없음", "입력값 오류", "미검토"]
        .indexOf(r.status) >= 0;
      rows.push([r.id, "외부 기준값 대조", r.field,
                 unresolved ? "미판정" : r.status,
                 "대조 원천: " + (r.against || ""),
                 (r.cells || []).map(function (c) { return c.output; }).join(" · "),
                 (r.cells || []).map(function (c) { return c.at || ""; }).join(" / "),
                 r.input || ""]);
    });
    (p.findings || []).forEach(function (f) {
      // 전 산출물 대조는 위 매트릭스가 칸마다 이미 냈다. 여기서는 **왜 어긋났는지**
      // 한 줄만 더한다 — 판정을 두 번 세면 합계가 부풀어 오른다.
      var at = (f.evidence || []).map(function (e) { return e.at; }).join(" / ");
      var kind = f.kind === "case_wide" ? "전 산출물 대조 — 사유"
        : f.kind === "output" ? "칸 값 검사"
        : f.kind === "manual_input" ? "외부 기준값 대조"
        : "산출물 간 대조";
      rows.push([f.ruleId, kind, f.ruleId,
                 f.unreviewed ? "미판정" : "불일치", f.message, f.document || "", at, ""]);
    });
    (p.unclassified || []).forEach(function (x) {
      rows.push(["", "미분류", "산출물 판별", "미판정",
                 "양식번호가 없어 판별하지 못했습니다", x.file, ""]);
    });
    (p.ignored || []).forEach(function (x) {
      rows.push(["", "건너뜀", "검사 대상 여부", "해당없음", x.reason || "", x.file, ""]);
    });
    return rows.map(function (r) { return r.map(cell).join(","); }).join("\n");
  }

  // 서버가 내는 단계는 넷이다 (src/app/case.py) — classify 한 번, 그다음
  // output·case_wide·pair 가 항목마다 반복된다. 반복이라 dict 에는 넷만 남고
  // detail 만 계속 바뀐다. 그래서 "지금 무엇을 보고 있나"가 detail 이고,
  // 단계 자체는 처음부터 넷으로 고정이다 — 단일 검토와 같은 타임라인이 된다.
  var CASE_STAGES = [
    { key: "classify",  label: "산출물 판별", desc: "양식번호로 무엇이 무엇인지 가려냅니다" },
    { key: "output",    label: "낱장 검사",   desc: "산출물마다 칸 값을 뽑아 규칙에 겁니다" },
    { key: "case_wide", label: "전 산출물 대조", desc: "여러 문서에 걸친 값이 서로 같은지 봅니다" },
    { key: "pair",      label: "문서 쌍 대조", desc: "짝지어진 두 문서를 맞대 봅니다" }
  ];

  // 진행 화면에서 단계마다 갈아끼우는 조각. api.js 의 repaintCaseStages 가
  // 같은 함수를 불러 전체 render 없이 이 안쪽만 바꾼다 — 그래야 취소 버튼이
  // 재생성되지 않아 hover 가 유지된다(단일 검토가 쓰는 방식과 같다).
  function caseStageList(k) {
    // 도달한 마지막 단계가 '진행 중', 그 앞은 '완료'. 서버가 총량을 안 주므로
    // 지어내지 않는다 — 남은 단계는 '대기'로 흐리게 둔다.
    var last = -1;
    CASE_STAGES.forEach(function (s, i) { if (k.stage[s.key] != null) last = i; });
    var ACC = "var(--accent)";
    return CASE_STAGES.map(function (s, i) {
      var done = i < last, active = i === last;
      return timelineItem({
        label: s.label, desc: s.desc,
        detail: k.stage[s.key] || "",
        detailColor: active ? ACC : "var(--text-3)",
        op: (!done && !active) ? 0.6 : 1,
        lineColor: (done || active) ? ACC : "var(--line)",
        dotBg: done ? ACC : (active ? "var(--panel)" : "var(--line-2)"),
        dotBorder: (done || active) ? ACC : "var(--line)",
        dotFg: done ? "#fff" : ACC,
        dotIcon: done ? ICONS.check : "",
        dotAnim: active ? "--pc:rgba(var(--accent-rgb),0.28);animation:dvpulse 1.4s ease-in-out infinite;" : "",
        bd: active ? ACC : "var(--line)",
        statusLabel: done ? "DONE" : (active ? "RUNNING" : "QUEUED"),
        statusColor: active ? ACC : "var(--text-3)"
      });
    }).join("");
  }

  function caseProgress(v) {
    var k = v.kase;
    var last = -1;
    CASE_STAGES.forEach(function (s, i) { if (k.stage[s.key] != null) last = i; });
    var pct = Math.round((last + 1) / CASE_STAGES.length * 100);
    var err = k.error
      ? '<div style="margin-top:14px;padding:12px 14px;background:var(--sev-crit-bg);border:1px solid var(--sev-crit-bd);border-radius:var(--r-sm);color:var(--sev-crit-fg);font-size:13px;">' + esc(k.error) + '</div>'
      : "";
    // 단일 검토의 진행 화면과 같은 껍데기다(그쪽 주석 참고 — 왜 유리가 아니라
    // 불투명 패널인지). 예전에는 평범한 카드에 "key: value" 네 줄이라 같은
    // 앱으로 안 보였는데, 그건 재질이 아니라 progressHead·단계 목록이 푼다.
    return '<div data-scroll="case-progress" style="padding:36px 32px;height:100%;overflow-y:auto;">' +
      '<div style="max-width:1040px;margin:0 auto;background:var(--panel);' +
        'border:1px solid var(--line);border-radius:var(--r-lg);padding:32px;box-shadow:var(--sh-2);">' +
        '<div style="margin-bottom:24px;">' +
          progressHead(false, 0, ["폴더 검토 중…", "낱장을 먼저 보고, 그다음 문서끼리 맞춰봅니다"], pct) +
        '</div>' +
        '<div id="kase-stages">' + caseStageList(k) + '</div>' + err +
        '<div style="display:flex;align-items:center;justify-content:space-between;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--text-3);">' +
          '<span>' + pct + '% · ' + CASE_STAGES.length + '단계 중 ' + Math.max(0, last + 1) + '</span>' +
          '<div style="display:flex;align-items:center;gap:16px;">' +
            '<span id="kase-elapsed" class="mono">' +
              esc(k.startedAt ? fmtElapsed(Date.now() - k.startedAt) + " 경과" : "시작하는 중") + '</span>' +
            '<button data-act="cancelCase" class="btn btn-ghost btn-ghost-accent" style="font-size:13px;padding:6px 14px;">검사 취소</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function body(v) {
    var inner = "";
    if (v.isHome) inner = appHomeView(v);
    else if (v.sUpload) inner = singleUpload(v);
    else if (v.sProgress) inner = singleProgress(v);
    else if (v.sResults) inner = singleResults(v);
    else if (v.kUpload) inner = caseUpload(v);
    else if (v.kRecognize) inner = caseRecognize(v);
    else if (v.kProgress) inner = caseProgress(v);
    else if (v.kResults) inner = caseReport(v);
    else if (v.cSetup) inner = compareSetup(v);
    else if (v.cProgress) inner = compareProgress(v);
    else if (v.cResults) inner = compareResults(v);
    else if (v.isChecklists) inner = checklistsView(v);
    else if (v.isChecklistRun) inner = checklistRunScreen(v);
    else if (v.isHistory) inner = historyView(v);
    else if (v.isSettings) inner = settingsView(v);
    // 화면이 바뀌면 **어느 화면이든 같은 방식으로** 들어온다. 화면마다 따로
    // 붙이면 어떤 화면은 연출이 있고 어떤 화면은 없는 채로 갈린다 — 실제로
    // 홈과 검토 진행 화면만 있고 나머지는 툭 바뀌던 상태였다. 한 자리에서 씌운다.
    //
    // 음수 지연은 enterAnim 과 같은 이유다: 진입 창(250ms) 안에 다시 그려져도
    // 처음부터 되감기지 않고 이미 흐른 만큼 건너뛴 자리에서 이어 붙는다.
    // 홈은 이 위에서 타일이 계단으로 더 앉는다(appHomeView tileEnter).
    //
    // 관용구는 fadeIn 하나다(8px 올라오며 나타남) — 제안 상자·드롭다운이 이미
    // 쓰는 것이다. 한때 원근을 넣어 판이 세워지듯 꺾어 봤는데, 타일 한 장이면
    // 몰라도 화면 전체가 그러면 이동할 때마다 큰 사건이 된다. 매번 보는
    // 화면에서 연출은 **있다는 것만 알면 되지 쳐다보게 만들면 안 된다.**
    var enter = v.anim.entered
      ? 'animation:fadeIn .2s var(--ease-out) backwards;animation-delay:-' + v.anim.enterElapsed + 'ms;'
      : '';
    return '<div id="main-scroll" data-scroll="main" style="flex:1;min-height:0;overflow:auto;' + enter + '">' + inner + '</div>';
  }

  function loginView() {
    var lastEmail = localStorage.getItem("dr_last_email") || "";
    var inputStyle = "width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:var(--r-md);font-size:15px;color:var(--text);background:var(--bg);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);box-sizing:border-box;";
    var labelStyle = "display:block;font-size:14px;font-weight:600;color:var(--text-2);margin-bottom:8px;";
    
    return '<div class="auth-canvas" style="width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;position:relative;overflow:hidden;">' +
      authBlobs() +
      '<div style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:0.04;mix-blend-mode:overlay;background-image:url(\'data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E\');"></div>' +
      '<div class="login-modal" style="position:relative;z-index:1;display:flex;width:100%;max-width:1320px;min-height:790px;background:var(--panel-glass);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-radius:calc(var(--r-xl) + 4px);overflow:hidden;box-shadow:' + AUTH_SHADOW + ';animation:fadeUp .6s var(--ease-out) forwards;">' +
        // 면 색(방사형 그라데이션 3겹)은 인라인이 아니라 index.html 의 .login-brand 가
        // 쥔다 — 다크에서 알파만 갈아 끼워야 하는데 인라인 style 은 테마를 못 탄다.
        '<div class="login-brand" style="flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:56px 48px;color:white;position:relative;overflow:hidden;">' +
          brandBackdrop() +
          // 그래인은 배경 도형 **위에** 와야 한 면으로 읽힌다 — 도형보다 먼저 그리면
          // 렌즈·문서만 매끈하게 남아 따로 얹은 판처럼 보인다.
          '<div style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:0.05;mix-blend-mode:overlay;background-image:url(\'data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E\');"></div>' +
          '<div class="hero-stage" data-hero-scene>' +
            '<span class="hero-doc hero-doc-left" aria-hidden="true"></span>' +
            '<span class="hero-doc hero-doc-right" aria-hidden="true"></span>' +
            // ?v= 는 index.html 의 favicon·스크립트가 이미 쓰는 규칙인데 여기만
            // 빠져 있었다. 파일명을 그대로 두고 그림만 갈면 브라우저는 옛 그림을
            // 계속 쓴다 — 실제로 돋보기 색을 바꾸고도 화면이 안 바뀌어 한참 헤맸다.
            // 마스코트를 갈 때마다 이 값도 같이 바꿀 것.
            '<img class="hero-mascot" src="public/login_hero.png?v=20260813-hero-2d" alt="DocSuree 문서 검토 마스코트">' +
            '<span class="hero-lens-glint" aria-hidden="true"></span>' +
          '</div>' +
          '<h1 class="brand-wordmark" style="margin:0 0 18px 0;line-height:1;">Doc<span style="color:var(--brand-accent);">Suree</span></h1>' +
          // 줄바꿈은 "퇴근을 앞당기는 / 가장 확실한 문서 검토" 로 끊는다. 예전엔
          // 관형어(가장 확실한)만 첫 줄 끝에 남고 꾸밈받는 말(문서 검토)이 다음
          // 줄로 넘어가, 한 덩어리인 말이 문법이 아닌 자리에서 갈라졌다.
          '<p style="font-size:18px;line-height:1.6;color:rgba(255,255,255,0.95);margin:0;font-weight:700;letter-spacing:-0.5px;">퇴근을 앞당기는<br>가장 확실한 문서 검토</p>' +
        '</div>' +
        '<div class="login-form" style="flex:1;display:flex;flex-direction:column;justify-content:center;background:var(--panel);padding:56px 52px;">' +
        '<div style="width:100%;max-width:400px;margin:0 auto;opacity:0;animation:fadeUp .8s var(--ease-out) .1s forwards;">' +
          '<h2 class="headline login-form-title" style="font-weight:700;color:var(--text);margin:0 0 8px 0;letter-spacing:-0.5px;">환영합니다</h2>' +
          '<p style="font-size:15px;color:var(--text-3);margin:0 0 36px 0;">사내 계정으로 로그인하여 시작하세요.</p>' +
          '<form action="javascript:void(0);" onsubmit="document.getElementById(\'loginBtn\').click();">' +
          '<div style="margin-bottom:24px;">' +
            '<label style="' + labelStyle + '">이메일 주소</label>' +
            '<input id="loginEmail" name="email" type="email" autocomplete="username" value="' + lastEmail + '" placeholder="name@company.com" style="' + inputStyle + '" onfocus="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--panel)\'" onblur="this.style.borderColor=\'var(--line)\';this.style.background=\'var(--bg)\'">' +
          '</div>' +
          '<div style="margin-bottom:32px;">' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
              '<label style="display:block;font-size:14px;font-weight:600;color:var(--text-2);margin:0;">비밀번호</label>' +
              '<span style="font-size:13px;color:var(--accent-ink);cursor:pointer;font-weight:600;transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);" onmouseover="this.style.opacity=0.7;this.style.textDecoration=\'underline\'" onmouseout="this.style.opacity=1;this.style.textDecoration=\'none\'" data-act="setMode" data-arg="forgot">비밀번호 찾기</span>' +
            '</div>' +
            '<input id="loginPwd" name="password" type="password" autocomplete="current-password" placeholder="••••••••" style="' + inputStyle + '" onfocus="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--panel)\'" onblur="this.style.borderColor=\'var(--line)\';this.style.background=\'var(--bg)\'">' +
          '</div>' +
          '<div style="display:flex;align-items:center;margin-bottom:24px;">' +
            '<input type="checkbox" id="rememberId" ' + (lastEmail ? 'checked' : '') + ' style="margin-right:8px;width:16px;height:16px;cursor:pointer;accent-color:var(--accent-ink);">' +
            '<label for="rememberId" style="font-size:14px;color:var(--text-2);cursor:pointer;user-select:none;">이메일 아이디 저장</label>' +
          '</div>' +
          '<button type="submit" id="loginBtn" class="btn btn-primary" data-act="doLogin" style="width:100%;padding:14px;border-radius:var(--r-md);font-size:15px;margin-bottom:16px;">로그인</button>' +
          '</form>' +
          '<div style="text-align:center;font-size:14px;color:var(--text-3);">' +
            '계정이 없으신가요? <span style="color:var(--accent-ink);font-weight:700;cursor:pointer;transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);" onmouseover="this.style.opacity=0.7;this.style.textDecoration=\'underline\'" onmouseout="this.style.opacity=1;this.style.textDecoration=\'none\'" data-act="setMode" data-arg="signup">회원가입</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '</div>' +
    '</div>';
  }


  // 로그인 계열 모달의 그림자. 예전엔 사진 배경 위에 떠 있어서 짙은 남색 그림자를
  // 크게 깔았는데, 바탕이 앱과 같은 밝은 캔버스로 바뀌면서 그 그림자는 화면에
  // 구멍을 뚫어 놓은 것처럼 무거워졌다. 그림자색은 앱 카드와 같은 계열로 맞춘다.
  var AUTH_SHADOW = "0 18px 50px rgba(17,24,39,0.10), 0 4px 12px rgba(17,24,39,0.05)";

  // 로그인 계열 화면의 배경 도형. 크기·위치·곡률은 index.html 의 .auth-blob 이 쥔다.
  function authBlobs() {
    return '<div class="auth-blob b1"></div><div class="auth-blob b2"></div>' +
           '<div class="auth-blob b3"></div><div class="auth-blob b4"></div>';
  }

  // 파란 브랜드 면 안쪽 배경. 바깥 캔버스(authBlobs)는 유기적인 덩어리지만 여기선
  // 제품의 어휘를 쓴다 — 가장자리에서 잘려 나가는 문서 면. 장식이라 스크린리더에서
  // 숨긴다. 크기·위치·움직임은 index.html 의 .bp-doc 이 쥔다.
  // (배경용 거대 돋보기도 한 번 넣었다가 지웠다 — index.html 쪽 주석 참고.)
  function brandBackdrop() {
    return '<span class="bp-doc bp-doc-tl" aria-hidden="true"></span>' +
           '<span class="bp-doc bp-doc-br" aria-hidden="true"></span>';
  }

  // 로그인 계열 화면(모달)의 뒤로가기. 모양·hover 는 index.html 의 .backlink 가 쥔다.
  function authBack(label) {
    return '<div class="backlink" data-act="setMode" data-arg="login">' + ICONS.arrowLeft + esc(label) + '</div>';
  }

  // 커스텀 셀렉트. 네이티브 <select> 는 펼친 목록을 OS 가 그려서 앱과 안 어울린다.
  // 값은 wrapper 의 data-value 에 담아두고 app.js 의 selToggle/selPick 이 여닫는다
  // (회원가입 폼 입력은 state 가 아니라 DOM 에 있어서 render() 를 못 부른다).
  var DEPTS = ["에너지인프라시스템실", "AX안전신뢰실", "우주항공국방기술실"];
  
  function getTeamsForDept(dept) {
    var all = teamOptions();
    if (!dept) return all;
    var validNames = [];
    if (dept === "AX안전신뢰실") {
      validNames = ["AX품질팀", "AI신뢰성1팀", "AI신뢰성2팀", "AI시험인증1팀", "AI시험인증2팀"];
    } else if (dept === "에너지인프라시스템실") {
      validNames = ["에너지검증1팀", "에너지검증2팀", "에너지검증3팀", "에너지검증 1팀", "에너지검증 2팀", "에너지검증 3팀"];
    } else if (dept === "우주항공국방기술실") {
      validNames = ["우주항공SW기술팀", "미래국방SW기술팀", "미래국방SW검증팀"];
    }
    if (validNames.length === 0) return all; // fallback for others
    return all.filter(function(t) {
      var n = t.name || t;
      return validNames.indexOf(n) !== -1;
    });
  }

  // 팀 목록은 서버(GET /api/health)가 준 것만 쓴다. 여기 손으로 적어두면 기준이
  // 없는 팀을 고를 수 있고, 그 사용자는 로그인해도 팀 기준이 안 붙은 채 공통
  // 기준만으로 검토한다 — "기준을 골랐는데 안 걸렸다"가 되고, 그건 이 프로젝트가
  // 계속 막으려던 조용한 0건이다.
  //
  // 아래 목록은 **file:// 목업 전용**이다. 거기엔 서버가 아예 없어서 검토도
  // 비교도 안 돌고 화면만 본다 — 빈 드롭다운을 보여줄 이유가 없다. 서버 위에서
  // 돌 때는 절대 쓰지 않는다: /api/health 가 아직 안 왔으면 빈 목록이 맞다.
  // 없는 기준을 지어내느니 아무것도 안 보여주는 편이 낫다.
  var MOCKUP_TEAMS = ["에너지검증 1팀", "에너지검증 2팀", "에너지검증 3팀", "AX품질팀",
                      "AI신뢰성1팀", "AI신뢰성2팀", "AI시험인증1팀", "AI시험인증2팀",
                      "우주항공SW기술팀", "미래국방SW기술팀", "미래국방SW검증팀"];

  function teamOptions() {
    if (window.location.protocol.indexOf("http") !== 0) return MOCKUP_TEAMS;
    return (state.server && state.server.checklists) || [];
  }

  // 팀 id → 화면에 쓰는 이름. state.user.team 에는 기준 파일명("ai-test-cert-1")이
  // 들어 있어 그대로 보여주면 사람이 읽을 것이 아니다. 목업 목록은 문자열이라
  // (id 와 이름이 같다) 그쪽도 같은 함수로 받는다.
  //
  // 못 찾으면 id 를 그대로 돌려준다 — /api/health 가 아직 안 왔을 뿐인데 빈칸을
  // 보여주면 "팀 미지정"으로 읽혀 실제 미지정과 구분이 안 된다.
  function teamLabel(id) {
    if (!id) return "";
    var opts = teamOptions();
    for (var i = 0; i < opts.length; i++) {
      var o = opts[i];
      if (typeof o === "string") { if (o === id) return o; }
      else if (o && o.id === id) return o.name;
    }
    return id;
  }

  var ICON_CARET = '<svg class="sel-caret" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';

  // options 는 문자열 배열이거나 {id, name} 배열이다. 팀은 보이는 이름과 값이
  // 다르다 — 화면엔 "에너지검증 2팀", 서버로 가는 값은 기준 파일명 "EV2" 다.
  // 문자열이면 둘이 같다(부서 등 기존 사용처).
  // opt: { value: 이미 고른 값, cls: 덧붙일 클래스 }. 회원가입 폼은 안 넘긴다
  // (아직 고른 게 없는 새 폼이라 placeholder 로 시작한다).
  function selectField(id, placeholder, options, opt) {
    opt = opt || {};
    var picked = opt.value || "", label = placeholder, hasPick = false;
    var items = options.map(function (o) {
      var val = o.id || o, name = o.name || o;
      var on = picked && val === picked;
      if (on) { label = name; hasPick = true; }
      return '<button type="button" class="sel-opt" role="option" aria-selected="' +
        (on ? "true" : "false") + '" ' +
        'data-act="selPick" data-arg="' + esc(id + "|" + val) + '">' +
        '<span>' + esc(name) + '</span>' +
        '<span class="sel-check">' + ICONS.check + '</span>' +
      '</button>';
    }).join("");
    return '<div class="sel' + (opt.cls ? " " + opt.cls : "") + '" id="' + esc(id) +
      '" data-value="' + esc(picked) + '">' +
      '<button type="button" class="sel-btn" data-act="selToggle" data-arg="' + esc(id) + '" ' +
        'aria-haspopup="listbox" aria-expanded="false">' +
        '<span class="sel-label"' + (hasPick ? "" : ' data-ph="1"') + '>' + esc(label) + '</span>' +
        ICON_CARET +
      '</button>' +
      '<div class="sel-menu" role="listbox">' + items + '</div>' +
    '</div>';
  }

  function signupView() {
    var inputStyle = "width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:var(--r-md);font-size:15px;color:var(--text);background:var(--bg);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);box-sizing:border-box;";
    var labelStyle = "display:block;font-size:14px;font-weight:600;color:var(--text-2);margin-bottom:8px;";
    
    var fOn = "this.style.borderColor='var(--accent)';this.style.background='var(--panel)'";
    var fOff = "this.style.borderColor='var(--line)';this.style.background='var(--bg)'";

    return '<div class="auth-canvas" style="width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;">' +
      authBlobs() +
      '<div style="position:relative;z-index:10;width:100%;max-width:520px;background:var(--panel);border-radius:var(--r-xl);box-shadow:' + AUTH_SHADOW + ';padding:48px;animation:fadeUp .4s ease-out forwards;">' +
        authBack("돌아가기") +
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:32px;">' +
          '<div style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;color:var(--accent-ink);">' + ICONS.logoMark + '</div>' +
          '<h2 style="font-size:22px;font-weight:700;color:var(--text);margin:0;letter-spacing:-0.5px;">Doc<span style="color:var(--accent-ink);">Suree</span> 계정 생성</h2>' +
        '</div>' +
        '<div style="margin-bottom:20px;">' +
          '<label style="' + labelStyle + '">이름</label>' +
          '<input id="signupName" type="text" placeholder="홍길동" style="' + inputStyle + '" onfocus="' + fOn + '" onblur="' + fOff + '">' +
        '</div>' +
        '<div style="display:flex;gap:16px;margin-bottom:20px;">' +
          '<div style="flex:1;min-width:0;">' +
            '<label style="' + labelStyle + '">소속 부서</label>' +
            selectField("signupDept", "부서 선택", DEPTS) +
          '</div>' +
          '<div style="flex:1;min-width:0;" id="signupTeamWrapper">' +
            '<label style="' + labelStyle + '">팀</label>' +
            selectField("signupTeam", "팀 선택", teamOptions()) +
          '</div>' +
        '</div>' +
        '<div style="margin-bottom:20px;">' +
          '<label style="' + labelStyle + '">이메일 주소</label>' +
          '<input id="signupEmail" type="email" placeholder="name@company.com" style="' + inputStyle + '" onfocus="' + fOn + '" onblur="' + fOff + '">' +
        '</div>' +
        '<div style="margin-bottom:40px;">' +
          '<label style="' + labelStyle + '">비밀번호</label>' +
          '<input id="signupPwd" type="password" placeholder="••••••••" style="' + inputStyle + '" onfocus="' + fOn + '" onblur="' + fOff + '" onkeyup="if(event.key===\'Enter\') document.getElementById(\'signupBtn\').click();">' +
        '</div>' +
        '<button id="signupBtn" class="btn btn-primary" data-act="doSignup" style="width:100%;padding:16px;border-radius:var(--r-md);font-size:15px;">회원가입 완료</button>' +
      '</div>' +
    '</div>';
  }


  function forgotView() {
    var inputStyle = "width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:var(--r-md);font-size:15px;color:var(--text);background:var(--bg);transition:border-color .2s var(--ease-out),background .2s var(--ease-out),color .2s var(--ease-out),box-shadow .2s var(--ease-out),opacity .2s var(--ease-out),transform .2s var(--ease-out);box-sizing:border-box;";
    var labelStyle = "display:block;font-size:14px;font-weight:600;color:var(--text-2);margin-bottom:8px;";
    
    return '<div class="auth-canvas" style="width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;">' +
      authBlobs() +
      '<div style="position:relative;z-index:10;width:100%;max-width:480px;background:var(--panel);border-radius:var(--r-xl);box-shadow:' + AUTH_SHADOW + ';padding:48px;animation:fadeUp .4s ease-out forwards;">' +
        authBack("로그인으로 돌아가기") +
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">' +
          '<div style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;color:var(--accent-ink);">' + ICONS.logoMark + '</div>' +
          '<h2 style="font-size:22px;font-weight:700;color:var(--text);margin:0;letter-spacing:-0.5px;">비밀번호 찾기</h2>' +
        '</div>' +
        '<p style="font-size:15px;color:var(--text-3);margin:0 0 32px 0;">가입하신 이메일 주소를 입력하시면 비밀번호 재설정 링크를 보내드립니다.</p>' +
        '<div style="margin-bottom:32px;">' +
          '<label style="' + labelStyle + '">이메일 주소</label>' +
          '<input id="forgotEmail" type="email" placeholder="name@company.com" style="' + inputStyle + '" onfocus="this.style.borderColor=\'var(--accent)\';this.style.background=\'var(--panel)\'" onblur="this.style.borderColor=\'var(--line)\';this.style.background=\'var(--bg)\'" onkeyup="if(event.key===\'Enter\') document.getElementById(\'forgotBtn\').click();">' +
        '</div>' +
        '<button id="forgotBtn" class="btn btn-primary" data-act="doForgot" style="width:100%;padding:16px;border-radius:var(--r-md);font-size:15px;">비밀번호 재설정 메일 받기</button>' +
      '</div>' +
    '</div>';
  }


  function view(v) {
    if (v.isLogin) return loginView();
    if (v.isSignup) return signupView();
    if (v.isForgot) return forgotView();
    return '<div class="dr-app">' + sidebar(v) +
      '<div style="flex:1;min-width:0;display:flex;flex-direction:column;background:var(--bg);">' + header(v) + body(v) + '</div>' +
    '</div>';
  }


    return {
      renderVals: renderVals, view: view, selectedSection: selectedSection,
      reviewHtml: reviewHtml, reviewJson: reviewJson,
      reviewMd: reviewMd, reviewCsv: reviewCsv, doAnnotate: doAnnotate,
      // 내보내기가 화면과 같은 판정을 싣게 한다.
      lineageView: lineageView,
      // app.js가 카드 하나만 갈아끼울 때 쓴다(전체 렌더 없이 = PDF 리로드 없이).
      findingCardClass: findingCardClass, findingCardInner: findingCardInner,
      // 번호 칩. 여러 곳을 문 지적은 번호마다 누를 수 있어야 한다.
      numberChip: numberChip,
      // 진행 화면 step 마다 레인·퍼센트·경과만 부분 갱신할 때 쓴다(버튼 hover 유지).
      progressFragments: progressFragments, progressHead: progressHead,
      laneMetrics: laneMetrics, laneInner: laneInner,
      reviewCriteriaInfo: reviewCriteriaInfo,
      // 검토 기준 3층. node 로 돌려 본문 전문·필터·여닫힘이 실제로 붙는지 본다.
      criteriaLayersSection: criteriaLayersSection,
      resultsRowCss: resultsRowCss,
      // 검색 결과 목록만 따로 그린다. app.js 의 input 리스너가 이것만 갈아끼워야
      // 입력 중 포커스와 한글 조합이 안 날아간다 — render()를 부르면 <input> 이
      // 통째로 새로 만들어진다.
      searchResultsHtml: searchResultsHtml,
      selectField: selectField, getTeamsForDept: getTeamsForDept,
      // 반영 확인 패널. node 로 돌려 판정이 제대로 붙는지 확인한다.
      lineageCardHtml: lineageCardHtml,
      // 반영 확인 패널. 뜻풀이가 살아 있는지 node 로 확인한다.
      lineageHtml: lineageHtml, lineagePanelHtml: lineagePanelHtml,
      lineageMarkIds: lineageMarkIds,
      lineageNaIds: lineageNaIds,
      // 탭 기본값이 두 곳에 있으면 화면과 로직이 다른 탭을 본다.
      reviewTabNow: reviewTabNow, lineageSummaryText: lineageSummaryText,
      lineageTabLabel: lineageTabLabel,
      // 산출물 세트 검토 리포트 CSV. app.js 의 액션이 내려받기를 건다.
      caseCsvText: caseCsvText,
      // 진행 화면 타임라인. api.js 가 단계마다 이 안쪽만 갈아끼운다 —
      // 여기서 안 내주면 부분 갱신이 옛 마크업을 다시 그려 화면이 갈린다.
      caseStageList: caseStageList,
      // 수정안이 '어느 기준에 맞추는 것인지'를 함께 보내려면 필요하다.
      criterionTextFor: criterionTextFor
    };
  };
})();

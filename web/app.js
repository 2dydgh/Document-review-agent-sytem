/*
 * DocReview frontend — ported from DocReviewDev.dc.html (Claude Design) to a
 * no-build vanilla-JS SPA. UI only; reads window.DOCREVIEW mock data.
 * Visual system: modern B2B SaaS (Linear/Vercel) — see index.html tokens.
 * Real backend (review_document) wiring is intentionally deferred.
 */
(function () {
  "use strict";

  // ---- props --------------------------------------------------------------
  // index.html 의 --accent 와 같은 값으로 유지할 것 (로고 배경 블루).
  var props = { accent: "#356998" };

  // ---- icons (Lucide SVGs) ------------------------------------------------
  var ICONS = window.DR.ICONS;

  // ---- state --------------------------------------------------------------
  var state = {
    mode: "login", screen: "upload", stageIndex: -1, serror: null, theme: "light", done: false,
    // 서버가 보고한 단계별 detail("6,180 chars"). 서버가 준 것만 들어온다 —
    // 비어 있으면 화면은 숫자를 그리지 않는다.
    stageDetail: {},
    // 진행 중인 /api/review 스트림의 AbortController. 다른 검토를 새로 시작하면
    // 이걸로 이전 스트림을 끊는다 — 안 그러면 두 스트림이 같은 window.DOCREVIEW를 다툰다.
    reviewAbort: null,
    // 검토의 실제 작업량과 진척. 서버가 Review 시작 때 lanes를 신고하고(청크 68·그룹 84)
    // 그 뒤 step으로 하나씩 채워 보낸다. 총량을 미리 알기에 퍼센트가 역주행하지 않는다.
    rev: { startedAt: 0, prepAt: 0, prep: {}, lanes: [], done: {}, note: "", active: "", criteriaOpen: false },
    cstep: "setup", cstageIndex: -1, cselected: null, cerror: null, cdone: false,
    // 케이스 검토(산출물 세트). 값을 **전부 state 에 둔다** — 회원가입 폼처럼 DOM 에
    // 들고 있으면 render() 한 번에 고른 것이 날아간다(아래 selToggle 주석 참고).
    // files 는 File 객체 배열이고 서버로 올릴 때까지 브라우저가 들고 있는다.
    kase: {
      step: "upload",      // upload | recognize | progress | results
      tab: "summary",      // 리포트 탭: summary | outputs | compare | other
      selOutput: "",       // 산출물 탭에서 고른 것
      view: null,          // {key, file, findings} — 뷰어에 띄운 산출물
      checked: {},         // {직접확인 id: true} — 사람이 눌렀나
      manualInputs: {},    // {직접확인 id: 외부 원천값} — 저장된 문서값과 추가 대조
      confirmedAt: "",     // 서버에 남긴 시각. 비면 아직 확정 전이다
      confirming: false,
      // 로그인한 사용자의 소속 팀이 채운다(doLogin). 한 팀을 박아두면 다른 팀이
      // 로그인해도 남의 기준으로 산출물을 재고, 그 실패는 조용한 0건이다.
      team: "",
      files: [],           // [File]
      recog: null,         // /api/classify-case 응답
      assign: {},          // {파일명: 산출물키} — 미분류를 사람이 지정한 것
      exclude: {},         // {파일명: true} — 사람이 뺀 것
      stage: {},           // 진행 detail
      startedAt: 0,
      payload: null,
      criteria: null,      // 팀 검토 기준 (GET /api/teams/{team}/criteria)
      criteriaLoading: false,
      criteriaError: "",   // 못 불러온 사유. "아직 안 부름"과 섞지 않는다
      criteriaFocus: "",   // 기준 화면에서 짚어 보여줄 항목 id
      matrixFocus: "",     // 필드 대조표에서 펼쳐 볼 항목 id
      error: null,
      abort: null
    },
    // 빈 값 = 서버 기본 기준. 예전 기본값 "prd"는 서버에 없는 목업 id 였다.
    checklist: "",
    // 검토자가 기준을 직접 골랐나. 골랐으면 자동 감지가 그 선택을 덮지 않는다.
    checklistPicked: false,
    // 단일 검토를 "이 체크리스트 기준으로 평가"할지. 위 checklist(자동 검토
    // 기준·id_pattern 등)와도, 아래 runChecklistId(독립 화면에서 사람이 직접
    // 채우는 화면)와도 다른 셋째 선택이다 — 등록된 체크리스트를 골라 그 항목별로
    // 자동 findings 를 묶어 본다. 빈 값 = 안 씀(기존 평면 지적 목록 그대로).
    reviewChecklistId: "",
    // 단일 검토에서 "체크리스트" 링크로 탭에 들어왔는지. true 면 탭이 "고르기"
    // 모드가 되어 행마다 "선택" + 상단 "검토로 돌아가기"를 띄운다. 옆
    // 네비게이션으로 그냥 들어오면(setMode) false 로 되돌린다 — 관리 모드다.
    checklistPickReturn: false,
    // /api/detect 결과. 업로드 문서에서 체크리스트별로 요건 ID가 몇 개
    // 걸리는지. null이면 아직 재지 않았다(감지는 편의 기능이라 없어도 검토는 된다).
    detect: null,
    // 체크리스트 라이브러리. preview 는 등록 전 확인용이다 —
    // 열 추측이 틀렸는데 조용히 등록되면 엉뚱한 항목으로 검토하게 된다.
    clib: { list: [], preview: null, detail: null, file: null, busy: false, error: null },
    // 검토 기준 3층(공통·팀별·업로드)을 층째로. 업로드 목록(clib)과 다르다 —
    // 여기는 "무엇으로 재는지"를 항목 본문까지 보여주는 자리다.
    clayers: { list: null, busy: false, error: null, open: {}, openItem: {}, how: "" },
    // 지금 채우고 있는 체크리스트. 자동 검토(rev)와 완전히 독립된 화면(mode
    // "checklistrun")에서 채운다 — LLM 을 기다리지 않는다. from: 뒤로가기
    // 대상("checklists"|"history"). documentName: 이 화면에서 적은 검토 대상
    // 문서명(자동 검토의 files.single 과 무관 — 이 화면은 그걸 거치지 않고도 온다).
    crun: { checklist: null, results: {}, saving: false, error: null, from: "checklists", documentName: "" },
    // 지금 채우는 중인 체크리스트 id(독립 화면 진입원과 무관하게 하나만 있다).
    runChecklistId: "",
    // unreviewed 는 심각도가 아니라 "검사를 못 했다" 보고의 칩이다 — info 와
    // 따로 켜고 끈다(info 를 꺼도 미검토 보고가 같이 사라지면 안 된다).
    sevFilter: { major: true, minor: true, info: true, unreviewed: true },
    checkerFilter: "all", selected: null, sort: "severity", llm: "on",
    files: { single: null, compareA: null, compareB: null },
    // 원본 PDF 표시(POST /api/annotate)의 진행·결과 문구.
    annot: { busy: false, msg: "" },
    // 인용 하나의 수정안(POST /api/suggest). "지적id|인용순번" → {busy, ok,
    // original, revised, reason}. 지적당 하나가 아니라 **인용당 하나**다 — 지적
    // 하나가 문장 열여덟 개를 근거로 드는 일이 있어, 첫 인용만 고쳐 주면 나머지는
    // 검토자가 손으로 옮겨 적어야 했다. 펼친 카드를 옮기면 통째로 비운다.
    fixes: {},
    // 원본/변환 PDF 뷰어. baseBlob=base PDF(원본 또는 변환본), origUrl=그 blob URL,
    // annot.viewUrl=표시본. converting=변환 중, convertError=변환 실패 문구.
    viewer: { mode: "orig", baseBlob: null, origUrl: null, converting: false, convertError: null },
    // 지적 좌표(POST /api/locate). {pages, items:[{id,no,page,sev,marks}], unlocated}.
    // 형광펜 오버레이와 카드→문서 점프가 읽는다.
    marks: null,
    profileMenuOpen: false, searchOpen: false, notiOpen: false,
    // 이 세션에서 우리가 직접 본 사건(api.js 의 notify). 서버 알림함이 아니라
    // 새로고침하면 비워지는 목록이고, 화면이 그렇다고 말한다.
    notis: [],
    // 검색어. <input> 이 아니라 여기에 둔다 — DOM 에 들고 있으면 render() 한
    // 번에 날아간다(회원가입 폼이 그렇게 아팠다).
    searchQ: "",
    // 검토 결과 패널 헤더의 내보내기(⇩) 드롭다운.
    exportMenuOpen: false,
    // 서버가 실제로 적용 중인 검토 기준(GET /api/health). null이면 아직 못 읽었다.
    server: null,
    // 저장된 검토 이력(GET /api/history). null이면 아직 못 읽었다(빈 배열과 다르다).
    history: null,
    // 이력을 **못 읽은** 상태. null(아직 안 읽음)·[](없음)과 다른 세 번째다.
    historyError: false, hbusy: false,
    // 삭제 확인 모달 대상. null이면 닫힘, {id, title}이면 그 기록을 지울지 묻는 중.
    confirmDelete: null,
    // 홈의 "무엇으로 재나" 가 쓰는 진짜 기준. {team, layers}
    homeCriteria: null,
    // 이 세션에서 단일 검토를 끝낸 적이 있나. 없으면 `지적사항` 으로 못 간다.
    reviewed: false,
    // 지적사항 화면 오른쪽 "검토 결과" 패널 접힘. 재현본은 그만큼 넓어지지만
    // PDF 카드는 안 커진다 — aspect-ratio로 높이에 맞춰 폭을 정해서, 자리가 나도
    // 좌우 여백만 늘 뿐이다. PDF를 크게 보려면 viewerFull(전체화면) 쪽을 쓴다.
    issuesCollapsed: false,
    // 검토 결과 패널의 탭. 재검토(이력 있음)일 때만 탭이 생기고, 그때 기본은
    // 반영 확인이다 — 검토자가 먼저 보고 싶은 것이 "지난번 지적이 고쳐졌나" 다.
    // null 이면 아직 안 골랐다는 뜻이라 화면이 기본값을 정한다.
    reviewTab: null,
    // 결과 화면 전체화면. 문서와 "검토 결과"를 둘 다 남긴 채 사이드바·헤더·백링크
    // 바만 덮어 세로를 번다(views.js resultsRowCss).
    viewerFull: false,
    // 비교 검토 화면 오른쪽 "불일치 내역 분석" 패널 접힘(단일과 독립).
    cIssuesCollapsed: false
  };


  // ---- helpers ------------------------------------------------------------
  var _H = window.DR.helpers;
  var esc = _H.esc, rgba = _H.rgba, downloadBlob = _H.downloadBlob, download = _H.download, fmtSize = _H.fmtSize;
  // Store a picked/dropped file into a slot; optionally jump into that mode.

  // ── 케이스 파일 모으기 ──────────────────────────────────────────────────
  // 폴더를 통째로 받는다. 산출물이 00.~03. 하위 폴더로 나뉘어 있어서, 파일만
  // 고르게 하면 사용자가 네 번 반복해야 한다.

  function openCasePicker(folder) {
    var inp = document.createElement("input");
    inp.type = "file";
    inp.multiple = true;
    if (folder) { inp.webkitdirectory = true; inp.directory = true; }
    inp.onchange = function () {
      actions.addCaseFiles(Array.prototype.slice.call(inp.files || []));
    };
    inp.click();
  }

  // 드롭된 항목을 재귀로 훑어 파일만 모은다. webkitGetAsEntry 를 안 쓰면
  // dataTransfer.files 에 폴더가 이름만 담겨 와 내용이 사라진다.
  function collectDropped(items, done) {
    var entries = [], pending = 1, out = [];
    for (var i = 0; i < items.length; i++) {
      var e = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
      if (e) entries.push(e);
    }
    if (!entries.length) { done(out); return; }
    function finish() { if (--pending === 0) done(out); }
    function walk(entry) {
      if (entry.isFile) {
        pending++;
        entry.file(function (f) { out.push(f); finish(); }, finish);
        return;
      }
      if (!entry.isDirectory) return;
      pending++;
      var reader = entry.createReader();
      (function readMore() {
        reader.readEntries(function (batch) {
          if (!batch.length) { finish(); return; }
          batch.forEach(walk);
          readMore();               // readEntries 는 한 번에 다 주지 않는다
        }, finish);
      })();
    }
    entries.forEach(walk);
    finish();
  }

  function handleFile(slot, nav, file) {
    if (!file || !state.files.hasOwnProperty(slot)) return;
    // file 원본을 들고 있어야 /api/compare로 실제 업로드할 수 있다.
    state.files[slot] = { name: file.name, size: file.size, file: file };
    if (nav === "single") {
      state.mode = "single"; state.screen = "upload";
      // 파일 드롭으로 들어오면 setMode를 안 거쳐 체크리스트 목록이 안 읽힌다.
      // 그러면 "체크리스트 선택"이 첫 화면에서 비어 있다 — 여기서 채운다.
      if (!state.clib.list.length) actions.loadChecklists();
    }
    else if (nav === "compare") { state.mode = "compare"; state.cstep = "setup"; }
    render();
    detectChecklist(file);
  }

  // 업로드한 문서를 체크리스트마다 재서 요건 ID가 몇 개 걸리는지 알아온다.
  //
  // 잘못된 체크리스트의 실패는 에러가 아니라 **조용한 0건**이다 — 검토를 통과한
  // 것처럼 보인다. 같은 실에서 온 문서인데도 ID 체계가 달라(SHN34: FR-GC_01,
  // SKN56: FR1-0305) 어떤 기본값도 옳을 수 없다. 그래서 고르기 전에 재본다.
  //
  // 서버가 없으면(정적 미리보기) 조용히 넘어간다 — 감지는 편의 기능이지
  // 검토의 전제가 아니다.
  function detectChecklist(file) {
    if (!servedOverHttp()) return;
    state.detect = { busy: true, best: null, list: [], error: null };
    render();
    var fd = new FormData();
    fd.append("file", file, file.name);
    postForm("api/detect", fd).then(function (body) {
      state.detect = { busy: false, best: body.best, list: body.detected || [], error: null };
      // 검토자가 직접 고른 기준은 말없이 갈아치우지 않는다. 아무것도 안 골랐을
      // 때만 감지 결과로 맞춰준다 — 그게 조용한 0건을 막는 가장 확실한 지점이다.
      if (body.best && !state.checklistPicked && state.checklist !== body.best) {
        state.checklist = body.best;
        if (servedOverHttp()) loadServerConfig(); else render();
        return;
      }
      render();
    }).catch(function (err) {
      // 감지 실패가 검토를 막지는 않는다. 다만 조용히 넘기지도 않는다.
      state.detect = { busy: false, best: null, list: [], error: errMessage(err) };
      render();
    });
  }

  // ---- backend ------------------------------------------------------------
  var _be = window.DR.backend({ state: state, render: render, repaintProgress: repaintProgress,
                                repaintCaseStages: repaintCaseStages });
  var servedOverHttp = _be.servedOverHttp, loadServerConfig = _be.loadServerConfig,
      loadHistory = _be.loadHistory, ago = _be.ago, postForm = _be.postForm,
      animate = _be.animate, holdDone = _be.holdDone, errMessage = _be.errMessage,
      errorBanner = _be.errorBanner, tickElapsed = _be.tickElapsed, fmtElapsed = _be.fmtElapsed,
      streamReview = _be.streamReview, clearTimers = _be.clearTimers,
      streamCase = _be.streamCase, tickCaseElapsed = _be.tickCaseElapsed,
      fetchCriteria = _be.fetchCriteria,
      fetchCriteriaLayers = _be.fetchCriteriaLayers,
      notify = _be.notify;

  // 산출물 세트 검토가 쓸 팀 기준. 로그인이 채우지만, 기록에서 되살린 화면이나
  // 팀 없이 만들어진 옛 계정은 비어 있을 수 있다. 그대로 서버에 보내면 404 가
  // 나므로 여기서 막고 무엇을 해야 하는지 말한다 — 실패 이유가 "그런 팀 기준이
  // 없습니다"로 뜨면 검토자는 자기가 뭘 잘못했는지 알 수 없다.
  function caseTeam() {
    return state.kase.team || (state.user && state.user.team) || "";
  }
  var _NO_TEAM = "소속 팀을 확인할 수 없습니다. 다시 로그인해 주세요.";

  function invalidateManualResult(k, id) {
    var p = k.payload;
    k.confirmedAt = "";
    k.error = "";
    if (!p) return;
    p.manualResults = (p.manualResults || []).filter(function (r) { return r.id !== id; });
    p.findings = (p.findings || []).filter(function (f) {
      return !(f.kind === "manual_input" && f.ruleId === id);
    });
    p.stats = p.stats || {};
    p.stats.findings = p.findings.filter(function (f) { return !f.unreviewed; }).length;
    p.stats.unreviewed = p.findings.filter(function (f) { return !!f.unreviewed; }).length;
  }

  function focusCaseNode(selector) {
    setTimeout(function () {
      var el = document.querySelector(selector);
      // index.html 의 prefers-reduced-motion 규칙(scroll-behavior:auto)은 여기
      // 안 먹는다: JS 가 behavior 를 명시하면 그쪽이 CSS 를 이긴다. 직접 묻는다.
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ block: "center", behavior: reduceMotion() ? "auto" : "smooth" });
      }
    }, 0);
  }

  // ---- actions ------------------------------------------------------------
  var actions = {
    doLogin: function() {
      var em = document.getElementById("loginEmail").value;
      var pw = document.getElementById("loginPwd").value;
      var remember = document.getElementById("rememberId").checked;
      var users = JSON.parse(localStorage.getItem("dr_users") || '{}');
      
      var valid = false;
      var uName = "홍길동";
      var uTeam = "";
      if (users[em]) {
        if (typeof users[em] === 'string' && users[em] === pw) {
          valid = true;
        } else if (users[em].pw === pw) {
          valid = true;
          uName = users[em].name || "홍길동";
          uTeam = users[em].team || "";
        }
      }
      
      if (valid) {
        if (remember) {
          localStorage.setItem("dr_last_email", em);
        } else {
          localStorage.removeItem("dr_last_email");
        }
        var btn = document.getElementById("loginBtn");
        btn.innerHTML = '<span style="display:inline-block;animation:spin 1s linear infinite;margin-right:8px;">' + ICONS.refresh + '</span>로그인 처리 중...';
        btn.style.pointerEvents = "none";
        btn.style.opacity = "0.8";
        setTimeout(function() {
          state.user = { name: uName, email: em, team: uTeam };
          // 소속 팀 기준을 기본으로 건다. 안 걸면 검토자가 매번 골라야 하고,
          // 안 고르면 공통 기준만으로 돈다 — 팀 기준 수십 건이 조용히 빠진다.
          // 고른 뒤에는 화면에서 바꿀 수 있다(기준 목록은 그대로 보인다).
          // 팀이 없으면 **비운다**. 예전에는 안 비워서, 팀 없는 계정이 화면에는
          // "미지정"으로 보이면서 실제 요청은 앞사람 팀으로 나갔다.
          state.checklist = uTeam;
          state.kase.team = uTeam;
          if (uTeam) {
            // 서버가 "지금 무슨 잣대로 재는지"를 다시 답해야 한다 — 안 그러면
            // 화면은 기준 없는 상태의 값을 계속 보여준다.
            if (servedOverHttp()) loadServerConfig();
          }
          state.mode = "home";
          state.profileMenuOpen = false;
          loadHomeCriteria();     // 방금 붙은 팀 기준을 홈이 말해야 한다
          render();
        }, 800);
      } else {
        alert("로그인 실패: 이메일 또는 비밀번호가 올바르지 않습니다.\\n(계정이 없으시다면 회원가입을 먼저 진행해주세요.)");
      }
    },
    toggleProfile: function() {
      state.profileMenuOpen = !state.profileMenuOpen;
      state.searchOpen = false;
      render();
    },
    openProfileSettings: function() {
      state.profileSettingsOpen = true;
      state.profileMenuOpen = false;
      render();
      var sDept = state.user ? state.user.dept : "";
      var pst = state.user ? state.user.team : "";
      var opts = state.server && state.server.checklists ? state.server.checklists : [];
      for (var i = 0; i < opts.length; i++) {
        if (opts[i].name === pst || opts[i] === pst) {
          pst = opts[i].id || opts[i];
          break;
        }
      }
      actions.selPick("psDept|" + sDept);
      actions.selPick("psTeam|" + pst);
    },
    closeProfileSettings: function() {
      state.profileSettingsOpen = false;
      render();
    },
    saveProfileSettings: function() {
      if (!state.user) return;
      var nm = document.getElementById("psName").value || state.user.name;
      var selDept = document.getElementById("psDept");
      var dept = selDept && selDept.dataset.value ? selDept.dataset.value : state.user.dept;
      var selTeam = document.getElementById("psTeam");
      var team = selTeam && selTeam.dataset.value ? selTeam.dataset.value : state.user.team;
      
      state.user.name = nm;
      state.user.dept = dept;
      state.user.team = team;
      
      var users = JSON.parse(localStorage.getItem("dr_users") || '{}');
      if (users[state.user.email]) {
        users[state.user.email].name = nm;
        users[state.user.email].dept = dept;
        users[state.user.email].team = team;
        localStorage.setItem("dr_users", JSON.stringify(users));
      }
      
      if (state.checklist !== team) {
        state.checklist = team;
        state.kase.team = team;
      }
      
      state.profileSettingsOpen = false;
      render();
    },
    // 알림을 펼치면 읽은 것으로 친다 — 목록을 봤는데도 빨간 점이 남아 있으면
    // 무엇을 더 해야 하는지 알 수 없다.
    toggleNoti: function () {
      state.notiOpen = !state.notiOpen;
      if (state.notiOpen) {
        state.notis.forEach(function (n) { n.unread = false; });
      }
      state.profileMenuOpen = false; state.searchOpen = false;
      render();
    },

    // 검색은 검토 기록(제목)과 등록된 체크리스트(이름)를 뒤진다. 둘 다 이미 받아
    // 둔 목록이라 새 엔드포인트가 없다 — 체크리스트만 아직 안 읽었으면 여기서
    // 채운다(검토 기준 화면에 한 번도 안 들어간 사람은 목록이 비어 있다).
    toggleSearch: function() {
      state.searchOpen = !state.searchOpen;
      // 열 때마다 빈 칸에서 시작한다. 지난 검색어가 남아 있으면 결과부터 뜨는데,
      // 그게 방금 친 것인지 저번 것인지 구별이 안 된다.
      if (state.searchOpen) {
        state.searchQ = "";
        if (!state.clib.list.length) actions.loadChecklists();
      }
      state.profileMenuOpen = false;
      render();
    },
    goSignup: function() {
      state.mode = "signup";
      render();
    },
    // 커스텀 셀렉트(회원가입 부서·팀). 회원가입 폼은 입력값을 state 가 아니라
    // DOM 에 들고 있어서, 여기서 render() 를 부르면 이미 친 이름·이메일이 날아간다 —
    // 그래서 이 두 액션만 다시 그리지 않고 DOM 을 직접 만진다.
    selToggle: function (id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var willOpen = !sel.classList.contains("open");
      closeSelects();
      if (willOpen) {
        sel.classList.add("open");
        sel.querySelector(".sel-btn").setAttribute("aria-expanded", "true");
      }
    },
    selPick: function (arg) {
      var cut = arg.indexOf("|");
      var selId = arg.slice(0, cut);
      var sel = document.getElementById(selId);
      var val = arg.slice(cut + 1);
      if (!sel) return;
      sel.setAttribute("data-value", val);
      var label = sel.querySelector(".sel-label");
      label.removeAttribute("data-ph");   // placeholder 회색을 벗는다
      var opts = sel.querySelectorAll(".sel-opt");
      for (var i = 0; i < opts.length; i++) {
        var on = opts[i].getAttribute("data-arg") === arg;
        opts[i].setAttribute("aria-selected", on ? "true" : "false");
        // 값과 보이는 이름은 다를 수 있다 — 팀은 값이 "EV2", 이름이 "에너지검증 2팀"
        // 이다. val 을 그대로 쓰면 화면에 파일명이 뜬다.
        if (on) label.textContent = opts[i].querySelector("span").textContent;
      }
      closeSelects();

      // 반영 확인 판정. 회원가입 폼과 달리 값이 state 에 있어야 한다 — DOM 에만
      // 두면 새로고침 한 번에 사라지고, 서버에도 안 간다.
      if (selId.indexOf("lnv-") === 0) {
        actions.setLineageVerdict(selId.slice(4), val);
        return;                       // setLineageVerdict 가 render() 한다
      }

      if (selId === "signupDept" || selId === "psDept") {
        var teamSelId = selId === "signupDept" ? "signupTeam" : "psTeam";
        var teamWrapperId = teamSelId + "Wrapper";
        var wrapper = document.getElementById(teamWrapperId);
        if (wrapper && _views.getTeamsForDept && _views.selectField) {
          var filteredTeams = _views.getTeamsForDept(val);
          var html = "";
          if (selId === "signupDept") {
             html += '<label style="display:block;margin-bottom:8px;font-size:14px;font-weight:600;color:var(--text);">팀</label>';
          } else {
             html += '<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">팀 (검사 기준)</div>';
          }
          html += _views.selectField(teamSelId, "팀 선택", filteredTeams);
          wrapper.innerHTML = html;
        }
      }
    },
    doSignup: function() {
      var em = document.getElementById("signupEmail").value;
      var pw = document.getElementById("signupPwd").value;
      var nm = document.getElementById("signupName").value || "홍길동";
      var dept = selValue("signupDept"), team = selValue("signupTeam");
      if (!em || !pw) {
        alert("이메일과 비밀번호를 모두 입력해주세요.");
        return;
      }
      var users = JSON.parse(localStorage.getItem("dr_users") || '{}');
      if (users[em]) {
        alert("이미 존재하는 계정입니다.");
        return;
      }
      users[em] = { pw: pw, name: nm, dept: dept, team: team };
      localStorage.setItem("dr_users", JSON.stringify(users));
      
      var btn = document.getElementById("signupBtn");
      btn.innerHTML = '<span style="display:inline-block;animation:spin 1s linear infinite;margin-right:8px;">' + ICONS.refresh + '</span>가입 처리 중...';
      btn.style.pointerEvents = "none";
      btn.style.opacity = "0.8";
      setTimeout(function() {
        alert("회원가입이 완료되었습니다! 로그인해주세요.");
        state.mode = "login";
        render();
      }, 800);
    },
    doForgot: function() {
      var em = document.getElementById("forgotEmail").value;
      if (!em) { alert("이메일을 입력해주세요."); return; }
      var users = JSON.parse(localStorage.getItem("dr_users") || '{}');
      if (!users[em]) {
        alert("가입되지 않은 이메일입니다.");
        return;
      }
      var btn = document.getElementById("forgotBtn");
      btn.innerHTML = '<span style="display:inline-block;animation:spin 1s linear infinite;margin-right:8px;">' + ICONS.refresh + '</span>이메일 전송 중...';
      btn.style.pointerEvents = "none";
      btn.style.opacity = "0.8";
      setTimeout(function() {
        alert("입력하신 이메일로 임시 비밀번호가 전송되었습니다.\\n(시뮬레이션 완료)");
        state.mode = "login";
        render();
      }, 800);
    },
    // 새로고침으로 나간다. state 를 손으로 비우면 반드시 하나를 빠뜨리고, 그
    // 하나가 다음 사람에게 남는다 — 실제로 kase.team 이 남아 팀 없는 계정이
    // 앞사람 팀 기준으로 검토됐다. 아이디 기억은 localStorage 라 살아남는다.
    doLogout: function() {
      location.reload();
    },
    // 새 문서를 검토하러 업로드 화면으로. 검토가 끝나면 screen이 "results"에
    // 머무는데, setMode는 mode만 바꾸므로 홈을 거쳐 돌아와도 묵은 결과가 다시
    // 떴다 — 페이지를 새로고침하지 않는 한 다음 문서를 볼 수 없었다.
    //
    // 앞 문서의 흔적을 여기서 다 지운다. 하나라도 남으면 새 문서 위에 이전
    // 지적·PDF가 얹혀 보인다 — 검토 도구에서 이건 그냥 오답이다.
    newReview: function (which) {
      if (state.viewer.origUrl) URL.revokeObjectURL(state.viewer.origUrl);
      if (state.annot.viewUrl) URL.revokeObjectURL(state.annot.viewUrl);
      state.viewer = { mode: "orig", baseBlob: null, origUrl: null, converting: false, convertError: null };
      state.annot = { busy: false, msg: "" };
      state.fixes = {};
      state.files.single = null;
      state.selected = null;
      state.serror = null;
      state.done = false;
      state.stageDetail = {};
      state.stageIndex = -1;
      // 고른 체크리스트와 그 판정·이유도 앞 문서의 흔적이다. 독립 화면
      // (checklistrun)은 startChecklistRun/openHistory 가 매번 새로 세우지만,
      // 여기서 안 지우면 그새 자동 검토 결과 쪽으로 묵은 crun이 남는다.
      state.crun = { checklist: null, results: {}, saving: false, error: null, from: "checklists", documentName: "" };
      state.runChecklistId = "";
      // 뷰어 캐시도 비운다. 안 그러면 다음 문서가 와도 "같은 blob"으로 보고 넘겨
      // 이전 PDF가 그대로 남는다.
      viewerFor = null;
      clearTimers();
      // 비교 결과에서 눌렀으면 비교 설정으로 돌아가야 한다 — 단일로 튀면
      // 방금 하던 일과 상관없는 화면이 뜬다.
      if (which === "compare") {
        state.files.compareA = null; state.files.compareB = null;
        state.cselected = null; state.cerror = null; state.cdone = false;
        state.cstageIndex = -1;
        state.mode = "compare"; state.cstep = "setup";
      } else {
        state.mode = "single"; state.screen = "upload";
        if (!state.clib.list.length) actions.loadChecklists();
      }
      render();
    },

    // ── 케이스 검토 ────────────────────────────────────────────────────────
    // 고른 값은 전부 state.kase 에 있다. DOM 에 들고 있으면 render() 한 번에
    // 날아간다 — 회원가입 폼이 그렇게 아팠고(selToggle 주석), 여기는 파일 10개에
    // 드롭다운이 붙어 훨씬 크게 아프다.
    pickCaseFiles: function () { openCasePicker(false); },
    pickCaseFolder: function () { openCasePicker(true); },
    clearCaseFiles: function () {
      state.kase.files = []; 
      state.kase.recog = null; 
      state.kase.error = null;
      state.kase.result = null;
      state.kase.payload = null;
      state.kase.checked = {};
      state.kase.manualInputs = {};
      state.kase.confirmedAt = "";
      state.kase.stage = 0;
      state.kase.step = "upload";
      render();
    },
    addCaseFiles: function (files) {
      var seen = {};
      state.kase.files.forEach(function (f) { seen[f.name] = true; });
      files.forEach(function (f) { if (!seen[f.name]) { state.kase.files.push(f); seen[f.name] = true; } });
      state.kase.recog = null; state.kase.error = null;
      render();
    },
    classifyCase: function () {
      var k = state.kase;
      if (!k.files.length) return;
      if (!caseTeam()) { k.error = _NO_TEAM; render(); return; }
      var fd = new FormData();
      fd.append("names", JSON.stringify(k.files.map(function (f) { return f.name; })));
      fd.append("team", caseTeam());
      k.error = null;
      fetch("api/classify-case", { method: "POST", body: fd })
        .then(function (res) {
          if (!res.ok) return res.json().catch(function () { return {}; })
            .then(function (b) { throw new Error(b.detail || ("서버 오류 (HTTP " + res.status + ")")); });
          return res.json();
        })
        .then(function (r) { k.recog = r; k.assign = {}; k.exclude = {}; k.step = "recognize"; render(); })
        .catch(function (err) { k.error = errMessage(err); render(); });
    },
    assignOutput: function (name, value) { state.kase.assign[name] = value || ""; render(); },
    toggleExclude: function (name) {
      state.kase.exclude[name] = !state.kase.exclude[name];
      render();
    },
    backToCaseUpload: function () { state.kase.step = "upload"; render(); },

    // 지적 → 그 문서를 뷰어로. 서버는 검사 뒤 임시본을 지우지만 **브라우저가
    // 원본을 들고 있다**(state.kase.files) — 기존 뷰어도 그때그때 다시 올리는
    // 구조라 같은 경로를 그대로 쓴다.
    openCaseDoc: function (arg) {
      var parts = String(arg || "").split("|");
      var key = parts[0], only = parts[1] || "";
      var p = state.kase.payload;
      if (!p) return;
      var out = (p.outputs || []).filter(function (o) { return o.key === key; })[0];
      if (!out) return;
      var file = state.kase.files.filter(function (f) { return f.name === out.file; })[0];
      if (!file) { state.kase.error = "원본 파일을 찾지 못했습니다: " + out.file; render(); return; }

      // 이 문서에 해당하는 근거만 남긴다. 상대 문서의 인용을 함께 넘기면 여기서는
      // 못 찾아 unlocated 만 쌓인다.
      var findings = (p.findings || []).filter(function (f) {
        // only 는 처음 이동할 지적일 뿐이다. 여기서 나머지를 버리면 특정 카드의
        // "문서에서 보기"로 열었을 때 같은 문서의 다른 하이라이트가 사라진다.
        return !f.unreviewed && (f.document || "").indexOf(key) >= 0;
      }).map(function (f) {
        // 화면(views.js caseDocView)이 버튼을 그릴 때와 **같은 규칙**으로 가른다.
        // 갈리면 버튼은 뜨는데 여기서 그 문서의 근거를 못 찾아 아무 일도 안 난다.
        var sides = window.DR.helpers.docSides(f.document);
        var i = sides.indexOf(key);
        var ev = (f.evidence || []);
        return { id: f.id, sev: f.sev, message: f.message,
                 evidence: (i >= 0 && ev[i]) ? [ev[i]] : ev };
      });

      state.kase.view = { key: key, file: file, findings: findings, focus: only };
      state.viewer = { mode: "orig", baseBlob: null, origUrl: null,
                       converting: false, convertError: null };
      state.marks = null;
      render();
    },
    closeCaseDoc: function () {
      state.kase.view = null;
      state.viewer = { mode: "orig", baseBlob: null, origUrl: null,
                       converting: false, convertError: null };
      state.marks = null;
      render();
    },
    // 기준은 리포트와 별개로 받아 온다. 한 번 받으면 들고 있는다 —
    // 탭을 오갈 때마다 다시 부르면 화면이 깜빡인다.
    loadCriteriaLayers: function () {
      var s = state.clayers;
      if (s.list || s.busy) return;
      s.busy = true; s.error = "";
      fetchCriteriaLayers(state.checklist || "")
        .then(function (b) { s.list = b.layers || []; })
        .catch(function (err) { s.error = errMessage(err); })
        .then(function () { s.busy = false; render(); });
      render();
    },
    // 항목 한 줄 펴기. 접힌 줄은 제목 한 줄이고, 기준 본문은 펴야 나온다.
    // 본문이 없는 줄은 아예 안 눌리므로 여기 오지 않는다(views.js).
    toggleCriteriaItem: function (key) {
      var o = state.clayers.openItem;
      o[key] = !o[key];
      render();
    },
    toggleCriteriaLayer: function (id) {
      var open = state.clayers.open;
      open[id] = !open[id];
      render();
    },
    // 검사 방식 필터("" = 전체). 같은 칩을 다시 누르면 풀린다.
    setCriteriaHow: function (how) {
      var s = state.clayers;
      s.how = (s.how === how ? "" : (how || ""));
      render();
    },
    openReviewCriteria: function () {
      state.rev.criteriaOpen = true;
      if (!state.clayers.list && !state.clayers.busy) actions.loadCriteriaLayers();
      else render();
    },
    closeReviewCriteria: function () {
      state.rev.criteriaOpen = false;
      render();
    },
    loadCriteria: function () {
      var k = state.kase;
      // 이미 있으면(또는 부르는 중이면) 다시 안 부른다 — 그래도 **그리기는 한다.**
      // 탭 전환(setCaseTab)과 대조표의 항목 이름(openCriteria)이 여기로 오는데,
      // render 없이 조기 반환하면 두 번째 클릭부터 탭이 죽은 것처럼 보였다.
      if (k.criteria || k.criteriaLoading) { render(); return; }
      if (!caseTeam()) { k.criteriaError = _NO_TEAM; render(); return; }
      k.criteriaLoading = true;
      k.criteriaError = "";
      fetchCriteria(caseTeam())
        .then(function (c) { k.criteria = c; })
        .catch(function (err) { k.criteriaError = errMessage(err); })
        .then(function () {
          k.criteriaLoading = false;
          render();
          if (k.criteriaFocus) focusCaseNode('[data-criteria-focused="true"]');
        });
      render();
    },
    // 리포트의 "미검토"에서 그 기준으로 건너뛴다. "못 봤다"만 알려주고 왜인지
    // 못 짚으면 검토자가 할 수 있는 게 없다.
    openCriteria: function (id) {
      state.kase.tab = "criteria";
      // 쌍 기준의 finding id 는 `1-7/대표자` 모양이지만 기준 id 는 `1-7`이다.
      state.kase.criteriaFocus = String(id || "").split("/")[0];
      actions.loadCriteria();
      focusCaseNode('[data-criteria-focused="true"]');
    },
    openMatrixDetail: function (id) {
      var k = state.kase;
      var same = k.tab === "matrix" && k.matrixFocus === id;
      k.tab = "matrix";
      k.matrixFocus = same ? "" : (id || "");
      render();
      if (k.matrixFocus) focusCaseNode('[data-matrix-row="' + k.matrixFocus + '"]');
    },
    toggleManual: function (id) {
      var k = state.kase;
      if (k.confirming) return;
      k.checked[id] = !k.checked[id];
      invalidateManualResult(k, id);
      render();
    },
    setManualInput: function (id, value) {
      var k = state.kase;
      if (k.confirming) return;
      k.manualInputs = k.manualInputs || {};
      k.manualInputs[id] = value;
      invalidateManualResult(k, id);
      // 타이핑 중에는 입력을 다시 만들지 않는다. 대신 현재 행의 옛 판정만 바로
      // 걷고, blur/change 뒤 전체 render가 합계까지 새 값으로 맞춘다.
      var input = Array.prototype.filter.call(
        document.querySelectorAll("[data-manual-input]"),
        function (node) { return node.getAttribute("data-manual-input") === id; })[0];
      var row = input && input.closest("[data-manual-row]");
      if (row) Array.prototype.forEach.call(
        row.querySelectorAll("[data-manual-result]"), function (node) { node.remove(); });
      var saved = document.getElementById("case-confirmed-at");
      if (saved) saved.remove();
    },
    // 확인 표시를 이력에 남긴다. 결과는 이미 저장돼 있는데 확인 표시만 브라우저에
    // 있으면, 나중에 그 기록을 열었을 때 "이 건은 발급했나"를 알 수 없다.
    confirmCase: function () {
      var k = state.kase, p = k.payload;
      if (!p || !p.history || !p.history.id) {
        k.error = "이력에 저장되지 않아 확정할 수 없습니다."; render(); return;
      }
      if (k.confirming) return;
      var ids = Object.keys(k.checked).filter(function (i) { return k.checked[i]; });
      k.error = "";
      k.confirming = true; render();
      fetch("api/history/" + encodeURIComponent(p.history.id) + "/confirm",
            { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ checked: ids, inputs: k.manualInputs || {} }) })
        .then(function (res) {
          if (!res.ok) return res.json().catch(function () { return {}; })
            .then(function (b) { throw new Error(b.detail || ("HTTP " + res.status)); });
          return res.json();
        })
        .then(function (body) {
          // 저장된 payload에는 자기 이력 id가 들어 있지 않다(_remember가 저장 뒤
          // 응답에만 붙인다). 현재 id를 다시 붙여야 값을 고쳐 재확정할 수 있다.
          body.history = p.history;
          k.payload = body;
          k.confirmedAt = body.confirmedAt || "";
          k.manualInputs = body.manualInputs || {};
          k.checked = {};
          (body.manualChecked || []).forEach(function (id) { k.checked[id] = true; });
          k.error = "";
          loadHistory();
        })
        .catch(function (err) { k.error = errMessage(err); })
        .then(function () { k.confirming = false; render(); });
    },
    // 반영 확인의 판정을 이력에 남긴다. 예전에는 드롭다운에 아무것도 안 붙어
    // 있어서, 검토자가 지적을 하나씩 판정해도 새로고침 한 번에 사라졌다.
    //
    // 기계 판정(lineage.items[].status)은 안 건드린다 — 서버가 lineageVerdicts
    // 로 따로 담는다. 그래야 판정 근거가 남고, 다시 검토해 기계 판정이 새로
    // 계산될 때 사람이 한 일까지 지워지지 않는다.
    setLineageVerdict: function (idx, value) {
      var D = window.DOCREVIEW;
      if (!D || idx == null) return;
      D.lineageVerdicts = D.lineageVerdicts || {};
      // **순번이 아니라 지적의 신원**으로 저장한다(서버가 lineage.items[].key 로 준다).
      // 순번은 그 검토 안에서만 뜻이 있어, 다음 검토에서 3번째는 다른 지적이다 —
      // "해당없음"이라 판정한 것을 이어주려면 무엇에 대한 판정인지가 남아야 한다.
      var item = ((D.lineage && D.lineage.items) || [])[Number(idx)] || {};
      var key = item.key || String(idx);
      D.lineageVerdicts[key] = value;
      // 검토자가 직접 고른 순간 `지난 판정` 이 아니게 된다. 태그를 안 떼면 이번에
      // 자기가 바꿔놓고도 지난번 것을 물려받은 줄 안다 — 실측으로 그렇게 남아 있었다
      // (이어받은 것 `해당없음`, 저장된 값 `미반영`, 태그는 그대로).
      if (D.lineageCarried) delete D.lineageCarried[key];
      // **여기서 render() 를 부르면 안 된다.** 통째로 그리면 pdf-mount 가 새로
      // 만들어져 뷰어가 PDF 를 다시 연다(syncViewer) — 판정 하나 바꿀 때마다
      // 문서가 깜빡이고 형광펜이 날아간다. select 가 repaintCard 를 쓰는 이유와
      // 같다. 고른 값은 셀렉트가 이미 제 label 을 바꿔 두었고, 남은 것은 셈
      // 두 군데와 형광펜뿐이다.
      repaintLineagePanel();          // `지난 판정` 태그가 떨어진다
      repaintLineageCounts();
      paintMarks();                   // 미반영만 칠하므로 문서도 따라 바뀐다
      // 지적 카드의 `해당없음` 뱃지도 이 판정에서 온다(renderVals 의
      // na: !!naIds[f.id] ← lineageNaIds 가 status === "해당없음" 인 matchId 를
      // 모은다). 여기를 빼먹어서 판정을 바꿔도 뱃지는 다음 전체 렌더까지
      // 옛 상태로 남아 있었다 — 검토자가 반영 확인에서 정리한 것을 지적
      // 목록은 아직 모르는 것처럼 보였다.
      repaintCard(item.match_id);
      if (!D.historyId) {
        state.serror = "이력에 저장되지 않아 판정을 남길 수 없습니다.";
        render(); return;
      }
      var fd = new FormData();
      fd.append("verdicts", JSON.stringify(D.lineageVerdicts));
      fetch("api/history/" + encodeURIComponent(D.historyId) + "/lineage",
            { method: "POST", body: fd })
        .then(function (res) {
          if (!res.ok) return res.json().catch(function () { return {}; })
            .then(function (b) { throw new Error(b.detail || ("HTTP " + res.status)); });
        })
        .catch(function (err) {
          // 저장에 실패했는데 화면만 바뀌면 검토자는 남았다고 믿는다.
          state.serror = "판정을 저장하지 못했습니다: " + errMessage(err);
          render();
        });
    },

    // 탭을 옮기면 문서에 칠하는 것도 바뀐다(markItems 참고).
    setReviewTab: function (t) { state.reviewTab = t; render(); paintMarks(); },

    setCaseTab: function (t) {
      state.kase.tab = t;
      // 기준 탭은 payload 와 별개로 서버에서 받아온다. 여기서 안 부르면 탭을
      // 직접 누른 검토자는 빈 화면만 본다 — openCriteria 로 들어올 때만 됐었다.
      if (t === "criteria") { actions.loadCriteria(); return; }
      render();
    },
    pickCaseOutput: function (key) { state.kase.selOutput = key; render(); },
    caseCsv: function () {
      var p = state.kase.payload;
      if (!p) return;
      download((p.caseId || "case") + "_검토결과.csv",
                 "\ufeff" + _views.caseCsvText(p), "text/csv;charset=utf-8");
    },
    runCase: function () {
      var k = state.kase;
      // 사람이 뺀 파일은 올리지 않는다. 지정한 것은 그대로 올린다 — 서버가 다시
      // 판별하지만, 지정은 아직 서버에 전달하지 않는다(다음 단계).
      var send = k.files.filter(function (f) { return !k.exclude[f.name]; });
      if (!send.length) { k.error = "올릴 파일이 없습니다."; render(); return; }
      k.step = "progress"; k.stage = {}; k.error = null;
      k.startedAt = Date.now(); k.payload = null;
      render();
      streamCase(send, caseTeam());
      tickCaseElapsed();
    },
    setMode: function (m) {
      state.mode = m;
      // 홈은 "무엇으로 재나"를 진짜 기준으로 말한다 — 들어올 때 읽는다.
      if (m === "home") loadHomeCriteria();
      // 화면을 옮기면 열려 있던 팝오버는 닫는다. 바깥 클릭으로 닫는 규칙이
      // 못 잡는 자리가 하나 있다 — 팝오버 **안**의 로그아웃이다(메뉴 안이라
      // 바깥 클릭에서 제외된다). 그대로 두면 다시 로그인했을 때 프로필 메뉴가
      // 열린 채로 떠 있었다.
      state.profileMenuOpen = false; state.searchOpen = false; state.notiOpen = false;
      // 체크리스트 화면에 들어올 때마다 목록을 새로 읽는다 — 다른 화면에서
      // 등록/삭제하고 돌아와도 묵은 목록이 뜨지 않게.
      if (m === "checklists") {
        // 옆 네비게이션으로 직접 들어오면 관리 모드다 — 검토에서 온 "고르기"
        // 모드를 끈다. 검토 링크는 setMode 를 안 거치는 goPickChecklist 로 온다.
        state.checklistPickReturn = false;
        // 묵은 미리보기·상세·파일·오류가 다시 뜬다. 화면에 돌아올 때마다 깨끗이 지운다.
        state.clib.preview = null;
        state.clib.detail = null;
        state.clib.file = null;
        state.clib.error = null;
        actions.loadChecklists();
        // 고른 팀이 바뀌면 층도 달라진다 — 화면에 들어올 때마다 다시 읽는다.
        state.clayers.list = null;
        actions.loadCriteriaLayers();
      }
      // 단일 검토 셋업의 "체크리스트로 평가" 카드도 등록 목록이 있어야 고를 수
      // 있다. 이미 읽었으면(다른 화면에서) 다시 부르지 않는다.
      if (m === "single" && !state.clib.list.length) actions.loadChecklists();
      render();
    },
    // 아직 안 간 단계로는 못 뛴다. 폴더 검토(goCaseStep)가 이미 그렇게 막는데
    // 단일 검토만 아무 데나 갈 수 있었다 — 업로드도 안 하고 `지적사항` 을 누르면
    // 빈 결과가, 예전에는 프로토타입 시절의 가짜 지적 11건이 떴다.
    go: function (s) {
      if (s === "results" && !state.reviewed) return;
      if (s === "progress" && !state.reviewed && state.stageIndex < 0) return;
      state.screen = s; render();
    },
    goCStep: function (s) { state.cstep = s; render(); },
    // 산출물 세트도 같은 단계 이동. 단, 아직 도달 못 한 단계로는 못 뛴다 —
    // recog 없이 recognize 로 가면 빈 표가, payload 없이 results 로 가면 빈
    // 리포트가 나온다. 검사 중(progress)에는 이동 자체를 막는다.
    goCaseStep: function (s) {
      var k = state.kase;
      if (k.step === "progress") return;
      if (s === "recognize" && !k.recog) return;
      if (s === "results" && !k.payload) return;
      if (s === "progress") return;
      k.step = s; k.view = null; render();
    },
    // 번호 하나를 눌러 그 자리로 간다. 한 지적이 여러 곳을 물면 번호도 여럿인데
    // (`3, 4, 5, 6`), 카드를 누르면 늘 첫 번호로만 갔다 — 나머지로 갈 길이 없었다.
    goMark: function (arg) {
      var cut = String(arg).indexOf("|");
      if (cut < 0) return;
      var id = arg.slice(0, cut), no = arg.slice(cut + 1);
      var it = ((state.marks || {}).items || []).filter(function (x) {
        return x.id === id;
      })[0];
      if (!it) return;
      var m = (it.marks || []).filter(function (x) {
        return String(x.no) === String(no);
      })[0] || (it.marks || [])[0];
      if (!m) return;
      window.DR.pdfview.highlight(id);
      window.DR.pdfview.goTo(m.page, m.rect);
    },
    toggleSev: function (k) { state.sevFilter[k] = !state.sevFilter[k]; render(); },
    setChecker: function (c) { state.checkerFilter = c; render(); },
    // 지적 카드 고르기. 전체 렌더는 pdf-mount 를 새로 만들어 뷰어를 다시 열게 하므로
    // (viewerFor 참고), 카드를 누를 때마다 문서가 깜빡인다 — 그래서 바뀌는 카드 둘만
    // 갈아끼우고 뷰어는 손대지 않는다. toggleIssues가 같은 이유로 쓰는 방식이다.
    select: function (id) {
      var prev = state.selected;
      state.selected = prev === id ? null : id;
      // 수정안은 그 지적에 딸린 것이다. 카드를 옮기면 남겨둘 이유가 없다.
      if (prev !== state.selected) state.fixes = {};

      // 텍스트 폴백(원본 PDF가 없어 본문을 그리는 화면)은 고른 지적에 따라
      // 형광 인용까지 다시 계산해야 한다 — 거기선 통째로 그리는 게 맞다.
      // 어차피 그 화면엔 iframe이 없어 잃을 것도 없다.
      if (!document.getElementById("pdf-mount")) { render(); return; }

      // 카드가 없어도 문서로는 간다. `반영 확인` 탭에는 지적 카드가 아예 없어서,
      // 예전에는 여기서 통째로 다시 그리고 끝났다 — 항목을 눌러도 새로고침만
      // 되고 그 자리로 안 갔다. 갈아끼울 카드가 없는 것과 갈 곳이 없는 것은 다르다.
      var cards = document.querySelectorAll("[data-card]");
      if (cards.length) repaintCard(prev, state.selected);
      syncViewer();
      // 고른 지적으로 문서를 옮긴다. locate() 좌표라 정확한 자리로 가고, 문서를
      // 다시 읽지 않으므로 깜빡임이 없다. 선택 해제면 강조만 끄고 그 자리에 둔다.
      window.DR.pdfview.highlight(state.selected || null);
      var it = ((state.marks || {}).items || []).filter(function (x) {
        return x.id === state.selected;
      })[0];
      if (it && it.marks && it.marks.length) {
        window.DR.pdfview.goTo(it.marks[0].page, it.marks[0].rect);
      }
    },
    // 지적 하나의 수정안을 받아 카드 안에 펼친다. 검토 때 미리 만들지 않는 이유는
    // 지적 대부분이 읽고 넘기는 것이라, 매번 문장을 새로 짓게 하면 검토가 느려지고
    // 비싸지기 때문이다 — 검토자가 그 지적을 붙들었을 때만 묻는다.
    suggestFix: function (key) {
      // 인용마다 따로 만든다 — arg 는 "지적id|인용순번" 이다. 예전엔 지적 하나에
      // 하나뿐이라 첫 인용만 고쳐졌고, 근거가 여럿인 지적(실측 18개)에서는
      // 나머지를 검토자가 손으로 옮겨 적어야 했다.
      var cut = String(key).lastIndexOf("|");
      var id = cut < 0 ? String(key) : String(key).slice(0, cut);
      var qi = cut < 0 ? 0 : parseInt(String(key).slice(cut + 1), 10) || 0;
      var f = null;
      (window.DOCREVIEW.findings || []).forEach(function (x) { if (x.id === id) f = x; });
      if (!f) return;
      var ev = (f.evidence || [])[qi] || {};

      state.fixes[key] = { busy: true };
      repaintCard(id);

      var fd = new FormData();
      fd.append("message", f.message || "");
      fd.append("quote", ev.quote || "");
      // 어느 기준에서 나온 지적인지 함께 보낸다 — 기준을 모르면 모델이 어느
      // 방향으로 고칠지 알 수 없다(SI 단위계는 "5kg" 가 아니라 "5 kg" 가 맞다).
      // 기준 없는 일반 검토면 빈 문자열이고, 서버는 그때 기준 절을 안 만든다.
      fd.append("criterion", _views.criterionTextFor(id) || "");
      // 같은 지적이 함께 든 다른 인용. 모순 지적은 두 곳이 어긋나 나오는데, 한
      // 곳만 보내면 모델이 지적 문장에 적힌 다른 쪽 표현을 정답으로 삼아 이쪽을
      // 거기 맞춰 고쳐 쓴다 — 실측: 개요의 "기능 및 성능 시험" 을 표 제목의
      // "기능 및 성능 및 기타 시험" 으로 바꿔 놨다. 하지도 않은 시험이 문서에
      // 들어갈 뻔했다. 다른 쪽을 보여줘야 "어느 쪽이 맞는지 확인하라"고 답한다.
      // 인용이 줄바꿈을 품을 일은 없다(문장 단위) — 줄바꿈으로 잇는다.
      fd.append("others", (f.evidence || []).filter(function (e, j) {
        return j !== qi && e && e.quote;
      }).map(function (e) { return e.quote; }).join("\n"));
      fd.append("llm", state.llm);
      fetch("api/suggest", { method: "POST", body: fd })
        .then(function (res) {
          if (!res.ok) {
            return res.text().then(function (b) {
              var d = b; try { d = JSON.parse(b).detail || b; } catch (e) { /* 평문 */ }
              throw new Error(String(d).slice(0, 160));
            });
          }
          return res.json();
        })
        .then(function (out) {
          if (!state.fixes[key]) return;   // 그새 다른 카드로 옮겼다(통째로 비웠다)
          state.fixes[key] = { busy: false, ok: !!out.ok, original: out.original || "",
                               revised: out.revised || "", reason: out.reason || "" };
          repaintCard(id);
        })
        .catch(function (e) {
          if (!state.fixes[key]) return;
          state.fixes[key] = { busy: false, ok: false, original: "", revised: "",
                               reason: "수정안을 받지 못했습니다: " + e.message };
          repaintCard(id);
        });
    },
    // 갈아끼우는 건 사람이 한다 — 원본이 PDF·HWPX라 도구가 직접 못 고친다.
    // 그래서 복사까지가 이 기능의 끝이다.
    copyFix: function (key) {
      var fx = state.fixes[key];
      if (!fx || !fx.revised) return;
      var text = fx.revised;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function () { window.prompt("복사하세요:", text); });
      } else {
        window.prompt("복사하세요:", text);   // http(비보안 컨텍스트)에선 clipboard가 없다
      }
    },
    cselect: function (id) { state.cselected = state.cselected === id ? null : id; render(); },
    // 기준을 바꾸면 잣대(id 패턴·범위·미작성 표시)가 통째로 달라진다. 서버에
    // 다시 물어 검토 기준 패널이 고른 것을 말하게 한다 — 안 그러면 example 로
    // 검토하면서 화면에는 acmd 가 떠 있다.
    // 검토를 중단하고 업로드 화면으로 돌아간다.
    //
    // abort() 만 불러선 안 된다. api.js 의 catch 는 AbortError 를 "새 검토가
    // 스스로 취소한 것"으로 보고 아무것도 하지 않는데(그 경우 새 검토가 이미
    // 화면을 세웠다), 사용자가 누른 중단은 세워줄 사람이 없어 진행 화면에
    // 멈춘 채 굳는다. 그래서 화면 복구를 여기서 직접 한다.
    cancelReview: function () {
      if (state.reviewAbort) { state.reviewAbort.abort(); state.reviewAbort = null; }
      clearTimers();
      state.done = false;
      state.stageIndex = -1;
      state.stageDetail = {};
      state.rev = { startedAt: 0, prepAt: 0, prep: {}, lanes: [], done: {}, note: "", active: "", criteriaOpen: false };
      state.serror = null;
      state.screen = "upload";
      render();
    },
    // 검사 취소 — 단일 검토(cancelReview)와 같은 자리, 같은 뜻. 인식 결과는
    // 남겨 두고 인식 확인 단계로 되돌린다. 업로드까지 되돌리면 폴더를 다시
    // 끌어다 놓아야 한다.
    cancelCase: function () {
      var k = state.kase;
      if (k.abort) { k.abort.abort(); k.abort = null; }
      k.stage = {};
      k.startedAt = 0;
      k.error = null;
      k.step = k.recog ? "recognize" : "upload";
      render();
    },
    setChecklist: function (id) {
      state.checklist = id;
      state.clayers = { list: null, busy: false, error: null, open: {}, openItem: {}, how: "" };
      // 직접 골랐다는 표시. 이후 감지 결과가 이 선택을 덮지 않는다.
      state.checklistPicked = true;
      // 서버가 새 잣대를 답할 때 한 번만 그린다. 여기서도 그리면 짧은 사이에
      // 화면을 두 번 갈아엎어 새로고침처럼 번쩍인다(로컬 서버라 왕복은 몇 ms다).
      // 서버가 없으면 답이 안 오므로 그때만 직접 그린다.
      if (servedOverHttp()) loadServerConfig(); else render();
    },
    // 단일 검토를 등록된 체크리스트 기준으로 평가할지 고른다("" = 안 씀).
    // setChecklist(자동 검토 기준)와 달리 감지·서버설정을 다시 부르지 않는다 —
    // 이 선택은 항목별 그룹핑에만 쓰이고 엔진의 id_pattern과 무관하다.
    pickReviewChecklist: function (id) {
      state.reviewChecklistId = id;
      state.clayers = { list: null, busy: false, error: null, open: {}, openItem: {}, how: "" };
      render();
    },
    // 단일 검토에서 "체크리스트가 없습니다 → 체크리스트" 링크로 왔다. 탭을
    // 고르기 모드로 열어, 등록/작성 후 "선택" → "검토로 돌아가기"로 복귀시킨다.
    // setMode 를 안 거친다 — setMode(checklists)는 고르기 모드를 끄기 때문이다.
    goPickChecklist: function () {
      state.checklistPickReturn = true;
      state.clib.preview = null; state.clib.detail = null;
      state.clib.file = null; state.clib.error = null;
      state.mode = "checklists";
      actions.loadChecklists();   // 완료되면 다시 render 한다
      render();
    },
    // 단일 검토의 보조 설정에서 새 체크리스트를 곧장 올린다. 고르기 모드로
    // 먼저 이동해야 등록 뒤에도 "검토로 돌아가기"와 선택 버튼이 유지된다.
    // goPickChecklist()의 render는 동기라, 돌아오면 숨은 file input도 이미 있다.
    uploadChecklistForReview: function () {
      actions.goPickChecklist();
      actions.openChecklistFile();
    },
    // 고르기 모드에서 이 체크리스트를 고른다 — 그 자리에서 선택 표시만 하고
    // 머문다. 곧장 돌아가면 순간이동처럼 뜨므로, 돌아가는 건 배너의
    // "검토로 돌아가기"로 사람이 누른다(backToReviewFromChecklist).
    selectChecklistForReview: function (id) {
      state.reviewChecklistId = id;
      render();
    },
    // 검토 화면으로 돌아간다(상단 배너). 위에서 고른 reviewChecklistId 는
    // 그대로 남아, 셋업 화면에 그 체크리스트가 칩으로 선택되어 있다.
    backToReviewFromChecklist: function () {
      state.checklistPickReturn = false;
      state.mode = "single"; state.screen = "upload";
      if (!state.clib.list.length) actions.loadChecklists();
      render();
    },
    setSort: function (k) { state.sort = k; render(); },
    setLlm: function (k) { state.llm = k; render(); },
    // 테마는 기억한다. 예전엔 <html>에 data-theme만 걸고 어디에도 남기지 않아
    // 새로고침하면 늘 라이트로 되돌아갔다 — "설정"이라 불러놓고 안 지켜졌다.
    setTheme: function (k) {
      state.theme = k;
      document.documentElement.setAttribute("data-theme", k);
      try { localStorage.setItem("dr_theme", k); } catch (e) { /* 사생활 보호 모드 */ }
      render();
    },
    openFile: function (slot) { var el = document.getElementById("file-" + slot); if (el) el.click(); },
    clearFile: function (slot) { if (state.files.hasOwnProperty(slot)) { state.files[slot] = null; render(); } },
    startReview: function () {
      clearTimers();
      // clearTimers()가 진행 중이던 holdDone의 advance()도 지운다 — 그대로 두면
      // done이 true로 눌어붙은 채 다음 검토로 들어간다.
      state.done = false;
      var f = state.files.single;
      // 문서 없이 시작하면 목업 findings가 진짜 결과처럼 떴다. 그 길을 막는다.
      if (!f || !f.file) {
        state.serror = "검토할 문서를 먼저 올려주세요.";
        state.mode = "single"; state.screen = "upload"; render();
        return;
      }
      if (!servedOverHttp()) {
        state.serror = "브라우저로 파일을 직접 연 상태입니다. `docreview serve`로 띄운 주소에서 검토하세요.";
        state.mode = "single"; state.screen = "upload"; render();
        return;
      }

      window.DOCREVIEW.doc.name = f.name;
      window.DOCREVIEW.doc.type = (f.name.split(".").pop() || "").toUpperCase();
      state.serror = null;
      state.stageDetail = {};
      state.rev = { startedAt: Date.now(), prepAt: 0, prep: {}, lanes: [], done: {}, note: "", active: "", criteriaOpen: false };
      state.clayers = { list: null, busy: false, error: null, open: {}, openItem: {}, how: "" };
      state.mode = "single"; state.screen = "progress"; state.stageIndex = -1;
      state.reviewed = false;                 // 이번 검토는 아직 결과가 없다
      state.selected = null;
      render();
      actions.loadCriteriaLayers();
      tickElapsed();   // 경과 시간은 이벤트가 없어도 흘러야 한다

      var fd = new FormData();
      fd.append("file", f.file);
      fd.append("llm", state.llm);
      if (state.checklist) fd.append("checklist", state.checklist);
      // 등록된 체크리스트를 평가 기준으로 골랐으면 함께 보낸다 — 서버가 항목별
      // findings(payload.checklist)를 되돌려 보낸다(done 이벤트는 api.js가 받는다).
      if (state.reviewChecklistId) fd.append("checklist_id", state.reviewChecklistId);
      streamReview(fd);
    },
    startCompare: function () {
      clearTimers();
      var fa = state.files.compareA, fb = state.files.compareB;
      if (fa) window.DOCREVIEW.compare.docA.name = fa.name;
      if (fb) window.DOCREVIEW.compare.docB.name = fb.name;
      state.cerror = null;
      state.mode = "compare"; state.cstep = "progress"; state.cstageIndex = -1; state.cselected = null;
      state.cdone = false;
      render();

      // 서버로 서빙되고 두 파일이 모두 올라와 있으면 실제 엔진을 호출한다.
      // 그 밖의 경우(file:// 프로토타입, 파일 미선택)는 기존 목업 흐름을 유지한다.
      var live = !!(fa && fb && fa.file && fb.file && servedOverHttp());
      animate(window.DOCREVIEW.compare.stages.length, function (i) { state.cstageIndex = i; },
        760, live, function () {
          holdDone(function () { state.cdone = true; },
                   function () { state.cdone = false; if (state.cstep === "progress") state.cstep = "results"; });
        });
      if (!live) return;

      var fd = new FormData();
      fd.append("parent", fa.file);
      fd.append("child", fb.file);
      fd.append("llm", state.llm);
      if (state.checklist) fd.append("checklist", state.checklist);
      postForm("api/compare", fd)
        .then(function (payload) {
          clearTimers();
          window.DOCREVIEW.compare = payload;
          state.cstageIndex = payload.stages.length - 1;
          var cA = (payload.docA && payload.docA.name) || "문서";
          var cB = (payload.docB && payload.docB.name) || "문서";
          notify(cA + " ↔ " + cB, {
            id: (payload.history && payload.history.id) || null,
            watching: state.mode === "compare" && state.cstep === "progress"
          });
          holdDone(function () { state.cdone = true; },
                   function () { state.cdone = false; if (state.cstep === "progress") state.cstep = "results"; });
          loadHistory(true);   // 완료 연출을 다시 시작하지 않고 이력만 동기화한다
        })
        .catch(function (err) {
          clearTimers();
          state.cdone = false;
          state.cerror = errMessage(err);
          state.cstep = "setup"; render();
        });
    },
    reloadHistory: function () { state.history = null; render(); loadHistory(); },
    // 저장해둔 검토를 다시 연다. 문서를 재업로드하지 않는다 — 그때 그 결과 그대로다.
    openHistory: function (id) {
      if (!id || state.hbusy) return;
      // 알림·검색에서도 부른다 — 결과로 넘어가는데 팝오버가 남아 있으면 안 된다.
      state.notiOpen = false; state.searchOpen = false;
      state.hbusy = true; render();
      fetch("api/history/" + encodeURIComponent(id))
        .then(function (res) {
          if (!res.ok) throw new Error("이력을 불러오지 못했습니다 (HTTP " + res.status + ")");
          return res.json();
        })
        .then(function (rec) {
          state.hbusy = false;
          clearTimers();
          var p = rec.payload;
          if (rec.kind === "case") {
            // 산출물 세트 검토. 원본 파일은 브라우저가 안 들고 있으므로 뷰어는 못 연다
            // (검사 때 올린 것은 서버가 이미 지웠다). 리포트와 확인 표시만 되살린다.
            var checked = {};
            (p.manualChecked || []).forEach(function (id) { checked[id] = true; });
            p.history = { saved: true, id: rec.id, at: rec.at };
            state.kase = {
              step: "results", tab: "summary", selOutput: "", view: null,
              checked: checked, manualInputs: p.manualInputs || {},
              confirmedAt: p.confirmedAt || "", confirming: false,
              team: "", files: [], recog: null, assign: {}, exclude: {},
              stage: {}, startedAt: 0, payload: p, criteria: null,
              criteriaLoading: false, criteriaError: "", criteriaFocus: "",
              matrixFocus: "", error: null, abort: null
            };
            state.mode = "case";
            render();
            return;
          }
          if (rec.kind === "compare") {
            window.DOCREVIEW.compare = p;
            state.mode = "compare"; state.cstep = "results";
            state.cstageIndex = (p.stages || []).length - 1;
            state.cselected = null; state.cerror = null;
          } else if (rec.kind === "checklist") {
            // compare/single 과 달리 payload로 감싸지 않는다 — rec 최상위에
            // checklist_id·checklist_name·document_name·results 를 그대로 담아
            // 온다. 저장된 스냅샷만으로 자체 완결이라(체크리스트가 나중에
            // 지워져도 이어서 보고 판정할 수 있다 — 재저장·CSV만 서버가 404로
            // 막는다) 여기선 GET /api/checklists/{id} 를 다시 부르지 않는다.
            var saved = rec.results || [];
            var items = saved.map(function (r) {
              return { no: r.no, text: r.text, group: r.group, note: "" };
            });
            var results = {};
            // 결과는 no 가 아니라 배열 위치(index)로 키잉한다(위 setVerdict
            // 주석 참고) — 저장 스냅샷의 순서를 그 위치로 그대로 되쓴다.
            saved.forEach(function (r, i) {
              if (r.verdict || r.reason) results[String(i)] = { verdict: r.verdict || null, reason: r.reason || "" };
            });
            state.crun = { checklist: { id: rec.checklist_id, name: rec.checklist_name, items: items },
                           results: results, saving: false, error: null, from: "history",
                           documentName: rec.document_name || "" };
            state.runChecklistId = rec.checklist_id;
            state.mode = "checklistrun";
            render();
            return;
          } else {
            // 이력은 원본 파일이 없다 — 뷰어 대신 텍스트 폴백으로 간다. 직전 실검토의
            // blob·파일이 남아 엉뚱한 PDF가 뜨지 않도록 뷰어 상태를 비운다.
            if (state.viewer.origUrl) URL.revokeObjectURL(state.viewer.origUrl);
            if (state.annot.viewUrl) URL.revokeObjectURL(state.annot.viewUrl);
            state.viewer = { mode: "orig", baseBlob: null, origUrl: null, converting: false, convertError: null };
            state.annot = { busy: false, msg: "" };
            state.files.single = null;
            viewerFor = null;
            window.DOCREVIEW.doc = p.doc;
            window.DOCREVIEW.sections = p.sections || [];
            window.DOCREVIEW.findings = p.findings;
            window.DOCREVIEW.stages = p.stages;
            // 라이브 done 핸들러(api.js)와 똑같이 기준↔지적 연결과, 업로드 기준을
            // 골랐을 때의 그룹 화면 상태를 되살린다.
            window.DOCREVIEW.criteriaResults = p.criteriaResults || null;
            window.DOCREVIEW.checklist = p.checklist || null;
            state.mode = "single"; state.screen = "results";
            state.stageIndex = (p.stages || []).length - 1;
            state.reviewed = true;      // 이력에서 되살린 것도 진짜 결과다
            state.done = true;          // 진행 탭이 "검토 중…"이라 거짓말하지 않게
            state.selected = null; state.serror = null;
          }
          render();
          // 서버가 원본을 보관해뒀다면(최근 몇 건) 되살려 뷰어로 — 재업로드·재검토 없이.
          // 밀려나 없으면 404 → 텍스트 폴백 그대로.
          if (rec.kind !== "compare") {
            var docName = (p.doc || {}).name || "document";
            fetch("api/history/" + encodeURIComponent(id) + "/original")
              .then(function (res) { return res.ok ? res.blob() : null; })
              .then(function (blob) {
                // 그새 다른 화면/검토로 넘어갔으면 붙이지 않는다(엉뚱한 PDF 방지).
                if (!blob || state.mode !== "single" || state.screen !== "results") return;
                if (window.DOCREVIEW.doc !== p.doc) return;
                // 세 번째 인자를 빼면 File 의 type 이 빈 문자열이 된다 — 서버가
                // application/pdf 로 보내도 여기서 버려지고, 그 blob URL 을 받은
                // iframe 은 PDF 를 못 그린다. 업로드 경로(input.files[0])는 브라우저가
                // 타입을 채워주므로 이력에서 되살릴 때만 나던 증상이었다.
                var file = new File([blob], docName, { type: blob.type || "application/pdf" });
                state.files.single = { name: docName, size: file.size, file: file };
                render();   // maybeConvert가 뷰어를 띄운다(pdf 직접·docx/hwpx 변환)
              })
              .catch(function () { /* 원본 없음/오류 — 텍스트 폴백 유지 */ });
          }
        })
        .catch(function (err) {
          state.hbusy = false;
          state.herror = errMessage(err);
          render();
        });
    },
    // 행의 삭제 버튼은 바로 지우지 않고 확인 모달을 연다.
    askDeleteHistory: function (id) {
      if (!id) return;
      var h = (state.history || []).filter(function (x) { return x.id === id; })[0];
      state.confirmDelete = { id: id, title: h ? h.title : "이 기록" };
      render();
    },
    cancelDelete: function () { state.confirmDelete = null; render(); },
    // 기록을 통째로 비운다. 하나씩 지우면 스무 건에 스무 번을 눌러야 한다.
    // 지우는 것은 같은 API 를 건마다 부르는 것이다 — 서버에 일괄 삭제를 따로
    // 두지 않는다(한 건이 실패해도 나머지는 지워지고, 결과는 목록이 말한다).
    askDeleteAll: function () {
      var n = (state.history || []).length;
      if (!n) return;
      state.confirmDelete = { id: "*", title: "기록 " + n + "건", all: true };
      render();
    },
    // 지적사항 화면의 "검토 결과" 사이드바를 접었다 폈다 — 문서를 넓게 정독할 때.
    // render()로 전체를 다시 그리면 문서 뷰어의 PDF iframe이 재부착되며 리로드된다.
    // 그래서 패널·레일은 늘 DOM에 있고, 둘의 실제 폭을 서로 넘겨주는 전환만 걸어
    // 뷰어를 건드리지 않는다. 문서 영역도 그 폭을 따라 한 번에 튀지 않고 늘어난다.
    toggleIssues: function () {
      var p = document.getElementById("issuesPanel"), r = document.getElementById("issuesRail");
      if (!p || !r) {
        state.issuesCollapsed = !state.issuesCollapsed; state.exportMenuOpen = false; render(); return;
      }
      // 열린 메뉴만 제자리에서 정리한다. 패널을 접기 위해 전체 render 를 부르면
      // 아래 애니메이션보다 먼저 PDF iframe 이 다시 만들어진다.
      if (state.exportMenuOpen) {
        state.exportMenuOpen = false;
        var menu = document.getElementById("exportMenu");
        if (menu) menu.remove();
        var exportBtn = p.querySelector('[data-act="toggleExportMenu"]');
        if (exportBtn) {
          exportBtn.style.borderColor = "var(--line)";
          exportBtn.style.background = "var(--bg)";
          exportBtn.style.color = "var(--text-3)";
        }
      }

      // 연속 실행 때는 지금 화면에 보이는 폭에서 반대 방향으로 이어간다.
      var app = p.closest && p.closest(".dr-app");
      var zoom = p.currentCSSZoom || (app && parseFloat(app.style.zoom)) || 1;
      var pRect = p.getBoundingClientRect(), rRect = r.getBoundingClientRect();
      var pNow = pRect.width / zoom, rNow = rRect.width / zoom;
      var pMarginNow = pRect.width ? (parseFloat(window.getComputedStyle(p).marginRight) || 0) : 0;
      if (p._issuesAnimation) p._issuesAnimation.cancel();
      if (r._issuesAnimation) r._issuesAnimation.cancel();

      state.issuesCollapsed = !state.issuesCollapsed;
      var collapsing = state.issuesCollapsed;
      p.style.display = "flex";
      r.style.display = "flex";

      if (reduceMotion() || !p.animate || !r.animate) {
        p.style.display = collapsing ? "none" : "flex";
        r.style.display = collapsing ? "flex" : "none";
        return;
      }

      var pTarget = parseFloat(window.getComputedStyle(p).width) || 400;
      var pMarginTarget = parseFloat(window.getComputedStyle(p).marginRight) || 32;
      var rTarget = parseFloat(window.getComputedStyle(r).width) || 44;
      p.style.pointerEvents = "none";
      r.style.pointerEvents = "none";
      p._issuesAnimation = p.animate([
        { width: pNow + "px", marginRight: pMarginNow + "px", opacity: pNow ? 1 : 0,
          transform: pNow ? "translateX(0)" : "translateX(12px)" },
        { width: (collapsing ? 0 : pTarget) + "px",
          marginRight: (collapsing ? 0 : pMarginTarget) + "px",
          opacity: collapsing ? 0 : 1,
          transform: collapsing ? "translateX(12px)" : "translateX(0)" }
      ], { duration: 300, easing: "cubic-bezier(.16, 1, .3, 1)", fill: "both" });
      r._issuesAnimation = r.animate([
        { width: rNow + "px", opacity: rNow ? 1 : 0,
          transform: rNow ? "translateX(0)" : "translateX(12px)" },
        { width: (collapsing ? rTarget : 0) + "px", opacity: collapsing ? 1 : 0,
          transform: collapsing ? "translateX(0)" : "translateX(12px)" }
      ], { duration: 300, easing: "cubic-bezier(.16, 1, .3, 1)", fill: "both" });

      p._issuesAnimation.onfinish = function () {
        if (state.issuesCollapsed !== collapsing) return;
        p.style.display = collapsing ? "none" : "flex";
        r.style.display = collapsing ? "flex" : "none";
        p.style.pointerEvents = "";
        r.style.pointerEvents = "";
        var pa = p._issuesAnimation, ra = r._issuesAnimation;
        p._issuesAnimation = null; r._issuesAnimation = null;
        if (pa) pa.cancel();
        if (ra) ra.cancel();
      };
    },
    // 결과 화면(문서 + "검토 결과")을 화면 전체로. 덮는 대상이 문서 카드가 아니라
    // 2단 행 전체인 이유는 views.js의 resultsRowCss 주석에 있다.
    //
    // toggleIssues와 같은 이유로 render()를 쓰지 않는다 — 전체 렌더는 PDF iframe을
    // 재부착해 리로드시키므로 읽던 쪽을 잃는다. 행을 옮기지도 않고(제자리
    // position:fixed) 스타일만 통째로 갈아끼운다. 다만 바뀌기 전후의 화면상
    // 사각형은 기억했다가 FLIP transform 으로 이어, 카드가 제자리에서 자연스럽게
    // 펼쳐지는 것처럼 보이게 한다. PDF 노드는 여전히 한 번도 옮기지 않는다.
    toggleViewerFull: function () {
      var row = document.getElementById("results-row");
      var btn = document.getElementById("viewerFullBtn");
      state.viewerFull = !state.viewerFull;
      if (!row || !btn) { render(); return; }
      var first = row.getBoundingClientRect();
      if (row._viewerFullAnimation) row._viewerFullAnimation.cancel();
      row.style.cssText = _views.resultsRowCss(state.viewerFull);
      btn.innerHTML = state.viewerFull ? window.DR.ICONS.minimize : window.DR.ICONS.maximize;
      btn.title = state.viewerFull ? "원래 크기로 (Esc)" : "전체화면";

      var last = row.getBoundingClientRect();
      if (reduceMotion() || !row.animate || !first.width || !last.width) return;
      // getBoundingClientRect 는 실제 화면 px, transform 은 zoom 전의 CSS px 를 쓴다.
      // 앱 전체가 화면 높이에 맞춰 CSS zoom 되므로 이동량만 그 비율로 되돌린다.
      var app = row.closest && row.closest(".dr-app");
      var zoom = row.currentCSSZoom || (app && parseFloat(app.style.zoom)) || 1;
      var dx = (first.left - last.left) / zoom;
      var dy = (first.top - last.top) / zoom;
      var sx = first.width / last.width;
      var sy = first.height / last.height;
      row._viewerFullAnimation = row.animate([
        { transformOrigin: "top left", transform: "translate(" + dx + "px," + dy + "px) scale(" + sx + "," + sy + ")", opacity: .96 },
        { transformOrigin: "top left", transform: "translate(0,0) scale(1,1)", opacity: 1 }
      ], { duration: 300, easing: "cubic-bezier(.16, 1, .3, 1)" });
      row._viewerFullAnimation.onfinish = function () { row._viewerFullAnimation = null; };
    },
    // 검토 결과 헤더의 내보내기(⇩) 드롭다운. 다른 팝오버는 닫는다.
    toggleExportMenu: function () {
      state.exportMenuOpen = !state.exportMenuOpen;
      state.profileMenuOpen = false; state.searchOpen = false;
      render();
    },
    // 비교 검토 화면의 "불일치 내역 분석" 사이드바 접기/펴기(단일과 독립).
    toggleCIssues: function () {
      var p = document.getElementById("cIssuesPanel"), r = document.getElementById("cIssuesRail");
      if (!p || !r) { state.cIssuesCollapsed = !state.cIssuesCollapsed; render(); return; }
      state.cIssuesCollapsed = !state.cIssuesCollapsed;
      p.style.display = state.cIssuesCollapsed ? "none" : "flex";
      r.style.display = state.cIssuesCollapsed ? "flex" : "none";
    },
    deleteHistory: function (id) {
      if (!id || state.hbusy) return;
      state.confirmDelete = null;   // 확인했으니 모달을 닫고 실제로 지운다
      state.hbusy = true; render();
      // `*` 는 전체다. 건마다 부르고 다 끝나면 한 번만 목록을 다시 읽는다.
      var ids = id === "*"
        ? (state.history || []).map(function (h) { return h.id; })
        : [id];
      var done = function () { state.hbusy = false; loadHistory(); };
      Promise.all(ids.map(function (one) {
        return fetch("api/history/" + encodeURIComponent(one), { method: "DELETE" })
          .catch(function () { /* 한 건이 실패해도 나머지는 지운다 */ });
      })).then(done, done);
    },
    // 원본 PDF에 형광펜을 얹어 받는다. 서버는 원본을 보관하지 않으므로 파일을
    // 다시 보낸다 — 검토 직후면 브라우저가 아직 들고 있어서 사용자는 아무것도
    // 안 해도 된다. 이력에서 연 검토는 원본이 없으니 다시 고르게 한다.
    // 문서 뷰어 줌. render() 를 부르지 않는다 — 전체 렌더는 뷰어를 다시 열어
    // 읽던 자리를 잃는다. pdfview 가 캔버스만 다시 그린다.
    zoom: function (arg) {
      window.DR.pdfview.zoom(arg === "fit" ? "fit" : parseFloat(arg));
    },
    // 형광펜 끄기. 지적이 수십 건이면 색이 겹쳐 원문이 안 보인다 — 끄고 읽다가
    // 다시 켠다. 전체 render()는 부르지 않는다. PDF 뷰어는 살아남더라도 오른쪽
    // 검토 결과 패널이 새 DOM으로 교체돼 읽던 카드의 스크롤이 맨 위로 돌아간다.
    // 바뀌는 것은 형광펜 레이어와 이 단추의 상태뿐이므로 둘만 제자리에서 고친다.
    toggleMarks: function () {
      state.marksOn = state.marksOn === false;
      window.DR.pdfview.setMarksVisible(state.marksOn);
      var buttons = document.querySelectorAll('[data-act="toggleMarks"]');
      for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        btn.title = state.marksOn ? "형광펜 끄기" : "형광펜 켜기";
        btn.setAttribute("aria-pressed", state.marksOn ? "true" : "false");
        btn.style.background = state.marksOn ? "var(--accent-weak)" : "var(--bg)";
        btn.style.color = state.marksOn ? "var(--accent-ink)" : "var(--text-3)";
      }
    },
    downloadMarked: function () {
      closeExportMenu();              // 항목을 골랐으니 메뉴를 닫는다
      var D = window.DOCREVIEW;
      var base = ((D.doc && D.doc.name) || "document").replace(/\.[^.]+$/, "");
      if (state.annot.blob) { downloadBlob(base + ".marked.pdf", state.annot.blob); return; }
      var f = state.files.single;
      if (f && f.file) { doAnnotate(f.file, function () { downloadBlob(base + ".marked.pdf", state.annot.blob); }); return; }
      state.annot = Object.assign({}, state.annot, { msg: "원본 PDF를 다시 선택하세요. (서버는 원본을 보관하지 않습니다)" });
      render();
    },
    exportAs: function (kind) {
      closeExportMenu();
      var base = window.DOCREVIEW.doc.name.replace(/\.[^.]+$/, "");
      // 본문은 views.js 가 만든다 — 여기는 내려받기 통로만 진다. 넷 다 지난번
      // 지적에 대한 검토자의 판정을 함께 싣는다(반영 확인이 회신서의 알맹이다).
      if (kind === "html") {
        // 문서 본문 + 모든 지적이 박힌 자기완결 HTML. 브라우저에서 인쇄하면 PDF가 된다.
        download(base + ".review.html", _views.reviewHtml(), "text/html");
      } else if (kind === "json") {
        download(base + ".review.json", _views.reviewJson(), "application/json");
      } else if (kind === "md") {
        download(base + ".review.md", _views.reviewMd(), "text/markdown");
      } else {
        download(base + ".review.csv", "﻿" + _views.reviewCsv(), "text/csv");
      }
    },

    // ---- 체크리스트 라이브러리 --------------------------------------------
    loadChecklists: function () {
      if (!servedOverHttp()) return;
      fetch("api/checklists").then(function (r) { return r.json(); })
        .then(function (b) { state.clib.list = b.checklists || []; render(); })
        .catch(function (e) { state.clib.error = errMessage(e); render(); });
    },

    // 파일을 고르면 먼저 재본다. 등록은 사람이 확인한 뒤에.
    previewChecklist: function (file) {
      if (!file || !servedOverHttp()) return;
      state.clib.busy = true; state.clib.error = null; state.clib.file = file;
      render();
      var fd = new FormData();
      fd.append("file", file, file.name);
      postForm("api/checklists/preview", fd).then(function (b) {
        var tables = b.tables || [];
        // 서버가 처음 추측한 열을 따로 찍어둔다 — setChecklistColumn이
        // t.columns.text를 그 자리에서 덮어써 버려서, 나중에 "사람이 고친
        // 열이 추측과 다른지"를 가리려면 원래 값을 여기서만 남길 수 있다.
        tables.forEach(function (t) {
          t.guessedText = (t.columns || {}).text;
          if (t.guessedText === undefined) t.guessedText = null;
        });
        state.clib.busy = false;
        state.clib.preview = { tables: tables, picked: 0,
                               name: file.name.replace(/\.[^.]+$/, "") };
        render();
      }).catch(function (e) {
        state.clib.busy = false; state.clib.preview = null;
        state.clib.error = errMessage(e); render();
      });
    },

    pickChecklistTable: function (i) {
      if (state.clib.preview) { state.clib.preview.picked = Number(i); render(); }
    },

    // 추측이 틀렸을 때 검토자가 직접 고친다.
    setChecklistColumn: function (arg) {
      var parts = String(arg).split(":");           // "text:2"
      var p = state.clib.preview;
      if (!p) return;
      var t = p.tables[p.picked];
      if (!t) return;
      var v = Number(parts[1]);
      t.columns[parts[0]] = v;
      render();
    },

    registerChecklist: function () {
      var p = state.clib.preview;
      if (!p || !state.clib.file) return;
      var t = p.tables[p.picked];
      if (!t || t.columns.text === null || t.columns.text === undefined) {
        state.clib.error = "'항목 내용' 열을 골라야 합니다.";
        render(); return;
      }
      state.clib.busy = true; render();
      var fd = new FormData();
      fd.append("file", state.clib.file, state.clib.file.name);
      fd.append("name", p.name || "");
      fd.append("table_index", String(p.picked));
      fd.append("columns", JSON.stringify(t.columns));
      postForm("api/checklists", fd).then(function () {
        state.clib.busy = false; state.clib.preview = null; state.clib.file = null;
        actions.loadChecklists();
      }).catch(function (e) {
        state.clib.busy = false; state.clib.error = errMessage(e); render();
      });
    },

    // 목록에서 눌러 항목을 들여다본다. 열을 틀리게 골라 등록한 것도 여기서 드러난다.
    //
    // 화면도 같이 옮긴다 — 검색 결과에서 바로 부르면 상세만 채워 놓고 다른 화면에
    // 머물러, 눌러도 아무 일이 없는 것처럼 보인다.
    openChecklist: function (id) {
      state.mode = "checklists";
      state.searchOpen = false;
      fetch("api/checklists/" + encodeURIComponent(id))
        .then(function (r) { return r.json(); })
        .then(function (c) { state.clib.detail = c; render(); })
        .catch(function (e) { state.clib.error = errMessage(e); render(); });
    },
    closeChecklist: function () { state.clib.detail = null; render(); },

    deleteChecklist: function (id) {
      fetch("api/checklists/" + encodeURIComponent(id), { method: "DELETE" })
        .then(function () { actions.loadChecklists(); })
        .catch(function (e) { state.clib.error = errMessage(e); render(); });
    },

    openChecklistFile: function () {
      var el = document.getElementById("file-checklist");
      if (el) el.click();
    },
    cancelChecklist: function () {
      state.clib.preview = null; state.clib.file = null; state.clib.error = null;
      render();
    },

    // ---- 체크 흐름(등록된 체크리스트를 판정·이유로 채우기) -------------------
    // 라이브러리 행의 "검토 시작" — 체크리스트 채우기를 자동 검토와 완전히
    // 떼어 독립 화면(mode "checklistrun")으로 곧장 연다.
    startChecklistRun: function (id) {
      if (!id) return;
      fetch("api/checklists/" + encodeURIComponent(id))
        .then(function (r) { return r.json(); })
        .then(function (c) {
          state.crun = { checklist: c, results: {}, saving: false, error: null,
                         from: "checklists", documentName: "" };
          state.runChecklistId = id;
          state.mode = "checklistrun";
          render();
        })
        .catch(function (e) { state.crun.error = errMessage(e); render(); });
    },

    // 인자 형식 "v|항목위치인덱스|판정값". data-arg 하나로 둘을 실어 보낸다.
    // no 가 아니라 배열 위치(index)로 키잉한다 — no 는 선택 안 하면 전부 ""
    // 이고 구간별 재시작으로 겹칠 수 있어(| 도 섞일 수 있어), 위치만이 항목을
    // 유일하게 가리킨다.
    setVerdict: function (arg) {
      var p = String(arg).split("|");
      var idx = p[1];
      var cur = state.crun.results[idx] || { verdict: null, reason: "" };
      cur.verdict = p[2] || null;
      state.crun.results[idx] = cur;
      render();
    },

    setReason: function (idx, text) {
      var cur = state.crun.results[idx] || { verdict: null, reason: "" };
      cur.reason = text;
      state.crun.results[idx] = cur;   // 입력 중에는 render 하지 않는다(포커스 유지)
    },

    saveChecklistRun: function () {
      var c = state.crun.checklist;
      if (!c) return;
      state.crun.saving = true; render();
      var fd = new FormData();
      // 독립 화면 자체에서 받은 문서명을 우선한다 — 자동 검토를 거치지 않고
      // 라이브러리/기록에서 곧장 들어온 경우 files.single 은 애초에 비어 있다.
      fd.append("document_name", state.crun.documentName || (state.files.single && state.files.single.name) || "");
      fd.append("results", JSON.stringify(state.crun.results));
      postForm("api/checklists/" + encodeURIComponent(c.id) + "/run", fd)
        .then(function () { state.crun.saving = false; render(); })
        .catch(function (e) {
          state.crun.saving = false; state.crun.error = errMessage(e); render();
        });
    },

    exportChecklistCsv: function () {
      var c = state.crun.checklist;
      if (!c) return;
      var fd = new FormData();
      fd.append("results", JSON.stringify(state.crun.results));
      fetch("api/checklists/" + encodeURIComponent(c.id) + "/csv",
            { method: "POST", body: fd })
        .then(function (r) { return r.blob(); })
        .then(function (b) { downloadBlob(c.name + ".checklist.csv", b); })
        .catch(function (e) { state.crun.error = errMessage(e); render(); });
    }
  };

  // ---- 뷰 레이어(views.js) 재바인딩 --------------------------------------
  var _views = window.DR.views({ state: state, props: props, render: render, backend: _be });
  var renderVals = _views.renderVals, view = _views.view,
      selectedSection = _views.selectedSection, reviewHtml = _views.reviewHtml,
      doAnnotate = _views.doAnnotate,
      findingCardClass = _views.findingCardClass, findingCardInner = _views.findingCardInner,
      numberChip = _views.numberChip;
  var lastScrolled = null;

  // 체크리스트 "이유" 입력을 두 가지 위협에서 지킨다. (1) 자동 검토는 몇 분간
  // SSE로 stage 이벤트를 계속 보내는데(api.js onReviewEvent의 "stage" 분기),
  // 그때마다 render()를 부른다 — 결과 화면에서 "이유"를 타이핑하는 도중에도
  // 이게 계속 들어온다. innerHTML을 통째로 갈아엎으면 그 input DOM 노드가
  // 아예 새로 만들어지므로 포커스·캐럿이 날아간다. (2) 한글 등 IME 조합
  // 중엔 아직 커밋되지 않은 글자가 DOM에만 있을 뿐 어디에도 값으로 남지
  // 않는다 — 그 상태에서 노드가 죽으면 그 글자는 그냥 사라진다(input
  // 이벤트로 넘어오기도 전에 노드가 죽는다). setReason이 render를 부르지
  // 않는 것만으론 부족하다 — 문제는 "남이" 부르는 render다.
  //
  // 예전엔 포커스가 [data-reason]에 있기만 해도 render() 전체를 건너뛰었다.
  // 그런데 검토 화면의 다른 버튼(검증 결과·저장·CSV 내보내기 등)을 누르는
  // 것도 mousedown → blur → focusout을 먼저 일으켜 클릭보다 먼저 렌더를
  // 끼워 넣는다 — 클릭 델리게이션(아래 document.addEventListener("click", ...))
  // 이 data-act를 찾는 시점엔 원래 누른 노드가 이미 통째로 새 노드로 바뀐
  // 뒤라 클릭이 그냥 씹혔다. 게다가 reasonComposing이 compositionend로만
  // 풀리는데, 일부 IME/브라우저 조합은 이 이벤트를 아예 안 보내는 경우가
  // 있어(문서화된 known issue) 그러면 render()가 앱 전체에서 영구히 멈췄다.
  //
  // 그래서 (1)번은 "건너뛰기"가 아니라 "캡처 후 복원"으로 바꾼다 — render()
  // 안, innerHTML을 갈아엎기 직전에 포커스된 입력의 data-reason 값과 캐럿
  // 위치를 기억해뒀다가 다시 그린 뒤 같은 input을 찾아 되살린다. data-scroll
  // 컨테이너의 스크롤 위치를 기억했다 되살리는 것과 정확히 같은 모양이다.
  // 이러면 클릭은 원래 노드가 살아있는 동안 델리게이션에 잡히고, 그 뒤
  // render가 일어나도 입력은 멀쩡히 이어진다.
  //
  // (2)번(진짜 조합 중)만은 여전히 render를 건너뛴다 — 조합 중인 글자는
  // 값 자체가 아직 확정되지 않아 캡처해서 복원할 수가 없기 때문이다. 이때
  // 건너뛴 렌더는 reasonRenderPending에 표시해뒀다가 compositionend에서
  // 몰아 그린다.
  //
  // watchdog: compositionend가 끝내 안 오는 브라우저/IME에 대비해, 조합
  // 시작 후 일정 시간이 지나도 종료 신호가 없으면 강제로 reasonComposing을
  // 풀고 밀린 렌더를 흘려보낸다(아래 boot()의 compositionstart 리스너 참고).
  // 이게 없으면 그 브라우저에서는 새로고침 전까지 앱이 영원히 멈춘다.
  //
  // focusout에서는 절대 몰아 그리지 않는다 — 이전 코드의 핵심 버그였다. 다른
  // 컨트롤을 누르면 그 클릭이 오기 "직전"에 focusout이 먼저 발생하므로,
  // 거기서 렌더를 흘려보내면 방금 누른 버튼의 DOM 노드가 클릭이 델리게이션에
  // 닿기도 전에 사라진다 — 저장 버튼이 조용히 안 눌리던 원인이 바로 이것
  // 이었다. 몰아 그리는 시점은 오직 compositionend(정상 종료)와 watchdog
  // (비정상 미종료 대비)뿐이다.
  var reasonComposing = false;
  var reasonRenderPending = false;
  var reasonComposeWatchdog = null;    // compositionend 유실 대비 타이머 id

  // pdf.js 뷰어에 지금 올라간 base blob. 문서가 바뀔 때만 다시 연다(syncViewer 참고).
  // iframe 시절의 pdfFrame/pdfSrcUrl/pdfLastKey 캐시를 이 하나가 대신한다 — pdf.js는
  // canvas라 노드를 DOM에서 옮겨도 리로드되지 않으므로 복잡한 키가 필요 없다.
  var viewerFor = null;


  // 뷰어가 지금 무엇을 그려야 하나. 단일 검토와 의뢰 건이 같은 부품(render-pdf ·
  // locate · pdfview)을 쓰므로 **출처만** 갈라 준다 — 부품을 복사하면 한쪽만 고쳐지는
  // 버그가 생긴다.
  function viewerSource() {
    if (state.mode === "case" && state.kase.step === "results" && state.kase.view) {
      var kv = state.kase.view;
      return { file: kv.file, name: kv.file ? kv.file.name : "",
               findings: kv.findings || [], images: [], single: false };
    }
    if (state.mode === "single" && state.screen === "results") {
      var f = state.files.single;
      return { file: f && f.file, name: (window.DOCREVIEW.doc || {}).name || "",
               findings: window.DOCREVIEW.findings || [],
               images: window.DOCREVIEW.images || [], single: true };
    }
    return null;
  }

  function maybeConvert() {
    var v = state.viewer;
    var src = viewerSource();
    if (!src) return;
    if (v.origUrl || v.converting || v.convertError) return;   // 이미 준비/진행/실패
    var f = { file: src.file };
    if (!f.file) return;                                       // 이력 등 — 텍스트 폴백
    var type = String((src.name.split(".").pop() || "")).toUpperCase();
    if (type === "PDF") {                                       // 변환 불필요
      v.baseBlob = f.file;
      v.origUrl = URL.createObjectURL(f.file);
      return;
    }
    // docx·hwp·hwpx는 LibreOffice로 PDF로 변환해 뷰어에 띄운다(hwp/hwpx는 H2Orestart
    // 필터로 원본을 직접 변환 — 진짜 레이아웃). 그 밖은 텍스트 폴백.
    if (type !== "DOCX" && type !== "HWPX" && type !== "HWP") return;
    v.converting = true; render();
    var fd = new FormData();
    fd.append("file", f.file);
    fetch("api/render-pdf", { method: "POST", body: fd })
      .then(function (res) {
        if (!res.ok) {
          return res.text().then(function (b) {
            var d = b; try { d = JSON.parse(b).detail || b; } catch (e) { /* 평문 */ }
            throw new Error(String(d).slice(0, 160));
          });
        }
        return res.blob();
      })
      .then(function (blob) {
        state.viewer.baseBlob = blob;
        state.viewer.origUrl = URL.createObjectURL(blob);
        state.viewer.converting = false;
        render();   // baseBlob 이 새 blob이라 syncViewer 가 자동으로 다시 연다
      })
      .catch(function (e) {
        state.viewer.converting = false;
        state.viewer.convertError = "원본을 PDF로 준비하지 못했습니다: " + e.message;
        render();
      });
  }

  // 결과 화면의 마운트에 pdf.js 뷰어를 세운다. 문서가 바뀔 때만 다시 연다(viewerFor
  // 위 선언 참고) — 전체 렌더마다 열면 읽던 자리가 날아간다. render() 끝에서 부른다.
  // 뷰어에 칠할 것. **탭에 따라 다르다.**
  //
  // `반영 확인` 탭은 지난 지적을 다루는 자리다. 거기서 이번 검토 지적을 통째로
  // 칠하면 무엇이 지난 지적이고 무엇이 새 것인지 문서 위에서 안 갈린다. 그래서
  // 지난 지적 중 **아직 미반영으로 둔 것**만 칠한다 — 검토자가 판정을 바꾸면
  // 칠이 따라 바뀐다. "판정을 바꾸면 뭐가 달라지나"에 대한 답이 이것이다.
  //
  // `안 보임` 은 이번 문서에 짝이 없어 칠할 자리도 없다(matchId 가 빈다).
  function markItems() {
    var all = state.markItems || [];
    if (_views.reviewTabNow() !== "lineage") return all;
    var keep = _views.lineageMarkIds();
    if (!keep) return all;
    // 색도 바꾼다. 이 탭에서 칠해진 것은 전부 "지난 지적인데 아직 미반영" 하나라
    // 심각도로 갈라 칠하면 두 탭이 같은 것을 말하는 것처럼 보인다.
    return all.filter(function (it) { return keep[it.id]; })
      .map(function (it) {
        return { id: it.id, no: it.no, marks: it.marks, message: it.message,
                 sev: "past" };
      });
  }

  // 판정을 바꾸면 달라지는 것은 셈 두 군데다 — 반영 확인 요약 줄과 탭 이름.
  // 통째로 다시 그리지 않고 글자만 갈아끼운다(뷰어를 안 건드리려고).
  // 반영 확인 패널만 다시 그린다. 통째로 render() 하면 pdf-mount 가 새로 만들어져
  // 뷰어가 PDF 를 다시 연다(syncViewer).
  function repaintLineagePanel() {
    var el = document.getElementById("lineagePanel");
    if (!el) return;
    var html = _views.lineagePanelHtml();
    if (html) el.outerHTML = html;
  }

  function repaintLineageCounts() {
    var L = _views.lineageView();
    if (!L) return;
    var sum = document.getElementById("lineageSummary");
    if (sum) sum.textContent = _views.lineageSummaryText(L);
    var tab = document.getElementById("tab-lineage");
    if (tab) tab.textContent = _views.lineageTabLabel(L);
  }

  function paintMarks() {
    if (!state.markItems || !window.DR.pdfview.isOpen()) return;
    window.DR.pdfview.setMarks(markItems(), function (id) {
      if (state.markSingle) actions.select(id);                // 형광펜 → 카드
    });
  }

  // 보고 있는 쪽·배율을 도구줄에 적는다. render 를 안 부른다 — 스크롤마다 통째로
  // 그리면 화면이 쉼 없이 흔들린다. 글자 하나만 갈아끼운다.
  // 내보내기 메뉴만 닫는다. render() 를 부르면 화면 전체가 다시 그려져 검토 결과
  // 패널까지 새로 그린다 — 내려받기 한 번에 화면이 새로고침된 것처럼 보였다.
  // 닫을 것은 팝오버 하나뿐이라 그 노드만 지운다(repaintCard 와 같은 방식).
  // 홈이 "무엇으로 재나"를 말하려면 진짜 기준이 있어야 한다. 서버 설정 세 줄로는
  // 못 한다 — 검토를 이끄는 것은 presets/criteria 의 공통·팀 기준이다.
  // 한 번만 읽고 팀이 바뀌면 다시 읽는다.
  function loadHomeCriteria() {
    if (!servedOverHttp()) return;
    var team = (state.user && state.user.team) || "";
    if (state.homeCriteria && state.homeCriteria.team === team) return;
    fetchCriteriaLayers(team)
      .then(function (b) {
        state.homeCriteria = { team: team, layers: b.layers || [] };
        render();
      })
      .catch(function () { /* 못 읽으면 홈이 안내 문구를 대신 낸다 */ });
  }

  function closeExportMenu() {
    state.exportMenuOpen = false;
    var menu = document.getElementById("exportMenu");
    if (menu) menu.remove();
  }

  function paintWhere(at) {
    var el = document.getElementById("pdf-where");
    if (!el) return;
    at = at || window.DR.pdfview.viewState();
    el.textContent = at ? at.page + " / " + at.pages + "쪽 · " + at.pct + "%" : "";
  }

  function syncViewer() {
    var mount = document.getElementById("pdf-mount");
    if (!mount) {                                  // 뷰어 화면이 아니거나 텍스트 폴백
      if (window.DR.pdfview.isOpen()) { window.DR.pdfview.close(); viewerFor = null; }
      return;
    }
    var blob = state.viewer.baseBlob;              // maybeConvert 가 채운다(원본/변환본)
    if (!blob) return;
    if (viewerFor === blob && mount.firstChild) return;   // 같은 문서 — 다시 안 연다
    viewerFor = blob;
    state.marks = null;
    mount.innerHTML = "";
    // 보고 있는 쪽·배율을 도구줄에 적는다. render 를 안 부른다 — 스크롤마다
    // 통째로 그리면 화면이 쉼 없이 흔들린다. 글자 하나만 갈아끼운다.
    window.DR.pdfview.onViewChange(paintWhere);
    window.DR.pdfview.open(mount, blob, {
      onError: function (msg) { state.viewer.convertError = msg; render(); },
    }).then(function () { loadMarks(blob); });
  }

  // 지적 좌표를 받아 형광펜을 얹는다. 표시본을 굽는 것과 달리 PDF 를 만들지 않아
  // 훨씬 싸고, 화면은 원본을 그대로 그린다 — 요약 페이지 오프셋이 아예 없다.
  function loadMarks(blob) {
    var src = viewerSource() || { name: "document", findings: [], images: [], single: true };
    var name = (src.name || "document").replace(/\.[^.]+$/, "") + ".pdf";
    var fd = new FormData();
    fd.append("file", new File([blob], name, { type: "application/pdf" }));
    fd.append("findings", JSON.stringify(src.findings));
    // 그림 설명에서 나온 지적은 인용문으로 위치를 찾을 수 없다(그 설명은 PDF
    // 텍스트 레이어에 없다). 그림의 번호·크기를 함께 주면 서버가 그림 자체를 짚는다.
    fd.append("images", JSON.stringify(src.images));
    fetch("api/locate", { method: "POST", body: fd })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (body) {
        if (!body || state.viewer.baseBlob !== blob) return;   // 그새 문서가 바뀌었다
        state.marks = body;
        // 형광펜 클릭 팝업에 지적 문구를 띄우려면 좌표에 message 를 실어 보낸다
        // (locate 응답엔 좌표만 있다). id 로 findings 에서 가져온다.
        var byId = {};
        src.findings.forEach(function (f) { byId[f.id] = f; });
        var items = (body.items || []).map(function (it) {
          var f = byId[it.id] || {};
          return { id: it.id, no: it.no, sev: it.sev, marks: it.marks,
                   message: f.message || "" };
        });
        state.markItems = items;                   // 탭에 따라 걸러 칠한다
        state.markSingle = !!src.single;
        paintMarks();
        if (!src.single) {
          // 폴더 검토 카드의 번호 자리만 갱신한다. render()를 부르면 pdf-mount가
          // 교체되어 방금 연 PDF를 다시 읽으므로 문서 뷰어는 그대로 둔다.
          var byNo = {};
          (body.items || []).forEach(function (it) { byNo[it.id] = it.no || ""; });
          document.querySelectorAll("[data-case-number]").forEach(function (el) {
            var id = el.getAttribute("data-case-number") || "";
            el.innerHTML = numberChip(byNo[id] || "", null, id, true);
          });

          // 특정 카드에서 들어왔더라도 문서의 모든 지적은 함께 칠하고, 처음 위치만
          // 그 카드로 잡는다. 전체 하이라이트와 클릭 의도를 동시에 보존한다.
          var focus = state.kase.view && state.kase.view.focus;
          var target = (body.items || []).filter(function (it) { return it.id === focus; })[0];
          if (target && target.marks && target.marks.length) {
            window.DR.pdfview.highlight(focus);
            window.DR.pdfview.goTo(target.marks[0].page, target.marks[0].rect);
          }
        }
        // 반영 확인 카드의 형광펜 번호도 방금 받은 좌표에서 온다. 이 패널은
        // 지적 카드가 아니라 repaintCard 가 못 닿는다 — 안 그리면 번호가
        // 영영 안 붙는다(좌표는 검토가 끝난 뒤에 온다).
        repaintLineagePanel();
        // 카드 번호도 방금 받은 좌표에서 온다. render() 는 뷰어를 리로드하므로,
        // 뷰어는 놔두고 카드만 다시 그려 번호를 띄운다. (이걸 안 하면 좌표가
        // 늦게 도착해도 카드가 안 갱신돼, 카드를 눌러야 그제서야 번호가 떴다.)
        // 카드 번호 갱신은 단일 검토 화면의 것이다(의뢰 건은 카드 구조가 다르다).
        if (src.single) {
          repaintCard.apply(null, src.findings.map(function (f) { return f.id; }));
        }
      })
      .catch(function () { /* 좌표를 못 받으면 형광펜 없이 문서만 보인다 */ });
  }

  // 지적 카드 몇 개만 다시 그린다. 전체 렌더는 PDF iframe을 재부착해 뷰어를
  // 새로고침시키므로(makePdfFrame 위 주석 참고), 카드만 바뀌는 상호작용은
  // 여기를 쓴다. 인자로 준 id 중 실제로 화면에 있는 것만 손댄다.
  function repaintCard() {
    var ids = Array.prototype.slice.call(arguments).filter(Boolean);
    if (!ids.length) return;
    var v = renderVals();
    var byId = {};
    (v.tableFindings || []).forEach(function (f) { byId[f.id] = f; });
    ids.forEach(function (fid) {
      var el = document.querySelector('[data-card="' + fid + '"]');
      var f = byId[fid];
      if (!el || !f) return;
      // 모양은 .fcard 규칙이 갖는다. 클래스만 바꾸면 hover 도 그대로 산다.
      el.className = findingCardClass(f);
      el.innerHTML = findingCardInner(f, v);
    });
  }

  // 진행 화면에서 step 이벤트마다 레인·퍼센트·경과만 부분 갱신한다. 전체 render를
  // 부르면 '검토 취소' 버튼 DOM이 step마다 재생성돼 hover(:hover)가 깜빡인다 —
  // 여기선 버튼을 안 건드리고 id로 감싼 조각들 안쪽만 갈아끼운다. 진행 화면이
  // 아니거나 조각 컨테이너가 없으면 false 를 돌려 호출측이 전체 render로 폴백한다.
  function repaintProgress() {
    if (state.mode !== "single" || state.screen !== "progress") return false;
    var host = document.getElementById("pg-lanes");
    if (!host) return false;
    var v = renderVals();
    var f = _views.progressFragments(v);
    var set = function (id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; };
    // 레인은 통째로 다시 그리지 않는다 — 그러면 바의 shimmer(흰빛)가 step 마다
    // 처음으로 튀고 width 트랜지션도 안 먹는다. 폭·카운터만 제자리로 고친다.
    // 상태(대기/진행/완료)가 바뀌었거나 레인 구성이 달라졌을 때만 통째로 그린다.
    if (!updateLanesInPlace(host, v.review.lanes)) set("pg-lanes", f.lanes);
    set("pg-note", f.note);
    set("pg-pct", f.pct);
    set("pg-elapsed", f.elapsed);
    return true;
  }

  // 산출물 세트 진행 화면의 타임라인만 갈아끼운다. 전체 render 를 하면 취소
  // 버튼이 재생성돼 hover 가 풀리고 유리 패널이 매 단계마다 다시 그려진다.
  // 화면 마크업은 views.js 한 곳에서만 만든다 — api.js 가 따로 지어내면 갈린다.
  function repaintCaseStages() {
    if (state.mode !== "case" || state.kase.step !== "progress") return false;
    var box = document.getElementById("kase-stages");
    if (!box) return false;
    box.innerHTML = _views.caseStageList(state.kase);
    return true;
  }

  // 이미 그려진 레인들의 폭·카운터만 고친다. DOM 을 새로 만들지 않아 shimmer 가
  // 끊기지 않고 width 가 부드럽게 는다. 상태 전환·구성 변경이면 false → 통째로.
  function updateLanesInPlace(host, lanes) {
    var wraps = host.querySelectorAll("[data-lane-idx]");
    if (wraps.length !== lanes.length) return false;
    for (var i = 0; i < lanes.length; i++) {
      var w = wraps[i];
      var m = _views.laneMetrics(lanes[i]);
      // 상태가 바뀌면 색·shimmer·완료표시가 통째로 달라진다. 예전엔 여기서 false 를
      // 돌려 **모든** 레인을 다시 만들었는데, 그러면 한 레인이 끝날 때마다 아직
      // 도는 다른 레인들의 shimmer 가 전부 처음으로 튀어 흰빛이 한꺼번에 번쩍였다
      // (바로 위 주석이 막으려던 그 현상을, 상태가 바뀔 때마다 스스로 냈다).
      // 바뀐 레인 **하나의 알맹이만** 갈면 나머지는 안 끊긴다.
      //
      // 겉 wrapper 는 살려둔다 — 노드가 살아 있어야 opacity(.5→1) 전환이 실제로
      // 돌고, 완료 표시는 방금 바뀐 그 레인에서만 popIn 으로 튀어나온다.
      var before = w.getAttribute("data-lane-status");
      // 마지막 수치가 들어오는 순간 run→done 으로 노드를 바로 갈면, 살아 있던
      // progress fill 의 transform 전환도 함께 버려져 마지막 몇 %가 순간이동한다.
      // 먼저 기존 바를 100%까지 채운 뒤 회색 바·체크로 교체한다. finishing 표식은
      // 그 사이 done 이벤트나 경과 타이머가 같은 노드를 다시 가는 것을 막는다.
      if (before === "run" && m.status === "done") {
        w.setAttribute("data-lane-status", "finishing");
        var lastFill = w.querySelector("[data-lane-fill]");
        if (lastFill) lastFill.style.transform = "scaleX(1)";
        (function (wrapper, lane) {
          setTimeout(function () {
            if (!wrapper.isConnected || wrapper.getAttribute("data-lane-status") !== "finishing") return;
            wrapper.setAttribute("data-lane-status", "done");
            wrapper.style.opacity = "1";
            wrapper.innerHTML = _views.laneInner(lane, true);
          }, 300);
        })(w, lanes[i]);
        continue;
      }
      if (before === "finishing" && m.status === "done") continue;
      if (before !== m.status) {
        w.setAttribute("data-lane-status", m.status);
        w.style.opacity = m.status === "wait" ? ".5" : "1";
        w.innerHTML = _views.laneInner(lanes[i], true);
        continue;
      }
      var fill = w.querySelector("[data-lane-fill]");
      if (fill) fill.style.transform = "scaleX(" + (m.pct / 100) + ")";
      var ctr = w.querySelector("[data-lane-counter]");
      if (ctr) ctr.textContent = m.counter;
    }
    return true;
  }

  // 움직임을 줄여 달라고 했는지. CSS 는 @media 로 알아서 따르지만, JS 가 직접
  // 움직이는 것(스크롤)은 물어봐야 안다.
  function reduceMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // 로그인 히어로만 포인터에 아주 작게 반응한다. 장식용 원근은 드문 브랜드
  // 접점에만 두고, 업무 화면에는 옮기지 않는다. requestAnimationFrame 한 번에
  // transform 하나만 써서 pointermove가 레이아웃을 다시 계산하지 않게 한다.
  function wireHeroParallax() {
    var scene = document.querySelector("[data-hero-scene]");
    if (!scene || reduceMotion() || !window.matchMedia ||
        !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    var frame = 0;
    scene.addEventListener("pointermove", function (e) {
      var rect = scene.getBoundingClientRect();
      var rx = ((e.clientY - rect.top) / rect.height - .5) * -4;
      var ry = ((e.clientX - rect.left) / rect.width - .5) * 4;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () {
        scene.style.transition = "none";
        scene.style.transform = "rotateX(" + rx.toFixed(2) + "deg) rotateY(" + ry.toFixed(2) + "deg)";
        frame = 0;
      });
    });
    scene.addEventListener("pointerleave", function () {
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      scene.style.transition = "transform .3s var(--ease-out)";
      scene.style.transform = "rotateX(0deg) rotateY(0deg)";
    });
  }

  // ---- render + wiring ----------------------------------------------------
  var root;
  function render() {
    // 한글 등 IME 조합 중엔 render를 통째로 건너뛴다 — 위 reasonComposing
    // 선언부 주석 참고(조합 중인 글자는 캡처해서 복원할 방법이 없는 유일한
    // 경우다). 조합이 끝나면(compositionend) 또는 watchdog이 강제로 풀면
    // flushReasonRender가 몰아서 그린다.
    if (reasonComposing) { reasonRenderPending = true; return; }
    // 실제로 그렸으면 밀린 렌더는 해소된 것이다. 이 줄이 없으면 click 끝에서
    // 한 번 더 그리게 된다(해롭진 않지만 뷰어 iframe이 다시 로드된다).
    reasonRenderPending = false;

    // 체크리스트 "이유" 입력에 포커스가 있으면 캡처 후 복원한다 — 위
    // reasonComposing 주석 참고(포커스만으로는 더 이상 렌더를 건너뛰지
    // 않는다: 건너뛰면 다른 버튼 클릭이 focusout에 가려 씹힌다).
    var reasonFocused = document.activeElement;
    var reasonKey = null, reasonSelStart = null, reasonSelEnd = null;
    if (reasonFocused && reasonFocused.getAttribute && reasonFocused.getAttribute("data-reason") != null) {
      reasonKey = reasonFocused.getAttribute("data-reason");
      try { reasonSelStart = reasonFocused.selectionStart; reasonSelEnd = reasonFocused.selectionEnd; }
      catch (e) { /* 일부 입력 타입은 selection 속성을 지원하지 않는다 */ }
    }

    // innerHTML로 통째로 다시 그리므로 스크롤 위치가 날아간다 — 안 그러면 심각도
    // 칩 하나만 눌러도 화면이 맨 위로 튕긴다. data-scroll 표식을 단 컨테이너의
    // 위치를 키별로 기억했다가 되살린다.
    //
    // 예전에는 id 두 개(main-scroll·doc-scroll)만 되살렸다. 그런데 업로드·비교
    // 설정 화면은 그 안에 자기 스크롤러를 하나 더 두고 있어(height:100% +
    // overflow:auto) 실제로 스크롤되는 건 그쪽이었고, 표식이 없어 복원에서
    // 빠졌다 — 체크리스트를 고를 때마다 화면이 맨 위로 올라간 이유다.
    var tops = {};
    Array.prototype.forEach.call(document.querySelectorAll("[data-scroll]"), function (el) {
      tops[el.getAttribute("data-scroll")] = el.scrollTop;
    });

    // **자리는 새로 그리고, 살아 있는 뷰어 알맹이만 옮겨 붙인다.**
    //
    // innerHTML 을 갈면 `#pdf-mount` 가 새 빈 노드가 되고, syncViewer 가 빈 자리를
    // 보고 PDF 를 처음부터 다시 읽는다 — 읽던 자리가 날아가고 깜빡인다. 내보내기
    // 메뉴를 열거나 닫기만 해도 그랬다(toggleExportMenu·exportAs 가 render 를 부른다).
    //
    // 옛 mount 노드를 통째로 새 자리에 바꿔치기하면 안 된다. 그 노드가 들고 있던
    // 크기 규칙이 새 화면과 어긋난다(단일 검토는 `flex:1;overflow:hidden`, 폴더
    // 검토는 `flex:1;min-height:0`). style 을 덮어써 맞춰 봤더니 이번엔 **빈 화면**이
    // 났다.
    //
    // pdfview 는 mount 안에 제 host 를 만들어 넣는다(pdfview.open). 그 host 만 새
    // mount 로 옮기면 캔버스·스크롤 위치·리스너가 그대로 살고, 자리는 새로 그린
    // 것이 쓰인다.
    var oldMount = document.getElementById("pdf-mount");
    var keptHost = oldMount && oldMount.firstChild;
    // 노드를 DOM 에서 떼면 스크롤 위치가 0 으로 초기화된다 — 옮겨 붙인 뒤 되돌려
    // 놓지 않으면 내려받기 한 번에 문서가 맨 위로 튄다. data-scroll 복원과 같은
    // 이유인데, 뷰어의 스크롤 상자는 pdfview 가 만든 것이라 그 표식이 없다.
    var keptTop = keptHost ? keptHost.scrollTop : 0;

    root.innerHTML = view(renderVals());
    wireHeroParallax();

    if (keptHost) {
      var viewerSlot = document.getElementById("pdf-mount");
      // 새 화면에 뷰어 자리가 없으면 안 옮긴다 — syncViewer 가 닫는다.
      if (viewerSlot) {
        viewerSlot.appendChild(keptHost);
        keptHost.scrollTop = keptTop;   // 읽던 자리로 되돌린다
        paintWhere();          // 도구줄이 새로 그려졌다 — 값을 되살린다
      }
    }

    Array.prototype.forEach.call(document.querySelectorAll("[data-scroll]"), function (el) {
      var t = tops[el.getAttribute("data-scroll")];
      if (t) el.scrollTop = t;
    });

    // 위에서 캡처해둔 "이유" 입력 포커스·커서를 새 DOM에 되살린다. data-scroll
    // 복원과 같은 자리, 같은 이유(innerHTML 교체가 그 사이 값을 다 지운다)다.
    if (reasonKey != null) {
      var reasonRestored = document.querySelector('[data-reason="' + reasonKey + '"]');
      if (reasonRestored) {
        reasonRestored.focus();
        if (reasonSelStart != null && reasonSelEnd != null) {
          try { reasonRestored.setSelectionRange(reasonSelStart, reasonSelEnd); }
          catch (e) { /* 무시 — 포커스만 되살아나도 충분하다 */ }
        }
      }
    }

    // 검색창은 열리자마자 칠 수 있어야 한다. <input autofocus> 는 문서를 파싱할
    // 때만 먹고 innerHTML 로 꽂은 노드에는 안 먹으므로 직접 준다. 이미 그 칸에
    // 있으면 건드리지 않는다 — 다시 focus 하면 캐럿이 끝으로 튄다.
    if (state.searchOpen) {
      var qbox = document.querySelector("[data-search-q]");
      if (qbox && document.activeElement !== qbox) qbox.focus();
    }

    // 지적을 새로 고른 렌더에서만 그 절로 옮긴다. 매 렌더마다 옮기면 사용자가
    // 문서를 훑는 동안 화면이 계속 튄다.
    if (state.selected !== lastScrolled) {
      lastScrolled = state.selected;
      var target = state.selected && document.getElementById("sec-" + selectedSection());
      // 순간이동하면 검토자는 자기가 어디서 어디로 왔는지 잃는다 — 지적과 문서를
      // 잇는 게 이 화면의 일인데, 문서가 툭 갈리면 그 연결이 안 보인다.
      //
      // index.html 의 prefers-reduced-motion 규칙(scroll-behavior:auto)은 여기
      // 안 먹는다: JS 가 behavior 를 명시하면 그쪽이 CSS 를 이긴다. 직접 묻는다.
      if (target) target.scrollIntoView({ block: "center", behavior: reduceMotion() ? "auto" : "smooth" });
    }
    // Landing scrolls naturally; the app is a fixed zoom-fit artboard.
    var home = state.mode === "home";
    document.documentElement.style.overflow = home ? "auto" : "hidden";
    document.body.style.overflow = home ? "auto" : "hidden";
    maybeConvert();
    syncViewer();
    fitViewport();
  }

  // 위 render()가 조합 중이라 건너뛴 게 있으면 여기서 몰아서 그린다.
  // compositionend(정상 종료)와 조합 watchdog(비정상 미종료 대비)만 부른다 —
  // focusout에서는 절대 부르지 않는다(위 reasonComposing 선언부 주석 참고:
  // 다른 컨트롤 클릭이 focusout 뒤에 오므로, 거기서 렌더하면 그 클릭이 씹힌다).
  //
  // **compositionend도 blur의 부산물로 온다.** 조합 중(한글을 치던 중)에 저장·
  // CSV 같은 다른 버튼을 누르면 브라우저는 blur 전에 조합을 끝내야 하므로
  // mousedown 시점에 compositionend가 먼저 발생한다. 여기서 곧바로 그려버리면
  // click이 델리게이션에 닿기 전에 원래 노드가 사라져 — focusout에서 그리던
  // 옛 버그와 똑같이 — 버튼이 조용히 안 눌린다. 한글 입력에서는 조합 중이
  // 오히려 기본 상태라 자주 난다.
  //
  // 그래서 조합하던 입력이 이미 포커스를 잃었으면 그리지 않고 표시만 남긴다.
  // 밀린 렌더는 뒤이어 오는 click이 델리게이션을 다 거친 뒤에 흘려보낸다
  // (아래 click 리스너 끝). 타이머로 미루지 않는 이유: 마우스를 오래 누르고
  // 있으면 타이머가 click보다 먼저 발화해 같은 버그가 그대로 재발한다.
  function flushReasonRender() {
    if (!reasonRenderPending) return;
    var el = document.activeElement;
    if (el && el.getAttribute && el.getAttribute("data-reason") != null) {
      render();                 // 여전히 그 입력에 있다 = 정상적인 조합 종료
      return;
    }
    // 포커스가 떠났다 — 지금 그리면 클릭이 씹힌다. click 쪽에 맡긴다.
  }

  // Scale the fixed 800px-tall artboard to fill the viewport height, and widen
  // it (flexible main column) to fill the width.
  function fitViewport() {
    if (!root) return;
    var app = root.querySelector(".dr-app");
    if (!app) return;
    var z = window.innerHeight / 800;
    z = Math.min(Math.max(z, 0.5), 2.4);
    app.style.zoom = String(z);
    app.style.width = (window.innerWidth / z) + "px";
  }

  // 커스텀 셀렉트(.sel)의 열림 상태는 state 가 아니라 DOM 클래스에 있다 —
  // 같은 화면의 폼 입력을 지우지 않으려면 다시 그리지 않아야 하기 때문이다.
  function closeSelects() {
    var open = document.querySelectorAll(".sel.open");
    for (var i = 0; i < open.length; i++) {
      open[i].classList.remove("open");
      open[i].querySelector(".sel-btn").setAttribute("aria-expanded", "false");
    }
  }
  function selValue(id) {
    var el = document.getElementById(id);
    return el ? el.getAttribute("data-value") || "" : "";
  }

  function boot() {
    // Set Document Title
    document.title = "DocSuree | 문서 일관성 검토 Agent";
    
    // 파비콘/앱 아이콘은 index.html <head>에 정적 <link>로 선언되어 있다.

    root = document.getElementById("root");
    document.addEventListener("click", function (e) {
      var el = e.target.closest ? e.target.closest("[data-act]") : null;
      var act = el && el.getAttribute("data-act");

      // 열려 있는 팝오버는 바깥을 누르면 닫는다. 예전엔 항목을 고르거나 같은
      // 버튼을 다시 눌러야만 닫혀서, 다른 곳을 눌러도 계속 열린 채 남았다.
      // 그 팝오버 안의 항목을 누른 경우와, 자기 자신을 여닫는 버튼은 제외한다.
      var inMenu = e.target.closest && e.target.closest("#exportMenu");
      if (state.exportMenuOpen && !inMenu && act !== "toggleExportMenu") {
        // 팝오버 하나 닫자고 화면을 통째로 다시 그리지 않는다 — 뷰어까지 흔들린다.
        closeExportMenu();
      }
      // 헤더의 프로필·알림 팝오버도 같은 규칙이다. 예전엔 이 둘만 빠져 있어서,
      // 열어두고 화면 아무 데나 눌러도 계속 떠 있었다(같은 버튼을 다시 누르는
      // 것이 닫는 유일한 길이었다). 메뉴 안의 항목은 자기 액션이 닫는다.
      var inProfile = e.target.closest && e.target.closest("#profileMenu");
      if (state.profileMenuOpen && !inProfile && act !== "toggleProfile") {
        state.profileMenuOpen = false;
        if (!act) render();
      }
      var inNoti = e.target.closest && e.target.closest("#notiMenu");
      if (state.notiOpen && !inNoti && act !== "toggleNoti") {
        state.notiOpen = false;
        if (!act) render();
      }

      // 펼친 셀렉트도 마찬가지 — 자기 자신을 여닫는 버튼과 목록 항목만 빼고
      // 어디를 누르든 닫는다. 다시 그리지 않으므로 클래스만 걷어낸다.
      if (act !== "selToggle" && act !== "selPick") closeSelects();

      // <select data-act>는 클릭이 아니라 change 로 다룬다. 여기서 잡으면
      // 사용자가 고르기도 전에 액션이 돌고 render 가 드롭다운을 닫아버린다.
      if (el && el.tagName !== "SELECT") {
        var arg = el.getAttribute("data-arg");
        if (actions[act]) actions[act](arg);
      }

      // 조합 중에 뭔가를 누르느라 미뤄둔 렌더가 있으면 여기서 흘려보낸다.
      // 이 자리여야 안전하다 — 델리게이션이 data-act를 이미 찾아 액션까지
      // 돌린 뒤라, 지금 노드를 갈아엎어도 씹힐 클릭이 없다
      // (flushReasonRender 주석 참고). 액션이 스스로 그렸으면 render()가
      // 표시를 지웠으므로 여기서는 아무 일도 일어나지 않는다.
      //
      // data-act가 없는 빈 자리를 눌렀을 때도 지나가야 한다. 예전엔 위에서
      // early return 했는데, 조합 중에 빈 공간을 누르면 조합만 끝나고 밀린
      // 렌더는 아무도 흘려보내지 않아 화면이 낡은 채 남았다.
      if (reasonRenderPending) { reasonRenderPending = false; render(); }
    });
    document.addEventListener("change", function (e) {
      var el = e.target;
      if (!el || el.type !== "file") return;
      var file = el.files && el.files[0];
      if (!file) return;
      if (!el.getAttribute("data-slot")) return;
      handleFile(el.getAttribute("data-slot"), el.getAttribute("data-nav"), file);
    });
    // 케이스 인식 화면의 "미분류 → 산출물 지정" 드롭다운.
    document.addEventListener("change", function (e) {
      var el = e.target;
      if (!el || el.tagName !== "SELECT") return;
      if (el.getAttribute("data-act") !== "assignOutput") return;
      actions.assignOutput(el.getAttribute("data-arg"), el.value);
    });
    // 체크리스트 파일 선택. 기존 슬롯(single/compareA/compareB)과 통로가 달라
    // 따로 잡는다 — 이건 검토할 문서가 아니라 검토 기준이다.
    document.addEventListener("change", function (e) {
      if (e.target && e.target.id === "file-checklist") {
        var f = e.target.files && e.target.files[0];
        e.target.value = "";          // 같은 파일을 다시 골라도 change 가 오게
        if (f) actions.previewChecklist(f);
      }
    });
    // 체크리스트 항목의 "이유" 입력. render()를 부르지 않는 setReason과 짝을
    // 이룬다 — 여기서 render를 부르면 입력 중 포커스를 잃는다.
    document.addEventListener("input", function (e) {
      var el = e.target.closest ? e.target.closest("[data-reason]") : null;
      if (el) actions.setReason(el.getAttribute("data-reason"), el.value);
    });
    // 독립 체크리스트 화면의 "검토 대상 문서명" 입력. data-reason과 같은 이유로
    // render()를 부르지 않는다 — 여기서 그리면 입력 중 포커스를 잃는다.
    document.addEventListener("input", function (e) {
      var el = e.target.closest ? e.target.closest("[data-checklist-doc]") : null;
      if (el) state.crun.documentName = el.value;
    });
    // 폴더 검토의 외부 원천값. 타이핑마다 render하면 포커스가 끊기므로 state만
    // 갱신한다. 확정 버튼을 누를 때 이 값을 서버가 저장된 문서 필드와 대조한다.
    document.addEventListener("input", function (e) {
      var el = e.target.closest ? e.target.closest("[data-manual-input]") : null;
      if (el) actions.setManualInput(el.getAttribute("data-manual-input"), el.value);
    });
    document.addEventListener("change", function (e) {
      var el = e.target.closest ? e.target.closest("[data-manual-input]") : null;
      if (el) render();
    });
    // 검색어. 위 둘과 달리 **화면이 바뀌어야 한다**(결과 목록). 그렇다고 render()를
    // 부르면 <input> 이 통째로 새로 만들어져 포커스도 캐럿도 조합 중인 한글도
    // 날아간다 — 그래서 결과 목록 노드 하나만 갈아끼운다. 입력 요소는 안 건드리므로
    // IME 도 그대로다(data-reason 이 compositionstart 감시까지 해야 했던 것과
    // 대조적이다 — 저쪽은 render 가 입력을 지웠기 때문이다).
    document.addEventListener("input", function (e) {
      var el = e.target.closest ? e.target.closest("[data-search-q]") : null;
      if (!el) return;
      state.searchQ = el.value;
      var box = document.getElementById("searchResults");
      if (box) box.innerHTML = _views.searchResultsHtml();
    });
    // 위 render()의 reasonComposing 가드와 짝이다. 조합 중엔 render를
    // 건너뛰고 몰아 둔다(위 reasonComposing 선언부 주석 참고 — 조합 중인
    // 글자는 캡처해서 복원할 방법이 없는 유일한 경우다). compositionend가
    // 정상적으로 오면 그 즉시 밀린 렌더를 흘려보낸다.
    //
    // watchdog: 일부 브라우저/IME 조합은 compositionend를 아예 안 보내는
    // known issue가 있다 — 그대로 두면 reasonComposing이 영원히 true로 남아
    // render()가 앱 전체에서 사실상 멈춘다(새로고침밖에 방법이 없다). 그래서
    // 조합 시작 후 일정 시간이 지나도 종료 신호가 없으면 강제로 풀고 밀린
    // 렌더를 흘려보낸다. 값은 넉넉히 잡는다 — 실제 조합은 보통 수백 ms 안에
    // 끝나므로, 이 타이머가 발동하는 건 사실상 비정상 상황뿐이다.
    var REASON_COMPOSE_WATCHDOG_MS = 4000;
    document.addEventListener("compositionstart", function (e) {
      if (!(e.target && e.target.closest && e.target.closest("[data-reason]"))) return;
      reasonComposing = true;
      if (reasonComposeWatchdog) clearTimeout(reasonComposeWatchdog);
      reasonComposeWatchdog = setTimeout(function () {
        reasonComposeWatchdog = null;
        reasonComposing = false;
        flushReasonRender();
      }, REASON_COMPOSE_WATCHDOG_MS);
    });
    document.addEventListener("compositionend", function (e) {
      if (!(e.target && e.target.closest && e.target.closest("[data-reason]"))) return;
      if (reasonComposeWatchdog) { clearTimeout(reasonComposeWatchdog); reasonComposeWatchdog = null; }
      reasonComposing = false;
      flushReasonRender();
    });
    // focusout에는 아무것도 걸지 않는다 — 위 reasonComposing 선언부 주석
    // 참고: 다른 버튼을 누르면 그 click보다 먼저 focusout이 발생하므로,
    // 여기서 render를 흘려보내면 방금 누른 버튼의 DOM 노드가 클릭이
    // 델리게이션에 닿기도 전에 사라져 클릭이 조용히 씹힌다.
    // 드롭은 네모 안에 정확히 놓지 않아도 받는다. **화면에 드롭존이 하나뿐이면**
    // 어디에 놓아도 그 하나로 보낸다 — 갈 곳이 하나인데 조준을 요구할 이유가 없다
    // (단일 검토·폴더 검토가 그렇다). 비교 검토는 A·B 둘이라 어디에 놓았는지가
    // 곧 어느 쪽인지이므로 넓히지 않는다 — 넓히면 우리가 찍어서 배정하게 된다.
    function soleZone(sel) {
      var all = document.querySelectorAll(sel);
      return all.length === 1 ? all[0] : null;
    }
    function zoneOf(e) {
      return (e.target && e.target.closest ? e.target.closest("[data-drop]") : null) ||
        soleZone("[data-drop]");
    }
    // 빗나간 드롭을 삼킨다. 안 그러면 브라우저가 그 파일로 페이지를 이동해
    // 지금까지 올려둔 것이 통째로 날아간다 — 비교 검토에서 A를 올려두고 B를
    // 빗맞히면 A까지 잃는다. 드롭존이 있는 화면에서만 건다.
    function hasZone() { return !!document.querySelector("[data-drop],[data-casedrop]"); }
    document.addEventListener("dragover", function (e) { if (hasZone()) e.preventDefault(); });
    document.addEventListener("drop", function (e) { if (hasZone()) e.preventDefault(); });
    document.addEventListener("dragover", function (e) { var z = zoneOf(e); if (z) { e.preventDefault(); z.style.filter = "brightness(.96)"; } });
    // dragleave 는 자식 요소를 지날 때마다 뜬다. 화면 전체가 드롭 대상이 된
    // 뒤로는 그때마다 강조를 껐다 켜면 끄는 쪽이 눈에 남는다 — 창 밖으로
    // 나간 것(relatedTarget 없음)만 원상복구한다. 드롭했을 때는 drop 이 지운다.
    document.addEventListener("dragleave", function (e) {
      if (e.relatedTarget) return;
      var z = zoneOf(e); if (z) z.style.filter = "";
    });
    function caseZoneOf(e) {
      return (e.target && e.target.closest ? e.target.closest("[data-casedrop]") : null) ||
        soleZone("[data-casedrop]");
    }
    document.addEventListener("dragover", function (e) {
      // 끌어다 놓는 중의 강조도 점선 카드 hover와 같은 브랜드 상태면으로 쓴다.
      // 선택 상태용 --accent-weak보다 옅어, 아직 드롭하지 않은 상태와 구별된다.
      var z = caseZoneOf(e); if (z) { e.preventDefault(); z.style.background = "var(--state-hover-brand)"; }
    });
    document.addEventListener("dragleave", function (e) {
      if (e.relatedTarget) return;      // 위 dragleave 주석 참고 — 창 밖만
      var z = caseZoneOf(e); if (z) z.style.background = "";
    });
    document.addEventListener("drop", function (e) {
      var kz = caseZoneOf(e); if (!kz) return;
      e.preventDefault(); kz.style.background = "";
      var dt = e.dataTransfer;
      // 폴더는 dataTransfer.files 에 이름만 담겨 온다 — webkitGetAsEntry 로
      // 내려가야 안이 나온다. 브라우저가 그걸 안 주면 파일만이라도 받는다.
      //
      // dt 는 핸들러가 끝나면 비워지므로 fallback 을 **여기서** 떠 둔다.
      // 메서드가 있는지만 보고 들어왔다가 그게 null 만 돌려주면(합성 드롭·
      // 일부 브라우저) 0건으로 조용히 끝나, 사용자는 드롭이 씹힌 줄도 모른다.
      var fallback = dt && dt.files ? Array.prototype.slice.call(dt.files) : [];
      if (dt && dt.items && dt.items.length && dt.items[0].webkitGetAsEntry) {
        collectDropped(dt.items, function (files) {
          actions.addCaseFiles(files.length ? files : fallback);
        });
      } else if (fallback.length) {
        actions.addCaseFiles(fallback);
      }
    }, true);
    document.addEventListener("drop", function (e) {
      var z = zoneOf(e); if (!z) return;
      if (caseZoneOf(e)) return;          // 케이스 드롭존은 위에서 처리했다
      e.preventDefault(); z.style.filter = "";
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) handleFile(z.getAttribute("data-drop"), z.getAttribute("data-nav"), file);
    });
    // 전체화면은 헤더 버튼 말고 Esc로도 빠져나온다. 화면을 다 덮고 있어 다른
    // 곳을 눌러 나가는 길이 없으므로, 갇힌 느낌이 들지 않게 관례대로 받아둔다.
    // 검색창도 Esc 로 닫는다. 전체화면보다 먼저 본다 — 전체화면 위에서 검색을
    // 열었으면 Esc 한 번에 둘 다 닫히는 게 아니라 위엣것부터 닫혀야 한다.
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (state.rev.criteriaOpen) { actions.closeReviewCriteria(); return; }
      if (state.searchOpen) { actions.toggleSearch(); return; }
      if (state.viewerFull) actions.toggleViewerFull();
    });
    // 키보드 접근 — 지적 카드·탭·심각도 칩은 div/span 이라 클릭 위임만 받는다.
    // tabindex(views.js)로 포커스를 받은 요소의 Enter/Space 를 클릭으로 잇는다.
    // 네이티브 버튼·입력은 브라우저가 이미 하므로 건드리지 않는다(Space 스크롤도
    // 그쪽에선 preventDefault 하면 안 된다).
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var el = e.target;
      if (!el || !el.getAttribute || el.getAttribute("data-act") == null) return;
      var tag = el.tagName;
      if (tag === "BUTTON" || tag === "A" || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      e.preventDefault();
      el.click();
    });
    // 홈 타일 포인터 글로우 — 커서 자리를 CSS 변수로 넘기면 ::after 의
    // radial-gradient 가 그 자리를 밝힌다(index.html [data-glow]). 마우스가
    // 있는 환경에서만 건다 — 터치에는 커서가 없다. .dr-app 이 zoom 을 쓰므로
    // 화면 좌표를 요소의 CSS 좌표로 되돌릴 때 zoom 으로 나눈다.
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
      document.addEventListener("mousemove", function (e) {
        var t = e.target && e.target.closest ? e.target.closest("[data-glow]") : null;
        if (!t) return;
        var r = t.getBoundingClientRect();
        var z = t.currentCSSZoom || 1;
        t.style.setProperty("--mx", ((e.clientX - r.left) / z) + "px");
        t.style.setProperty("--my", ((e.clientY - r.top) / z) + "px");
      });
    }
    window.addEventListener("resize", fitViewport);
    // 테마는 index.html 의 <head> 스크립트가 첫 페인트 전에 이미 걸어놨다
    // (안 그러면 흰 화면이 번쩍인다). 여기선 그 값을 state 로 받아오기만 한다 —
    // 두 곳에서 각자 계산하면 설정 화면의 선택 표시가 실제 화면과 어긋난다.
    state.theme = document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark" : "light";
    loadServerConfig();
    loadHistory();
    (function waitData() {
      if (window.DOCREVIEW) render();
      else setTimeout(waitData, 60);
    })();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

// 홈 화면 — 검토자가 "어떻게 검토하고 무엇으로 재는지"를 알 수 있어야 한다.
// 실행: node --test web/tests/   (pytest 가 tests/test_frontend_js.py 로 감싼다)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function build(st) {
  const win = { DR: {}, location: { protocol: "http:", href: "http://x/" } };
  win.DR.ICONS = new Proxy({}, { get: () => "<svg/>" });
  win.DR.helpers = {
    esc: (s) => String(s == null ? "" : s), rgba: () => "", fmtSize: () => "1KB",
    download: () => {}, downloadBlob: () => {}, docSides: () => ({}),
    sentences: (s) => [String(s == null ? "" : s)],
  };
  new Function("window", fs.readFileSync(path.join(__dirname, "..", "views.js"), "utf8"))(win);
  const views = win.DR.views({
    state: st, props: { accent: "#356998" }, render: () => {},
    backend: { errorBanner: () => "", ago: () => "1분 전", fmtElapsed: () => "0:03" },
  });
  win.DOCREVIEW = {
    doc: { name: "문서.pdf", type: "PDF" }, sections: [], findings: [], stages: [],
    images: [], compare: { stages: [], findings: [], docA: {}, docB: {}, stats: {} },
    sevMeta: { major: { label: "치명", kr: "치명", order: 0 },
               minor: { label: "주의", kr: "주의", order: 1 },
               info: { label: "참고", kr: "참고", order: 2 } },
    typeMeta: { missing: { label: "누락" }, mismatch: { label: "불일치" },
                extra: { label: "초과" } },
  };
  global.window = win;
  return views;
}

function state(criteria) {
  return {
    mode: "home", screen: "upload", stageIndex: -1, done: false, reviewed: false,
    sevFilter: { major: true, minor: true, info: true },
    checkerFilter: "all", sort: "severity", exportMenuOpen: false,
    rev: { startedAt: 0, prepAt: 0, prep: {}, lanes: [], done: {}, note: "" },
    kase: { step: "upload", checked: {}, tab: "summary" },
    cstep: "setup", cstageIndex: -1, cdone: false,
    files: {}, annot: { busy: false, msg: "", numbers: {} },
    viewer: { baseBlob: null, mode: "orig", converting: false, convertError: null },
    marks: null, selected: null, theme: "light",
    user: { name: "김검토", team: "ai-test-cert-1" },
    server: { checklists: [], checklist: "", scope_label: "", llm_provider: "local",
              llm_model: "qwen", placeholder_markers: ["TBD"],
              teams: [{ id: "ai-test-cert-1", name: "AI시험인증1팀" }] },
    history: [], detect: null,
    crun: { checklist: null, results: {}, name: '', documentName: '' }, clib: { list: [] }, checklist: "",
    homeCriteria: criteria,
  };
}

// 기준 항목 n 건 중 auto 건이 저절로 돈다. `agent` 는 presets/criteria 가 들고
// 서버가 /api/criteria 로 그대로 내보내는 값이라, 여기서도 진짜 이름을 쓴다.
const items = (agent, n, auto) =>
  Array.from({ length: n }, (_, i) => ({
    agent, howChecked: i < auto ? "LLM · 자동" : "사람이 확인",
  }));

// 꼬리표 세 가지(전부 자동 · 일부만 자동 · 아무것도 자동 아님)가 다 나오게 짰다.
// 공통 7건(자동 4) · 팀 13건(자동 6) — 합 20건, 자동 10.
const LAYERS = [
  { scope: "공통", id: "common", name: "공통 기준",
    items: [...items("형식·완전성", 4, 4),      // 전부 자동
            ...items("정합성·추적성", 2, 0),    // 전부 사람
            ...items("표현·내용품질", 1, 0)] },
  { scope: "팀별", id: "ai-test-cert-1", name: "AI시험인증1팀",
    items: [...items("문서작성·생성", 6, 3),    // 일부만 자동
            ...items("표준·체크리스트", 3, 2),
            ...items("형식·완전성", 2, 1),
            ...items("검토의견·이력", 2, 0)] },
];

// 업로드 체크리스트까지 있는 경우. 걸리는 방식이 다른 셋을 다 담는다.
const LAYERS3 = [...LAYERS, {
  scope: "업로드", id: "up1", name: "SVVP 체크리스트", editable: true,
  items: [...items("표준·체크리스트", 5, 4), ...items("형식·완전성", 3, 2)],
}];

const home = (criteria) => {
  const views = build(state(criteria));
  return views.view(views.renderVals());
};

test("홈이 없는 기능을 약속하지 않는다", () => {
  // 심각도 패널이 "전체 점수에 반영됩니다"라고 했는데 점수는 **없앤 기능**이다
  // (CLAUDE.md 기능 방침). "4단계"라 적혔지만 실제로 그리는 것은 셋이었다.
  const html = home(null);
  assert.ok(!html.includes("전체 점수"), "없는 점수를 약속한다");
  assert.ok(!html.includes("4단계"), "심각도가 넷이라고 말한다");
  assert.ok(!html.includes("발견된 문제 심각도"), "지운 패널이 남아 있다");
});

test("홈이 검토 흐름을 보여준다", () => {
  const html = home(null);
  assert.match(html, /검토 방법/);
  for (const step of ["문서를 올린다", "글자를 읽는다", "기준으로 잰다", "지적을 짚는다"]) {
    assert.ok(html.includes(step), `흐름에 "${step}" 가 없다`);
  }
  assert.match(html, /class="flow-step flow-enter"[^>]*--flow-delay:/,
               "단계 사이 설명 모션이 진입 순서를 안 따른다");
  assert.match(html, /class="flow-figure-number">4</,
               "검토 방법의 편집형 단계 요약이 없다");
});

test("새 검토는 중복 범위 라벨이 없는 실제 버튼이다", () => {
  const html = home(null);
  assert.ok(!html.includes("빠른 시작"), "카드만으로 분명한 첫 줄에 중복 제목이 생겼다");
  for (const scope of ["한 문서", "두 문서", "한 폴더"]) {
    assert.ok(!html.includes(`<span class="qs-scope">${scope}</span>`),
              `제목을 반복하는 범위 라벨(${scope})이 남아 있다`);
  }
  assert.strictEqual((html.match(/<button type="button" class="tile act qs grow b2"/g) || []).length, 3,
                     "빠른 시작 카드가 키보드로 누를 수 있는 버튼이 아니다");
});

test("무엇으로 재는지를 진짜 기준으로 말한다", () => {
  // 예전에는 서버 설정 세 줄(`적용 중인 검토 기준`)을 보여줬는데, 검토를 이끄는
  // 것은 presets/criteria 의 공통·팀 기준이다.
  const html = home({ team: "ai-test-cert-1", layers: LAYERS });
  assert.ok(!html.includes("적용 중인 검토 기준"), "옛 패널이 남아 있다");
  assert.match(html, /<span class="tile-h">검토 기준<\/span>/, "기준 타일 제목이 없다");
  assert.ok(html.includes("공통 기준") && html.includes("AI시험인증1팀"),
            "어느 기준이 걸리는지 안 보여준다");
  assert.match(html, /class="tile crit[^>]*data-glow/,
               "기준을 돋보기처럼 훑는 포인터 빛이 사라졌다");
  assert.match(html, /class="crit-secret-mark"[^>]*aria-hidden="true"/,
               "포인터 빛으로 찾을 숨은 마크가 없다");
  assert.match(html, /crit-secret-mark[^]*mascot-investigator-192\.png/,
               "숨은그림에 알아볼 수 있는 전신 마스코트를 쓰지 않는다");
  assert.strictEqual((html.match(/class="crit-flow-pulse/g) || []).length, 3,
                     "세 기준에서 문서까지 흐르는 애니메이션 경로가 없다");

  // 기준은 **제 타일**을 갖고, 겹이 몇이든 타일은 하나다 — 이게 격자를 안
  // 흔드는 조건이다. 한때 겹마다 타일을 주는 안을 만들어 비교했는데, 업로드
  // 체크리스트마다 겹이 늘어나 셋이 되는 순간 격자 오른쪽이 통째로 비었다.
  const tiles = html.split(/(?=class="tile[ "])/).slice(1);
  assert.strictEqual(tiles.filter((t) => t.includes("검토 기준")).length, 1,
                     "기준 타일이 겹마다 쪼개졌다 — 격자가 흔들린다");
});

test("홈에서는 기준 건수를 말하지 않는다", () => {
  // 홈에 선 사람에게 "공통 7건 · 팀 13건"은 아무 결정도 바꾸지 않는다. 건수가
  // 궁금해지는 순간은 기준 화면에 들어간 뒤다. 홈은 **어느 겹이 걸리는가**만
  // 그림으로 말한다.
  const html = home({ team: "ai-test-cert-1", layers: LAYERS3 });
  const tile = html.split(/(?=class="tile[ "])/).slice(1)
    .filter((t) => t.includes("검토 기준"))[0];
  // 픽스처는 공통 7 · 팀 13 · 업로드 8 = 28건. 어느 수도 화면에 없어야 한다.
  for (const n of ["7건", "13건", "8건", "28건", "20건"]) {
    assert.ok(!tile.includes(n), `기준 타일에 건수(${n})가 남아 있다`);
  }
});

test("세 겹을 늘 셋으로 보여준다", () => {
  // 공통·팀별은 씨앗이라 늘 걸리고, 업로드 체크리스트는 검사를 시작할 때 고른
  // 것만 걸린다(server.py 의 compose_review_preset(seed, picked, team) 중 picked).
  // 없는 겹도 자리를 지키고 흐린 상태로 선다. 감추면 "우리 팀 기준이 안 걸렸다"와
  // "그런 겹이 원래 없다"가 구별되지 않고, 체크리스트를 올려 쓸 수 있다는 것
  // 자체를 모른 채로 남는다.
  //
  // 상태는 입력 노드에 늘 적는다. hover 뒤로 숨기지 않는다 — 터치에는 hover가
  // 없고, 안 올려본 사람은 자기 팀 기준이 안 걸린 것을 끝까지 모른다.
  const labels = (html) => {
    const tile = html.split(/(?=class="tile[ "])/).slice(1)
      .filter((t) => t.includes("검토 기준"))[0];
    const parts = tile.split(/<div class="crit-source-node([^"]*)"/);
    const out = [];
    for (let i = 1; i < parts.length; i += 2) {
      out.push({ off: parts[i].includes("is-off"),
                 optional: parts[i].includes("is-optional"), html: parts[i + 1] });
    }
    return out;
  };

  // 셋 다 있는 경우 — 전부 채워진다.
  const full = labels(home({ team: "ai-test-cert-1", layers: LAYERS3 }));
  assert.strictEqual(full.length, 3, "겹이 셋이 아니다");
  assert.ok(full.every((c) => !c.off), "다 걸렸는데 흐리게 선 겹이 있다");
  assert.match(full[2].html, /선택 가능 1개/, "체크리스트를 현재 적용처럼 말한다");
  assert.ok(full[2].optional, "선택 가능한 체크리스트를 이미 적용된 실선으로 그린다");

  // 체크리스트를 안 올린 경우. 셋째만 흐린 상태다.
  const plain = labels(home({ team: "ai-test-cert-1", layers: LAYERS }));
  assert.strictEqual(plain.length, 3, "빈 겹을 감췄다");
  assert.deepStrictEqual(plain.map((c) => c.off), [false, false, true],
                         "안 걸린 겹의 상태가 구분되지 않는다");
  assert.match(plain[2].html, /검토할 때 선택/, "빈 겹이 아무 말도 안 한다");

  // 로그인하지 않아 팀 기준이 없는 경우. 둘째도 흐린 상태다.
  const noTeam = home({ team: "", layers: LAYERS.slice(0, 1) });
  assert.deepStrictEqual(labels(noTeam).map((c) => c.off), [false, true, true],
                         "팀 기준이 없는데 걸린 것처럼 선다");
  assert.match(noTeam, /로그인하면 소속 팀 기준이 함께 걸립니다/,
               "왜 안 걸리는지 말하지 않는다");
  // 이름표는 자리를 아끼려고 줄인 것이다 — 팀 **이름**은 아래 결론 줄이 온전히
  // 말한다(원에 마우스를 올리면 <title> 로도 뜬다).
  assert.match(home({ team: "ai-test-cert-1", layers: LAYERS }),
               /기준이 공통 기준과 함께 걸립니다/, "어느 팀 기준이 걸렸는지 안 말한다");

  // 그림은 합집합을 교집합처럼 그리지 않는다. 입력 셋이 선을 따라 한 문서로
  // 모이고, 흐린 입력의 선도 점선으로 자리를 지킨다.
  const glyph = home({ team: "ai-test-cert-1", layers: LAYERS });
  // 앞 칸의 점이 상태를 진다 — 번호(01·02·03)가 아니다. 세 기준은 1·2·3등이
  // 아니라 합쳐지는 것이라 번호는 없는 순서를 말하고, 검토 기준 화면에는 이미
  // 진짜 기준 번호가 따로 있어 헷갈린다.
  assert.equal((glyph.match(/class="crit-source-dot"/g) || []).length, 3,
               "겹마다 상태 점이 붙지 않았다");
  assert.equal((glyph.match(/class="crit-source-node/g) || []).length, 3, "입력이 셋이 아니다");
  assert.equal((glyph.match(/class="crit-source-node is-off/g) || []).length, 1,
               "안 걸린 입력이 그림에서 채워져 있다");
  assert.match(glyph, /class="crit-flow-lines"/, "기준이 합쳐지는 선이 없다");
  assert.match(glyph, /class="crit-document-node"/, "기준을 적용할 문서가 없다");
  assert.match(glyph, /검토 문서/, "가운데 대상이 문서라고 말하지 않는다");
});

test("세 겹이 합쳐진다고 말한다", () => {
  // 셋을 나란히만 두면 "셋 중 하나를 고르는 것"으로도 읽힌다. 실제로는 합집합이다
  // (modules/preset 의 compose_review_preset = 공통 ∪ 팀 ∪ 업로드).
  assert.match(home({ team: "ai-test-cert-1", layers: LAYERS }),
               /세 기준을 모아 한 문서를 검토합니다/, "세 입력이 합쳐진다는 말이 없다");
  // 체크리스트를 올린 사람에게는 걸리는 방식이 다르다는 것까지 말한다.
  assert.match(home({ team: "ai-test-cert-1", layers: LAYERS3 }),
               /체크리스트는 검토를 시작할 때 고릅니다/, "고르는 것이라는 말이 없다");
  const note = home({ team: "ai-test-cert-1", layers: LAYERS3 });
  assert.match(note, /<div class="crit-note"><span>[^<]*공통 기준[^<]*<\/span><span>체크리스트는/,
               "서로 다른 두 설명이 한 줄에서 어중간하게 꺾인다");
});

test("홈에 들어올 때 격자가 차례로 앉는다", () => {
  // 벤토 타일 여섯이 한꺼번에 튀어나오면 무엇부터 볼지가 안 잡힌다. 원근은
  // 격자가 지고(index.html .bento), 타일은 50ms 씩 어긋나 판 하나가 세워지는
  // 것으로 읽힌다.
  const html = home({ team: "ai-test-cert-1", layers: LAYERS });
  // 관용구는 결과 카드와 같은 listIn 이다 — 홈 전용 키프레임을 따로 두지 않는다.
  //
  // 타일과 흐름 단계를 **갈라서** 잰다. 한 통에 넣으면 단계가 늘어질 때 "타일이
  // 늦다"는 엉뚱한 말로 실패한다(실제로 그렇게 한 번 걸렸다). 둘은 성격이 다르다
  // — 타일은 격자를 세우는 것이고, 단계는 그 위에서 순서를 말하는 것이다.
  const delaysIn = (frag) => [...frag.matchAll(/listIn[^"]*animation-delay:(\d+)ms/g)]
    .map((m) => Number(m[1]));
  const flow = html.slice(html.indexOf("검토 방법"));
  const tiles = delaysIn(html.slice(0, html.indexOf("검토 방법")));
  const steps = [...flow.matchAll(/--flow-delay:(-?\d+)ms/g)]
    .map((m) => Number(m[1]));

  assert.ok(tiles.length >= 5, `타일에 진입 지연이 안 붙었다 (${tiles.length}개)`);
  // 어긋나야 차례로 앉는다 — 전부 0 이면 한꺼번에 튀어나오는 것과 같다.
  assert.ok(new Set(tiles).size > 1, "지연이 전부 같다 — 계단이 없다");
  assert.ok(Math.max(...tiles) <= 250, `마지막 타일이 ${Math.max(...tiles)}ms 로 늦다`);

  // 흐름 단계는 1→2→3→4 순서가 곧 내용이라 번호가 반드시 어긋나야 한다.
  assert.strictEqual(steps.length, 4, `흐름 단계 지연이 ${steps.length}개다`);
  assert.deepStrictEqual(steps, [...steps].sort((a, b) => a - b), "단계 순서가 뒤섞였다");
  assert.ok(new Set(steps).size === 4, "단계가 한꺼번에 나온다 — 순서를 못 말한다");
  // 카드가 자리 잡은 뒤 설명을 보여 주되 1초 안에는 끝낸다.
  assert.ok(Math.min(...steps) >= 300, "카드가 앉기 전에 흐름 모션이 묻힌다");
  assert.ok(Math.max(...steps) + 320 <= 1000,
            `진입이 ${Math.max(...steps) + 320}ms 로 길다`);
});

test("타일 크기가 우선순위를 말한다", () => {
  // 벤토 격자 — 예전에는 큰 흰 카드 넷이 세로로 쌓여 무엇부터 봐야 할지
  // 안 보였다. 검토를 **시작하는 것**이 제일 크고, 흐름은 가로로 넓게 깔린다.
  const html = home({ team: "ai-test-cert-1", layers: LAYERS });
  assert.match(html, /class="bento"/, "격자가 없다");
  // `tile-h`·`tile-sub` 같은 자식 클래스는 타일이 아니다 — 정확히 `tile` 로
  // 시작하고 공백이나 따옴표가 뒤따르는 것만 센다.
  const cls = [...html.matchAll(/class="(tile(?:\s[^"]*)?)"/g)].map((m) => m[1].split(" "));
  // **크기가 곧 위계다.** 매번 보는 최근 검토가 가장 큰 칸이고, 처음 몇 번만
  // 읽는 흐름은 그보다 작다. 예전에는 둘 다 가로 전체라 화면이 "이게 다 똑같이
  // 중요하다"고 말했다.
  const span = { b2: 2, b3: 3, b4: 4, b6: 6 };
  const spanOf = (c) => span[c.filter((x) => span[x])[0]] || 1;
  // 타일 경계로 갈라 잰다. `class="tile-h"` 같은 자식도 `tile` 로 시작하므로
  // 뒤에 공백이나 따옴표가 오는 것만 타일로 본다.
  const chunks = html.split(/(?=class="tile[ "])/).slice(1);
  // **폭이 아니라 면적으로 잰다.** 흐름이 제 줄(b6)을 갖게 되면서 폭만 보면
  // 설명이 제일 큰 타일이 됐는데, 실제로는 한 줄짜리 띠라 두 줄을 먹는 최근
  // 검토(b4 r2 = 8칸)가 여전히 더 크다(b6 = 6칸). 폭만 재던 것은 최근 검토를
  // 뺀 전부가 1행이던 시절의 근사치였다.
  const at = (needle) => {
    const t = chunks.filter((x) => x.includes(needle))[0];
    if (!t) return 0;
    const c = t.slice(7, t.indexOf('"', 7)).split(" ");
    return spanOf(c) * (c.includes("r2") ? 2 : 1);
  };
  assert.ok(at("최근 검토") > at("검토 방법"),
            "흐름이 최근 검토만큼 크다 — 크기가 위계를 안 말한다");
  // 검토 셋은 **같은 크기**다. 무엇을 고를지는 문서가 몇 개냐일 뿐이라
  // 하나만 크게 두면 나머지가 곁다리로 보인다. 시작 타일의 표식은 qs(화살표
  // 호버) — 기준 타일도 act+b2 를 갖게 되면서 act 만으로는 못 가른다.
  const starts = cls.filter((c) => c.includes("qs"));
  assert.strictEqual(starts.length, 3, `검토 시작 타일이 ${starts.length}개다 (셋이어야 한다)`);
  assert.ok(starts.every((c) => c.includes("b2")), "시작 타일 크기가 갈라졌다");
  assert.strictEqual((html.match(/class="qs-icon"/g) || []).length, 3,
                     "검토 시작 아이콘 셋이 솔리드 브랜드 면을 함께 쓰지 않는다");
  for (const kind of ["단일 문서 검토", "문서 비교 검토", "폴더 검토"]) {
    assert.ok(html.includes(kind), `${kind} 가 없다`);
  }
  // 읽기만 하는 타일은 안 들린다 — act 는 누를 수 있는 것에만 붙는다.
  // 셋: 시작 타일뿐이다. 기준 타일은 한때 전체가 문이었지만 읽을 것이 잔뜩
  // 실린 타일이라, 층 이름을 눌러도 종류 줄을 눌러도 같은 전체 목록으로 가는
  // 것이 함정이었다. 문은 머리줄의 `모두 보기` 버튼 하나로 줄였다 — 이름도
  // 옆 칸 최근 검토의 손잡이와 같다(한때 "전체 보기"로 갈려 있었다).
  assert.strictEqual(cls.filter((c) => c.includes("act")).length, 3,
                     "누를 수 있는 타일 수가 다르다");
  const crit = html.split(/(?=class="tile[ "])/).slice(1)
    .filter((t) => t.includes("검토 기준"))[0];
  assert.ok(!/class="tile crit[^"]*\bact\b/.test(html), "기준 타일 전체가 아직 문이다");
  assert.match(crit, /class="tile crit[^"\n]*\bgrow\b/,
               "기준 타일이 최근 검토와 세로 끝선을 맞추지 않는다");
  // 그 하나뿐인 문은 진짜 button 이어야 한다 — span 이면 키보드로 못 닿는다.
  assert.match(crit, /<button type="button"[^>]*data-act="setMode" data-arg="checklists"/,
               "기준 화면으로 갈 길이 없다");
  // 무게는 **크기와 자리**가 말한다 — 그게 벤토다. 색 면도 강조 띠도 대봤는데
  // 둘 다 시끄럽기만 했다. 면은 다 같은 흰색이다.
  assert.ok(!html.includes("lead"), "면에 장식을 다시 붙였다");

  // 줄마다 6칸이 꽉 차야 빈칸이 안 생긴다. 두 줄을 먹는 타일(.r2)은 칸도 두 배로
  // 센다 — 세로 span 을 빼고 세면 꽉 찬 격자가 "6의 배수가 아니다"로 잡힌다.
  const cells = cls.reduce(function (n, c) {
    return n + spanOf(c) * (c.includes("r2") ? 2 : 1);
  }, 0);
  assert.strictEqual(cells % 6, 0, `칸 합이 6의 배수가 아니다: ${cells}`);
  // 높이가 다 같으면 그건 격자가 아니라 줄이다 — 벤토이려면 세로도 갈려야 한다.
  assert.ok(cls.some((c) => c.includes("r2")), "타일 높이가 전부 같다");
});

test("흐름 설명은 기록이 생겨도 남는다", () => {
  // 예전에는 기록이 생기면 흐름("검토 방법")이 통째로 물러났다.
  // 이유는 자리 다툼이었다 — 기준 타일과 오른쪽 2열을 나눠 써서 하나가 나오면
  // 하나가 빠졌고, 그래서 "처음 몇 번만 읽는 설명"이라는 명분이 붙었다.
  //
  // 그런데 홈은 이 서비스가 무엇을 하는지 알게 되는 곳이고, 그걸 문장으로
  // 말하는 타일은 이것 하나다. 검토를 한 번 해본 사람에게만 안 보이는
  // 자기소개는 앞뒤가 안 맞는다 — 시연하려고 홈을 열면 이미 기록이 있다.
  // 흐름에 제 줄(b6)을 주고 나니 다툴 자리가 없어 조건 자체가 사라졌다.
  const st = state({ team: "ai-test-cert-1", layers: LAYERS });
  st.history = [{ id: "h1", title: "문서.pdf", at: "2026-08-11T00:00:00Z", findings: 3 }];
  const views = build(st);
  const html = views.view(views.renderVals());
  assert.ok(html.includes("검토 방법"), "기록이 생기니 흐름 설명이 사라진다");
  for (const step of ["문서를 올린다", "글자를 읽는다", "기준으로 잰다", "지적을 짚는다"]) {
    assert.ok(html.includes(step), `흐름에 "${step}" 가 없다`);
  }
  const cls = [...html.matchAll(/class="(tile(?:\s[^"]*)?)"/g)].map((m) => m[1].split(" "));
  const span = { b2: 2, b3: 3, b4: 4, b6: 6 };
  const spanOf = (c) => span[c.filter((x) => span[x])[0]] || 1;
  const cells = cls.reduce((n, c) => n + spanOf(c) * (c.includes("r2") ? 2 : 1), 0);
  assert.strictEqual(cells % 6, 0, `칸 합이 6의 배수가 아니다: ${cells}`);
  // 기준 타일이 흐름의 칸을 이어받았는지 — r2 가 최근 검토 말고도 있어야 한다.
  assert.ok(cls.filter((c) => c.includes("r2")).length >= 2, "기준 타일이 칸을 이어받지 않았다");
});

test("최근 기록은 조밀하게 6건을 보이고 모두 보기와 지적 상태를 구분한다", () => {
  const st = state({ team: "ai-test-cert-1", layers: LAYERS });
  st.history = Array.from({ length: 7 }, (_, i) => ({
    id: `h${i}`, title: `문서${i}.pdf`, at: "2026-08-11T00:00:00Z", findings: i + 1,
  }));
  const views = build(st);
  const html = views.view(views.renderVals());
  assert.strictEqual((html.match(/class="hrow"/g) || []).length, 6,
                     "홈 최근 검토가 6건보다 많거나 적다");
  assert.ok(!html.includes("문서6.pdf"), "일곱 번째 기록까지 홈에 노출됐다");
  assert.match(html, /class="btn btn-sm btn-primary home-see-all"[^>]*>모두 보기/,
               "모두 보기가 솔리드 액션 버튼이 아니다");
  assert.match(html, /class="history-count"/, "지적 건수 상태 칩이 사라졌다");
  assert.match(html, /class="history-row-arrow"/, "최근 검토 행 화살표가 솔리드 호버를 쓰지 않는다");
});

test("못 읽은 것과 없는 것을 섞지 않는다", () => {
  // 예전에는 이력 요청이 실패해도 빈 배열을 넣어서, 서버가 죽었을 때 홈이
  // "아직 검토한 문서가 없습니다"라고 말했다 — 검토를 스무 건 한 사람에게
  // 한 건도 없다고 한 셈이다. CLAUDE.md 의 "모르면 모른다고 말한다"가 막는 것이
  // 검사 결과만이 아니라 화면 전체에 걸린다.
  const st = state(null);
  st.history = []; st.historyError = true;
  const views = build(st);
  const html = views.view(views.renderVals());
  assert.ok(!html.includes("아직 검토한 문서가 없습니다"), "실패를 '없음'으로 말한다");
  assert.match(html, /불러오지 못했습니다/, "못 읽었다고 말하지 않는다");
  // 상태만 말하고 손잡이가 없으면 새로고침밖에 길이 없다.
  assert.match(html, /data-act="reloadHistory"/, "다시 시도할 길이 없다");
});

test("비어 있으면 무엇을 하면 채워지는지 말한다", () => {
  const st = state(null);
  st.history = []; st.historyError = false;
  const views = build(st);
  const html = views.view(views.renderVals());
  assert.match(html, /아직 검토한 문서가 없습니다/);
  assert.match(html, /검토를 시작하면 여기에 남습니다/, "빈 화면이 다음 걸음을 안 알려준다");
});

test("아직 못 읽었으면 지어내지 않는다", () => {
  const html = home(null);
  assert.ok(!html.includes("· 자동 "), "기준도 없이 숫자를 낸다");
  assert.match(html, /불러오는 중…|로그인하면/);
});


test("홈의 인사와 빠른 시작 손잡이를 지킨다", () => {
  const html = home({ team: "ai-test-cert-1", layers: LAYERS });
  // 이름은 강조된다. 이 테스트가 지키는 것은 **강조가 살아 있는가**지 그 수단이
  // 아니다 — 예전에 실제로 흘린 적이 있다.
  //
  // 홈 인사의 이름은 브랜드색으로 구분하되 링크 동작이나 장식 획은 없다.
  assert.match(html, /<span class="home-greeting-name">김검토 님<\/span>, 환영합니다/,
               "이름 강조가 빠졌다");
  // 진입 때는 wave-enter 가 붙어 한 번 흔들린다 — 있어도 없어도 아이콘은 있어야 한다.
  assert.match(html, /class="home-greeting-wave[^"]*" aria-hidden="true"/,
               "인사말의 펼친 손 아이콘이 빠졌다");
  assert.ok(!html.includes("home-greeting-eagle"),
            "chat 안내자로 옮길 홈 마스코트가 아직 인사말에 남아 있다");
  assert.ok(!html.includes('class="mark"'), "인사말에 형광펜 획이 남아 있다");
  // 화살표는 늘 자리를 지키다 호버하면 색이 찬다(.qs:hover .qs-arrow).
  assert.match(html, /class="qs-arrow"/, "화살표가 빠졌다");
});

// Shared fake data for the DocReview UI prototype.
// Exposed as a global so the frontend can read it synchronously.
// NOTE: mock data only — no real backend (review_document) is wired yet.
(function () {
  var doc = {
    name: "제품요구사항서_결제모듈_v0.3.md",
    type: "PRD",
    checklist: "generic",
    words: 1842,
    chars: 6180,
    uploadedAt: "2026-07-07 14:22",
    sections: [
      { id: "1", title: "개요", level: 1, text: "본 문서는 결제 모듈 리뉴얼(v2)의 요구사항을 정의한다. 기존 PG 연동을 유지하면서 신규 간편결제 수단을 추가하고, 결제 실패율을 낮추는 것을 목표로 한다." },
      { id: "1.1", title: "배경", level: 2, text: "현행 결제 실패율은 3.2%로, 업계 평균(1.8%) 대비 높다. 로그 분석 결과 주요 원인은 결제창 이탈과 외부 PG 타임아웃이며, 특히 모바일 웹에서 이탈률이 두드러진다." },
      { id: "2", title: "목표", level: 1, text: "결제 성공률을 99% 이상으로 끌어올리고, 신규 간편결제 3종(A페이·B페이·C페이)을 2주 내 순차 출시한다. 결제 완료까지의 평균 단계 수를 5단계에서 3단계로 줄인다." },
      { id: "3", title: "범위", level: 1, text: "인앱 결제 화면, 결제 수단 관리, 영수증 발급을 포함한다. 정산·세금계산서 발행·해외 결제는 이번 범위 밖으로 한다. 관리자 도구는 필요한 최소한만 다룬다." },
      { id: "4", title: "기능 요구사항", level: 1, text: "결제 요청 생성, 결제 수단 선택, 결제 승인/취소, 부분 취소, 영수증 재발급 기능을 제공한다. 각 기능은 실패 시 사용자에게 원인을 안내해야 한다." },
      { id: "4.1", title: "결제 수단 관리", level: 2, text: "사용자는 카드·계좌·간편결제를 등록/삭제/기본 설정할 수 있다. 등록 정보는 토큰화하여 저장하며 원본 카드번호는 보관하지 않는다." },
      { id: "4.2", title: "영수증 발급", level: 2, text: "결제 완료 시 전자 영수증을 즉시 발급하고, 마이페이지에서 재발급을 지원한다. 발급 실패는 재시도 큐로 처리한다." },
      { id: "5", title: "비기능 요구사항", level: 1, text: "결제 API의 p95 응답시간은 800ms 이하여야 한다. 가용성은 월 99.9%를 목표로 한다. 모든 요청은 감사 로그를 남긴다." },
      { id: "6", title: "일정", level: 1, text: "설계 1주, 구현 2주, QA 1주로 총 4주를 계획한다. 간편결제 3종은 위험 분산을 위해 순차 배포한다." }
    ]
  };

  // sev: major | minor | info ; checker: completeness | consistency
  // **가짜 지적은 없다.** 예전에는 프로토타입 시절의 11건이 여기 있었고,
  // 검토를 한 번도 안 돌려도 `지적사항` 화면에 그것이 떴다 — 진짜 결과와
  // 구별할 방법이 없다. 이력 목록에서 목업을 지운 것과 같은 이유다
  // (views.js historyView 주석).
  //
  // 아래 stages·checklists 는 지적이 아니라 **화면 뼈대**다. 검토 전에도
  // 파이프라인 단계를 그려야 해서 남긴다(서버가 오면 그걸로 덮인다).
  var findings = [];

  var stages = [
    { key: "ingestion", label: "Ingestion", desc: "텍스트/마크다운 로더로 원문 적재", detail: "TextLoader · 6,180 chars" },
    { key: "normalize", label: "Normalize", desc: "마크다운 heading을 섹션 트리로 정규화", detail: "9 sections" },
    { key: "chunking", label: "Chunking", desc: "섹션을 검토 단위로 분할", detail: "12 chunks · max 4000" },
    { key: "review", label: "Review", desc: "선택된 체크리스트 대조 및 LLM 심층 분석", detail: "completeness · consistency" },
    { key: "report", label: "Report", desc: "중복 제거 · 심각도 정렬 · 렌더", detail: "6 findings" }
  ];

  var checklists = [
    { id: "generic", name: "Generic", required: ["개요", "목표", "요구사항", "보안 요구사항", "참고문헌"] },
    { id: "prd", name: "PRD", required: ["개요", "배경", "목표", "범위", "기능 요구사항", "일정"] },
    { id: "api", name: "API Spec", required: ["개요", "엔드포인트", "인증", "에러 코드"] }
  ];

  window.DOCREVIEW = {
    doc: doc,
    // 미리보기 본문. 서버 payload는 이걸 최상위에 싣는다(to_ui_review_payload) —
    // 목업도 같은 자리에 둬야 화면이 두 벌의 모양을 알 필요가 없다.
    sections: [],
    findings: findings,
    stages: stages,
    checklists: checklists,
    // 서버 검토 뒤에는 모든 적용 기준과 그 기준이 낸 지적의 연결이 들어간다.
    criteriaResults: null,
    // 업로드 기준을 고른 경우에만 그룹 결과 화면을 켜는 호환 별칭.
    checklist: null,
    compare: {
      docA: { name: "요구사항명세서_결제_SRS_v1.2.md", type: "SRS", words: 2140 },
      docB: { name: "설계서_결제_SDD_v0.8.md", type: "SDD", words: 3020 },
      stats: { requirements: 12, matched: 9, missing: 2, mismatch: 2, extra: 1 },
      stages: [
        { label: "Ingestion", desc: "SRS·SDD 원문 적재", detail: "2 docs · 5,160 chars" },
        { label: "Alignment", desc: "요구 ↔ 설계 매칭", detail: "12 requirements" },
        { label: "Cross-check", desc: "누락·불일치·초과 검사", detail: "compare checker" },
        { label: "Report", desc: "중복 제거 · 정렬", detail: "5 findings" }
      ],
      findings: [
        { id: "c1", type: "missing", sev: "major", a: "4", b: null, message: "SRS의 '부분 취소' 요구가 SDD 설계에 대응 항목이 없다.", suggestion: "SDD에 부분 취소 처리 흐름과 상태 전이를 설계로 추가하라." },
        { id: "c2", type: "mismatch", sev: "major", a: "2", b: "2", message: "성공률 목표 불일치: SRS는 99%, SDD는 98%로 서로 다르다.", suggestion: "두 문서의 목표 지표를 하나로 합의해 동기화하라." },
        { id: "c3", type: "missing", sev: "major", a: "4.2", b: null, message: "SRS '영수증 재발급'에 대응하는 SDD 컴포넌트가 없다.", suggestion: "영수증 재발급 서비스와 재시도 큐 설계를 SDD에 추가하라." },
        { id: "c4", type: "extra", sev: "minor", a: null, b: "3.4", message: "SDD의 '캐시 레이어'가 SRS 요구에 근거가 없다.", suggestion: "해당 설계의 근거 요구를 SRS에 추가하거나 범위에서 제외하라." },
        { id: "c5", type: "mismatch", sev: "minor", a: "1", b: "2", message: "용어 불일치: SRS는 '간편결제', SDD는 'Quick Pay'로 표기한다.", suggestion: "용어집을 만들어 양 문서 표기를 통일하라." }
      ]
    },
    typeMeta: {
      missing: { label: "설계 누락", short: "누락" },
      mismatch: { label: "불일치", short: "불일치" },
      extra: { label: "근거 없음", short: "초과" }
    },
    sevMeta: {
      major: { label: "Major", kr: "주의", order: 0 },
      minor: { label: "Minor", kr: "경미", order: 1 },
      info: { label: "Info", kr: "정보", order: 2 }
    }
  };
})();

# DocReview Frontend (UI 프로토타입)

Claude Design `DocReviewDev.dc.html`를 빌드 없이 동작하는 정적 SPA로 이식한 것입니다.

- **UI 전용 · 목업 데이터만** 사용합니다. 실제 백엔드(`src/docreview`, `review_document`)는
  **연결하지 않았습니다** — 다음 단계 과제입니다.
- 백엔드 코드는 전혀 건드리지 않았습니다.

## 실행

빌드/의존성 없이 파일만 열면 됩니다.

```bash
# 브라우저로 바로 열기
xdg-open frontend/index.html

# 또는 로컬 서버 (파일 프로토콜 이슈 없이)
python3 -m http.server -d frontend 8000   # http://localhost:8000
```

## 파일

| 파일 | 역할 |
|------|------|
| `index.html` | 폰트·스타일·마운트 지점 |
| `app.js` | 상태 + 렌더 로직 (`DCLogic` → 바닐라 JS 이식) |
| `docreview-data.js` | 목업 데이터 (`window.DOCREVIEW`) |

## 구현된 화면

- **단일 검토**: Upload → Review(파이프라인 애니메이션) → Findings(심각도/체커/정렬 필터,
  행 펼침, JSON/MD/CSV export) → Summary(health score)
- **문서 비교**: Setup → Compare → Report(매칭률·누락/불일치/근거없음, 교차검토 테이블)
- **체크리스트 · 기록 · 설정** 화면

## 실제 결과 넣기 (서버 없이)

```bash
docsuree compare --parent 상위문서.md --child 하위문서.md \
  --emit-ui frontend/docreview-result.js          # → window.DOCREVIEW.compare
docsuree review 문서.md \
  --emit-ui frontend/docreview-review-result.js   # → doc / findings / stages
```

두 생성물(git 제외)은 `docreview-data.js` 뒤에 로드되며 **서로 다른 키를 덮어쓰므로 공존**합니다.
파일이 없으면 해당 화면은 목업을 그대로 씁니다.

채워지는 것: 단일 검토의 findings·요약, 비교 화면의 매칭률·누락·근거없음 카드와
우측 "비교 결과 내역" 목록.
아직 목업인 것: 비교 화면 가운데 두 문서 뷰어 패널(app.js에 HTML로 하드코딩), "불일치"
카드(내용 판정 미구현이라 항상 0).

## 브라우저에서 직접 업로드 (로컬 API 서버)

```bash
uv sync --extra web          # fastapi / uvicorn (선택 의존성)
docsuree serve              # http://127.0.0.1:8000
```

- **단일 검토**: 문서 1개 업로드 → `POST /api/review`
- **문서 비교**: 문서 2개 업로드 → `POST /api/compare`

실패하면 입력 화면으로 돌아가며 서버 메시지가 배너로 뜹니다.

파일이 모두 선택되고 `http(s)`로 서빙 중일 때만 API를 호출합니다. `file://`로 열었거나
파일을 안 골랐으면 기존 목업/`--emit-ui` 결과를 그대로 씁니다.

인증이 없으므로 `--host`를 `127.0.0.1` 밖으로 열지 마세요. 업로드는 30MB로 제한됩니다.
로그인 화면은 `localStorage` 기반 UI 흉내이며 실제 보호 장치가 아닙니다.

## 다음 단계

"불일치" 판정(LLM triage)을 붙여 비교 화면의 빈 카드를 채웁니다.

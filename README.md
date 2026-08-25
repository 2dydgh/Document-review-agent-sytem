<div align="center">

<img src="web/public/login_hero.png" alt="DocSuree investigator mascot" width="220">

# DocSuree

### 문서를 읽고, 근거를 찾아, 스스로 검토하는 문서 검토 Agent

**Doc** + **Suree** — 문서를 살피는 독수리, 문서를 修理하는 검토자, 근거로 확신하는 **Sure**.

<img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
<img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
<img src="https://img.shields.io/badge/vLLM-Qwen3-5C5CFF?style=flat-square" alt="vLLM Qwen3" />
<img src="https://img.shields.io/badge/Network-On--premise-3974A5?style=flat-square&logo=shield&logoColor=white" alt="On-premise" />
<img src="https://img.shields.io/badge/Status-Active_Development-F2A65A?style=flat-square" alt="Active development" />

</div>

<br />

<img src="docs/assets/home.png" width="100%" alt="DocSuree home dashboard" />

<div align="center">
  <sub>단일 문서 · 문서 비교 · 폴더 검토와 검토 기준을 한 화면에서 관리합니다.</sub>
</div>

---

## DocSuree는 무엇을 하는가

문서를 올리고 **무엇을 검토할지 자연어로 입력하면**, DocSuree가 문서의 종류와 관계를
파악하고 검토 계획을 세웁니다. 검색·문맥 확인·값 비교를 반복한 뒤, 원문에서 다시 확인된
근거만 지적으로 제출합니다.

> **Agent는 근거를 찾고, 코드는 그 근거를 검증합니다.**

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>🔍 능동 탐색</h3>
      <p>고정 체크리스트만 실행하지 않고 문서와 요청에 맞춰 확인할 곳을 찾아갑니다.</p>
    </td>
    <td width="33%" valign="top">
      <h3>📌 근거 중심</h3>
      <p>모든 지적에 원문 인용과 확인 경로를 남깁니다. 결론만 있는 후보는 채택하지 않습니다.</p>
    </td>
    <td width="33%" valign="top">
      <h3>🚫 검증 게이트</h3>
      <p>인용이 원문에 실제로 존재하는지 문자열로 대조해 환각 후보를 걸러냅니다.</p>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>🧾 미검토 공개</h3>
      <p>이상이 없는 것과 확인하지 못한 것을 구분하고, 절단·실패 범위를 숨기지 않습니다.</p>
    </td>
    <td valign="top">
      <h3>🏢 사내망 실행</h3>
      <p>문서를 외부 LLM API로 보내지 않고 사내 vLLM·VLM 엔드포인트만 사용합니다.</p>
    </td>
    <td valign="top">
      <h3>🧩 모듈형 구조</h3>
      <p>파서·LLM 클라이언트·기준·리포트 기능을 독립 모듈로 분리해 재사용할 수 있습니다.</p>
    </td>
  </tr>
</table>

## 실제 검토 화면

<img src="docs/assets/review-screen.png" width="100%" alt="DocSuree review result with PDF highlights and findings" />

검토 결과 화면에서 원문 하이라이트와 지적사항을 함께 확인할 수 있습니다.
사용자는 각 지적을 판정하고, 수정본을 올려 반영 여부를 다시 검토할 수 있습니다.

## 현재 구현 상태

> DocSuree는 현재 개발 중입니다. 아래 표는 목표가 아니라 실제 구현 상태를 구분해 표시합니다.

| 영역 | 상태 |
|---|---|
| 텍스트 · Markdown · HWPX · 디지털 PDF · DOCX 파싱 | ✅ 구현됨 |
| 구형 `.hwp` 바이너리 파싱 | ✅ 구현됨 — rhwp → HWPX 변환 |
| 규칙 체커 6종 · LLM 체커 3종 | ✅ 구현됨 |
| 단일 문서 검토 · 두 문서 비교 | ✅ 구현됨 |
| Markdown · PDF · RTM Excel 리포트 | ✅ 구현됨 |
| PDF 하이라이트 · 지적 위치 이동 | ✅ 구현됨 |
| 기준 자동 감지 · 3층 기준 병합 | ✅ 구현됨 |
| Agent 오케스트레이션 · 능동 탐색 · 재검토 | 🚧 작업 중 |
| 스캔 PDF OCR | ⏳ 인터페이스만 구현 |
| 점수 산출 | ➖ 의도적으로 제외 — 검증된 정답 셋 구축 후 판단 |

## 검토 흐름

<img src="docs/assets/upload.png" width="100%" alt="DocSuree document upload and AI analysis pipeline" />

문서를 첨부하고 적용할 검토 기준을 선택하면, 화면 오른쪽에서
`Ingestion → Normalize → Chunking → Review → Report` 파이프라인을 확인할 수 있습니다.

<br />

```text
문서 업로드
    ↓
문서 종류·구조·관계 파악
    ↓
검토 목적 입력 및 계획 확인
    ↓
검색 · 문맥 읽기 · 값/관계 비교
    ↓
Finding 후보 생성
    ↓
Validator — 인용 ↔ 원문 대조
    ↓
확정 지적 · 사람 확인 필요 · 이상 없음 · 미검토
    ↓
판정 · 수정 · 재검토 · 리포트
```

<details>
<summary><strong>Agent와 Validator의 역할 자세히 보기</strong></summary>

<br />

Agent는 매 단계에서 다음 행동을 다시 선택합니다.

- `find_term` — 용어와 표현 검색
- `find_requirement` — 요건 ID와 표기 변형 검색
- `get_section` — 절 단위 문맥 읽기
- `get_neighbors` — 앞뒤 문맥 확인
- `compare_values` — 숫자·단위·조건 비교
- `compare_links` — 상·하위 문서 대응 관계 비교

Agent가 만든 Finding 후보는 별도의 Validator를 통과해야 합니다.
인용문이 원문에 없거나 근거가 부족하면 재탐색하거나 폐기하며,
판단할 수 없는 항목은 `미검토` 또는 `사람 확인 필요`로 남깁니다.

</details>

## 시스템 구조

```text
┌─────────────────────────────────────────────────────────────────┐
│ Web UI · Vanilla SPA                                            │
│ 업로드 · SSE 진행 표시 · 결과 · pdf.js 하이라이트              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────▼──────────────────────────────────┐
│ FastAPI · src/app                                               │
│ review · compare · detect · annotate · suggest                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ Agent Orchestrator  [Work in Progress]                          │
│ 문서 파악 · 계획 · 검색 · 문맥 읽기 · 비교 · 재탐색            │
└──────┬──────────┬──────────────┬──────────────┬─────────────────┘
       │          │              │              │
  doc_parser    preset      rule/LLM checker   report
       │          │              │              │
       └──────────┴──────────────┬──────────────┘
                                 ▼
                 Validator — 인용 ↔ 원문 대조
                                 │
                                 ▼
                Finding · Unreviewed · Report
```

모듈은 DocSuree 애플리케이션을 알지 않으며 공개 인터페이스로만 연결됩니다.
조립은 `src/app/`에서 담당합니다.

## 지원 문서

| 형식 | 파싱 | 원본 레이아웃 뷰어 | 비고 |
|---|:---:|:---:|---|
| 디지털 PDF | ✅ | ✅ | pdfplumber + pypdf |
| 스캔 PDF | ⛔ | ✅ | OCR 미구현 |
| HWP | ✅ | ⚙️ | rhwp → HWPX, 뷰어는 LibreOffice 필요 |
| HWPX | ✅ | ⚙️ | 뷰어 변환 실패 시 텍스트 폴백 |
| DOCX | ✅ | ⚙️ | OOXML 직접 파싱 |
| Markdown · TXT | ✅ | — | 원문 그대로 |

> 파싱과 뷰잉은 별개입니다. LibreOffice가 없어도 문서 검토는 동작하며,
> LibreOffice는 원본 레이아웃을 PDF로 재현하는 뷰어 기능에만 사용됩니다.

## 주요 기능

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>검토</strong>
      <ul>
        <li>단일 문서 검토</li>
        <li>두 문서 추적성·내용 비교</li>
        <li>폴더 단위 산출물 검토</li>
        <li>규칙 체커 6종 · LLM 체커 3종</li>
      </ul>
    </td>
    <td width="50%" valign="top">
      <strong>결과</strong>
      <ul>
        <li>원문 PDF 하이라이트</li>
        <li>Markdown · PDF 리포트</li>
        <li>RTM 요구사항 추적표</li>
        <li>지적별 수정안과 재검토</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <strong>검토 기준</strong>
      <ul>
        <li>공통 → 팀 → 업로드 기준 병합</li>
        <li>검사 매개변수도 기준에서 관리</li>
        <li>팀명과 규칙값 하드코딩 방지</li>
      </ul>
    </td>
    <td valign="top">
      <strong>투명성</strong>
      <ul>
        <li>`unreviewed` 상태 분리</li>
        <li>폐기된 후보 수 INFO 공개</li>
        <li>최근 검토 이력 재열람</li>
      </ul>
    </td>
  </tr>
</table>

## 기술 스택

| 구분 | 기술 |
|---|---|
| Language · Package | Python 3.11+ · uv |
| API | FastAPI · Uvicorn |
| Document | pdfplumber · pypdf · rhwp-python · OOXML |
| LLM · VLM | 사내 vLLM Qwen3 · OpenAI-compatible endpoint |
| Frontend | Vanilla JavaScript · pdf.js |
| Report | fpdf2 · Markdown · Excel RTM |
| Viewer conversion | LibreOffice · H2Orestart · Java |
| Quality | pytest · ruff |

## 빠른 시작

### CLI

```bash
uv sync

# 단일 문서 검토
uv run docsuree review 검토할문서.pdf

# 결과 저장
uv run docsuree review 검토할문서.pdf --out report.md
```

### Web UI

```bash
uv sync --extra web
uv run docsuree serve
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

> 현재 인증 기능이 없으므로 `--host 0.0.0.0`으로 외부에 노출하지 마세요.
> 업로드 크기 제한은 30MB입니다.

## 저장소 구조

```text
DocReview/
├── src/
│   ├── app/                # API · 화면 · 계정 조립부
│   └── modules/
│       ├── doc_parser/     # PDF · HWP · HWPX · DOCX · MD
│       ├── llm_client/     # 사내 vLLM · VLM 단일 창구
│       ├── preset/         # 검토 기준 병합
│       ├── report/         # MD · PDF · RTM · 하이라이트
│       └── agent_*/        # 검사 관점별 모듈
├── web/
│   ├── public/             # 런타임 정적 자산
│   ├── brand/source/       # 브랜드 원본
│   └── vendor/             # pdf.js
├── docs/assets/            # README 스크린샷
├── presets/                # 공통 · 팀별 검토 기준
├── golden/                 # 정답 재검증 셋
├── tests/
├── ENGINE.md
└── README.md
```

## 개발

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

- 공개 함수는 타입 힌트를 사용합니다.
- 비트리비얼 로직에는 실행 가능한 검증을 둡니다.
- 입력 검증·에러 처리·보안은 최소 구현 대상에서 제외하지 않습니다.
- `.env`, 인증키, 실제 사내 문서와 50MB 이상 파일을 커밋하지 않습니다.

## 보안 및 프라이버시

- 문서 원본을 외부 LLM 서비스로 전송하지 않습니다.
- 모델 호출은 설정된 사내 엔드포인트를 통해서만 수행합니다.
- 데이터 디렉터리와 업로드 문서는 Git 추적 대상에서 제외해야 합니다.
- 공개 저장소에 실제 검토 문서·리포트·자격 증명을 포함하지 마세요.

---

<div align="center">
  <img src="web/public/mascot-investigator-192.png" alt="DocSuree" width="72">
  <br />
  <strong>DocSuree</strong> — 못 한 것을 못 했다고 말하는 문서 검토 Agent
</div>

# report

Finding → 렌더(md/json)·형광펜 PDF·엑셀·통계·진행단계.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

렌더 `render_markdown` `render_json` `render_rtm_markdown` `render_rtm_json` · UI `to_ui_payload` `to_ui_review_payload` `to_ui_checklist_review_payload` `render_ui_js` `render_review_ui_js` · `collect` · 진행 `review_stages` `REVIEW_STAGES` `REVIEW_DETAIL` `fmt_*` · 형광펜 `annotate` `locate` `Marked` `number_overlay` `find_font`.

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document 등 공통 타입은 `modules.shared`.

## 의존성
- 외부 패키지: pdfplumber, pypdf, fpdf2(형광펜·요약 PDF).
- 모듈 의존: `shared`(Finding 등).

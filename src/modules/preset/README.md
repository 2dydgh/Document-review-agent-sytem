# preset

팀 기준·체크리스트를 로드·파싱·저장·내보내기. 도메인 데이터는 presets/에 두고 주입.

## 공개 인터페이스
`__init__.py`에서 export하는 것만 외부에서 쓴다:

`build_items` `find_header` `guess_columns` `extract_tables` `UnsupportedChecklistFormat` · `Checklist` `ChecklistItem` `VERDICTS` · `ChecklistStore` `ChecklistError` · `to_csv`.

## 입출력 스키마
검사 Agent는 공통 Finding 스키마로 반환한다(루트 CLAUDE.md 참조). Finding·Document 등 공통 타입은 `modules.shared`.

## 의존성
- 외부 패키지: 표준 라이브러리(zipfile·xml·csv·json). PDF 표 추출 시 pdfplumber.
- 모듈 의존: `shared`.

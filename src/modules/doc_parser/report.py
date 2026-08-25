"""테스트셋 전체를 공통 문서 모델로 파싱하고 manifest(정답)와 대조해 리포트한다.

DocumentModel 기반으로 채점한다:
  - 페이지 분류(스캔 페이지 집합) 정확도  ← meta.scanned_pages vs 정답
  - 표 블록 유무                          ← TABLE 블록 존재 vs 정답 table
  - 중첩표                                ← TABLE.nested_tables (진짜 중첩만 True로 채점,
                                             빈 값이면 항상 '미채점' — Docling 경로의 span
                                             휴리스틱은 실제 문서에서 25% 오탐이 확인돼
                                             폐기했다, docling_adapter.py 모듈 docstring 참조)
  - 워터마크 후보                          ← meta.watermark_candidates
  - 권한 제한 문서 열림·파싱               ← opened + 텍스트 존재
"""
from __future__ import annotations

import json

from .config import MANIFEST, OUT_DIR, TESTSET_DIR, ensure_dirs
from .model import TABLE
from .router import parse_document


def _mark(ok):
    """채점 결과(True/False/None)를 콘솔 표기(PASS/FAIL/-)로 변환. None="미채점"."""
    return "  -  " if ok is None else (" PASS" if ok else " FAIL")


def main() -> None:
    """PoC 엔트리포인트(run_poc.py)의 마지막 단계 — 테스트셋 11개 전부를
    doc_parser.parse_document() 로 파싱하고, manifest.json 의 정답과 대조해 콘솔에
    리포트를 출력한다. 파일별 상세 결과는 data/out/*.json 으로도 저장한다."""
    ensure_dirs()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    truths = {t["filename"]: t for t in manifest["files"]}

    totals = {k: [0, 0] for k in ("classify", "table", "nested", "watermark", "open")}
    rows = []

    for fn, truth in truths.items():
        # 실제 파싱 호출 — pdf-inspector 분류/추출 →
        # (등록됐다면)PaddleOCR/Docling 훅 순으로 내부 실행됨.
        # ocr=False: run_poc.py 의 --ocr 플래그로만 켜지게 유지(합성 테스트셋 빠른 반복 우선,
        # parse_document() 기본값 ocr=True 의 자동등록은 이 PoC 파이프라인엔 적용 안 함).
        doc = parse_document(TESTSET_DIR / fn, password=truth.get("user_pw", "") or "", ocr=False)
        d = doc.to_dict()
        (OUT_DIR / fn.replace(".pdf", ".json")).write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

        opened = d["meta"].get("opened", False)
        meta = d["meta"]

        # 페이지분류: pdf_backend 가 채운 meta.scanned_pages(pdf-inspector 판정)와
        # manifest 정답의 scanned_pages 집합이 정확히 일치하는지
        classify_ok = None
        if opened:
            pred = set(meta.get("scanned_pages", []))
            classify_ok = (pred == set(truth.get("scanned_pages", [])))

        # 표검출: TABLE 타입 블록 존재 유무만 비교(구조 정확도는 별개)
        table_blocks = [b for b in d["blocks"] if b["type"] == TABLE]
        table_ok = (bool(table_blocks) == bool(truth.get("table"))) if opened else None

        # 중첩표: TableData.nested_tables(진짜 재귀 중첩 구조)가 채워진 경우에만 True.
        # PDF 백엔드는 이 필드를 아직 채우지 않으므로(Docling 의 span 근사는 오탐이 확인돼
        # 폐기 — docling_adapter.py 참조) 항상 미채점(None)으로 남는다. False 로 채점해
        # "확인해봤는데 없다"처럼 보이게 하지 않는다 — 확인 자체를 못 하는 것과 다르다.
        nested_ok = None
        if opened and truth.get("nested_table"):
            has_real_nested = any(b.get("table", {}).get("nested_tables") for b in table_blocks)
            nested_ok = True if has_real_nested else None

        # 워터마크: pdf_backend._detect_watermarks() 가 채운 후보 리스트가 비어있지 않은지
        wm_ok = ((len(meta.get("watermark_candidates", [])) > 0)
                 if (opened and truth.get("watermark")) else None)

        # 권한열림: 복사금지 등 권한 플래그가 걸려 있어도 실제 텍스트 블록이 나왔는지
        # (= _normalize() 의 복호화 prestep이 제대로 동작해 콘텐츠가 파싱됐는지 확인)
        open_ok = None
        if truth.get("permission_restricted"):
            has_text = any(b["type"] in ("heading", "paragraph") and b.get("text")
                           for b in d["blocks"])
            open_ok = opened and has_text

        for key, ok in [("classify", classify_ok), ("table", table_ok),
                        ("nested", nested_ok), ("watermark", wm_ok), ("open", open_ok)]:
            if ok is not None:
                totals[key][1] += 1
                totals[key][0] += 1 if ok else 0

        rows.append((fn, truth["title"], classify_ok, table_ok, nested_ok, wm_ok, open_ok,
                     len(d["blocks"]), len(d["warnings"])))

    print("\n" + "=" * 104)
    print("doc_parser PoC 리포트 — 공통 문서 모델 기준  (PASS/FAIL/- =미채점)")
    print("=" * 104)
    print(f"{'파일':22s} {'설명':22s} {'분류':>5s} {'표':>5s} {'중첩':>5s} {'워터':>5s} "
          f"{'권한':>5s} {'blocks':>6s} {'warn':>5s}")
    print("-" * 104)
    for fn, title, c, t, n, w, o, nb, wn in rows:
        title = (title[:20] + "..") if len(title) > 20 else title
        print(f"{fn:22s} {title:22s} {_mark(c):>5s} {_mark(t):>5s} {_mark(n):>5s} "
              f"{_mark(w):>5s} {_mark(o):>5s} {nb:>6d} {wn:>5d}")
    print("-" * 104)
    summ = []
    for key, label in [("classify", "페이지분류"), ("table", "표검출"),
                       ("nested", "중첩표"), ("watermark", "워터마크"), ("open", "권한열림")]:
        ok, tot = totals[key]
        if tot:
            summ.append(f"{label} {ok}/{tot}")
    print("합계: " + "  |  ".join(summ))
    print(f"\n상세 JSON: {OUT_DIR}")


if __name__ == "__main__":
    main()

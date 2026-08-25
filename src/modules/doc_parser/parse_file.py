"""임의의 PDF 1개를 doc_parser로 파싱해 결과를 확인하는 스크립트.
더미 테스트셋(run_poc.py)과 달리 정답(manifest)이 없는 실제 파일을 빠르게 찔러볼 때 쓴다.

사용:
    python parse_file.py <PDF경로>                       # 기본(OCR·Docling 둘 다 자동 ON)
    python parse_file.py <PDF경로> --out result.json
    python parse_file.py <PDF경로> --no-ocr                 # OCR 끄고 빠르게(구조만 확인)
    python parse_file.py <PDF경로> --no-docling             # Docling 끄고 빠르게(pdf-inspector만)
    python parse_file.py <PDF경로> --password 1234         # user 비밀번호 있는 경우

2026-08-04: Docling도 OCR과 같은 이유로 기본 ON으로 바꿨다 — 옵션 켜는 걸 깜빡해서
"pdf-inspector만 돌린, 표 구조도 없고 헤더/풋터도 안 갈리는" 훨씬 나쁜 결과를 최선인
줄 알고 받는 실패가 실제로 있었다(doc_parser/__init__.py의 _ensure_docling 참조).
"""
from __future__ import annotations

import os
import subprocess
import sys

# run_poc.py 와 동일한 이유: --docling 의 수식/코드 enrichment 가 torch.compile() 경로를
# 타면서 CUDA 커널 템플릿을 encoding= 없이 읽어 한국어 Windows(cp949)에서 죽는 걸
# 실측 확인함(PyTorch 쪽 문제). PYTHONUTF8 은 인터프리터 시작 시점에만 적용되므로
# 아직 안 켜져 있으면 켜서 스스로 재실행한다(1회만).
# 실측(2026-08-03): os.execv(Windows)는 인자에 "["가 있으면 명령줄 재구성이 깨져
# "[별지 제8호서식] 지위승계 신고서....hwp" 같은 실제 정부 서식 파일명이 여러 인자로
# 쪼개지는 버그가 있다(CPython 자체 이슈, msvcrt 계열 실행이 subprocess의
# list2cmdline만큼 견고하게 따옴표 처리를 안 함). subprocess.run은 이 문제가 없어
# execv 대신 사용한다.
# 실측(2026-08-06): `-m modules.doc_parser.parse_file` 로 띄우면 sys.argv[0] 이 "-m ..." 이
# 아니라 이 파일의 절대경로라, sys.argv 를 그대로 재실행하면 패키지 컨텍스트를 잃고
# `from . import ...` 가 ImportError(attempted relative import with no known parent
# package)로 죽는다 — README 가 안내하는 명령이 PYTHONUTF8 미설정 환경에서 항상 실패했다.
# -m 실행이면 __spec__.name 에 원래 모듈명이 있으므로 그걸로 다시 -m 실행한다.
if os.environ.get("PYTHONUTF8") != "1":
    os.environ["PYTHONUTF8"] = "1"
    cmd = ([sys.executable, "-m", __spec__.name, *sys.argv[1:]]
           if __spec__ is not None else [sys.executable, *sys.argv])
    raise SystemExit(subprocess.run(cmd).returncode)

import argparse
import json
from pathlib import Path

from .router import parse_document


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF 1개 파싱 테스트")
    parser.add_argument("pdf", type=Path, help="파싱할 PDF 경로")
    parser.add_argument("--password", default="", help="user 비밀번호(있는 경우)")
    parser.add_argument("--no-ocr", action="store_true",
                        help="PaddleOCR 자동 실행 끄기(기본은 이미지 있으면 자동 OCR)")
    parser.add_argument("--no-docling", action="store_true",
                        help="Docling 훅 끄기(기본은 자동 연결 — 표 구조/헤더풋터가 훨씬 나빠짐)")
    parser.add_argument("--out", type=Path, default=None,
                        help="결과 JSON 저장 경로(생략 시 콘솔 요약만)")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"파일을 찾을 수 없습니다: {args.pdf}")
        raise SystemExit(2)

    print(f"파싱: {args.pdf}")
    doc = parse_document(args.pdf, password=args.password,
                            ocr=not args.no_ocr, docling=not args.no_docling)
    d = doc.to_dict()

    print("\n--- meta ---")
    print(json.dumps(d["meta"], ensure_ascii=False, indent=2))

    type_counts: dict[str, int] = {}
    for b in d["blocks"]:
        type_counts[b["type"]] = type_counts.get(b["type"], 0) + 1

    print(f"\n블록 {len(d['blocks'])}개 (타입별: {type_counts}), 경고 {len(d['warnings'])}개")
    for w in d["warnings"]:
        print(f"  경고: {w}")

    if args.out:
        args.out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n상세 결과 저장: {args.out}")
    else:
        print("\n(상세 블록 내용까지 보려면 --out result.json 옵션을 쓰세요)")


if __name__ == "__main__":
    main()

"""doc_parser PoC 엔트리포인트: 테스트셋 생성 → 텍스트 엔진 폴백 게이트 → 파싱 → 리포트.

옵션:
    python run_poc.py               # 전체
    python run_poc.py --no-gen      # 테스트셋 재생성 생략
    python run_poc.py --ocr         # PaddleOCR 훅 연결(스캔 페이지 실제 OCR)
    python run_poc.py --docling     # Docling 훅 연결(표 구조/중첩/그림 복원)
"""
from __future__ import annotations

import os
import subprocess
import sys

# Docling의 수식/코드 enrichment(--docling)가 내부적으로 torch.compile()을 타는데,
# 그 경로에서 PyTorch가 CUDA 커널 템플릿 파일을 encoding= 지정 없이 열어서, 이 PC처럼
# 시스템 로캘이 cp949(한국어 Windows)인 환경에서 UnicodeDecodeError로 죽는다(실측 확인).
# PYTHONUTF8 은 인터프리터 시작 시점에만 적용되는 플래그라 지금 프로세스에서 켜봐야
# 늦으므로, 아직 안 켜져 있으면 켜서 스스로 재실행한다(1회만, 무한루프 방지).
# 실측(2026-08-03): os.execv(Windows)는 인자에 "["가 있으면 명령줄 재구성이 깨져
# "[별지 제8호서식] 지위승계 신고서....hwp" 같은 실제 정부 서식 파일명이 여러 인자로
# 쪼개지는 버그가 있다(CPython 자체 이슈, msvcrt 계열 실행이 subprocess의
# list2cmdline만큼 견고하게 따옴표 처리를 안 함). subprocess.run은 이 문제가 없어
# execv 대신 사용한다.
# 실측(2026-08-06): `-m modules.doc_parser.run_poc` 로 띄우면 sys.argv[0] 이 "-m ..." 이
# 아니라 이 파일의 절대경로라, sys.argv 를 그대로 재실행하면 패키지 컨텍스트를 잃고
# `from . import ...` 가 ImportError 로 죽는다. -m 실행이면 __spec__.name 에 원래 모듈명이
# 있으므로 그걸로 다시 -m 실행한다.
if os.environ.get("PYTHONUTF8") != "1":
    os.environ["PYTHONUTF8"] = "1"
    cmd = ([sys.executable, "-m", __spec__.name, *sys.argv[1:]]
           if __spec__ is not None else [sys.executable, *sys.argv])
    raise SystemExit(subprocess.run(cmd).returncode)

from . import generate_testset, report
from .config import TESTSET_DIR
from .router import (
    check_cid_quality,
    register_docling,
    register_ocr,
    set_text_engine,
)


def main() -> None:
    if "--no-gen" not in sys.argv:
        print("[1/4] 더미 PDF 테스트셋 생성 ...")
        generate_testset.main()

    print("\n[2/4] 텍스트 엔진 폴백 게이트 — pdf-inspector 한글(CID) 추출 품질 검증 ...")
    text_pdfs = [str(TESTSET_DIR / f) for f in
                 ("01_simple_text.pdf", "02_multicolumn.pdf", "11_long.pdf")]
    gate = check_cid_quality(text_pdfs)
    print(f"    한글 추출 비율(pdf-inspector/PyMuPDF) = {gate.ratio:.3f} → "
          f"{'PASS' if gate.passed else 'FAIL'}")
    if not gate.passed:
        print("    FAIL → TEXT_ENGINE=pymupdf 로 전환(라우팅 구조는 유지)")
        set_text_engine("pymupdf")

    if "--ocr" in sys.argv:
        print("\n[3/4] PaddleOCR 훅 연결 ...")
        from .ocr_paddle import make_ocr_lines_hook
        register_ocr(make_ocr_lines_hook(lang="korean"))
    else:
        print("\n[3/4] PaddleOCR 훅 미연결(--ocr 로 활성화)")

    if "--docling" in sys.argv:
        print("\n[3b/4] Docling 훅 연결 ...")
        from .docling_adapter import make_docling_hook
        register_docling(make_docling_hook())
    else:
        print("\n[3b/4] Docling 훅 미연결(--docling 로 활성화)")

    print("\n[4/4] 파싱 + 리포트 ...")
    report.main()


if __name__ == "__main__":
    main()

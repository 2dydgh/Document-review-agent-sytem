"""공통 경로/디바이스/폰트 설정.

경로·연산 디바이스는 **환경변수로 주입**하고 코드에는 저장소 구조나 GPU 번호를 두지
않는다(CLAUDE.md "코드에 GPU 번호·서버 주소 하드코딩 금지, 기준은 항상 주입받는다").

    DOC_PARSER_TESTSET   더미 PDF·실문서가 있는 입력 폴더
    DOC_PARSER_OUT       파싱 결과 JSON·리포트 출력 폴더
    DOC_PARSER_DEVICE    OCR·구조복원 모델을 올릴 디바이스
                         auto(기본) | cpu | cuda | cuda:N | mps | xpu  (gpu = cuda 별칭)

경로가 미설정이면 **모듈 자기 폴더 기준**으로 떨어진다 — 이 폴더를 통째로 다른
프로젝트에 복사해도 그대로 동작해야 하기 때문(모듈 README "모듈만 떼어 쓸 때" 참조).
DocSuree 에서는 작업용 데이터가 git 밖(`local(작업용)/`)에 있으므로 환경변수로 지정한다.

디바이스가 미설정(auto)이면 각 엔진의 자체 자동 감지에 맡긴다. 배포에서는
docker-compose 의 `environment:` 로 주입해 "마이그레이션 = 설정 교체"가 되게 한다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# 모듈 자기 폴더 — 폴더째 복사해도 기준이 따라오도록 이 파일 위치를 쓴다.
ROOT = Path(__file__).resolve().parent

TESTSET_DIR = Path(os.environ.get("DOC_PARSER_TESTSET") or (ROOT / "testset"))
OUT_DIR = Path(os.environ.get("DOC_PARSER_OUT") or (ROOT / "out"))
MANIFEST = TESTSET_DIR / "manifest.json"

# 디바이스 정규형은 Docling/torch 표기(cuda)를 따르고, PaddleOCR 표기(gpu)로는
# ocr_device() 가 변환해 준다. 엔진마다 이름만 다를 뿐 같은 물건을 가리킨다.
_DEVICE_RE = re.compile(r"^(auto|cpu|mps|xpu|cuda(:\d+)?)$")
DEVICE = (os.environ.get("DOC_PARSER_DEVICE") or "auto").strip().lower()
if DEVICE.startswith("gpu"):
    DEVICE = DEVICE.replace("gpu", "cuda", 1)
if not _DEVICE_RE.match(DEVICE):
    # 조용히 CPU 로 떨어지면 "GPU 서버에 배포했는데 왜 느리지"를 아무도 못 찾는다.
    raise ValueError(
        f"DOC_PARSER_DEVICE 값이 올바르지 않습니다: {DEVICE!r} "
        "(auto | cpu | cuda | cuda:N | gpu | gpu:N | mps | xpu)"
    )


def ocr_device() -> str | None:
    """PaddleOCR 표기의 디바이스("cpu"/"gpu"/"gpu:0"). auto 면 None —
    PaddleOCR 은 device=None 을 받으면 자체 기본 디바이스를 고른다(자동 감지 유지)."""
    return None if DEVICE == "auto" else DEVICE.replace("cuda", "gpu")


def docling_device() -> str:
    """Docling AcceleratorOptions 표기("auto"/"cpu"/"cuda[:N]"/"mps"/"xpu") — 정규형 그대로."""
    return DEVICE

# 한글 렌더용 폰트 (Windows 기본). 없으면 첫 후보로 fallback.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    r"C:\Windows\Fonts\batang.ttc",
]


def korean_font() -> str | None:
    """설치된 한글 TrueType 폰트 경로를 후보 목록 순서대로 찾아 반환.
    generate_testset.py 가 더미 PDF에 한글을 그릴 때 사용(없으면 PDF 내장 CID 폰트로
    대체되는데, 이 경우 pdf-inspector 가 텍스트 추출에 실패하는 것으로 확인됨)."""
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def ensure_dirs() -> None:
    """testset/out 출력 폴더가 없으면 생성. run_poc.py 실행 초입에서 호출."""
    TESTSET_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

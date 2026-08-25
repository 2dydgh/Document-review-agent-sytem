"""테스트 공용 헬퍼.

`tests/data/` (커밋되는 시험용 픽스처)와 루트 `data/` (커밋되지 않는 실문서)는
다른 것이다. 여기 있는 sample() 은 후자를 다룬다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.doc_parser.ingestion import base as _ingestion_base

_ROOT = Path(__file__).resolve().parent.parent
DATA = _ROOT / "data"

# LLM 주소를 환경변수로도 받으므로(app/config.py), 개발자 셸에 그 값이 있으면
# 설정 파일을 읽는 테스트가 사람마다 다르게 돌아간다. 전부 지우고 시작한다 —
# 환경변수를 시험하는 테스트는 monkeypatch 로 직접 넣는다.
_LLM_ENV = ("LLM_QWEN_URL", "LLM_QWEN_MODEL", "LLM_QWEN_LABEL", "LLM_OCR_URL", "LLM_API_KEY")


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolate_extra_loaders(monkeypatch):
    """app.parser_bridge.install_trkim_parser() 는 실제 서버/CLI 기동 코드다.

    tests/test_cli_integration.py 등이 app.cli.main() 을 그대로 호출하면 이
    함수가 `ingestion_base.EXTRA_LOADERS`(진짜 전역 리스트)에 TrkimLoader 를
    영구히 꽂는다 — 되돌리는 코드가 없다. 이후 같은 pytest 프로세스에서 도는
    모든 .pdf/.docx/.hwpx/.hwp 로딩이 그 로더를 거치게 되어, 순서상 나중에 도는
    tests/test_ingestion_pdf_outline.py 가 실제로 원인이 아닌 자기 파일 안에서
    실패했다(단독 실행은 통과, 전체 스위트만 실패). 매 테스트마다 리스트를
    복사해 두고 monkeypatch 가 되돌리게 하면 어느 테스트가 무엇을 꽂든 다음
    테스트로 새지 않는다.
    """
    monkeypatch.setattr(_ingestion_base, "EXTRA_LOADERS",
                        list(_ingestion_base.EXTRA_LOADERS))


def sample(name: str) -> Path | None:
    """실문서를 파일 이름으로 찾는다 — data/ 하위 어디에 있든. 없으면 None.

    고정 경로를 박아두면 안 된다. data/ 는 gitignore 대상이라 기계마다 유무가 다른데,
    팀별 폴더(에너지검증팀/·형식확인용예시파일/)로 정리되면서 경로가 바뀌었고 테스트는
    그대로였다. skipif 로 감싸여 있어 에러도 안 났다 — 파일이 멀쩡히 있는데도 .hwp
    로더와 PDF 실문서 검증 12개가 조용히 skip 되고 있었다. 이름으로 찾으면 폴더를
    다시 정리해도 안 깨진다.
    """
    if not DATA.is_dir():
        return None
    direct = DATA / name
    if direct.exists():
        return direct
    return next(iter(sorted(DATA.rglob(name))), None)

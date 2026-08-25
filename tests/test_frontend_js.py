"""프론트엔드 순수 로직은 Node 내장 테스트 러너로 돌린다.

이 저장소는 `pytest` 한 번으로 전부 도는 게 관례라 여기서 감싼다. node가 없으면
skip한다 — 백엔드만 건드리는 사람이 Node를 깔 이유는 없다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_TESTS = ROOT / "web" / "tests"


@pytest.mark.skipif(shutil.which("node") is None, reason="node가 없다")
def test_frontend_pure_logic_passes() -> None:
    # node --test 에 디렉터리를 주면(Node 26) 모듈로 실행하려 든다 — 파일을 명시한다.
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.js"))
    assert files, "frontend/tests 에 *.test.js 가 없다 — 테스트가 무의미하다"
    # encoding 지정 필수: node --test 리포터가 유니코드 체크마크(✔)를 UTF-8로
    # 찍는데, 인코딩을 안 주면 시스템 로캘(한국어 Windows는 cp949)로 디코드하다
    # 실패한다. 그 디코드는 stdout/stderr 를 읽는 백그라운드 스레드 안에서 일어나
    # 예외가 조용히 묻히고(PytestUnhandledThreadExceptionWarning), 그 스레드는
    # fh.close() 까지 못 가 파이프 핸들이 새 나간다 — 전체 스위트에서만 보이던
    # 산발적 실패의 근원.
    proc = subprocess.run(
        ["node", "--test", *files],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

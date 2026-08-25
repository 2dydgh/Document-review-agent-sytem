"""변환이 시한을 넘기면 **껍데기가 아니라 그 아래 프로세스까지** 죽는다.

`/usr/bin/soffice` 는 껍데기고 진짜 일은 `soffice.bin` 이 한다.
`subprocess.run(timeout=…)` 은 직접 자식만 죽이므로 soffice.bin 이 고아로 남는다.

실측(2026-08-21): 그렇게 남은 soffice.bin 하나가 **22일**을 돌았고, 그 검토
스레드가 끝나지 못해 업로드 원본(6MB)까지 22일간 /tmp 에 남았다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from modules.doc_parser import convert


def test_시한을_넘기면_손자_프로세스까지_죽는다(tmp_path: Path, monkeypatch) -> None:
    """껍데기 셸이 자식을 낳고 기다리는 모양을 그대로 만든다."""
    monkeypatch.setattr(convert, "_TIMEOUT", 1)
    # sh 가 sleep 을 백그라운드로 낳고 자신도 기다린다 — soffice → soffice.bin 과 같은 꼴.
    marker = tmp_path / "pid"
    script = f"sleep 300 & echo $! > {marker}; wait"

    with pytest.raises(convert.ConvertTimeout):
        convert._run_soffice(["/bin/sh", "-c", script], tmp_path)

    child = int(marker.read_text().strip())
    for _ in range(50):                       # killpg 가 반영될 틈을 준다
        if not _alive(child):
            break
        time.sleep(0.1)
    assert not _alive(child), f"손자 프로세스 {child} 가 살아남았다"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 좀비는 살아 있는 것으로 안 센다 — 부모가 거둬가면 사라진다.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def test_시한_초과는_폴백_대상이_아니다() -> None:
    """hwpx 는 변환 실패 시 텍스트 재현본으로 물러선다. 하지만 시한 초과는
    soffice 가 물렸다는 뜻이라 폴백도 같은 시한을 한 번 더 쓴다(2분 + 2분).
    폴백 handler 가 잡는 예외 계열에 들어가면 안 된다."""
    assert not issubclass(convert.ConvertTimeout, RuntimeError)
    assert not issubclass(convert.ConvertTimeout, subprocess.CalledProcessError)
    assert issubclass(convert.ConvertTimeout, convert.ConvertUnavailable)


def test_새_세션에서_돈다() -> None:
    """그룹째 죽이려면 먼저 우리 그룹에서 떼어놔야 한다 — 안 그러면 killpg 가
    서버 자신까지 죽인다."""
    src = Path(convert.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _run_soffice("):src.index("def _soffice_to_pdf(")]
    assert "start_new_session=True" in body, "soffice 가 서버와 같은 프로세스 그룹에서 돈다"
    assert "os.killpg" in body, "껍데기만 죽이고 있다"
    assert signal.SIGKILL is not None

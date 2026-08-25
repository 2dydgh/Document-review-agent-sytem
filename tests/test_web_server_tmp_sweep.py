"""죽은 서버가 남긴 업로드 임시 폴더를 서버가 뜰 때 걷는다.

업로드 원본은 임시 폴더에 풀리고, 검토가 끝나면 청소 스레드가 지운다. 그런데
그 스레드는 daemon 이라 **서버가 죽으면 같이 죽는다** — 지우지 못한 폴더를 그
뒤로 아무도 다시 보지 않았다.

실측(2026-08-21): /tmp 에 8/13·8/14 업로드분 세 벌이 남아 있었고 안에는
시험의뢰서·성적서 같은 실무 원본 20MB 가 그대로였다. 권한이 700 이라 남이
읽지는 못해도, 여러 계정이 붙는 서버에 오래 둘 물건이 아니다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from app.server import _TMP_MAX_AGE_S, _sweep_stale_uploads  # noqa: E402


def _aged(path: Path, seconds: float) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "원본.docx").write_bytes(b"x")
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def test_오래된_업로드_폴더를_지운다(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    stale = _aged(tmp_path / "docreview-case-old", _TMP_MAX_AGE_S + 60)
    stale_single = _aged(tmp_path / "docreview-single", _TMP_MAX_AGE_S + 60)

    _sweep_stale_uploads()

    assert not stale.exists() and not stale_single.exists()


def test_도는_검토의_폴더는_안_지운다(tmp_path, monkeypatch) -> None:
    """검토 1건은 최대 5분이다(CLAUDE.md 성능 스펙) — 갓 만든 폴더를 지우면
    도는 검토에서 원본이 사라진다."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    fresh = _aged(tmp_path / "docreview-case-now", 60)

    _sweep_stale_uploads()

    assert fresh.exists(), "도는 검토의 원본을 지웠다"


def test_남의_폴더는_건드리지_않는다(tmp_path, monkeypatch) -> None:
    """접두사가 다른 것은 우리 것이 아니다. /tmp 는 모두의 자리다."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    other = _aged(tmp_path / "vscode-typescript1003", _TMP_MAX_AGE_S + 60)

    _sweep_stale_uploads()

    assert other.exists(), "남의 임시 폴더를 지웠다"


def test_못_지워도_서버는_뜬다(tmp_path, monkeypatch) -> None:
    """남의 계정 것이면 rmtree 가 실패한다. 그것 때문에 서버가 안 뜨면 안 된다."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    _aged(tmp_path / "docreview-locked", _TMP_MAX_AGE_S + 60)

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr("pathlib.Path.stat", boom)
    _sweep_stale_uploads()          # 예외가 새어 나오면 여기서 실패한다

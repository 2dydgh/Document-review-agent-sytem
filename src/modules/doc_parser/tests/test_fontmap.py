"""없는 글꼴을 무엇으로 대신할지 — LibreOffice 에 줄 fontconfig 규칙.

왜 필요한가: 사내 문서는 맑은 고딕·굴림·바탕을 쓰는데 리눅스 서버에는 없다.
LibreOffice 는 "대신 뭘 쓸지"를 모르면 아무거나 고르고, 글자폭이 달라져 줄바꿈과
쪽수가 원본과 어긋난다(실측: 사내 문서 22개 중 쪽수가 맞는 것이 13개뿐이었다).

여기서는 XML 이 규칙대로 만들어지는지만 본다 — LibreOffice 없이 돌아야 한다.
"""
from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from modules.doc_parser.convert import _FONT_ALIASES, _font_env, fontconfig_xml


def test_xml_is_well_formed() -> None:
    """깨진 XML 을 주면 fontconfig 가 규칙을 통째로 버린다 — 조용히."""
    body = fontconfig_xml()
    ET.fromstring(body[body.index("<fontconfig>"):])


def test_system_config_is_included() -> None:
    """시스템 설정을 안 물려받으면 글꼴 경로를 잃어 아무 글꼴도 못 찾는다."""
    assert "/etc/fonts/fonts.conf" in fontconfig_xml()


def test_uses_alias_not_strong_binding() -> None:
    """**핵심 계약.** alias/prefer 는 요청한 글꼴을 앞에 두므로 진짜가 있으면 진짜가
    이긴다. assign+strong 으로 갈아끼우면 진짜 맑은 고딕이 깔려 있어도 대체본이
    쓰인다 — 글꼴을 설치한 보람이 사라진다(실측으로 확인했다).
    """
    body = fontconfig_xml()
    assert 'binding="strong"' not in body
    assert "<alias>" in body and "<prefer>" in body


@pytest.mark.parametrize("name", ["맑은 고딕", "굴림", "바탕", "HY헤드라인M"])
def test_documents_actual_fonts_are_covered(name: str) -> None:
    """사내 문서 24개를 훑어 실제로 쓰이는 글꼴 목록에서 뽑은 것들이다."""
    assert name in fontconfig_xml()


def test_gothic_and_serif_go_to_different_targets() -> None:
    """바탕(명조)을 고딕으로 대체하면 문서에서 갈라 쓰던 두 글꼴이 한 몸이 된다."""
    gothic = _FONT_ALIASES["Noto Sans CJK KR"]
    serif = _FONT_ALIASES["Noto Serif CJK KR"]
    assert "맑은 고딕" in gothic and "바탕" in serif
    assert not (set(gothic) & set(serif)), "같은 글꼴이 양쪽에 있으면 뒤엣것이 이긴다"


def test_font_env_points_at_a_written_file(tmp_path: Path) -> None:
    env = _font_env(tmp_path)
    conf = Path(env["FONTCONFIG_FILE"])
    assert conf.is_file()
    assert "<alias>" in conf.read_text(encoding="utf-8")
    # 시스템 환경을 지우면 soffice 가 PATH·HOME 을 잃는다.
    assert set(os.environ) <= set(env)


def test_font_env_survives_an_unwritable_dir(tmp_path: Path) -> None:
    """파일을 못 써도 변환은 돌아야 한다. 규칙이 없을 뿐이다."""
    blocked = tmp_path / "nope"
    blocked.write_text("파일이라 하위 경로를 못 만든다")
    env = _font_env(blocked)
    assert "FONTCONFIG_FILE" not in env


@pytest.mark.skipif(not __import__("shutil").which("fc-match"),
                    reason="fontconfig 도구가 없는 환경")
def test_real_font_wins_over_the_substitute(tmp_path: Path, monkeypatch) -> None:
    """진짜로 깔린 글꼴은 대체되지 않는다 — fc-match 로 확인한다.

    이 프로젝트가 이 규칙을 넣는 이유가 "없을 때만 대신"이라서, 있는 것까지
    바꿔버리면 규칙이 해를 끼친다. 나중에 사내 글꼴을 서버에 깔면 그때 이
    검사가 값을 한다.
    """
    installed = subprocess.run(["fc-list", "--format", "%{family[0]}\\n"],
                               capture_output=True, text=True).stdout.split("\n")
    have = sorted({f.strip().split(",")[0] for f in installed if f.strip()})
    if len(have) < 2:
        pytest.skip("서로 다른 설치 글꼴이 둘 이상 필요하다")
    target, source = have[:2]
    missing = "DocSuree Definitely Missing Font"
    monkeypatch.setattr(
        "modules.doc_parser.convert._FONT_ALIASES",
        {target: (source, missing)})
    env = _font_env(tmp_path)

    real = subprocess.run(
        ["fc-match", "--format", "%{family[0]}", source],
        capture_output=True, text=True, env=env).stdout
    substitute = subprocess.run(
        ["fc-match", "--format", "%{family[0]}", missing],
        capture_output=True, text=True, env=env).stdout

    assert real == source, f"있는 글꼴 {source!r} 이 {real!r} 로 바뀌었다"
    assert substitute == target, f"없는 글꼴이 {target!r} 대신 {substitute!r} 로 갔다"

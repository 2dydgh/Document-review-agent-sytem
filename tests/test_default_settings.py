"""저장소에 커밋된 기본 설정이 실제 문서를 향하는지 지킨다.

겪은 사고(두 번):
  1. 기본 설정이 데모용 체크리스트(id_pattern: SR-\\d+)를 가리키고 있었다.
  2. 그 뒤 기본값이 acmd.yaml 을 가리켰는데 그것도 실문서가 아니었다.
둘 다 증상이 같다 — 패턴이 안 맞아 요건 ID를 0개 찾는데, **오류가 아니라
"0건"이 뜬다.** 검토를 통과한 것처럼 보인다.

예전에는 실제 ID 문자열을 이 파일에 박아두고 대조했지만, 그 문자열 자체가
가짜 데이터에서 온 것이었다(RQ-SFR-PR-01-001). 실문서는 `data/` 에 있고
gitignore 라 테스트가 의존할 수 없다. 그래서 특정 문서의 ID를 박는 대신
**어떤 문서군에도 성립하는 불변식**을 지킨다:

  - 배포 설정은 검토 기준을 아예 박아두지 않는다.
  - 기준이 요건 ID 형식을 적었다면 그 정규식은 자기 id_example 을 잡아낸다.

세 번째 사고가 첫 불변식을 바꿨다 — 기본값이 shn34-esf-ccs.yaml 을 가리켰는데,
그건 실문서 기반이긴 해도 **개발 중에 한 번 올라온 문서를 보고 거꾸로 뽑은 값**
이었다. 반드시 하나를 가리켜야 한다는 요구 자체가 원인이었으므로, 이제 아무것도
가리키지 않는다. 기준은 3층(공통·팀별·업로드)에서만 온다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import load_config

_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS = sorted((_ROOT / "config").glob("settings*.toml"))

def test_settings_files_exist():
    assert _SETTINGS, "config/settings*.toml이 하나도 없다"


@pytest.mark.parametrize("path", _SETTINGS, ids=lambda p: p.name)
def test_shipped_settings_do_not_pin_a_checklist(path):
    """배포 설정은 검토 기준을 박아두지 않는다.

    예전 불변식은 "설정에 id_pattern 이 있어야 한다"였다. 그 보증이 곧 사고의
    원인이었다 — 반드시 하나를 가리켜야 하니 **한 번 올라온 문서에서 뽑은
    잣대**가 전 문서의 기본값이 됐고, 다른 계통에는 한 개도 안 걸리면서 화면엔
    "0건"이 떴다. 지금은 팀 기준을 골라야 잣대가 정해진다(아래 테스트).
    """
    assert not load_config(path).checklist_path, (
        f"{path.name}: 검토 기준이 박혀 있다. 기준은 3층(공통·팀별·업로드)에 두고 "
        "화면이 고르게 한다(POST /api/detect).")


def test_criteria_params_pattern_matches_its_own_example():
    """기준이 요건 ID 형식을 적었다면, 그 정규식이 자기 예시를 실제로 잡는다.

    화면은 검토자에게 정규식이 아니라 id_example 을 보여준다. 둘이 어긋나면
    화면이 거짓말을 한다.

    **값이 하나도 없어도 통과다.** 지금 어느 팀 기준도 ID 형식을 적지 않는다 —
    전부 "요구사항 ID 목록을 추출한다"까지만 말한다. 부여 규칙이 있다고 전제는
    하지만(AI신뢰성1 no.1 "식별자 번호 부여 규칙을 기반으로", EV2 no.41
    "IS24-GDL-0000 문서 표준화 가이드 참고") 그 내용이 xlsx 에 안 실려 씨앗에
    안 들어왔다. 규정에서 값을 받아 채우면 이 시험이 그때부터 지킨다.
    """
    for f in sorted((_ROOT / "presets" / "criteria").rglob("*.y*ml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for item in spec.get("items", []) or []:
            params = item.get("params") or {}
            pattern, example = params.get("id_pattern"), params.get("id_example")
            if not pattern:
                continue
            assert example, f"{f.name} no.{item.get('no')}: id_pattern 만 있고 예시가 없다"
            assert re.search(pattern, example), (
                f"{f.name} no.{item.get('no')}: "
                f"id_pattern이 자기 예시 '{example}'를 못 잡는다")

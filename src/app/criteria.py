"""단일 검토 한 건에 쓸 기준 조립. 웹과 CLI가 **같은 것**을 쓴다.

전에는 웹(`/api/review`)만 팀 기준과 칸 값 검사기를 붙이고, CLI(`docsuree review`)는
`team=None` 을 박아둬 늘 공통 기준만 돌았다. 같은 문서를 두 경로로 넣으면 다른 결과가
나왔고, 어느 쪽이 맞는지는 코드를 열어야 알 수 있었다. 조립을 여기 하나로 모은다.

빈 팀 기준을 드러내는 자리이기도 하다. `presets/criteria/teams/` 에는 `items: []` 인
껍데기가 있는데(우주항공SW기술팀 등), 그 팀을 골라도 붙는 기준이 하나도 없어 결과가
**팀을 아예 안 고른 것과 한 글자도 다르지 않았다.** 그런데 화면은 그 사실을 말하지
않아 "우리 팀 기준으로 검토했더니 이상 없음"으로 읽혔다 — CLAUDE.md 가 금지한 조용한
0건이다. 가드를 호출부마다 달면 이번처럼 한쪽이 빠지므로 조립하는 여기에 단다.
"""
from __future__ import annotations

from pathlib import Path

from modules.preset import compose_review_preset
from modules.shared import Anchor, Finding, Severity


class UnknownTeam(ValueError):
    """열거된 목록에 없는 팀 이름.

    브라우저가 보낸 문자열로 경로를 만들면 서버의 아무 파일이나 읽게 된다
    (`../../etc/passwd`). 그래서 경로를 조립하지 않고 열거한 목록에서만 찾는다.
    """


def team_spec(seed_root: Path, team: str) -> dict:
    """팀 id → 기준 파일 내용(원본 dict). 목록에 없는 이름은 거절한다.

    **glob 은 `load_presets` 와 같아야 한다.** 여기서 `*.y*ml` 로 넓게 잡으면
    `team.yml` 이 검증은 통과하는데 조립(`compose_review_preset` → `load_presets`,
    `*.yaml`)에서는 안 잡혀, 팀을 골랐는데 기준이 하나도 안 붙는다. 이 저장소가
    계속 막아 온 조용한 0건이다.

    Preset(`load_presets` 가 만드는 것)이 아니라 원본 dict 를 돌려주는 이유는
    `outputs` 때문이다 — 칸 값 지도는 Preset 에 실리지 않는다(`_read` 가 버린다).
    """
    import yaml  # noqa: PLC0415

    for f in sorted((Path(seed_root) / "teams").glob("*.yaml")):
        if f.stem == team:
            return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    raise UnknownTeam(f"그런 팀 기준이 없습니다: {team}")


def _unreviewed(message: str, suggestion: str, checker: str = "review") -> Finding:
    """검사를 못 했다는 보고. 지적(문제 발견)이 아니다 — unreviewed 로 갈라 둔다."""
    return Finding(checker=checker, severity=Severity.INFO, message=message,
                   anchor=Anchor(page=None, section=None),
                   suggestion=suggestion, unreviewed=True)


def criteria_for_single_review(seed_root: Path, team: str,
                               uploaded=None) -> tuple[list, list[Finding]]:
    """단일 검토의 합쳐진 기준과, 기준 자체에 관한 미검토 보고.

    공통 ∪ 팀 ∪ 선택 업로드 기준을 한 번만 조립한다. 팀 기준이 빈 경우처럼 문서를
    읽기 전에도 알 수 있는 보고만 여기서 만든다. 산출물 식별·필드맵 보고는 파일명을
    아는 호출부가 별도로 붙인다.
    """
    seed_root = Path(seed_root)
    notices: list[Finding] = []
    spec: dict = {}
    if team:
        spec = team_spec(seed_root, team)

    preset = compose_review_preset(seed_root, uploaded, team=team or None)
    if team and not (spec.get("items") or []) and not spec.get("outputs"):
        name = spec.get("name") or team
        notices.append(_unreviewed(
            f"{name}은 검토 기준이 아직 비어 있어, 이 문서를 공통 기준으로만 "
            "검토했습니다. 팀 기준에 걸리는 지적은 여기 없습니다.",
            "팀 기준에 검토 항목을 먼저 채워야 합니다(관리자 문의)."))
    return list(preset.items), notices


def for_single_review(seed_root: Path, team: str, filename: str,
                      uploaded=None) -> tuple[list, tuple, list[Finding]]:
    """단일 검토 한 건의 (기준 items, 추가 검사기, 미검토 보고).

    - items: 공통 ∪ 팀 ∪ 업로드. 팀을 안 고르면 공통(∪ 업로드)만.
    - 추가 검사기: 팀 기준의 `outputs` 절이 만드는 칸 값 검사기. 파일명으로 산출물을
      못 가리면 안 건다 — 엉뚱한 필드맵으로 검사하면 거짓 지적이 난다.
    - 미검토 보고: 걸지 못한 검사를 말한다. 호출부는 findings 에 그대로 더하면 된다.

    팀 이름이 목록에 없으면 UnknownTeam. 웹은 400으로, CLI는 stderr 로 옮긴다.
    """
    seed_root = Path(seed_root)
    items, notices = criteria_for_single_review(seed_root, team, uploaded)
    spec = team_spec(seed_root, team) if team else {}

    extra: tuple = ()
    if team:
        # 이름·항목수는 spec 에서 바로 읽는다. 예전에는 load_presets 로 디렉터리를
        # 통째로 다시 파싱해 Preset 을 찾았는데, 쓰는 값이 name·item_count 뿐이라
        # 같은 파일을 두 번 읽는 셈이었다. 출처가 둘이면 어느 쪽이 맞는지 코드가
        # 확신하지 못해 `mine.name or spec.name or team` 같은 3단 폴백이 생긴다.
        # Preset._read 도 여기서 읽는 것과 같은 키를 쓴다(name, items).
        if (spec.get("items") or []) or spec.get("outputs"):
            from .case import presence_checker_for  # noqa: PLC0415

            checkers, why = presence_checker_for(filename, spec)
            extra = tuple(checkers) if checkers else ()
            if why:
                notices.append(_unreviewed(
                    why, "파일명에 양식번호를 넣거나 폴더 검토를 쓰세요.",
                    checker="completeness"))

    return items, extra, notices

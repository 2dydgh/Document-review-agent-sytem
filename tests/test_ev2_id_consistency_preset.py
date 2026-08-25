from pathlib import Path

from modules.agent_checklist import mode_for
from modules.preset import load_presets


def test_ev2_repeated_id_consistency_is_a_whole_document_criterion():
    root = Path(__file__).resolve().parents[1] / "presets" / "criteria"
    ev2 = next(p for p in load_presets(root) if p.id == "EV2")
    criterion = next(c for c in ev2.items if str(c.no) == "32")

    assert mode_for(criterion) == "LLM-문서"
    assert "동일 ID가 두 번 이상 등장" in criterion.note
    assert "서로 다른 원문을 근거로" in criterion.note


def test_eis_teams_share_the_same_required_sections():
    """에너지인프라시스템실 3팀(EV1·EV2·EV3)은 같은 문서 표준을 쓴다.

    필수 절 **검사**는 공통 10번이 켜지만 **목록**은 기준이 준다(엔진에 장절
    이름을 박지 않는다). 값이 없으면 그 팀의 모든 검토가 "필수 절 목록이 검토
    기준에 없어 …" 로 뜬다 — EV2 에만 있던 값을 EV1·EV3 에도 넣은 이유다.

    AX안전신뢰실 팀들은 여기 없다. 그 실은 한 팀이 ConOps·SRS·SDD·검토의견서를
    함께 보는데 지금 값은 검토당 하나뿐이라, 뭘 넣어도 다른 문서에서 틀린다.
    """
    from app.config import apply_criteria_params
    from modules.preset import compose_review_preset
    from modules.shared import ReviewConfig

    root = Path(__file__).resolve().parents[1] / "presets" / "criteria"
    want = ["1.0 Purpose", "2.0 Scope", "3.0 References",
            "4.0 Definitions and Abbreviations"]
    for team in ("EV1", "EV2", "EV3"):
        preset = compose_review_preset(root, None, team=team)
        got = apply_criteria_params(ReviewConfig(doc_type=""), preset.items)
        assert got.required_sections == want, team

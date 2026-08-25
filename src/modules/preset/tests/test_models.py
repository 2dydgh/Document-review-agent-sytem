import json
from dataclasses import asdict

from modules.preset import AGENTS, SCOPES, Criterion, Preset


def test_criterion_has_agent_and_defaults():
    c = Criterion(no="1", text="식별자 규칙", agent="형식·완전성")
    assert c.agent == "형식·완전성"
    assert c.mode == ""                # 기본은 미지정 — agent 라벨이 정한다
    assert c.source == ""
    assert c.params == {}


def test_preset_scope_and_team():
    p = Preset(id="x", name="AI신뢰성1팀", source_filename="", registered_at="",
               scope="팀별", team="AI신뢰성1팀")
    assert p.scope == "팀별"
    assert p.team == "AI신뢰성1팀"


def test_old_upload_json_still_loads_without_new_fields():
    # 기존 .docreview JSON 은 새 필드가 없다 — 기본값으로 로드돼야 한다.
    old = {"no": "1", "text": "용어 일관성", "group": "", "note": "", "raw": []}
    c = Criterion(**old)
    assert c.agent == "" and c.params == {}


def test_criterion_json_round_trip():
    c = Criterion(no="2", text="표&그래프", agent="표현·내용품질",
                  mode="조각", source="문서검증 No.3",
                  params={"id_pattern": "FR-"})
    back = Criterion(**json.loads(json.dumps(asdict(c))))
    assert back == c


def test_vocab_lists_present():
    assert "형식·완전성" in AGENTS and "문서작성·생성" in AGENTS
    assert set(SCOPES) == {"공통", "팀별", "업로드"}

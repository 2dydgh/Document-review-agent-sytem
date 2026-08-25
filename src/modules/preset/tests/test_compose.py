from modules.preset import Criterion, Preset, resolve_criteria


def _p(scope, team, texts):
    return Preset(id=scope, name=scope, source_filename="", registered_at="",
                  scope=scope, team=team,
                  items=[Criterion(no=str(i), text=t) for i, t in enumerate(texts)])


def test_union_of_common_team_upload():
    common = _p("공통", "", ["오탈자"])
    team = _p("팀별", "AI신뢰성1팀", ["식별자 규칙"])
    upload = _p("업로드", "", ["임시항목"])
    out = resolve_criteria(common, team, upload)
    assert {c.text for c in out} == {"오탈자", "식별자 규칙", "임시항목"}


def test_duplicate_text_merged_once():
    common = _p("공통", "", ["오탈자"])
    team = _p("팀별", "T", ["오탈자", "식별자"])  # 오탈자 중복
    out = resolve_criteria(common, team, None)
    assert [c.text for c in out].count("오탈자") == 1
    assert [c.text for c in out] == ["오탈자", "식별자"]  # 공통 먼저


def test_upload_optional():
    common = _p("공통", "", ["오탈자"])
    out = resolve_criteria(common, None, None)
    assert [c.text for c in out] == ["오탈자"]


def test_all_none_gives_empty():
    assert resolve_criteria(None, None, None) == []


def test_same_no_in_different_layers_is_split():
    """번호는 파일 안에서만 유일하다. 합칠 때 갈라 놓지 않으면 판정이 섞인다.

    실측: ai-test-cert-1 팀은 공통 16번과 팀 16번이 둘 다 LLM-조각이라, 검토
    파이프라인이 '16' 하나로 접어 한쪽 판정을 다른 쪽에도 얹었다.
    """
    common = Preset(id="공통", name="", source_filename="", registered_at="",
                    scope="공통", items=[Criterion(no="16", text="오탈자")])
    team = Preset(id="T", name="", source_filename="", registered_at="",
                  scope="팀별", items=[Criterion(no="16", text="표준 반영 여부")])
    out = resolve_criteria(common, team, None)
    assert [c.no for c in out] == ["16", "16(팀별)"]
    # 원본 번호를 되짚을 수 있어야 한다 — 다시 매기면 팀 기준서와 대조가 끊긴다.
    assert out[1].text == "표준 반영 여부"


def test_unique_no_is_left_alone():
    common = Preset(id="공통", name="", source_filename="", registered_at="",
                    scope="공통", items=[Criterion(no="9", text="필수 절")])
    team = Preset(id="T", name="", source_filename="", registered_at="",
                  scope="팀별", items=[Criterion(no="19", text="파일명")])
    assert [c.no for c in resolve_criteria(common, team, None)] == ["9", "19"]

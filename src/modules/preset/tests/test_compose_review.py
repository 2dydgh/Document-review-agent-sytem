import yaml

from modules.preset import Criterion, Preset, compose_review_preset


def _seed(root, stem, scope, team, texts, agent=""):
    """씨앗을 심는다. 층은 파일 위치가 정한다 — 공통은 common.yaml, 팀은 teams/ 아래."""
    path = (root / "common.yaml") if scope == "공통" else (root / "teams" / f"{stem}.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "name": stem, "team": team,
        "items": [{"no": str(i), "text": t, "agent": agent}
                  for i, t in enumerate(texts)],
    }, allow_unicode=True), encoding="utf-8")


def test_compose_merges_common_and_upload(tmp_path):
    _seed(tmp_path, "common", "공통", "", ["오탈자"])
    uploaded = Preset(id="u", name="업로드", source_filename="", registered_at="",
                      scope="업로드", items=[Criterion(no="1", text="용어 일관성")])
    merged = compose_review_preset(tmp_path, uploaded)
    assert {c.text for c in merged.items} == {"오탈자", "용어 일관성"}


def test_compose_picks_team(tmp_path):
    _seed(tmp_path, "common", "공통", "", ["오탈자"])
    _seed(tmp_path, "t1", "팀별", "AI신뢰성1팀", ["식별자 규칙"])
    _seed(tmp_path, "t2", "팀별", "AX품질팀", ["템플릿"])
    merged = compose_review_preset(tmp_path, None, team="AI신뢰성1팀")
    texts = {c.text for c in merged.items}
    assert "식별자 규칙" in texts and "템플릿" not in texts  # 고른 팀만


def test_compose_no_seeds_returns_upload_only(tmp_path):
    uploaded = Preset(id="u", name="U", source_filename="", registered_at="",
                      scope="업로드", items=[Criterion(no="1", text="x")])
    merged = compose_review_preset(tmp_path, uploaded)   # 씨앗 없음
    assert [c.text for c in merged.items] == ["x"]


def test_compose_stamps_layer(tmp_path):
    """합친 뒤에도 기준의 출처 층이 남는다 — 공통·팀은 늘 돌지만 업로드는 검토자가
    고른 것이라, 화면이 지적의 출처를 말하려면 여기서 층이 찍혀야 한다."""
    _seed(tmp_path, "common", "공통", "", ["오탈자"])
    _seed(tmp_path, "t1", "팀별", "AI신뢰성1팀", ["식별자 규칙"])
    uploaded = Preset(id="u", name="업로드", source_filename="", registered_at="",
                      scope="업로드", items=[Criterion(no="1", text="용어 일관성")])
    merged = compose_review_preset(tmp_path, uploaded, team="AI신뢰성1팀")
    layers = {c.text: c.layer for c in merged.items}
    assert layers == {"오탈자": "공통", "식별자 규칙": "팀별", "용어 일관성": "업로드"}

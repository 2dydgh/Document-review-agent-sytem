"""씨앗 프리셋 로더. 층은 **파일 위치**가 정한다.

    criteria/common.yaml      → 공통 기준 (모든 팀·문서에 항상 적용)
    criteria/teams/<팀>.yaml  → 팀 기준 (수정·추가 가능)

파일 안의 scope 값을 믿지 않는다 — teams/ 에 둔 파일이 scope: 공통 이라고 적혀
있으면 그건 실수다. 위치가 진실이다.
"""
import yaml

from modules.preset import (Criterion, compose_review_preset, load_presets,
                            save_seed_items)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_공통_기준은_common_yaml_에서_읽는다(tmp_path):
    _write(tmp_path / "common.yaml", {
        "name": "공통 기준",
        "items": [{"no": "1", "text": "오탈자", "agent": "표현·내용품질"}],
    })

    presets = load_presets(tmp_path)

    assert [p.id for p in presets] == ["common"]
    assert presets[0].scope == "공통"
    assert presets[0].items[0].agent == "표현·내용품질"
    assert presets[0].item_count == 1


def test_팀_기준은_teams_아래에서_읽는다(tmp_path):
    _write(tmp_path / "teams" / "ai-test-cert-1.yaml", {
        "name": "AI시험인증1팀",
        "team": "AI시험인증1팀",
        "items": [{"no": "12", "text": "문서 양식 검토", "agent": "형식·완전성"}],
    })

    presets = load_presets(tmp_path)

    assert [p.id for p in presets] == ["ai-test-cert-1"]
    assert presets[0].scope == "팀별"
    assert presets[0].team == "AI시험인증1팀"


def test_위치가_scope_를_정한다(tmp_path):
    # 파일에 적힌 scope 는 무시한다. teams/ 에 있으면 팀별이다.
    _write(tmp_path / "teams" / "wrong.yaml", {"name": "잘못 적힌 것",
                                               "scope": "공통", "items": []})

    assert load_presets(tmp_path)[0].scope == "팀별"


def test_공통과_팀_기준을_함께_읽고_공통이_먼저다(tmp_path):
    # compose 가 공통 → 팀 순으로 합치므로 순서가 뜻을 갖는다.
    _write(tmp_path / "common.yaml", {"name": "공통 기준", "items": []})
    _write(tmp_path / "teams" / "b-team.yaml", {"name": "B", "team": "B", "items": []})
    _write(tmp_path / "teams" / "a-team.yaml", {"name": "A", "team": "A", "items": []})

    assert [p.id for p in load_presets(tmp_path)] == ["common", "a-team", "b-team"]


def test_teams_가_없어도_공통만_읽는다(tmp_path):
    _write(tmp_path / "common.yaml", {"name": "공통 기준", "items": []})

    assert [p.id for p in load_presets(tmp_path)] == ["common"]


def test_빈_디렉터리는_빈_목록(tmp_path):
    assert load_presets(tmp_path) == []


def test_없는_디렉터리는_빈_목록(tmp_path):
    assert load_presets(tmp_path / "nope") == []


def test_씨앗을_다시_써도_손으로_넣은_절은_남는다(tmp_path):
    # xlsx 에서 나오는 것은 items 뿐이다. outputs(문서 지도)는 사람이 문서 구조를
    # 보고 정하는 값이라 스크립트가 만들 수 없다. 재생성이 그걸 지우면 작업물이
    # 통째로 날아간다.
    path = tmp_path / "teams" / "t.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({
        "name": "T", "team": "T",
        "outputs": [{"key": "갑지", "form_no": "SST-K-TP-7-08-06(00)"}],
        "items": [{"no": "1", "text": "옛 항목"}],
    }, allow_unicode=True), encoding="utf-8")

    save_seed_items(path, name="T", team="T",
                    items=[Criterion(no="2", text="새 항목")])

    got = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert got["outputs"] == [{"key": "갑지", "form_no": "SST-K-TP-7-08-06(00)"}]
    assert [i["text"] for i in got["items"]] == ["새 항목"]


def test_없는_파일에_씨앗을_쓰면_새로_만든다(tmp_path):
    path = tmp_path / "teams" / "new.yaml"

    save_seed_items(path, name="새 팀", team="새 팀",
                    items=[Criterion(no="1", text="항목")])

    assert load_presets(tmp_path)[0].team == "새 팀"


def test_여러_줄_설명은_블록으로_쓴다(tmp_path):
    # 한 줄로 접히면 팀이 파일을 고칠 수 없다.
    path = tmp_path / "teams" / "t.yaml"

    save_seed_items(path, name="T", team="T",
                    items=[Criterion(no="1", text="첫 줄\n둘째 줄")])

    assert "|-" in path.read_text(encoding="utf-8")


def test_머리말_주석은_재생성해도_남는다(tmp_path):
    # yaml 을 고른 이유가 주석이다. 재생성이 주석을 지우면 그 이유가 사라진다 —
    # "이 파일이 왜 이렇게 생겼나"를 적어둔 곳이 파일 머리다.
    path = tmp_path / "teams" / "t.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("# 왜 이렇게 생겼나\n# 둘째 줄\nname: T\nitems: []\n",
                    encoding="utf-8")

    save_seed_items(path, name="T", team="T", items=[Criterion(no="1", text="항목")])

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 왜 이렇게 생겼나\n# 둘째 줄\n")
    assert "항목" in text


def test_손으로_쓴_절의_주석은_재생성해도_남는다(tmp_path):
    """실제로 한 번 날아갔다 — ai-test-cert-1.yaml 의 실측 기록 6건.

    머리말만 건지면 부족하다. outputs·case_wide 같은 손으로 쓴 절에 "왜 이 문서를
    뺐나"(실측 근거)가 주석으로 붙어 있고, 그게 이 파일에서 제일 비싼 정보다.
    yaml.safe_load → yaml.dump 왕복은 그 주석을 통째로 버린다.
    """
    path = tmp_path / "teams" / "t.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name: T\n"
        "outputs:\n"
        "- key: 갑지\n"
        "  # 실측: 의뢰번호가 이 문서에 없다(접수번호만). W-의뢰번호에서 뺀 이유다.\n"
        "  form_no: SST-K-TP-7-08-06(00)\n"
        "case_wide:\n"
        "# md 는 전 문서 일치라고 했지만 실측으로 셋은 담고 있지 않다.\n"
        "- id: W-의뢰번호\n"
        "items:\n"
        "- 'no': '1'\n"
        "  text: 옛 항목\n",
        encoding="utf-8")

    save_seed_items(path, name="T", team="T",
                    items=[Criterion(no="2", text="새 항목")])

    text = path.read_text(encoding="utf-8")
    assert "# 실측: 의뢰번호가 이 문서에 없다(접수번호만). W-의뢰번호에서 뺀 이유다." in text
    assert "# md 는 전 문서 일치라고 했지만 실측으로 셋은 담고 있지 않다." in text
    # items 는 갈아끼워진다.
    got = yaml.safe_load(text)
    assert [i["text"] for i in got["items"]] == ["새 항목"]
    assert got["outputs"] == [{"key": "갑지", "form_no": "SST-K-TP-7-08-06(00)"}]


def test_items_가_마지막_절이_아니어도_그_절만_갈아끼운다(tmp_path):
    path = tmp_path / "teams" / "t.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name: T\n"
        "items:\n"
        "- 'no': '1'\n"
        "  text: 옛 항목\n"
        "# 아래는 손으로 쓴 절이다\n"
        "pairs:\n"
        "- id: 1-7\n",
        encoding="utf-8")

    save_seed_items(path, name="T", team="T",
                    items=[Criterion(no="2", text="새 항목")])

    text = path.read_text(encoding="utf-8")
    assert "# 아래는 손으로 쓴 절이다" in text
    got = yaml.safe_load(text)
    assert [i["text"] for i in got["items"]] == ["새 항목"]
    assert got["pairs"] == [{"id": "1-7"}]


def test_빈_필드는_쓰지_않는다(tmp_path):
    path = tmp_path / "teams" / "t.yaml"

    save_seed_items(path, name="T", team="T", items=[Criterion(no="1", text="항목")])

    got = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert got["items"] == [{"no": "1", "text": "항목"}]   # note·raw·agent… 없음


def test_team_is_found_by_file_id_not_only_by_team_field(tmp_path):
    """API·화면은 파일명(id)으로 팀을 고른다. team 값으로만 찾으면 조용히 안 붙는다.

    실재하는 어긋남: ai-test-cert-1.yaml 의 team 은 "AI시험인증1팀"이다.
    """
    (tmp_path / "teams").mkdir()
    (tmp_path / "common.yaml").write_text(
        "name: 공통\nitems:\n- 'no': C-1\n  text: 오탈자\n", encoding="utf-8")
    (tmp_path / "teams" / "ai-test-cert-1.yaml").write_text(
        "name: AI시험인증1팀\nteam: AI시험인증1팀\n"
        "items:\n- 'no': '1'\n  text: 문서 양식 검토\n", encoding="utf-8")

    by_id = compose_review_preset(tmp_path, None, team="ai-test-cert-1")
    by_team = compose_review_preset(tmp_path, None, team="AI시험인증1팀")
    assert [c.text for c in by_id.items] == [c.text for c in by_team.items]
    assert "문서 양식 검토" in [c.text for c in by_id.items]


def test_모르는_키는_무시하고_흔적을_남긴다(tmp_path):
    """오타 키 하나(Criterion(**i) TypeError)가 load_presets 전체 —
    /api/health 포함 대부분의 API를 500으로 만들던 사고 방지 (2026-08-06)."""
    _write(tmp_path / "common.yaml", {
        "name": "공통",
        "items": [{"no": "1", "text": "오탈자", "agent": "표현·내용품질",
                   "checkk": "오타난 키"}],
    })
    presets = load_presets(tmp_path)
    item = presets[0].items[0]
    assert item.no == "1"
    assert "무시된 키: checkk" in (item.note or "")

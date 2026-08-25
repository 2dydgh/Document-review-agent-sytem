from modules.preset import Criterion, ChecklistStore


def test_save_records_scope_and_team(tmp_path):
    st = ChecklistStore(tmp_path)
    p = st.save("AI신뢰성1팀", "req.xlsx", {}, [Criterion(no="1", text="식별자")],
                scope="팀별", team="AI신뢰성1팀")
    got = st.get(p.id)
    assert got.scope == "팀별" and got.team == "AI신뢰성1팀"


def test_old_upload_defaults_to_upload_scope(tmp_path):
    # scope/team 없이 저장한 파일도 로드되면 scope="업로드"
    st = ChecklistStore(tmp_path)
    p = st.save("올린것", "x.csv", {}, [Criterion(no="1", text="t")])
    got = st.get(p.id)
    assert got.scope == "업로드" and got.team == ""


def test_legacy_verdict_method_key_still_loads(tmp_path):
    """예전 버전이 저장한 파일이 필드 이름을 갈았다고 못 열리면 안 된다.

    `verdict_method` 를 `mode` 로 바꾼 뒤 실제로 .docreview/checklists/ 의 파일이
    전부 400 이 됐다 — 등록해 둔 101개짜리 체크리스트를 다시 올리는 것 말고는
    복구할 방법이 없었다.
    """
    import json

    st = ChecklistStore(tmp_path)
    p = st.save("옛날것", "x.xlsx", {}, [Criterion(no="1", text="t")])
    path = tmp_path / f"{p.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for item in raw["items"]:
        item["verdict_method"] = item.pop("mode")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    got = st.get(p.id)
    assert [c.no for c in got.items] == ["1"]

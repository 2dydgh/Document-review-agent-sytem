import json
from datetime import datetime

import pytest

from app.history import HistoryStore, HistoryError


def _compare_payload(a="srs.hwpx", b="sdd.hwpx", findings=3):
    return {
        "docA": {"name": a, "type": "HWPX"},
        "docB": {"name": b, "type": "HWPX"},
        "stats": {"requirements": 12, "matched": 9, "missing": 3},
        "findings": [{"id": i, "msg": f"f{i}"} for i in range(findings)],
        "stages": [],
    }


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history")


def test_save_then_get_returns_the_whole_result(store):
    """목록에서 클릭하면 그때 그 결과가 그대로 복원돼야 한다."""
    payload = _compare_payload()
    entry = store.save("compare", payload)
    assert store.get(entry.id)["payload"] == payload


def test_save_creates_the_directory(tmp_path):
    store = HistoryStore(tmp_path / "nope" / "history")
    store.save("review", {"doc": {"name": "a.md"}, "findings": []})
    assert store.list()


def test_summary_titles_both_kinds(store):
    store.save("compare", _compare_payload("A.hwpx", "B.hwpx", findings=3))
    store.save("review", {"doc": {"name": "solo.md"}, "findings": [{"id": 1}]})
    titles = {e.title: e.findings for e in store.list()}
    assert titles == {"A.hwpx ↔ B.hwpx": 3, "solo.md": 1}


def test_list_is_newest_first(store):
    for i in range(3):
        store.save("compare", _compare_payload(a=f"{i}.hwpx"),
                   now=datetime(2026, 7, 13, 10, i))
    assert [e.title.split(" ")[0] for e in store.list()] == ["2.hwpx", "1.hwpx", "0.hwpx"]


def test_list_respects_limit(store):
    for i in range(5):
        store.save("review", {"doc": {"name": f"{i}.md"}, "findings": []})
    assert len(store.list(limit=2)) == 2


def test_list_on_empty_store_is_empty_not_an_error(store):
    assert store.list() == []


def test_same_second_saves_do_not_collide(store):
    """같은 초에 두 건이 들어와도 덮어쓰면 안 된다."""
    now = datetime(2026, 7, 13, 10, 0, 0)
    a = store.save("review", {"doc": {"name": "a.md"}, "findings": []}, now=now)
    b = store.save("review", {"doc": {"name": "b.md"}, "findings": []}, now=now)
    assert a.id != b.id
    assert len(store.list()) == 2


def test_same_second_saves_keep_their_order(store):
    """실제로 겪은 버그: 비교와 단일 검토를 같은 초에 저장했더니 목록에서 순서가
    뒤집혔다. ID의 시각이 초 단위라, 같은 초 안에서는 뒤의 무작위 해시로 정렬됐다.
    """
    for i in range(6):
        store.save("review", {"doc": {"name": f"{i}.md"}, "findings": []},
                   now=datetime(2026, 7, 13, 10, 0, 0, microsecond=i))
    assert [e.title for e in store.list()] == ["5.md", "4.md", "3.md",
                                               "2.md", "1.md", "0.md"]


def test_delete_removes_only_that_entry(store):
    a = store.save("review", {"doc": {"name": "a.md"}, "findings": []})
    b = store.save("review", {"doc": {"name": "b.md"}, "findings": []})
    store.delete(a.id)
    assert [e.id for e in store.list()] == [b.id]
    with pytest.raises(HistoryError):
        store.get(a.id)


@pytest.mark.parametrize("bad", [
    "../../../etc/passwd",
    "../settings",
    "..%2F..%2Fsecret",
    "20260713T100000000000-deadbeef/../../x",
    "",
    "not-an-id",
])
def test_malicious_ids_are_refused_not_resolved(store, tmp_path, bad):
    """ID는 파일 이름이 된다. 그대로 갖다 붙이면 아무 파일이나 읽거나 지울 수 있다."""
    (tmp_path / "secret.json").write_text('{"x": 1}', encoding="utf-8")
    with pytest.raises(HistoryError):
        store.get(bad)
    with pytest.raises(HistoryError):
        store.delete(bad)
    assert (tmp_path / "secret.json").is_file()


def test_corrupt_file_is_skipped_not_fatal(store):
    """쓰다 만 파일 하나가 목록 전체를 죽이면 안 된다."""
    good = store.save("review", {"doc": {"name": "good.md"}, "findings": []})
    (store.root / "20260713T100000000000-badbadba.json").write_text("{ truncated",
                                                              encoding="utf-8")
    assert [e.id for e in store.list()] == [good.id]


def test_old_entries_are_pruned(tmp_path):
    store = HistoryStore(tmp_path / "h", max_entries=3)
    for i in range(5):
        store.save("review", {"doc": {"name": f"{i}.md"}, "findings": []},
                   now=datetime(2026, 7, 13, 10, i))
    assert [e.title for e in store.list()] == ["4.md", "3.md", "2.md"]
    assert len(list(store.root.glob("*.json"))) == 3


def test_no_partial_file_is_left_behind(store):
    store.save("review", {"doc": {"name": "a.md"}, "findings": []})
    assert not list(store.root.glob("*.tmp"))


def test_unknown_kind_is_refused(store):
    with pytest.raises(HistoryError):
        store.save("nonsense", {})


def test_record_is_readable_json_on_disk(store):
    """사람이 열어볼 수 있어야 한다 — 한글이 \\uXXXX로 깨지지 않게."""
    entry = store.save("compare", _compare_payload("요구사항.hwpx", "설계.hwpx"))
    text = (store.root / f"{entry.id}.json").read_text(encoding="utf-8")
    assert "요구사항.hwpx" in text
    assert json.loads(text)["title"] == "요구사항.hwpx ↔ 설계.hwpx"

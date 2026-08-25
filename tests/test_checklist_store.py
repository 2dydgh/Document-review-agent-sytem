"""등록된 체크리스트 저장소."""
import json
from datetime import datetime, timezone

import pytest

from modules.preset import store as store_module
from modules.preset import Criterion
from modules.preset import ChecklistError, ChecklistStore


def _items(n=2):
    return [Criterion(no=str(i), text=f"항목 {i}", group="가", note="전체",
                          raw=[str(i), "가", f"항목 {i}", "전체"])
            for i in range(1, n + 1)]


def test_save_then_get_round_trips(tmp_path):
    s = ChecklistStore(tmp_path)
    saved = s.save("내부검토", "IS16.pdf", {"text": 2}, _items())
    got = s.get(saved.id)
    assert got.name == "내부검토"
    assert got.source_filename == "IS16.pdf"
    assert [i.text for i in got.items] == ["항목 1", "항목 2"]
    assert got.items[0].raw == ["1", "가", "항목 1", "전체"]


def test_list_is_newest_first(tmp_path):
    s = ChecklistStore(tmp_path)
    a = s.save("가", "a.csv", {}, _items(1))
    b = s.save("나", "b.csv", {}, _items(1))
    assert [c.id for c in s.list()] == [b.id, a.id]


def test_list_does_not_carry_items(tmp_path):
    """목록에 101개 항목을 전부 실어 보낼 이유가 없다. 개수만 있으면 된다."""
    s = ChecklistStore(tmp_path)
    s.save("가", "a.csv", {}, _items(3))
    row = s.list()[0]
    assert row.items == []
    assert row.item_count == 3


def test_delete_removes_it(tmp_path):
    s = ChecklistStore(tmp_path)
    saved = s.save("가", "a.csv", {}, _items(1))
    s.delete(saved.id)
    assert s.list() == []
    with pytest.raises(ChecklistError):
        s.get(saved.id)


def test_unknown_id_raises(tmp_path):
    with pytest.raises(ChecklistError):
        ChecklistStore(tmp_path).get("없는id")


def test_id_from_the_browser_cannot_escape_the_directory(tmp_path):
    """브라우저가 보낸 문자열을 경로로 그대로 쓰면 서버의 아무 파일이나 열게 된다."""
    with pytest.raises(ChecklistError):
        ChecklistStore(tmp_path).get("../../etc/passwd")


def test_saving_without_items_is_refused(tmp_path):
    """항목 없는 체크리스트는 체크할 것이 없다."""
    with pytest.raises(ChecklistError):
        ChecklistStore(tmp_path).save("가", "a.csv", {}, [])


def test_list_uses_filename_as_id_even_if_json_disagrees(tmp_path):
    """list() 는 파일명을 신뢰해야 한다. get()/delete() 는 파일명으로 파일을 찾으므로
    JSON 안에 적힌 id 를 그대로 내보내면(복사·변조된 파일 등으로 둘이 어긋날 때)
    목록에는 있는데 클릭하면 404 나는 항목이 생긴다."""
    s = ChecklistStore(tmp_path)
    saved = s.save("가", "a.csv", {}, _items(1))
    path = tmp_path / f"{saved.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["id"] = "손상된다른아이디123456"  # 파일명과 다른 id 를 흉내
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    listed = s.list()[0]
    assert listed.id == saved.id  # 파일명에서 온 id 여야 한다
    got = s.get(listed.id)  # list() 가 보여준 id 로 실제 조회가 돼야 한다
    assert got.name == "가"


def test_get_wraps_type_error_from_bad_item_shape_as_checklist_error(tmp_path):
    """items 안의 객체가 Criterion 이 모르는 키를 갖고 있으면
    Criterion(**i) 가 TypeError 를 낸다 — bare TypeError 가 아니라 이
    모듈의 계약대로 ChecklistError 로 나와야 한다."""
    s = ChecklistStore(tmp_path)
    saved = s.save("가", "a.csv", {}, _items(1))
    path = tmp_path / f"{saved.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["items"] = [{"이상한_키": "값"}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ChecklistError):
        s.get(saved.id)


def test_get_wraps_attribute_error_from_non_dict_json_as_checklist_error(tmp_path):
    """JSON 자체는 유효해도 최상위가 딕셔너리가 아니면(배열 등) raw.get 이
    AttributeError 를 낸다 — 이것도 bare 예외가 아니라 ChecklistError 로
    나와야 한다."""
    s = ChecklistStore(tmp_path)
    saved = s.save("가", "a.csv", {}, _items(1))
    path = tmp_path / f"{saved.id}.json"
    path.write_text(json.dumps(["딕셔너리가 아니다"]), encoding="utf-8")

    with pytest.raises(ChecklistError):
        s.get(saved.id)


def test_two_stores_in_different_directories_do_not_share_ordering_state(
        tmp_path, monkeypatch):
    """예전 구현은 list() 정렬 키를 만드는 시계가 클래스 변수였다 — 한 저장소의
    시각이 (NTP 보정 등으로) 미래로 밀리면 완전히 무관한 디렉터리를 가리키는
    다른 ChecklistStore 인스턴스까지 그 영향을 받았다. 지금은 상태가 전혀 없어야
    하므로, 한쪽 저장소가 미래 시각으로 저장해도 다른 저장소는 실제 현재 시각을
    그대로 써야 한다."""
    store_a = ChecklistStore(tmp_path / "a")
    store_b = ChecklistStore(tmp_path / "b")

    far_future = datetime(2999, 1, 1, tzinfo=timezone.utc)

    class _FrozenFutureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return far_future

    with monkeypatch.context() as m:
        m.setattr(store_module, "datetime", _FrozenFutureDatetime)
        store_a.save("가", "a.csv", {}, _items(1))

    saved_b = store_b.save("나", "b.csv", {}, _items(1))

    assert saved_b.registered_at < far_future.isoformat(timespec="microseconds")

"""체크한 결과를 CSV 로. 실무가 엑셀에 붙여 쓰므로 CSV 로 충분하다."""
from modules.preset import to_csv
from modules.preset import Preset, Criterion


def _cl():
    return Preset(
        id="a" * 16, name="내부검토", source_filename="IS16.pdf",
        registered_at="2026-07-22T00:00:00+00:00", columns={},
        items=[Criterion(no="1", text="서명 스캔 여부", group="스캔·서명"),
               Criterion(no="2", text="책갈피 작동 여부", group="책갈피")])


def test_header_and_a_judged_row():
    # results 는 no 가 아니라 항목의 위치 인덱스(문자열)로 키잉한다 — "0" 은
    # 첫 항목(no="1")을 가리킨다.
    out = to_csv(_cl(), {"0": {"verdict": "Satisfied", "reason": "확인함"}})
    lines = out.strip().splitlines()
    assert lines[0] == "번호,분류,항목,판정,이유"
    assert lines[1] == "1,스캔·서명,서명 스캔 여부,Satisfied,확인함"


def test_unjudged_items_are_still_exported():
    """판정한 것만 내보내면 받아 본 사람은 그게 전부라고 읽는다.
    안 본 항목이 사라지는 것이 이 기능에서 가장 위험한 실패다."""
    out = to_csv(_cl(), {"0": {"verdict": "Satisfied", "reason": ""}})
    lines = out.strip().splitlines()
    assert len(lines) == 3                      # 헤더 + 2항목
    assert lines[2] == "2,책갈피,책갈피 작동 여부,미판정,"


def test_none_verdict_is_written_as_unjudged():
    out = to_csv(_cl(), {"0": {"verdict": None, "reason": ""}})
    assert "미판정" in out.splitlines()[1]


def test_empty_no_items_are_judged_independently_by_position():
    """no 를 열로 고르지 않으면(또는 못 찾으면) 모든 항목이 no="" 를 공유한다.
    no 를 키로 쓰면 항목 하나를 판정하는 순간 no="" 인 나머지 전부가 같은
    판정으로 뭉친다 — 위치(인덱스)로 찾아야 서로 독립적으로 판정된다."""
    cl = Preset(
        id="c" * 16, name="가", source_filename="", registered_at="",
        columns={}, items=[Criterion(no="", text="항목 A"),
                            Criterion(no="", text="항목 B"),
                            Criterion(no="", text="항목 C")])
    # 위치 0(항목 A)만 판정했다.
    out = to_csv(cl, {"0": {"verdict": "Satisfied", "reason": "A만 확인"}})
    lines = out.strip().splitlines()
    assert len(lines) == 4  # 헤더 + 3항목
    assert lines[1] == ",,항목 A,Satisfied,A만 확인"
    # 항목 B·C는 no 가 같아도(둘 다 "") 따라 판정되면 안 된다 — 여전히 미판정.
    assert lines[2] == ",,항목 B,미판정,"
    assert lines[3] == ",,항목 C,미판정,"


def test_commas_and_newlines_are_quoted():
    cl = Preset(id="b" * 16, name="가", source_filename="", registered_at="",
                   columns={}, items=[Criterion(no="1", text="가, 나")])
    out = to_csv(cl, {"0": {"verdict": "N/A", "reason": "줄\n바꿈"}})
    assert '"가, 나"' in out
    assert '"줄\n바꿈"' in out

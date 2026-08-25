"""체크리스트 파일에서 항목을 뽑아내는 파서.

실측(2026-07-22): 열 구성이 파일마다 다르고 한 파일 안에서도 바뀐다.
  IS16 p1  No. | 종류 | 체크리스트 항목 | 적용 문서
  IS16 p2  No  | 위치 | 체크리스트 항목 | 의견/비고
  IS22     Characteristic | Detail Characteristic | ID | Evaluation Item | 평가 항목 | 평가 관점
그래서 추측하되, 못 맞히면 비워 두고 사람에게 고르게 한다.
"""
from modules.preset import VERDICTS
from modules.preset.parse import (build_items, find_header, guess_columns,
                                       read_csv)

IS16 = ["No.", "종류", "체크리스트 항목", "적용 문서"]
IS22 = ["Characteristic", "Detail Characteristic", "ID",
        "Evaluation Item", "평가 항목", "평가 관점"]


def test_verdicts_use_the_field_vocabulary():
    """RVVR 부록의 실제 표기다. O/X 로 바꾸면 산출물이 기존 문서와 말이 달라진다."""
    assert VERDICTS == ("Satisfied", "Modification Required",
                        "Not Satisfied", "N/A")


def test_guess_columns_on_the_internal_checklist():
    got = guess_columns(IS16)
    assert got["no"] == 0
    assert got["group"] == 1
    assert got["text"] == 2
    assert got["note"] == 3          # 마지막 미배정 열


def test_guess_columns_on_the_evaluation_checklist():
    """'Evaluation Item'(3)이 '평가 항목'(4)보다 앞이라 먼저 잡혀야 한다."""
    got = guess_columns(IS22)
    assert got["group"] == 0
    assert got["no"] == 2
    assert got["text"] == 3
    assert got["note"] == 5          # 마지막 미배정 열 = 평가 관점


def test_a_column_is_not_assigned_to_two_roles():
    got = guess_columns(["항목"])
    assert got["text"] == 0
    assert got["no"] is None and got["group"] is None and got["note"] is None


def test_unknown_header_guesses_nothing():
    """못 맞히면 지어내지 않는다. 틀린 추측을 조용히 등록하면 엉뚱한 검토가 된다."""
    got = guess_columns(["가", "나", "다"])
    assert got["text"] is None


def test_find_header_skips_title_rows():
    """실측: IS16 p1 은 첫 행이 'PDF 검토' 제목이고 헤더는 그 다음이다."""
    rows = [["PDF 검토", "", "", ""], IS16, ["1", "스캔·서명", "서명 스캔 여부", "전체"]]
    assert find_header(rows) == 1


def test_find_header_returns_none_when_nothing_matches():
    assert find_header([["가", "나"], ["1", "2"]]) is None


def test_build_items_skips_rows_above_the_header():
    rows = [["PDF 검토", "", "", ""], IS16,
            ["1", "스캔·서명", "서명 스캔 여부", "전체"],
            ["2", "책갈피", "책갈피 작동 여부", "전체"]]
    items = build_items(rows, 1, guess_columns(IS16))
    assert [i.no for i in items] == ["1", "2"]
    assert items[1].text == "책갈피 작동 여부"
    assert items[1].group == "책갈피"
    assert items[1].note == "전체"


def test_build_items_keeps_the_raw_row():
    """열 추측이 틀렸을 때 되짚고, 2단계에서 다른 열을 쓰려면 원본이 필요하다."""
    rows = [IS16, ["1", "스캔·서명", "서명 스캔 여부", "전체"]]
    assert build_items(rows, 0, guess_columns(IS16))[0].raw == \
        ["1", "스캔·서명", "서명 스캔 여부", "전체"]


def test_build_items_drops_rows_without_item_text():
    """빈 행·구분선은 항목이 아니다."""
    rows = [IS16, ["1", "종류", "", "전체"], ["", "", "", ""],
            ["2", "책갈피", "책갈피 작동 여부", "전체"]]
    assert [i.no for i in build_items(rows, 0, guess_columns(IS16))] == ["2"]


def test_read_csv_handles_utf8_with_bom():
    """엑셀이 내보낸 CSV 는 BOM 이 붙는다. 그대로 두면 첫 헤더가 안 맞는다."""
    data = "﻿No,항목\n1,책갈피 확인\n".encode("utf-8")
    assert read_csv(data) == [["No", "항목"], ["1", "책갈피 확인"]]

"""trkim 격자 → `| 셀 | 셀 |` 로 낼 때 가로 병합을 한 칸으로 접는가.

로더가 병합을 어떻게 푸느냐는 취향이 아니라 **계약**이다. `fields/extract.py` 는
"라벨 오른쪽 칸이 값" 으로 값을 꺼내고, legacy 로더(ingestion/docx.py·hwpx.py)는
원본 XML 의 `tc` 를 세어 가로 병합을 애초에 한 칸으로 낸다. trkim 은 앵커+빈칸
격자를 그대로 내므로, 접지 않으면 라벨이 두 칸을 먹는 순간 값이 한 칸 밀린다.

실측(SST-K-TP-7-01-01 시험 의뢰 검토 기록서, 접수번호가 2열 병합):
문서에 `RN-26-999` 가 멀쩡히 있는데 `'접수번호' 이(가) 비어 있습니다` 가 major 로
나갔다. 검토자가 고칠 것이 없는 지적이고, 근거로 다는 인용이 값이 아니라 라벨이라
인용 대조도 못 잡는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.parser_bridge import _collapse_hmerge


@dataclass
class _Table:
    cells: list[list[str]]
    merges: list[dict] = field(default_factory=list)


def test_가로_병합의_이어짐_칸을_접는다():
    # | 접수번호(2열 병합) | RN-26-999 | 접수일(2열 병합) | 2026. 01. 01. |
    td = _Table(
        cells=[["접수번호", "", "RN-26-999", "접수일", "", "2026. 01. 01."]],
        merges=[{"row": 0, "col": 0, "row_span": 1, "col_span": 2},
                {"row": 0, "col": 3, "row_span": 1, "col_span": 2}])

    got = _collapse_hmerge(td, td.cells)

    assert got == [["접수번호", "RN-26-999", "접수일", "2026. 01. 01."]]


def test_세로_병합의_이어짐_행은_빈_칸으로_남긴다():
    # legacy 도 그 자리를 남긴다(원본 XML 에 tc 가 있다). 같이 걷어내면 행마다
    # 칸 수가 달라져 _table_rows 의 열 맞춤이 무너진다.
    td = _Table(cells=[["구분", "값"], ["", "값2"]],
                merges=[{"row": 0, "col": 0, "row_span": 2, "col_span": 1}])

    assert _collapse_hmerge(td, td.cells) == [["구분", "값"], ["", "값2"]]


def test_가로_세로_동시_병합은_가로만_접는다():
    td = _Table(cells=[["머리", "", "값"], ["", "", "값2"]],
                merges=[{"row": 0, "col": 0, "row_span": 2, "col_span": 2}])

    assert _collapse_hmerge(td, td.cells) == [["머리", "값"], ["", "값2"]]


def test_병합이_없으면_그대로_둔다():
    td = _Table(cells=[["a", "b"], ["c", "d"]])

    assert _collapse_hmerge(td, td.cells) == [["a", "b"], ["c", "d"]]

"""산출물 세트 검토가 칸 값을 판정한다.

지금까지 파이프라인은 필드를 **뽑기만** 하고 판정하지 않았다 — 프리셋에
`required`·`pattern`·`format` 이 실려 있는데 읽는 코드가 없어서, 산출물마다
"단일 문서 검사는 아직 없습니다"로 남았다.

여기서 재는 것: `review_case` 가 `FieldPresenceChecker` 를 돌려 그 결함을 지적으로
내는가, 그리고 **문서 간 대조(case_wide·pairs)와 섞이지 않는가**. 층이 섞이면
리포트가 같은 결함을 두 곳에서 세게 된다.
"""
from pathlib import Path

import pytest

from app.case import review_case, to_ui_case_payload

SPEC = {
    "outputs": [
        {"key": "갑지", "form_no": "SST-K-TI-03-03(07)",
         "fields": [
             {"name": "성적서번호", "labels": ["성적서번호"],
              "pattern": r"SST-\d{2}-\d{3}-C\d+", "required": True},
             {"name": "의뢰기관명", "labels": ["기관명"], "required": True},
         ],
         "fixed_text": ["슈어소프트테크㈜"],
         "signatures": [{"role": "시험실무자", "placeholder": "성명"}]},
    ],
}


def _write(tmp_path: Path, name: str, *lines: str) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def clean(tmp_path):
    return _write(tmp_path, "SST-K-TI-03-03(07) 갑지.txt",
                  "| 성적서번호 | SST-26-999-C01 |",
                  "| 기관명 | 한국소프트웨어시험연구소 |",
                  "| 시험실무자 | 홍길동  (서명) |",
                  "슈어소프트테크㈜")


@pytest.fixture
def dirty(tmp_path):
    """실측된 결함을 그대로 옮겼다 — 서명 미작성, 성적서번호 하이픈 누락."""
    return _write(tmp_path, "SST-K-TI-03-03(07) 갑지.txt",
                  "| 성적서번호 | SST-26-999C01 |",
                  "| 기관명 |  |",
                  "| 시험실무자 | 성명                (서명) |",
                  "슈어소프트테크㈜")


def test_결함이_없으면_지적하지_않는다(clean):
    got = review_case([clean], SPEC)

    assert [f.message for f in got.findings] == []


def test_칸_값_결함을_지적한다(dirty):
    got = review_case([dirty], SPEC)

    assert sorted(f.rule_id for f in got.findings) == [
        "F-서명-시험실무자", "F-성적서번호", "F-의뢰기관명"]
    assert all(not f.unreviewed for f in got.findings)


def test_지적이_산출물에도_달린다(dirty):
    """리포트는 산출물별로 편다. 전체 목록에만 있으면 어느 산출물의 문제인지
    화면이 다시 짜맞춰야 한다."""
    got = review_case([dirty], SPEC)

    assert got.outputs[0].key == "갑지"
    assert sorted(f.rule_id for f in got.outputs[0].findings) == [
        "F-서명-시험실무자", "F-성적서번호", "F-의뢰기관명"]


def test_지적에_어느_산출물인지_실린다(dirty):
    got = review_case([dirty], SPEC)

    assert {f.document for f in got.findings} == {"갑지"}


def test_검사했으면_미검토가_아니다(clean):
    """지금까지는 전부 status='unreviewed' 였다 — 검사를 안 했으니 맞았다.
    이제 검사하므로 통과는 통과라고 말해야 한다."""
    got = review_case([clean], SPEC)

    assert got.outputs[0].status == "reviewed"
    assert "지적 0건" in got.outputs[0].reason


def test_필드맵이_없으면_여전히_미검토다(tmp_path):
    spec = {"outputs": [{"key": "을지", "form_no": "SST-K-TI-03-04(08)"}]}
    path = _write(tmp_path, "SST-K-TI-03-04(08) 을지.txt", "| 아무 | 내용 |")

    got = review_case([path], spec)

    assert got.outputs[0].status == "unreviewed"
    assert got.findings == []


def test_문서를_못_읽으면_미검토다(tmp_path):
    path = _write(tmp_path, "SST-K-TI-03-03(07) 갑지.zzz", "x")

    got = review_case([path], SPEC)

    assert got.outputs[0].status == "unreviewed"
    assert got.outputs[0].error != ""


def test_화면_payload_가_단일문서_지적을_가른다(dirty):
    """kind 로 층을 가른다. 이미 case_wide 와 pair 가 갈려 있고, 매트릭스가
    보여주는 것을 리포트가 두 번 세지 않게 하려는 것이다."""
    payload = to_ui_case_payload(review_case([dirty], SPEC))

    kinds = {f["kind"] for f in payload["findings"]}
    assert kinds == {"output"}
    assert payload["stats"]["findings"] == 3


def test_산출물_payload_에_지적_수가_실린다(dirty):
    payload = to_ui_case_payload(review_case([dirty], SPEC))

    assert payload["outputs"][0]["findings"] == 3

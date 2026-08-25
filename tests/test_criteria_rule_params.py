"""기준 yaml 의 `params` 가 실제로 검사기를 돌리는가.

`params` 는 코드가 아니라 데이터라 아무도 안 읽어 본다. 정규식 하나가 깨져 있어도
앱은 조용하다 — 검사기가 "재지 못했다"는 INFO 한 장을 내고 끝나서, 화면에는 그
기준이 그냥 지적 없이 지나간 것처럼 보인다.

**두 가지를 건다.**

1. 규칙 기준 전부 — params 로 만든 검사기가 정말 검사를 하는가. 값이 비었거나
   정규식이 깨졌으면 검사기가 "검사를 수행하지 않았습니다"로 답한다. 그걸 잡는다.
2. 새로 붙인 규칙 둘 — 맞게 쓴 문서는 통과하고 틀린 문서는 걸리는가. 오탐이
   나는 규칙은 안 붙이느니만 못하다(실측에서 세 번 되돌렸다).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.config import apply_criteria_params
from modules.agent_checklist.checklist_map import RULE_CHECKS
from modules.doc_parser import RawDoc, normalize
from modules.shared import Context, ReviewConfig

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ROOT / "presets" / "criteria"


def _rule_items() -> list[tuple[str, str, dict]]:
    """(파일, 기준번호, 기준) — params 를 가진 규칙 기준 전부."""
    out = []
    for path in sorted(CRITERIA.rglob("*.yaml")):
        blob = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for it in blob.get("items") or []:
            if it.get("check") in RULE_CHECKS and it.get("params"):
                out.append((path.name, str(it.get("no")), it))
    return out


def _ctx(item: dict | None = None) -> Context:
    """검사기가 받는 Context.

    params 는 **두 길**로 간다. `checklist_map` 이 검사기에 직접 넘기는 것
    (`forbid`·`pattern`·`fields`)과, `apply_criteria_params` 가 ReviewConfig 로
    올리는 것(`required_sections`·`id_pattern`·`placeholder_markers`)이다.
    앱이 하는 대로 둘 다 태워야 이 시험이 진짜 경로를 잰다.
    """
    review = ReviewConfig(doc_type="")
    if item is not None:
        review = apply_criteria_params(review, [SimpleNamespace(params=item["params"])])
    return Context(review=review, llm=None)


def _doc(text: str, footers: list[str] | None = None,
         headers: list[str] | None = None):
    doc = normalize(RawDoc(source_path="d.md", text=text))
    if footers is not None:
        doc.meta["footers"] = footers
    if headers is not None:
        doc.meta["headers"] = headers
    return doc


def _probe():
    """검사기가 "볼 데이터가 없다"고 핑계댈 수 없는 최소 문서.

    머릿말·꼬리말이 없으면 header_footer 가, 표가 없으면 fontsize 가 "못 읽었다"고
    답하는데, 그건 params 가 아니라 이 문서의 문제다 — 여기서 재려는 것과 다르다.
    """
    doc = _doc("# 1. 개요\n\n내용.\n", footers=["꼬리말"], headers=["머릿말"])
    doc.meta["tables"] = [{"columns": ["TF1."], "fontSizes": {9.0: 10}}]
    return doc


@pytest.mark.parametrize(("fname", "no", "item"),
                         [(f, n, i) for f, n, i in _rule_items()],
                         ids=[f"{f}:{n}" for f, n, _ in _rule_items()])
def test_params_actually_drive_a_check(fname: str, no: str, item: dict) -> None:
    """params 로 만든 검사기가 "검사를 수행하지 않았습니다"라고 하면 안 된다.

    그 말은 값이 비었거나 정규식이 깨졌다는 뜻이다 — 기준은 규칙이라고 적혀 있는데
    실제로는 아무것도 안 재고 있다.
    """
    checker = RULE_CHECKS[item["check"]](item["params"], [])
    # 빈 문서로 돌린다. 지적이 나올 리 없으니, 나오는 INFO 는 "못 쟀다" 뿐이다.
    excuses = [f.message for f in checker.check(_probe(), _ctx(item))
               if f.unreviewed and "수행하지 않았습니다" in f.message]
    assert not excuses, (
        f"{fname} {no}: params 가 검사기를 못 돌립니다 — {excuses[0]}")


# ── 새로 붙인 규칙 둘의 맞는 예·틀린 예 ────────────────────────────────
# 실측(시험 산출물 11종)에서 오탐 0건인 것을 확인하고 붙였다. 여기 시험은 그
# 상태를 고정한다 — 단위를 더하다가 맞게 쓴 표기를 잡기 시작하면 깨진다.

def _checker(no: str):
    for _, n, it in _rule_items():
        if n == no:
            return RULE_CHECKS[it["check"]](it["params"], [])
    pytest.fail(f"{no} 기준이 규칙이 아니거나 params 가 없습니다")


@pytest.mark.parametrize("text", [
    "온도 25.7 °C 에서 측정",
    "RAM 16.00 GB / HDD 500.00 GB",
    "수행 횟수: 3 회, 데이터 1000 건, 대상 2 개",
    "속도 1 s 이하, 규모 500 LOC",
    "의뢰번호 SST-26-999, 성적서 SST-26-999-C01",   # 문서번호는 단위가 아니다
    "작성일 2026. 01. 05.",                          # 날짜도 아니다
])
def test_표기3_맞게_쓴_표기는_안_걸린다(text: str) -> None:
    got = [f for f in _checker("표기-3").check(_doc(f"# 1. 개요\n\n{text}\n"))
           if not f.unreviewed]
    assert not got, f"맞게 쓴 표기를 잡았다 — {got[0].message}"


@pytest.mark.parametrize("text", ["26.6°C", "16.00GB", "3회", "1000건", "500LOC", "1s"])
def test_표기3_붙여_쓴_표기는_걸린다(text: str) -> None:
    got = [f for f in _checker("표기-3").check(_doc(f"# 1. 개요\n\n측정값 {text} 이다.\n"))
           if not f.unreviewed]
    assert got, f"{text} 를 놓쳤다"


@pytest.mark.parametrize(("footer", "hit"), [
    ("SST-K-TI-03-04(08) 페이지 ( 6 ) / 총 ( 12 )", False),
    ("SST-K-TI-03-04(08) 페이지 (6) / 총 (12)", True),      # 공백 없음
    ("SST-K-TI-03-04(08) 페이지 (  6  ) / 총 ( 12 )", True),  # 공백 둘
    ("SST-K-TI-03-04(08) 페이지 ( 6 )", True),               # 총 칸 없음
])
def test_서식9_꼬리말_쪽수_형식(footer: str, hit: bool) -> None:
    got = [f for f in _checker("서식-9").check(_doc("# 1. 개요\n\n내용.\n", footers=[footer]))
           if not f.unreviewed]
    assert bool(got) is hit


def test_서식3_과_서식9_는_갈려_있다() -> None:
    """서식-3 은 "쪽수 표기가 있는가", 서식-9 는 "형식이 맞는가"다. 공백이 틀린
    꼬리말에서 서식-3 은 통과하고 서식-9 만 걸려야 둘을 나눈 뜻이 산다."""
    doc = _doc("# 1. 개요\n\n내용.\n", footers=["SST-K-TI-03-04(08) 페이지 (6) / 총 (12)"])
    loose = [f for f in _checker("서식-3").check(doc) if not f.unreviewed]
    strict = [f for f in _checker("서식-9").check(doc) if not f.unreviewed]
    assert not loose, "서식-3 이 형식까지 보고 있다 — 서식-9 와 겹친다"
    assert strict, "서식-9 가 형식을 안 본다"


# ── 테스트케이스 글꼴 ────────────────────────────────────────────────────
# fontsize 는 "어느 표"인지 못 가리고 표 안에 직접 박힌 크기를 다 본다. 그 한계
# 때문에 갑지는 규칙에서 되돌렸다(yaml 갑지-3 주석) — 여기서 그 경계를 고정한다.

def _doc_with_table_sizes(sizes: dict):
    doc = _doc("# 1. 개요\n\n내용.\n")
    doc.meta["tables"] = [{"columns": ["TF1. 시험 항목"], "fontSizes": sizes}]
    return doc


@pytest.mark.parametrize("no", ["설계서-8", "을지-6"])
@pytest.mark.parametrize(("sizes", "hit"), [
    ({8.0: 139}, False),          # 실측: 시험설계서
    ({9.0: 40}, False),
    ({8.0: 100, 9.0: 40}, False),
    ({10.0: 9}, True),            # 실측: 갑지 기관명 표 — 여기서는 진짜 위반이다
    ({11.0: 200}, True),
])
def test_테스트케이스_글꼴은_8_또는_9pt(no: str, sizes: dict, hit: bool) -> None:
    got = [f for f in _checker(no).check(_doc_with_table_sizes(sizes), _ctx())
           if not f.unreviewed]
    assert bool(got) is hit


@pytest.mark.parametrize("no", ["설계서-8", "을지-6"])
def test_직접_박힌_크기가_없으면_미검토다(no: str) -> None:
    """"이상 없음"이 아니라 "못 봤음"이다 — 문단 스타일이 정하는 크기는 아직 못 읽는다."""
    doc = _doc("# 1. 개요\n\n내용.\n")
    doc.meta["tables"] = [{"columns": ["TF1."], "fontSizes": {}}]
    got = _checker(no).check(doc, _ctx())
    assert len(got) == 1 and got[0].unreviewed


def test_갑지는_아직_규칙이_아니다() -> None:
    """설계서·을지와 같은 규칙인데 갑지에서만 사람이다.

    실측: 갑지에 직접 박힌 크기는 **기관명 표의 10pt 9자**뿐이고 테스트케이스 표가
    없다. 규칙으로 두면 멀쩡한 갑지가 매번 MAJOR 로 뜬다. 표를 가려낼 수 있게
    되면 그때 올린다 — 그때 이 시험이 깨져서 알려준다.
    """
    blob = yaml.safe_load((CRITERIA / "teams" / "ai-test-cert-1.yaml").read_text("utf-8"))
    item = next(it for it in blob["items"] if it["no"] == "갑지-3")
    assert item.get("mode") == "사람" and not item.get("check")

"""검사기가 팀을 안 가리는가.

설계 스펙은 "새 팀이 와도 규칙 어휘의 조합으로 표현되는 한 코드를 건드리지 않는다"고
주장한다. 그 주장은 팀이 하나뿐일 때는 검증되지 않는다.

여기서 재는 것: AI시험인증1팀용으로 만든 `FieldPresenceChecker` 를 **EV2 기준 YAML만
얹어서** 돌렸을 때 EV2 문서의 결함이 나오는가. 코드가 EV2 를 위해 바뀌어야 한다면
어휘가 모자란 것이고, 그 자리를 `docs/checker-inventory.md` 에 적는다.

실측 대상은 data/에너지검증팀/SKN56_CDMS_RVVR_Rev08.docx 다. data/ 는 gitignore 되어
있으므로(팀 자료) 없으면 skip 하되, 구조를 옮겨 적은 합성 문서로 어휘 자체는 항상
검증한다 — 실문서가 없다고 검증이 통째로 사라지면 안 된다.
"""
from pathlib import Path

import pytest
import yaml
from conftest import sample

from modules.agent_format import FieldPresenceChecker, SignatureSpec
from modules.doc_parser import FieldSpec, RawDoc, load_document, normalize

ROOT = Path(__file__).resolve().parent.parent
EV2 = ROOT / "presets" / "criteria" / "teams" / "EV2.yaml"
REAL_NAME = "SKN56_CDMS_RVVR_Rev08.docx"


def _checker_from(preset_path: Path, output_key: str) -> FieldPresenceChecker:
    """기준 YAML 의 outputs 절 → 검사기. **코드가 아니라 데이터로 만든다.**

    변환이 여기 있는 이유는 src/app/case.py._field_specs 와 같다 — 기준을 읽는 것은
    preset, 값을 꺼내는 것은 doc_parser, 둘을 잇는 것은 조립의 일이다.
    """
    spec = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    output = next(o for o in spec["outputs"] if o["key"] == output_key)
    return FieldPresenceChecker(
        fields=[FieldSpec(name=f["name"], source=f.get("from", "table"),
                          labels=tuple(f.get("labels", ())),
                          at=f.get("at", "right"),
                          options=tuple(f.get("options", ())),
                          select=f.get("select", ""),
                          pattern=f.get("pattern", ""),
                          format=f.get("format", ""), equals=f.get("equals", ""),
                          required=bool(f.get("required", False)),
                          columns=tuple(f.get("columns", ())),
                          key=f.get("key", ""),
                          required_columns=tuple(f.get("required_columns", ())))
                for f in output.get("fields", [])],
        fixed_text=list(output.get("fixed_text", [])),
        signatures=[SignatureSpec(role=s["role"], placeholder=s["placeholder"],
                                  at=s.get("at", "right"))
                    for s in output.get("signatures", [])])


# 실문서 구조를 그대로 옮겨 적은 조각들. 표지와 개정기록이 한 문서에 있다.
_COVER_BLANK = ["| NON NUCLEAR SAFETY RELATED | J2005-SRS-01 REVISION 08 | STATUS 1 |",
                "| 작 성 자 : |  | Date : |  |",
                "| 검 토 자 : |  | Date : |  |",
                "| 승 인 자 : |  | Date : |  |",
                "| 발 행 일 : |  |  |  |  |"]
_COVER_DONE = ["| 작 성 자 : | 정연석 | Date : | 2025. 04. 14. |",
               "| 검 토 자 : | 구자철 | Date : |  |",
               "| 승 인 자 : | 구자철 | Date : |  |",
               "| 발 행 일 : | 2025. 05. 07. |  |  |  |"]
# 열 사이에 빈 칸이 하나씩 끼어 있다(실측).
_LOG = ["| 개정번호 |  | 일시 |  | 해당 절 |  | 개정 사유 |  | 담당자 |  | 승인자 |",
        "| 00 |  | ’21.06.21 |  | 문서 전체 |  | 신규 발행 |  | 정연석 |  | 구자철 |",
        "| 01 |  | ’22.12.19 |  | 문서 전체 |  | 전면 개정 |  | 정연석 |  | 구자철 |"]


def _ev2(*blocks):
    """블록 사이를 빈 줄로 띄운다 — 실문서에서 표지와 개정기록은 별개 표다.
    이어 붙이면 로더가 한 표로 묶어 지적 위치가 어긋난다."""
    return normalize(RawDoc(source_path="t.docx",
                            text="\n\n".join("\n".join(b) for b in blocks)))


# ── 어휘 검증 (실문서 없이도 항상 돈다) ──────────────────────────────────

def test_EV2_기준만으로_표지_미작성을_잡는다():
    """실문서 표지 구조를 그대로 옮겨 적었다. 라벨에 자간이 들어가 있다."""
    got = _checker_from(EV2, "RVVR").check(_ev2(_COVER_BLANK, _LOG))

    assert sorted(f.rule_id for f in got) == [
        "F-검토자", "F-발행일", "F-승인자", "F-작성자"]
    assert all(not f.unreviewed for f in got)


def test_EV2_기준은_작성된_표지를_통과시킨다():
    got = _checker_from(EV2, "RVVR").check(_ev2(_COVER_DONE, _LOG))

    assert got == []


def test_표지_자체가_없으면_미검토다():
    """빈 표지와 표지 없는 문서를 섞으면 안 된다. 후자는 필드맵이 어긋났을
    가능성이라 사람이 봐야 한다."""
    doc = normalize(RawDoc(source_path="t.docx", text="| 본문 | 내용 |"))

    got = _checker_from(EV2, "RVVR").check(doc)

    assert len(got) == 5      # 표지 4칸 + 개정기록 표
    assert all(f.unreviewed for f in got)


# ── 표의 모든 행 (항목 21 개정기록 완전성) ───────────────────────────────

def test_EV2_기준만으로_개정기록의_빈_칸을_잡는다():
    """항목 21 — 개정번호·개정일자·작성자·변경 내용·승인 정보가 누락 없이."""
    log = list(_LOG)
    log[2] = "| 01 |  |  |  | 문서 전체 |  | 전면 개정 |  | 정연석 |  | 구자철 |"

    got = _checker_from(EV2, "RVVR").check(_ev2(_COVER_DONE, log))

    assert [(f.rule_id, f.anchor.section) for f in got] == [("F-개정기록", "표2 3행")]
    assert "일시" in got[0].message


def test_EV2_개정기록이_다_채워져_있으면_통과다():
    got = _checker_from(EV2, "RVVR").check(_ev2(_COVER_DONE, _LOG))

    assert got == []


# ── 실문서 회귀 (data/ 가 있을 때만) ─────────────────────────────────────

def test_실문서_EV2_표지가_미작성이다():
    path = sample(REAL_NAME)
    if path is None or not path.exists():
        pytest.skip(f"{REAL_NAME} 없음 — data/ 어딘가에 두면 이 검증이 돈다")

    doc = normalize(load_document(str(path)))
    got = _checker_from(EV2, "RVVR").check(doc)

    # 실측(2026-07-31): 네 칸이 전부 비어 있다. 결재가 안 된 작업본이거나
    # 항목 20 이 잡아야 할 결함이다 — 어느 쪽인지는 팀이 판단한다.
    assert sorted(f.rule_id for f in got) == [
        "F-검토자", "F-발행일", "F-승인자", "F-작성자"]
    assert all(not f.unreviewed for f in got), \
        "라벨맵이 실문서와 어긋났다 — EV2.yaml 의 labels 를 고쳐야 한다"

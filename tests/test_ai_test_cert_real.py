"""AI시험인증1팀 실산출물로 재는 회귀 테스트.

data/ 는 gitignore 되어 있다(팀 자료). 없으면 skip 하되 **조용히 넘어가지 않는다** —
이름으로 찾고 사유를 남긴다(conftest.sample 의 교훈: 경로를 박아두면 파일이 멀쩡히
있는데도 조용히 skip 된다).

여기서 재는 것은 **기준 파일(presets/criteria/teams/ai-test-cert-1.yaml)이 실제 문서와
맞는가**다. 필드맵이 문서 구조와 어긋나면 값이 안 나오고, 그 상태로 대조하면 전부
"판단불가"가 된다.
"""
import zipfile
from pathlib import Path

import pytest
import yaml
from conftest import sample

from modules.agent_trace import PairRow, PairRule, compare_pair
from modules.doc_parser import FieldSpec, extract_fields, load_document, normalize

ZIP_NAME = "AI시험인증1팀_시험산출물 샘플.zip"
ZIP = sample(ZIP_NAME)
PRESET = (Path(__file__).resolve().parent.parent
          / "presets" / "criteria" / "teams" / "ai-test-cert-1.yaml")


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    if ZIP is None or not ZIP.exists():
        pytest.skip(f"{ZIP_NAME} 없음 — data/ 어딘가에 두면 이 검증이 돈다")
    root = tmp_path_factory.mktemp("case")
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(root)
    return root


def _specs(key: str) -> list[FieldSpec]:
    preset = yaml.safe_load(PRESET.read_text(encoding="utf-8"))
    output = next(o for o in preset["outputs"] if o["key"] == key)
    return [FieldSpec(name=f["name"], source=f.get("from", "table"),
                      labels=tuple(f.get("labels", ())), at=f.get("at", "right"),
                      options=tuple(f.get("options", ())), select=f.get("select", ""))
            for f in output["fields"]]


def _values(root: Path, key: str, needle: str) -> dict:
    path = next(p for p in root.rglob("*.docx") if needle in p.name)
    return extract_fields(normalize(load_document(path)), _specs(key))


@pytest.fixture(scope="module")
def gapji(case):
    return _values(case, "갑지", "갑지")


@pytest.fixture(scope="module")
def eulji(case):
    return _values(case, "을지", "을지")


def test_갑지_필드맵이_문서와_맞는다(gapji):
    missing = [name for name, v in gapji.items() if not v.found]
    assert missing == [], f"필드맵이 문서와 어긋난다: {missing}"


def test_을지_필드맵이_문서와_맞는다(eulji):
    missing = [name for name, v in eulji.items() if not v.found]
    assert missing == [], f"필드맵이 문서와 어긋난다: {missing}"


def test_갑지_주소는_의뢰기관_주소지_회사_주소가_아니다(gapji):
    # 갑지에 `주소 :`(슈어소프트테크)와 `주소`(의뢰기관)가 둘 다 있다. 부분일치로
    # 찾으면 회사 주소를 집어 문서 간 대조에서 거짓 불일치를 만든다.
    assert "슈어" not in (gapji["의뢰기관주소"].value or "")
    assert "성남" not in (gapji["의뢰기관주소"].value or "")


def test_갑지_시험장소_체크박스는_하나만_선택돼_있다(gapji):
    assert gapji["시험장소"].selected == ("현장 시험",)


def test_지적_위치가_표와_행으로_나온다(gapji):
    # 이 문서들은 제목이 0개라 섹션만으로는 위치가 전부 "0"이다.
    assert gapji["의뢰기관명"].anchor.section.startswith("표")


def test_을지_갑지_대조에서_성적서번호와_시험기간이_어긋난다(eulji, gapji):
    """md §1-5. 둘 다 한 글자 차이라 사람이 읽으면 같은 값으로 보인다.

        성적서번호  을지 SST-26-999-C01      ↔ 갑지 SST-26-999C01    (하이픈)
        시험기간    을지 ~2026. 01. 15.      ↔ 갑지 ~ 2026. 01. 15.  (공백)
    """
    pair = PairRule(id="1-5", left="을지", right="갑지", rows=(
        PairRow(field="성적서번호"),
        PairRow(field="시험기간"),
        PairRow(field="의뢰기관명"),
    ))

    findings = compare_pair(eulji, gapji, pair)

    flagged = {f.rule_id for f in findings if not f.unreviewed}
    assert flagged == {"1-5/성적서번호", "1-5/시험기간"}
    # 값이 같은 필드는 지적이 없어야 한다 — 오탐이 나오면 대조가 못 쓴다.
    assert not [f for f in findings if f.unreviewed], "판정 못 한 항목이 있다"


def test_대조_지적은_양쪽_근거를_싣는다(eulji, gapji):
    pair = PairRule(id="1-5", left="을지", right="갑지",
                    rows=(PairRow(field="성적서번호"),))

    f = compare_pair(eulji, gapji, pair)[0]

    assert [e.quote for e in f.evidence] == \
        ["성적서번호 | SST-26-999-C01", "성적서번호 | SST-26-999C01"]
    assert all(e.anchor.section for e in f.evidence)

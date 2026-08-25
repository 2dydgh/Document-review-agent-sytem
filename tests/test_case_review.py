"""케이스 검토 — 산출물 세트를 한 번에.

검사 1건이 문서 하나가 아니라 **산출물 세트**다. 팀 워크플로우가 폴더 세트이고,
87개 대조 항목은 문서가 여럿 모여야 판정된다.

여기서 확인하는 것은 조립이다: 파일 목록을 주면 판별하고, 필드를 뽑고, 대조하고,
못 한 것을 못 했다고 말하는가.
"""
import zipfile
from pathlib import Path

import pytest
import yaml
from conftest import sample

from app.case import review_case
from app.manual_review import manual_review_patch

ZIP_NAME = "AI시험인증1팀_시험산출물 샘플.zip"
ZIP = sample(ZIP_NAME)
PRESET = (Path(__file__).resolve().parent.parent
          / "presets" / "criteria" / "teams" / "ai-test-cert-1.yaml")


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(PRESET.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    if ZIP is None or not ZIP.exists():
        pytest.skip(f"{ZIP_NAME} 없음 — data/ 어딘가에 두면 이 검증이 돈다")
    root = tmp_path_factory.mktemp("case")
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(root)
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.fixture(scope="module")
def result(files, spec):
    return review_case(files, spec)


def test_산출물_10종을_모두_인식한다(result):
    assert result.missing_outputs == []
    assert len(result.outputs) == 10


def test_참고_예시는_건너뛰되_목록으로_남긴다(result):
    # 조용히 버리면 "다 검사했다"가 거짓이 된다.
    skipped = [Path(i["path"]).name for i in result.ignored]
    assert any(n.startswith("99.") for n in skipped)
    assert len(skipped) == 2
    # 왜 건너뛰었는지도 남아야 한다 — "건너뜀"이라고만 하면 조용히 버린 것과
    # 구분이 흐려진다.
    assert all(i["reason"] for i in result.ignored)


def test_양식번호가_없는_파일은_추측하지_않고_미분류로_남긴다(result):
    # 접수 문서(고객 제출물)와 발행본 PDF. 추측해 배정하면 엉뚱한 필드맵으로
    # 검사해 거짓 지적이 난다.
    names = [Path(p).name for p in result.unclassified]
    assert any("접수 문서" in n for n in names)


def test_케이스_번호를_의뢰번호에서_찾는다(result):
    assert result.case_id == "SST-26-999"


def test_한_글자_차이를_잡는다(result):
    """둘 다 전 산출물 대조가 낸다. 시험기간은 계획서·을지·갑지 **3곳**에 있어
    쌍으로 두면 같은 결함이 3번 난다 — md §3 이 "2개 문서만으로는 부분 판정"
    이라고 한 그대로다."""
    flagged = {f.rule_id for f in result.findings if not f.unreviewed}

    assert "W-성적서번호" in flagged
    assert "W-시험기간" in flagged


def test_쌍은_정확히_두_곳에만_있는_값에만_쓴다(result):
    """대표자는 의뢰서·갑지 2곳뿐이라 쌍이 맞다. 실측: 갑지가 '홍길동1' 이다."""
    rep = [f for f in result.findings if f.rule_id == "1-7/대표자"]

    assert len(rep) == 1
    assert "홍길동" in rep[0].message


def test_같은_결함을_쌍_수만큼_내지_않는다(result):
    """시험기간이 3곳에 있다. 쌍이면 계획서↔을지 · 계획서↔갑지 · 을지↔갑지 로
    3건이 난다. 전 산출물 대조는 1건에 근거 3개다."""
    period = [f for f in result.findings if "시험기간" in (f.rule_id or "")]

    assert len(period) == 1
    assert len(period[0].evidence) == 3


def test_이제_10종_모두_필드맵이_있다(result):
    """마지막까지 막혀 있던 제출물 확인증은 칸 하나로 뽑을 값이 없었다.
    `from: table_rows` 로 제출물 목록 표를 읽어 풀렸다(2026-07-31)."""
    assert [o.key for o in result.outputs if not o.field_specs] == []
    assert all(o.status == "reviewed" for o in result.outputs)


def test_필드맵이_없는_산출물은_통과가_아니라_미검토다(files, spec):
    """기준에서 필드맵을 빼면 "지적 0건 = 이상 없음"이 아니라 미검토여야 한다.

    실제 기준을 쓰지 않고 지어낸다 — 실측 기준이 완성될수록 이 불변식을 잴
    표본이 사라지기 때문이다. 실제로 10종을 다 채우자 이 검증이 죽었다.
    """
    stripped = dict(spec)
    stripped["outputs"] = [{k: v for k, v in o.items()
                            if k not in ("fields", "fixed_text", "signatures")}
                           for o in spec["outputs"]]

    got = review_case(files, stripped)

    assert all(o.status == "unreviewed" for o in got.outputs)
    assert all("필드맵" in o.reason for o in got.outputs)


def test_문서가_없으면_그_쌍은_미검토로_이유와_함께_남는다(files, spec):
    # 을지를 뺀 케이스. 지적 0건이 아니라 "을지 없음"이라고 말해야 한다.
    without = [f for f in files if "을지" not in f.name]

    result = review_case(without, spec)

    unreviewed = [f for f in result.findings if f.unreviewed]
    assert unreviewed, "을지가 없는데 대조가 조용히 통과했다"
    assert any("을지" in f.message for f in unreviewed)


def test_전_산출물_대조가_매트릭스를_만든다(result):
    """문서 간 md §3. 리포트의 필드 × 산출물 표가 이걸 그린다 — 맞은 곳까지
    남아야 "N곳 중 몇 곳을 봤다"를 말할 수 있다."""
    by_id = {cw.id: cw for cw in result.case_wide}

    # §3 은 "한 값이 N곳에서 같은가"(rule: exact)다. §4 의 작성일자 선후는 판정
    # 모양이 달라(순서) 여기 세지 않는다 — 섞으면 어느 절이 몇 개인지 흐려진다.
    exact = [cw for cw in result.case_wide if cw.id != "W-작성일자-순서"]
    assert len(exact) == 12, "§3 항목이 다 돌지 않았다"
    # 성적서번호는 을지·갑지가 실제로 어긋나 있다(3곳 중 2곳 확인).
    cert = by_id["W-성적서번호"]
    assert cert.status == "불일치"
    assert [c.value for c in cert.cells if c.found] == \
        ["SST-26-999-C01", "SST-26-999C01"]
    # 못 본 곳은 셀에 남되 값이 없다 — 빼버리면 몇 곳을 못 봤는지 사라진다.
    assert [c.output for c in cert.cells if not c.found] == ["시험기록서"]


def test_버전_표기가_달라도_제품명은_같은_값으로_본다(result):
    """갑지는 버전 포함 전체, 을지는 버전 제외로 쓴다(문서 간 §1-5)."""
    product = next(cw for cw in result.case_wide if cw.id == "W-제품명")

    seen = [c.value for c in product.cells if c.found]
    assert seen == ["Apple (Ver 1.0.1)", "Apple", "Apple",
                    "Apple", "Apple(ver 1.0)", "Apple (Ver 1.0.1 )"]
    # 버전을 떼고 보므로 여섯이 다 같다.
    assert product.status == "일치"


def test_버전만_다른_것은_이_규칙이_못_잡는다(result):
    """시험기록서만 `Apple(ver 1.0)` 이고 나머지는 `1.0.1` 이다(실측).

    W-제품명은 ignoring: version 이라 **버전을 떼고 비교해 통과시킨다.** 실제
    불일치인데 규칙이 못 잡는 자리다 — 버전만 따로 대조하려 해도 기록서는 버전이
    제품명 칸 안에 섞여 있어 지금 어휘로는 못 뽑는다.
    이 테스트는 그 구멍이 **알고 두는 것**임을 못박는다(docs/open-questions.md).
    """
    product = next(cw for cw in result.case_wide if cw.id == "W-제품명")

    record = next(c for c in product.cells if c.output == "시험기록서")
    assert record.value == "Apple(ver 1.0)"
    assert record.ok is True     # 버전이 달라도 통과한다 — 이것이 구멍이다


def test_필드맵이_없으면_통과가_아니라_미검토다(result):
    """필드맵을 10종 중 9종까지 채웠어도 5항목은 여전히 못 잰다 — 문서에 그 칸이
    없거나(시험항목명) 문서마다 표기가 달라서다(시험일자: 계획서는 기간, 체크리스트는
    시험 일자, 기록서는 저장 일자). 조용히 넘기면 못 본 것이 "이상 없음"으로 보인다.
    """
    unreviewed = [cw.id for cw in result.case_wide if cw.status == "미검토"]

    assert "W-시험항목명" in unreviewed
    assert "W-시험일자" in unreviewed
    # 미검토는 지적으로도 남아야 리포트가 센다.
    ids = {f.rule_id for f in result.findings if f.unreviewed}
    assert "W-시험항목명" in ids


def test_전_산출물_대조는_지적을_한_번만_낸다(result):
    """의뢰번호는 md §1 의 18쌍 중 12쌍에 등장한다. 쌍마다 판정하면 같은 지적이
    12번 난다. 그래서 3곳 이상에 걸친 값은 전부 이 층으로 접었다."""
    cert = [f for f in result.findings if f.rule_id == "W-성적서번호"]

    assert len(cert) == 1
    assert len(cert[0].evidence) == 2      # 근거는 본 곳 수만큼


def test_같은_필드를_두_층에_두지_않는다(spec):
    """case_wide 와 pairs 에 같은 필드가 있으면 지적이 두 번 난다. 실제로 성적서번호가
    양쪽에 있어 그렇게 났다 — 기준 파일이 지켜야 하는 불변식이다."""
    wide = {c["field"] for c in spec.get("case_wide", [])}
    paired = {r["field"] for p in spec.get("pairs", []) for r in p.get("rows", [])}

    assert not (wide & paired), f"두 층에 겹친 필드: {sorted(wide & paired)}"


def test_시험환경_대조_5곳에_모두_추출_규칙이_있다(spec):
    """대조 대상으로 적고 필드맵을 빼면 문서 누락과 설정 누락이 뒤섞인다."""
    outputs = {
        o["key"]: {f["name"] for f in o.get("fields", [])}
        for o in spec["outputs"]
    }
    rules = {c["field"]: c for c in spec["case_wide"]}

    for field in ("시험환경_온도", "시험환경_습도"):
        rule = rules[field]
        assert rule["outputs"] == ["시험계획서", "시험설계서", "을지", "시험기록서", "갑지"]
        assert all(field in outputs[key] for key in rule["outputs"])


def test_작성일자_선후_관계를_본다(result):
    """문서 간 md §4: 의뢰서 → 계획서 → 설계서 → 시험 수행.

    §3 과 판정 모양이 다르다 — "다 같은가"가 아니라 **순서**가 값이다.
    실측 샘플은 계획서 2026. 01. 02. · 설계서 2026. 01. 03. 로 순서가 맞다.
    """
    order = next(cw for cw in result.case_wide if cw.id == "W-작성일자-순서")
    assert order.status == "일치"
    assert [(c.output, c.value) for c in order.cells] == [
        ("시험계획서", "2026. 01. 02."), ("시험설계서", "2026. 01. 03.")]


def test_모든_지적이_무엇이_잡았는지_말한다():
    """`Finding.label` 이 비면 화면 뱃지가 `MAJOR` 로 되돌아간다.

    두 번 놓쳤던 자리다 — 한 번은 단일 검토 카드가 뱃지를 따로 그려서, 한 번은
    산출물 간 대조·전체 대조가 **함수**라 체커 stamp 를 안 거쳐서. 지적을 만드는
    자리가 늘 때마다 빠뜨리기 쉬우므로 소스에서 센다.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "app" / "case.py"
           ).read_text(encoding="utf-8")
    adds = re.findall(r"result\.findings\.(?:extend|append)\((.*)", src)
    # out.findings 는 위에서 이미 stamp 된 것을 다시 담는 자리다.
    bare = [a for a in adds if "stamp(" not in a and "out.findings" not in a]
    assert bare == [], "label 없이 지적을 담는 자리: " + " / ".join(bare)


def test_외부_입력값을_저장된_문서값과_추가_대조한다():
    payload = {
        "manual": [{"id": "M-접수번호", "text": "접수번호 확인",
                    "against": "시스템 부여값"}],
        "outputs": [
            {"key": "시험의뢰서", "fields": [
                {"name": "접수번호", "value": "RN-26-001", "found": True,
                 "at": "표 1"}]},
            {"key": "시험기록서", "fields": [
                {"name": "접수번호", "value": "RN-26-002", "found": True,
                 "at": "표 2"}]},
        ],
        "findings": [],
        "stats": {"findings": 0, "unreviewed": 0},
    }

    patch = manual_review_patch(
        payload, ["M-접수번호"], {"M-접수번호": "RN-26-001"})

    assert patch["manualResults"][0]["status"] == "수정 필요"
    assert [c["ok"] for c in patch["manualResults"][0]["cells"]] == [True, False]
    assert patch["manualResults"][0]["correctValue"] == "RN-26-001"
    assert patch["manualResults"][0]["affected"] == [{
        "output": "시험기록서", "currentValue": "RN-26-002",
        "correctValue": "RN-26-001", "at": "표 2"}]
    assert patch["findings"][0]["kind"] == "manual_input"
    assert "일괄 수정" in patch["findings"][0]["message"]
    assert "대상 1개 문서" in patch["findings"][0]["message"]
    assert patch["findings"][0]["document"] == "시험의뢰서 · 시험기록서"
    assert patch["stats"]["findings"] == 1


def test_외부_입력_재확정은_이전_추가_지적을_중복하지_않는다():
    payload = {
        "manual": [{"id": "M-접수번호", "against": "시스템 부여값"}],
        "outputs": [{"key": "시험의뢰서", "fields": [
            {"name": "접수번호", "value": "RN-26-001", "found": True, "at": "표 1"}]}],
        "findings": [], "stats": {},
    }
    first = manual_review_patch(
        payload, ["M-접수번호"], {"M-접수번호": "RN-99-999"})
    payload.update(first)

    second = manual_review_patch(
        payload, ["M-접수번호"], {"M-접수번호": "RN-88-888"})

    assert len([f for f in second["findings"] if f["kind"] == "manual_input"]) == 1


def test_외부_접수일은_날짜_표기가_달라도_같은_값이다():
    payload = {
        "manual": [{"id": "M-접수일", "against": "Works"}],
        "outputs": [{"key": "시험의뢰서", "fields": [
            {"name": "접수일", "value": "2026. 01. 02.", "found": True,
             "at": "표 1"}]}],
        "findings": [], "stats": {},
    }

    patch = manual_review_patch(
        payload, ["M-접수일"], {"M-접수일": "2026-01-02"})

    assert patch["manualResults"][0]["status"] == "일치"
    assert patch["findings"] == []


def test_외부_접수일은_달력에_없는_날짜를_일치로_보지_않는다():
    payload = {
        "manual": [{"id": "M-접수일", "against": "Works"}],
        "outputs": [{"key": "시험의뢰서", "fields": [
            {"name": "접수일", "value": "2026. 99. 99.", "found": True,
             "at": "표 1"}]}],
        "findings": [], "stats": {},
    }

    patch = manual_review_patch(
        payload, ["M-접수일"], {"M-접수일": "2026-99-99"})

    assert patch["manualResults"][0]["status"] == "입력값 오류"
    assert patch["findings"][0]["unreviewed"] is True


def test_외부_대조_미검토는_못_읽은_문서와_근거_쪽을_보존한다():
    payload = {
        "manual": [{"id": "M-접수번호", "against": "시스템"}],
        "outputs": [
            {"key": "읽힘", "fields": [{
                "name": "접수번호", "value": "RN-1", "found": True,
                "at": "표1", "page": 3, "label": "접수번호",
                "sourceQuote": "접수번호 | RN-1"}]},
            {"key": "못읽힘", "fields": [{
                "name": "접수번호", "value": None, "found": False,
                "at": "표2", "page": 5}]},
        ],
        "findings": [], "stats": {},
    }

    patch = manual_review_patch(
        payload, ["M-접수번호"], {"M-접수번호": "RN-1"})

    finding = patch["findings"][0]
    assert finding["document"] == "읽힘 · 못읽힘"
    assert finding["evidence"] == [{
        "at": "표1", "page": 3, "quote": "접수번호 | RN-1",
        "document": "읽힘"}]

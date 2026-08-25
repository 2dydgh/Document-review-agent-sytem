from modules.agent_history import (
    KEY_SEP,
    STATUSES,
    find_prior,
    guess_original_name,
    incomplete_checkers,
    match_findings,
)


def test_guess_strips_revision_suffix():
    assert guess_original_name("품기문서1_검토결과_수정.pdf") == "품기문서1_검토결과"
    assert guess_original_name("SRS_v2.hwpx") == "SRS"
    assert guess_original_name("그냥문서.pdf") == "그냥문서"   # 접미사 없으면 그대로


def test_find_prior_matches_by_title():
    entries = [{"id": "a", "title": "품기문서1_검토결과", "at": "2026-07-01T00:00:00"},
               {"id": "b", "title": "다른문서", "at": "2026-07-02T00:00:00"}]
    got = find_prior(entries, "품기문서1_검토결과")
    assert got["id"] == "a"
    assert find_prior(entries, "없는문서") is None


def _f(checker, msg, section="1", quote=""):
    ev = [{"quote": quote}] if quote else []
    return {"checker": checker, "message": msg, "section": section, "evidence": ev}


def test_match_classifies_closed_open_new():
    prior = [_f("completeness", "TBD 남음", "2", "TBD"),      # 고쳐질 것
             _f("consistency", "용어 흔들림", "3", "해안선")]  # 남을 것
    new = [_f("consistency", "용어 흔들림", "3", "해안선"),   # 그대로 → 그대로 있음
           _f("completeness", "새 결함", "4", "XYZ")]         # 신규
    review = match_findings(prior, new)
    by_msg = {it.finding["message"]: it.status for it in review.items}
    # **관찰이지 판정이 아니다.** "안 보임" 은 "고쳐졌다"가 아니라 "같은 인용을
    # 못 찾았다" 이다 — 문장을 다듬어도, 절이 옮겨져도 못 찾는다.
    assert by_msg["TBD 남음"] == "안 보임"       # 새 검토에 없다
    assert by_msg["용어 흔들림"] == "그대로 있음"  # 여전히 있다
    assert len(review.new_findings) == 1        # "새 결함" 은 신규
    assert review.new_findings[0]["message"] == "새 결함"


def test_statuses_vocab():
    """기계가 본 것(OBSERVED)과 사람이 내린 판정(STATUSES)은 다른 축이다.

    예전에는 `열림`·`닫힘` 하나로 뭉쳐 있었다. 이슈 트래커 말이라 검토자에게 안 통하고,
    무엇보다 추정을 단정으로 만들었다 — `닫힘` 은 "못 찾았다" 일 뿐인데 "고쳐졌다" 로
    읽힌다.
    """
    from modules.agent_history import DEFAULT_VERDICT, LEGACY, OBSERVED
    assert OBSERVED == ("그대로 있음", "안 보임", "판단 못 함")
    assert STATUSES == ("미반영", "반영됨", "해당없음")
    # 관찰마다 사람 판정의 초기값이 있어야 한다 — 없으면 드롭다운이 빈다.
    assert set(DEFAULT_VERDICT) == set(OBSERVED)
    assert set(DEFAULT_VERDICT.values()) <= set(STATUSES)
    # 옛 어휘로 저장된 이력을 읽을 수 있어야 한다.
    assert LEGACY["열림"] == "그대로 있음" and LEGACY["닫힘"] == "안 보임"


def test_process_reports_are_not_lineage_items():
    """검토 과정 보고(info·미검토)는 반영 확인에서 뺀다.

    고칠 대상이 아닌데다, 내용에 실행마다 바뀌는 값이 박혀 있다("후보 5건"→"4건",
    파일명). 두면 문서가 한 글자도 안 바뀌어도 "고쳐졌다"로 읽힌다 — 실측 5건 중 2건.
    """
    info = dict(_f("quotes", "지적 후보 5건이 원문 대조를 통과하지 못했습니다"), sev="info")
    skipped = dict(_f("presence", "칸 값 검사를 걸지 않았습니다"), unreviewed=True)
    real = _f("consistency", "용어 흔들림", "3", "해안선")
    review = match_findings([info, skipped, real], [real])
    assert [it.finding["message"] for it in review.items] == ["용어 흔들림"]
    # 신규 쪽도 마찬가지 — 매번 "신규 지적"으로 뜨면 안 된다.
    review2 = match_findings([real], [real, info, skipped])
    assert review2.new_findings == []


def test_blind_checker_yields_undecidable_not_gone():
    """이번에 제 몫을 다 못 한 검사기의 지적은 `안 보임` 이 아니라 `판단 못 함`.

    안 본 것을 "사라졌다"로 내면 안 고친 결함이 "반영됨"으로 읽힌다 — 가장 위험한
    오판이다. 실측: 재검토에서 LLM 호출 1건이 실패해 그 청크의 지적이 통째로 빠졌다.
    """
    prior = [_f("consistency", "용어 흔들림", "3", "해안선"),
             _f("completeness", "TBD 남음", "2", "TBD")]
    new = [dict(_f("consistency", "LLM 호출 실패로 일부를 못 봤습니다"),
                sev="info", unreviewed=True)]
    review = match_findings(prior, new, blind=incomplete_checkers(new))
    by_msg = {it.finding["message"]: it.status for it in review.items}
    assert by_msg["용어 흔들림"] == "판단 못 함"   # 그 검사기가 못 봤다
    assert by_msg["TBD 남음"] == "안 보임"         # 다른 검사기는 제 몫을 했다
    # 검사기별로 가른다 — 하나 실패했다고 전부 판단 못 함이면 기능이 죽는다.
    assert incomplete_checkers(new) == {"consistency"}


def test_인용이_하나라도_겹치면_같은_지적이다():
    """모델은 *무엇을* 지적할지가 아니라 **몇 건으로 묶어 낼지**를 바꾼다.

    아래 둘 다 같은 문서를 두 번 검토한 실측이다(SKN56_CDMS_RVVR_Rev05).
    인용 목록이 통째로 같기를 요구하던 때는 여기서 가짜 `안 보임` 2건과
    가짜 `신규` 4건이 났다 — 문서는 한 글자도 안 바뀌었는데.
    """
    # ① 지적 문구까지 한 글자도 안 틀리는데 인용만 2개 → 3개
    prior_12 = {"checker": "consistency", "section": "12", "message": "수일치 오류",
                "evidence": [{"quote": "The existing criticality analysis result"},
                             {"quote": "The integrity levels of requirements"}]}
    new_12 = dict(prior_12, evidence=prior_12["evidence"]
                  + [{"quote": "the integrity level of CDMS Server software is same."}])
    # ② 인용 4개짜리 지적 1건 → 같은 내용을 2건으로 쪼갬
    prior_103 = {"checker": "consistency", "section": "10.3", "message": "용어 혼용",
                 "evidence": [{"quote": "운영권조정"}, {"quote": "운영권 조정"},
                              {"quote": "운영파일"}, {"quote": "운영 파일"}]}
    new_103a = {"checker": "consistency", "section": "10.3", "message": "띄어쓰기 불일치",
                "evidence": [{"quote": "운영권조정"}, {"quote": "운영권 조정"}]}
    new_103b = {"checker": "consistency", "section": "10.3", "message": "표기 불일치",
                "evidence": [{"quote": "운영파일"}, {"quote": "운영 파일"}]}
    진짜신규 = {"checker": "consistency", "section": "7.1", "message": "마침표 앞 공백",
              "evidence": [{"quote": "SRS Rev.08 has the following changes ."}]}

    review = match_findings([prior_12, prior_103],
                            [new_12, new_103a, new_103b, 진짜신규])
    assert all(it.status == "그대로 있음" for it in review.items), \
        "문서가 안 바뀌었는데 사라졌다고 한다"
    # 쪼개진 조각들은 신규가 아니다 — 원래 지적의 다른 포장일 뿐이다.
    assert [f["section"] for f in review.new_findings] == ["7.1"]


def test_검사기가_다르면_같은_문장을_인용해도_다른_지적이다():
    """인용만 보면 안 된다. 한 문장을 형식 검사기와 표현 검사기가 함께 문다."""
    prior = [_f("completeness", "TBD 남음", "2", "TBD 한 줄")]
    new = [_f("consistency", "표현이 모호하다", "2", "TBD 한 줄")]
    review = match_findings(prior, new)
    assert review.items[0].status == "안 보임"
    assert len(review.new_findings) == 1


def test_판정_열쇠는_순번이_아니라_지적의_신원이다():
    """`{"3": "해당없음"}` 은 그 검토 안에서만 뜻이 있다.

    다음 검토의 3번째는 다른 지적이다. 검토자가 "우리 문서엔 해당 안 된다"고 판정한
    것을 이어주려면, 판정이 **무엇에 대한 것인지**가 남아야 한다.
    """
    from modules.agent_history import verdict_key
    a = _f("consistency", "용어 흔들림", "10.3", "운영파일")
    a["evidence"].append({"quote": "운영 파일"})
    b = _f("consistency", "표현이 다르게 적힘", "10.3", "운영 파일")
    b["evidence"].append({"quote": "운영파일"})
    # 문구가 달라도 인용이 같으면 같은 열쇠 — 순서도 안 탄다.
    assert verdict_key(a) == verdict_key(b)
    # 검사기가 다르면 다른 지적이다.
    assert verdict_key(a) != verdict_key(_f("completeness", "용어 흔들림", "10.3", "운영파일"))
    # 열쇠를 다시 갈라 인용을 꺼낼 수 있어야 다음 검토에서 겹침으로 맞출 수 있다.
    kind, checker, *quotes = verdict_key(a).split(KEY_SEP)
    assert (kind, checker) == ("q", "consistency")
    assert set(quotes) == {"운영파일", "운영 파일"}


def test_인용이_없는_지적도_열쇠를_갖는다():
    """규칙 검사기는 인용을 안 다는 것이 있다. 그것도 판정할 수 있어야 한다."""
    from modules.agent_history import verdict_key
    key = verdict_key({"checker": "completeness", "section": "2",
                       "message": "TBD  남음"})
    assert key.startswith("m" + KEY_SEP)
    assert key == verdict_key({"checker": "completeness", "section": "2",
                               "message": "TBD 남음"})   # 공백만 다른 건 같다


def _lineage(prior, new):
    return match_findings(prior, new).items


def test_해당없음은_다음_검토로_이어진다():
    """검사기는 다음에도 똑같이 낸다 — 안 이으면 매번 같은 것을 다시 눌러야 한다."""
    from modules.agent_history import carry_verdicts, verdict_key
    old = _f("consistency", "영문 문법", "12", "Does the software")
    before = {verdict_key(old): "해당없음"}
    now = _f("consistency", "영문 문법 오류", "12", "Does the software")
    carried = carry_verdicts(before, _lineage([now], [now]))
    assert carried == {verdict_key(now): "해당없음"}


def test_인용이_늘어도_같은_지적으로_이어준다():
    """열쇠 글자로만 맞추면 안 된다 — 모델이 인용을 하나 더 뜨면 열쇠가 달라진다."""
    from modules.agent_history import carry_verdicts, verdict_key
    old = _f("consistency", "용어 혼용", "10.3", "운영파일")
    before = {verdict_key(old): "해당없음"}
    now = _f("consistency", "용어 혼용", "10.3", "운영파일")
    now["evidence"].append({"quote": "운영 파일"})       # 이번엔 둘을 인용
    assert verdict_key(now) != verdict_key(old)          # 열쇠는 달라졌는데
    carried = carry_verdicts(before, _lineage([now], [now]))
    assert carried == {verdict_key(now): "해당없음"}      # 같은 지적으로 이어진다


def test_반영됨은_이어지지_않는다():
    """`반영됨` 은 **이번 회차에 고쳐졌나**에 대한 답이라 다음엔 다시 물어야 한다.

    이으면 위험하다 — 잘못 눌렀거나 작성자가 되돌렸을 때, 안 고쳐진 결함이 두 번째로
    조용히 넘어간다.
    """
    from modules.agent_history import carry_verdicts, verdict_key
    f = _f("consistency", "용어 혼용", "10.3", "운영파일")
    for verdict in ("반영됨", "미반영"):
        assert carry_verdicts({verdict_key(f): verdict}, _lineage([f], [f])) == {}


def test_다른_검사기의_판정은_안_옮겨온다():
    """같은 문장을 형식 검사기와 표현 검사기가 함께 문다. 다른 지적이다."""
    from modules.agent_history import carry_verdicts, verdict_key
    old = _f("completeness", "TBD 남음", "2", "TBD 한 줄")
    now = _f("consistency", "표현이 모호하다", "2", "TBD 한 줄")
    assert carry_verdicts({verdict_key(old): "해당없음"}, _lineage([now], [now])) == {}


def test_인용_범위가_달라도_같은_지적이다():
    """모델이 같은 문장을 뜨면서 앞뒤를 더 물거나 덜 문다.

    실측(SKN56 CDMS RVVR, 같은 문서 재검토). 표 칸 표시가 인용에 딸려 오느냐만
    달랐는데 `안 보임` + `신규` 로 갈라져, 안 고친 결함이 "반영됨"으로 읽혔다.
    """
    문장 = "Each system and software interface are described correctly in table 1, 2 and 3."
    prior = _f("consistency", "수일치 오류", "9", 문장)
    new = _f("consistency", "'Each'는 단수 취급한다", "9", "[Rev.00] Satisfied " + 문장)
    review = match_findings(prior=[prior], new=[new])
    assert review.items[0].status == "그대로 있음"
    assert review.new_findings == []

    # 반대 방향도 같다 — 이번엔 앞머리를 덜 물었다.
    긴 = "Satisfied The existing criticality analysis result, which result of the prior report"
    review = match_findings([_f("consistency", "문법 오류", "12", 긴)],
                            [_f("consistency", "문법 오류", "12", 긴[len("Satisfied "):])])
    assert review.items[0].status == "그대로 있음"


def test_짧은_인용은_포함만으로_이어붙이지_않는다():
    """`운영파일` 은 문서 곳곳에 있다. 포함만으로 이으면 다른 지적이 한 덩어리가 된다.

    포함은 글자가 정확히 같을 때보다 약한 신호라, 짧은 쪽이 문장 조각쯤은 돼야 한다.
    """
    prior = _f("consistency", "띄어쓰기", "10.2", "운영파일")
    new = _f("consistency", "전혀 다른 지적", "3", "표 1 의 운영파일 목록을 참고한다")
    review = match_findings([prior], [new])
    assert review.items[0].status == "안 보임"
    assert len(review.new_findings) == 1


def test_정확히_같은_인용이_있으면_범위는_안_본다():
    """겹치는 인용이 하나라도 있으면 거기서 끝난다 — 굳이 넓게 볼 이유가 없다."""
    prior = _f("consistency", "용어 혼용", "10.3", "운영권조정")
    new_exact = _f("consistency", "용어 혼용", "10.3", "운영권조정")
    review = match_findings([prior], [new_exact])
    assert review.items[0].status == "그대로 있음"
    assert review.new_findings == []


def test_같은_지적을_이번_검토의_어디로_갈지_알려준다():
    """목록만 있으면 검토자가 "그래서 어딘데" 를 알 수 없다.

    이전 지적의 좌표는 **이전 문서** 것이라 이번 문서에서 못 쓴다. 대신 이번 검토에서
    같은 결함을 짚은 지적을 가리킨다 — 화면이 그 id 로 문서의 그 자리를 연다.
    """
    prior = _f("consistency", "용어 흔들림", "3", "해안선 표기")
    now = dict(_f("consistency", "용어가 다르게 적힘", "3", "해안선 표기"), id="F-7")
    review = match_findings([prior], [now])
    assert review.items[0].status == "그대로 있음"
    assert review.items[0].match_id == "F-7"


def test_안_보이면_가리킬_자리도_없다():
    """`안 보임` 은 이번 문서에 그 지적이 없다는 뜻이다. 지어내서 가리키지 않는다."""
    review = match_findings([_f("consistency", "용어 흔들림", "3", "해안선 표기")], [])
    assert review.items[0].status == "안 보임"
    assert review.items[0].match_id == ""

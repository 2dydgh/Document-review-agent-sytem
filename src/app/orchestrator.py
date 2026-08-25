"""파이프라인 오케스트레이터."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from modules.agent_trace import ContentMatchChecker, TraceabilityChecker, build_rtm
from modules.doc_parser import chunk, load_document, normalize
from modules.llm_client import build_llm, build_vlm
from modules.report import (
    REVIEW_DETAIL,
    collect,
    fmt_chars,
    fmt_chunks,
    fmt_findings,
    fmt_sections,
    merge_duplicates,
    stamp,
)
from modules.shared import (
    Anchor,
    Config,
    Context,
    Document,
    Finding,
    RtmRow,
    Severity,
)

from .images import describe_images


def _read_images(raw, config, emit):
    """그림을 비전 모델로 읽고, 못 읽었으면 그 사실을 지적으로 남긴다.

    조용히 넘기면 그림 안의 내용을 검토한 것처럼 보인다. 실측으로 네트워크 구성도
    한 장에서 시스템 이름과 연결 관계가 나왔다 — 놓치면 추적성 검사가 통째로 못 본다.
    """
    raw = describe_images(raw, build_vlm(config), on_progress=emit,
                          concurrency=config.llm_concurrency)
    images = raw.meta.get("images") or []
    unread = len(images) - raw.meta.get("images_read", 0)
    if not images or unread <= 0:
        return raw, []

    why = ("그림 해석용 모델이 연결되지 않았습니다"
           if raw.meta.get("images_read", 0) == 0 and not config.vlm_base_url
           else "일부 그림을 읽지 못했습니다")
    # label 은 stamp() 가 체커에서 찍지만, 여기는 체커 없이 직접 만드는 지적이라
    # 자리가 없다 — 안 적으면 화면 필터 칩에 checker 키("images")가 영어로 뜬다.
    return raw, [Finding(
        checker="images",
        label="그림 해석",
        severity=Severity.INFO,
        message=(f"그림 {unread}/{len(images)}장을 읽지 않았습니다 — {why}. "
                 f"그림 안의 표·구성도에 적힌 내용은 검토되지 않았습니다."),
        anchor=Anchor(page=None, section=None),
        suggestion=("설정의 vlm_base_url 또는 환경변수 LLM_OCR_URL 로 비전 모델을 "
                    "연결하면 그림 안의 글자까지 읽습니다."),
        unreviewed=True,
    )]


def _parser_warning_findings(raw) -> list[Finding]:
    """로더가 meta["parser_warnings"] 에 남긴 항목을 미검토 INFO 지적으로 편다.

    trkim 파서 경로(3-way 통합, 기본 파서)는 표 셀 글꼴·그림 ZIP part 경로를
    모델 자체에서 못 만든다 — 그래서 TrkimLoader.load 가 같은 파일을 legacy
    로더로 한 번 더 읽어 meta["tables"]/["images"] 를 접붙인다(정상 경로라면
    이 보충이 성공해 표 글꼴 검사·그림 해석이 그대로 동작한다). parser_warnings
    는 그 보충이 실패했을 때(예: legacy 가 못 읽는 스캔 PDF)와 trkim 파서 자체
    경고(model.warnings)일 때만 채워진다 — parser_bridge.TrkimLoader 참고.
    조용히 넘기면 "검사했더니 이상 없음"과 구분되지 않는다(CLAUDE.md "모르면
    모른다고 말한다"). _read_images 와 같은 계약이다.
    """
    return [Finding(
        checker="parser",
        label="문서 읽기",   # _read_images 와 같은 이유 — 체커 없는 직접 생성 지적
        severity=Severity.INFO,
        message=w,
        anchor=Anchor(page=None, section=None),
        unreviewed=True,
    # 같은 문장은 한 번만 카드로 만든다. 같은 그림이 머리말과 본문에 함께 들어간
    # 문서에서 똑같은 OCR 경고가 두 장 떴다 — 같은 사실을 두 번 말하면 검토자는
    # 문제가 둘인 줄 안다. 순서는 지킨다(dict.fromkeys).
    ) for w in dict.fromkeys(raw.meta.get("parser_warnings") or [])]


def _ingestion_detail(raw) -> str:
    """진행 화면 '문서 준비' 줄. meta 에 실제로 있는 것만 띄운다.

    "1.2만자" → "1.2만자 · 236쪽 · 표 194". PDF 가 아닌 입력(docx·hwpx)은
    meta 에 쪽·표가 없으므로 예전 문자열 그대로 나간다 — 없는 수를 지어내지 않는다.
    """
    parts = [fmt_chars(len(raw.text))]
    pages = raw.meta.get("pages")
    if pages:
        parts.append(f"{pages}쪽")
    # meta["tables"] 는 표마다 열·글꼴을 담은 **목록**이다(표 글꼴 검사가 읽는다).
    # 여기서 필요한 건 개수뿐이다. 예전에는 `표 {tables}` 로 그대로 이어붙여,
    # Word 문서를 올리면 진행 화면에 딕셔너리가 통째로 찍혔다.
    tables = len(raw.meta.get("tables") or ())
    if tables:
        parts.append(f"표 {tables}")
    return " · ".join(parts)


@dataclass
class ReviewResult:
    source_path: str
    findings: list[Finding] = field(default_factory=list)
    rtm: list[RtmRow] = field(default_factory=list)
    # 파이프라인 통계 (UI 진행바 표시용)
    section_count: int = 0
    chunk_count: int = 0
    char_count: int = 0
    # 그림의 번호·크기. 화면이 이것을 /api/locate 로 돌려보내면 서버가 뷰어용 PDF
    # 안의 이미지와 짝지어 좌표를 낸다 — 그림 설명에서 나온 지적을 짚기 위해서다.
    images: list[dict] = field(default_factory=list)
    # 정규화된 문서 본문. 미리보기가 이걸 렌더한다 — 업로드 원본은 검토가 끝나면
    # 지워지므로(web/server.py), 여기서 넘겨주지 않으면 본문을 다시 얻을 길이 없다.
    # 비교(review_documents)는 문서가 둘이라 이 자리에 담지 않는다.
    document: Document | None = None


def _review_plans(checkers: Sequence, doc: Document, ctx: Context) -> tuple[list[dict], set[int]]:
    """진행 화면용 작업 계획과 자체 진행 단위가 있는 검사기 집합.

    규칙 검사기는 매우 빨라 별도 ``plan``을 구현하지 않는다. 그렇다고 화면에서
    아예 빼면 사용자는 LLM 두 줄만 보고 규칙 검사가 실행되지 않은 것으로 읽는다.
    자체 계획이 없는 검사기들을 하나의 규칙 검사 레인으로 묶어 정직하게 센다.
    """
    plans: list[dict] = []
    planned: set[int] = set()
    rule_count = 0
    for checker in checkers:
        plan_fn = getattr(checker, "plan", None)
        plan = plan_fn(doc, ctx) if plan_fn is not None else None
        if plan is None:
            rule_count += 1
            continue
        planned.add(id(checker))
        plans.append(plan)
    if rule_count:
        plans.insert(0, {
            "kind": "rule",
            "total": rule_count,
            "label": "규칙 검사",
            "description": "필수 항목·서식·목록을 자동 규칙으로 확인",
            "scope": f"{rule_count}개 검사",
        })
    return plans, planned


def review_document(path: str | Path, config: Config,
                    on_progress: Callable[[dict], None] | None = None,
                    criteria: Sequence = (),
                    extra_checkers: Sequence = ()) -> ReviewResult:
    """평면 결과가 필요한 기존 호출부용 단일 문서 검토 어댑터.

    실제 검사는 ``review_document_by_criteria`` 한 곳에서 한다. CLI·기존 모듈 사용자는
    항목별 결과가 필요 없으므로 같은 결과를 ``ReviewResult`` 모양으로만 접어 받는다.
    """
    detailed = review_document_by_criteria(
        path, criteria, config, on_progress=on_progress,
        extra_checkers=extra_checkers)
    return ReviewResult(
        source_path=detailed.source_path,
        findings=detailed.findings,
        section_count=detailed.section_count,
        chunk_count=detailed.chunk_count,
        char_count=detailed.char_count,
        document=detailed.document,
        images=detailed.images,
    )


def review_documents(
    parent_path: str | Path, child_path: str | Path, config: Config
) -> ReviewResult:
    parent_path = Path(parent_path)
    child_path = Path(child_path)
    parent = normalize(load_document(parent_path), doc_type=config.review.doc_type)
    child = normalize(load_document(child_path), doc_type=config.review.doc_type)
    llm = build_llm(config)
    ctx = Context(review=config.review, llm=llm, chunks=[], other=child,
                  llm_concurrency=config.llm_concurrency)
    findings: list[Finding] = []
    for checker in (TraceabilityChecker(), ContentMatchChecker()):
        findings.extend(stamp(checker, checker.check(parent, ctx)))
    rtm = build_rtm(parent, child, config.review.id_pattern,
                    config.review.scope_pattern,
                    config.review.id_rollup_separator)
    source = f"{parent_path} ↔ {child_path}"
    return ReviewResult(source_path=source, findings=collect(findings), rtm=rtm)


def _item_status(findings: list[Finding]) -> str:
    """체크리스트 항목 상태. 지적 0건과 "검사 못 함"을 구분한다.

    미검토 보고(Finding.unreviewed)만 있는 항목을 clean 으로 두면 검사하지 않은
    것이 "이상 없음"으로 보이고, flagged 로 두면 "문제 발견"으로 보인다. 둘 다
    거짓이라 상태를 하나 더 둔다.
    """
    if any(not f.unreviewed for f in findings):
        return "flagged"
    if findings:
        return "unreviewed"
    return "clean"


@dataclass
class ItemResult:
    no: str
    text: str
    group: str
    status: str                    # flagged | clean | unreviewed | manual
    findings: list[Finding] = field(default_factory=list)
    # 기준 본문 밖의 것. 화면이 "이 기준이 뭐였는지"를 보여주려면 필요하다 —
    # 원본 엑셀은 사내 파일이라 앱에 없고, 검토자가 "공통3" 을 보고도 무엇을
    # 확인하라는 건지 알 길이 없었다.
    note: str = ""                 # 확인 방법(세부 기준)
    mode: str = ""                 # 규칙 | 조각 | 전체 | 사람 — 왜 그 상태인지
    # mode 를 기준이 직접 적었는가. "사람이 그렇게 정했다"와 "아무도 안 정해서
    # 사람 몫으로 떨어졌다"는 검토자가 할 일이 다르다.
    mode_declared: bool = False
    layer: str = ""                # 공통 | 팀별 | 업로드 — 이 기준이 온 층


@dataclass
class CriteriaReviewResult:
    source_path: str
    items: list[ItemResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    section_count: int = 0
    chunk_count: int = 0
    char_count: int = 0
    document: Document | None = None
    images: list[dict] = field(default_factory=list)


def _out_of_target(criterion, output_key: str) -> str:
    """이 기준이 **이 문서**를 볼 항목이 아닌가. 아니면 "" (적용한다).

    돌려주는 문자열은 왜 아닌지다 — 화면이 그대로 쓴다.

    기준이 `applies_to` 를 안 적었으면 문서를 가리지 않는다(대부분이 그렇다).
    적었는데 이 문서가 어느 산출물인지 **가리지 못했으면**(output_key 가 빈
    문자열) 적용 여부를 모르는 것이다. 모르는 것을 해당없음으로 두면 검사한 적
    없는 기준이 "정상"으로 보인다 — 그건 이 도구가 낼 수 있는 최악의 거짓말이다.
    """
    targets = list(getattr(criterion, "applies_to", None) or ())
    if not targets:
        return ""
    if not output_key:
        return (f"이 기준은 {' · '.join(targets)} 전용인데, 올린 문서가 어느 "
                "산출물인지 파일명으로 가리지 못해 적용 여부를 판단하지 못했습니다.")
    if output_key in targets:
        return ""
    return f"이 기준은 {' · '.join(targets)} 전용입니다 (이 문서는 {output_key})."


def review_document_by_criteria(path, criteria: Sequence, config,
                                on_progress: Callable[[dict], None] | None = None,
                                field_specs: Sequence = (), output_key: str = "",
                                extra_checkers: Sequence = ()) -> CriteriaReviewResult:
    """공통·팀·선택 업로드 기준이 이끄는 단일 문서 검토.

    항목을 키워드 맵으로 검사기에 잇는다. 걸린 검사기는 **한 번만** 돌리고(항목마다
    반복하면 같은 LLM 작업을 항목 수만큼 되풀이한다), 그 지적을 걸린 항목 **각각**에
    단다. 안 걸린 항목은 사람 확인 몫이다. ``extra_checkers`` 는 outputs 구조 절에서
    온 검사라 기준 항목에 억지로 귀속하지 않고 평면 지적으로만 남긴다.
    """
    from modules.agent_checklist import (
        checker_key,
        llm_checkers_for,
        missing_value,
        mode_for,
        out_of_scope,
        rule_checkers,
    )

    emit = on_progress or (lambda ev: None)
    path = Path(path)

    # 수정 2026-08-06: 파싱 전에 running 을 먼저 알린다 — 스캔 PDF 는 OCR 로
    # 파싱에만 수 분이 걸리는데, 첫 이벤트가 파싱 뒤에 나가면 화면은 그동안
    # 바이트 하나 못 받아 멈춘 것처럼 보인다(실측 75초+ 무소식).
    emit({"key": "ingestion", "status": "running",
          "detail": "문서 파싱 중 — 스캔 문서는 OCR 때문에 수 분 걸릴 수 있습니다"})
    raw = load_document(path)
    raw, image_findings = _read_images(raw, config, emit)
    parser_findings = _parser_warning_findings(raw)
    emit({"key": "ingestion", "status": "done", "detail": _ingestion_detail(raw)})
    doc = normalize(raw, doc_type=config.review.doc_type)
    sections = list(doc.iter_sections())
    emit({"key": "normalize", "status": "done", "detail": fmt_sections(len(sections))})
    chunks = chunk(doc, max_chars=config.chunk_max_chars)
    emit({"key": "chunking", "status": "done", "detail": fmt_chunks(len(chunks))})

    llm = build_llm(config)
    ctx = Context(review=config.review, llm=llm, chunks=chunks, on_progress=emit,
                  llm_concurrency=config.llm_concurrency, rescue_max=config.llm_rescue_max)

    # 기준 목록 → 검사기. 조각 기준은 하나의 ChunkCriteriaChecker 에 묶이고, 규칙
    # 기준은 agent 라벨이 정한 규칙 검사기를 쓴다(같은 검사기는 한 번만 만든다).
    #
    # 예전에는 여기서 base_checkers(Placeholder·Consistency)를 체크리스트와 무관하게
    # 항상 돌렸다. 그래서 기준 7개 중 0개가 검사되는 팀에서도 "기본 검토" 항목에
    # 지적이 나와 검사된 것처럼 보였다. 지금은 그 자리를 공통 프리셋이 가져간다 —
    # 호출부가 공통 기준을 items 에 합쳐 넘긴다(compose_review_preset).
    items = list(criteria)
    # 이 문서를 볼 항목이 아닌 기준은 **검사기를 만들기 전에** 뺀다. 결과 자리에서만
    # 걸러도 화면은 맞지만, 그때는 이미 그 기준이 LLM 프롬프트에 실려 나간 뒤다 —
    # 갑지 전용 기준을 시험의뢰서와 함께 물으면 돈과 시간이 나가고, 모델이 없는
    # 것을 찾다 지어낼 자리도 생긴다.
    applicable = [c for c in items if not _out_of_target(c, output_key)]
    # 검사기를 **이름으로** 들고 있는다. 규칙은 기준이 댄 check 이름, LLM 은 mode.
    # 지적을 나눠 줄 때 이 이름이 열쇠다 — 예전처럼 type 으로 묶으면 어느 기준의
    # 것인지 알 수 없어 같은 라벨 기준 전부에 같은 지적을 복사하게 된다.
    rules = rule_checkers(applicable, field_specs)
    # 기준값이 없어 돌 수 없는 규칙 검사는 **만들지 않는다.** 만들어 두면 "검사할
    # 것이 검토 기준에 없어 수행하지 않았습니다" 한 장을 매 검토마다 낸다 — 문서
    # 이야기가 아니라 기준이 비었다는 이야기라 지적 목록에 있을 것이 아니다.
    # 그 사실은 아래에서 **그 기준의 상태**(사람 확인 필요)가 지고, 왜인지는
    # note 가 말한다. 값을 적은 팀에서는 그대로 자동으로 돈다.
    blocked_rules: dict[str, str] = {}
    for c in applicable:
        why = missing_value(c, config.review)
        if not why:
            continue
        key = checker_key(c)
        if key and rules.pop(key, None) is not None:
            blocked_rules[key] = why
    llm_checkers = (llm_checkers_for(applicable, doc_max_chars=config.llm_doc_max_chars)
                    if config.llm_enabled else {})
    extras = {f"_extra:{i}": checker for i, checker in enumerate(extra_checkers)}
    by_key: dict = {**rules, **extras, **llm_checkers}

    # review_document 과 같은 이유로, 체커 루프 전에 작업량(plan)을 한 번에 모아
    # review 이벤트에 실어 보낸다. 이게 있어야 진행 화면이 레인을 그리고 퍼센트가
    # 정직해진다 — 빠른 규칙 체커도 한 레인으로 묶어 실행 여부를 숨기지 않는다.
    checkers = list(by_key.values())
    plans, planned = _review_plans(checkers, doc, ctx)
    # review_document 과 같은 이유 — 규칙 검사가 한 레인으로 묶이므로 실행도
    # 한 덩어리로 먼저 온다. rules·llm dict 병합 순서에 기대지 않는다.
    by_key = dict(sorted(by_key.items(), key=lambda kv: id(kv[1]) in planned))

    first_event = {"key": "review", "status": "running", "detail": REVIEW_DETAIL}
    if plans:
        first_event["plan"] = plans
    emit(first_event)

    findings_by_key: dict = {}
    rules_done = 0
    for key, ck in by_key.items():
        label = getattr(ck, "label", None)
        active = label if id(ck) in planned else "규칙 검사"
        emit({"key": "review", "status": "running",
              "detail": f"{label} 중" if label else f"{ck.name} 검사 중",
              "active": active})
        findings_by_key[key] = collect(stamp(ck, ck.check(doc, ctx)))
        if id(ck) not in planned:
            rules_done += 1
            emit({"key": "review", "status": "running",
                  "detail": f"규칙 검사 {rules_done}/{plans[0]['total']} 완료",
                  "active": "규칙 검사",
                  "step": {"kind": "rule", "i": rules_done,
                           "total": plans[0]["total"], "label": "규칙 검사"}})
    emit({"key": "review", "status": "done", "detail": REVIEW_DETAIL, "active": ""})

    item_results: list[ItemResult] = []
    all_findings: list[Finding] = []
    if not items and not extra_checkers:
        all_findings.append(Finding(
            checker="review",
            severity=Severity.INFO,
            message="적용할 검토 기준이 없어 이 문서를 검사하지 않았습니다.",
            anchor=Anchor(page=None, section=None),
            suggestion="검토 기준(공통·팀별)이 설치되어 있는지 확인하세요.",
            unreviewed=True,
        ))

    def _result(criterion, mode: str, status: str, findings=(),
                note_suffix: str = "") -> ItemResult:
        """항목 결과. 기준 자체(note·mode)도 함께 싣는다 — 화면이 "이 기준이
        뭐였는지"를 보여줄 수 있어야 번호가 의미를 갖는다. 원본 엑셀은 사내
        파일이라 앱에 없고, 검토자가 "공통3" 을 보고도 확인할 길이 없었다.

        note_suffix 는 왜 사람 몫인지를 덧붙인다. "규칙이라 적혀 있는데 왜
        수동인가"에 답이 없으면 데이터가 잘못된 것처럼 보인다."""
        note = getattr(criterion, "note", "") or ""
        if note_suffix:
            note = f"{note}\n\n{note_suffix}".strip()
        return ItemResult(
            no=criterion.no, text=criterion.text, group=criterion.group,
            status=status, findings=list(findings), note=note, mode=mode,
            # 이 mode 를 **기준이 직접 적었나**. 안 적으면 라벨 기본값이고, 라벨도
            # 없으면 "사람" 으로 떨어진다(checklist_map.mode_for). 둘을 못 가르면
            # 화면이 "이 기준은 문서만으로 판정할 수 없다"고 말하게 되는데, 업로드
            # 체크리스트는 mode 칸 자체가 없어 **전부** 그 말을 뒤집어썼다 —
            # "PDF 필드오류 문자열이 있는가" 처럼 기계가 볼 수 있는 항목까지.
            mode_declared=(getattr(criterion, "mode", "") or "").strip() == mode,
            layer=getattr(criterion, "layer", "") or "")

    for it in items:
        mode = mode_for(it)
        no = str(getattr(it, "no", "") or "")
        # 이 문서를 볼 항목인가부터. 아니면 규칙·LLM 갈래를 아예 타지 않는다.
        # 문서를 못 가려 판단이 안 서는 경우는 `na` 가 아니라 사람 몫이다 —
        # 위 _out_of_target 주석 참고.
        why = _out_of_target(it, output_key)
        if why:
            item_results.append(_result(
                it, mode, "na" if output_key else "manual", note_suffix=why))
            continue
        if mode in ("LLM-조각", "LLM-문서") and llm_checkers.get(mode) is not None:
            # 상태는 검사기가 낸 판정이 정한다. 지적 유무로 정하면 "안 물어본 것"과
            # "물어봤고 통과"가 같아진다.
            #
            # 조각 기준은 한 검사기가 여럿을 본다 — 지적을 낸 기준(rule_id)으로
            # 갈라야 한다. 예전에는 항목마다 그 검사기의 지적 **전부**를 받아,
            # 오탈자 기준 아래에 모호성 지적이 뜨고 같은 라벨 기준 둘의 건수가
            # 늘 똑같았다.
            verdict = llm_checkers[mode].verdicts.get(no, "미판정")
            mine = [f for f in findings_by_key.get(mode, []) if f.rule_id == no]
            # "해당없음"과 "검사 못 함"을 섞지 않는다. 앞은 정상이고(이 기준이
            # 이 문서를 대상으로 하지 않는다) 뒤는 고쳐야 할 것이다(LLM 이 안
            # 붙었거나 응답이 없었다). 한 말로 뭉치면 검토자가 "검사 안 됨 5" 를
            # 보고 무엇을 해야 하는지 알 수 없다.
            status = {"위반": "flagged", "통과": "clean",
                      "해당없음": "na"}.get(verdict, "unreviewed")
            # 미판정에도 두 가지가 있고 검토자가 할 일이 다르다.
            #   전부 무응답  → 서버가 안 붙었거나 죽었다. 고칠 곳은 설정·장비다.
            #   응답은 왔는데 이 기준만 미판정 → 모델이 그 기준을 빠뜨렸다
            #     (_BATCH 주석의 커버리지 문제). 다시 돌리면 나올 수 있다.
            # 한 말로 뭉치면 검토자가 무엇을 해야 하는지 알 수 없다.
            ck = llm_checkers[mode]
            if status == "unreviewed" and ck.calls and ck.unanswered == ck.calls:
                item_results.append(_result(
                    it, mode, "noanswer",
                    note_suffix="LLM 이 답하지 않아 이 기준을 보지 못했습니다."))
                continue
            if status == "unreviewed":
                item_results.append(_result(
                    it, mode, status, mine,
                    note_suffix="LLM 이 답했지만 이 기준의 판정은 오지 않았습니다 "
                                "— 다시 검토하면 나올 수 있습니다."))
                continue
            item_results.append(_result(it, mode, status, mine))
            continue
        if mode == "규칙":
            # 기준이 댄 이름의 검사기 것만 받는다. 이름을 안 댔거나 모르는 이름이면
            # 이 기준을 검사하는 규칙이 아직 없다 — 사람 몫이다. 예전에는 agent
            # 라벨로 이어서, 규칙 검사기 둘이 낸 지적이 그 라벨을 단 기준 전부에
            # (EV2 는 15개) 복사됐다. 하나짜리 결함이 열다섯 건으로 보였다.
            key = checker_key(it)
            if not key:
                item_results.append(_result(
                    it, mode, "manual",
                    note_suffix="이 기준을 검사하는 규칙이 아직 없습니다."))
                continue
            if key in blocked_rules:
                # 검사할 규칙은 있는데 **잴 값**을 기준이 안 줬다. 값을 적은 팀에서는
                # 그대로 자동으로 돈다 — 그 차이를 말해야 검토자가 "우리 팀은 왜
                # 사람이 보나"를 알 수 있다.
                item_results.append(_result(
                    it, mode, "manual",
                    note_suffix=f"{blocked_rules[key]}이 검토 기준에 없어 자동으로 "
                                f"검사하지 못합니다 — 사람이 확인합니다. "
                                f"(목록을 기준에 적은 팀에서는 자동으로 검사합니다.)"))
                continue
            fs = findings_by_key.get(key, [])
            item_results.append(_result(it, mode, _item_status(fs), fs))
            continue
        # 문서 검토 항목이 아닌 계열(생성·이력 관리). "사람이 확인" 과 갈라야
        # 한다 — 사람 확인은 이 문서를 사람이 보라는 뜻이고, 이쪽은 이 문서를
        # 볼 항목이 아니라는 뜻이다. 규칙·LLM 갈래를 다 거친 뒤라, 기준이
        # mode·check 를 명시했으면 그쪽이 이미 가져갔다.
        if out_of_scope(it):
            item_results.append(_result(it, mode, "outofscope"))
            continue
        # 전체·사람: 검사기가 없다. 사람 몫으로 둔다.
        item_results.append(_result(it, mode, "manual"))
    # 지적 자체는 검사기당 한 벌만 최종 목록에 담는다(항목마다 중복 담지 않는다).
    for fs in findings_by_key.values():
        all_findings.extend(fs)
    # 그림·파서 경고 보고는 어느 체크리스트 항목에도 속하지 않는다(파이프라인에 대한 보고다).
    all_findings.extend(image_findings)
    all_findings.extend(parser_findings)

    # 같은 근거·같은 종류의 중복 카드 병합. 항목이 버린 지적을 참조하고 있으면
    # 생존 지적으로 갈아끼운다 — 참조를 끊으면 그 기준의 지적이 조용히 사라지고,
    # 갈아끼우면 카드의 "기준: … 외 N건" 이 두 기준을 다 말한다.
    all_findings, _replaced = merge_duplicates(all_findings)
    if _replaced:
        for ir in item_results:
            merged, seen_ids = [], set()
            for f in ir.findings:
                g = _replaced.get(id(f), f)
                if id(g) not in seen_ids:
                    seen_ids.add(id(g))
                    merged.append(g)
            ir.findings = merged

    emit({"key": "report", "status": "done", "detail": fmt_findings(len(all_findings))})
    return CriteriaReviewResult(
        source_path=str(path), items=item_results, findings=all_findings,
        section_count=len(sections), chunk_count=len(chunks),
        char_count=sum(len(s.text) for s in sections), document=doc,
        images=list(raw.meta.get("images") or []))


def review_with_checklist(path, checklist, config,
                          on_progress: Callable[[dict], None] | None = None,
                          field_specs: Sequence = (),
                          output_key: str = "") -> CriteriaReviewResult:
    """구 API 호환 어댑터. 새 코드는 ``review_document_by_criteria``를 사용한다."""
    return review_document_by_criteria(
        path, getattr(checklist, "items", ()), config,
        on_progress=on_progress, field_specs=field_specs, output_key=output_key)


# 결과 타입을 직접 import한 기존 모듈을 위한 호환 이름.
ChecklistReviewResult = CriteriaReviewResult

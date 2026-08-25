"""문서 비교를 브라우저에서 실행하는 로컬 API 서버.

`--emit-ui`(정적 내보내기)가 "터미널에서 만든 결과를 페이지가 읽는" 방식이라면,
여기서는 페이지가 파일을 올리고 결과를 받아온다. 엔진은 동일한 `review_documents`를
쓰고, 응답 모양도 `to_ui_payload`로 통일해 프론트엔드가 그대로 대입할 수 있게 한다.

로컬 전용이다. 인증이 없으므로 127.0.0.1 밖으로 열지 말 것.
"""
from __future__ import annotations

import json
import queue
import shutil
import tempfile
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from modules.agent_trace import extract_id_anchors
from modules.doc_parser import (
    ConvertUnavailable,
    UnsupportedFormatError,
    load_document,
    normalize,
    to_pdf,
)
from modules.llm_client import build_llm
from modules.preset import (
    ChecklistError,
    ChecklistStore,
    UnsupportedChecklistFormat,
    build_items,
    compose_review_preset,
    extract_tables,
    find_header,
    guess_columns,
    load_presets,
    to_csv,
)
from modules.report import annotate, locate, to_ui_payload
from modules.shared import suggest_revision

from .config import apply_criteria_params, load_config
from .history import HistoryError, HistoryStore
from .orchestrator import review_documents


def _disposition(filename: str) -> str:
    """다운로드 파일명을 헤더에 안전하게 싣는다.

    HTTP 헤더는 latin-1만 담는다. 한글 파일명을 그대로 넣으면 Starlette이
    인코딩하다 UnicodeEncodeError로 죽고, 화면에는 500이 뜬다 — 실제로 그렇게
    터졌다(운영개념기술서_v2.0.pdf).

    RFC 5987: 옛 브라우저용 ASCII 이름과 filename*(UTF-8 퍼센트 인코딩)을 함께
    보낸다. 요즘 브라우저는 filename*을 쓴다.
    """
    ascii_name = filename.encode("ascii", "ignore").decode() or "review.pdf"
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}")


# 실무 HWPX는 이미지가 많아 쉽게 수 MB를 넘는다 (샘플 상세설계서가 4MB).
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
_CHUNK = 64 * 1024

# src/docreview/web/server.py → 저장소 루트
_REPO_ROOT = Path(__file__).resolve().parents[2]
# 씨앗 프리셋(공통·팀별) 디렉터리. 배포에 씨앗이 없으면 compose 가 업로드만 돌려준다.
_SEED_DIR = _REPO_ROOT / "presets" / "criteria"

# /api/review 스트림에서 스레드 종료를 알리는 표식. None은 이벤트일 수도 있으니 쓰지 않는다.
_DONE = object()


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    """업로드를 dest_dir에 저장한다. 경로 탈출과 과대 파일을 막는다."""
    # 브라우저가 보낸 filename은 신뢰할 수 없다. "../../etc/passwd" → "passwd".
    name = Path(upload.filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    size = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(_CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_BYTES // 1024 // 1024}MB).")
            fh.write(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail=f"'{name}'가 비어 있습니다.")
    return dest


def _rules_only(config):
    """LLM 을 쓰지 않는 설정. 화면의 "규칙만 · 빠름"이 이걸 쓴다.

    텍스트 모델과 비전 모델을 **둘 다** 꺼야 한다. provider 만 echo 로 바꾸면
    vlm_base_url 이 살아남아 "빠름"을 골랐는데도 그림 해석이 돌아 느려진다.
    """
    return replace(config, llm_provider="echo", vlm_base_url="", llm_enabled=False)


#: 임시 폴더를 몇 시간 지나면 남의 것으로 보고 지우는가. 검토 1건은 최대 5분
#: 이므로(CLAUDE.md 성능 스펙) 이보다 한참 짧다 — 24시간이면 도는 검토를 지울
#: 위험은 사실상 없고, 죽은 서버가 남긴 것만 걷힌다.
_TMP_MAX_AGE_S = 24 * 3600


def _sweep_stale_uploads() -> None:
    """죽은 서버가 남긴 업로드 임시 폴더를 걷는다. 서버가 뜰 때 한 번 돈다.

    업로드 원본은 `tempfile.TemporaryDirectory(prefix="docreview…")` 에 풀리고,
    검토 스레드가 끝나면 청소 스레드가 지운다. 그런데 그 청소 스레드는
    daemon 이라 **서버가 죽으면 같이 죽는다** — 지우지 못한 폴더를 그 뒤로
    아무도 다시 보지 않았다.

    실측(2026-08-21): /tmp 에 8/13·8/14 업로드분 세 벌이 남아 있었고, 안에는
    시험의뢰서·성적서 같은 **실무 원본 20MB** 가 그대로 있었다. 권한이 700 이라
    남이 읽지는 못해도, 여러 계정이 붙는 서버에서 오래 둘 물건이 아니다.
    CLAUDE.md 의 "보관 기간 경과 시 자동 삭제" 방침이 임시 폴더에는 없었다.

    **지우다 실패해도 서버는 뜬다.** 남의 계정 것일 수도, /tmp 를 못 읽을 수도
    있다 — 뒷정리 하나가 서버를 못 뜨게 하는 것이 훨씬 나쁘다. 목록 훑기까지
    통째로 감싸는 이유가 그것이다.
    """
    try:
        root = Path(tempfile.gettempdir())
        cutoff = time.time() - _TMP_MAX_AGE_S
        for path in root.glob("docreview*"):
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        return


def create_app(settings: str | Path = "config/settings.toml",
               frontend_dir: str | Path | None = None,
               history_dir: str | Path | None = None,
               seed_dir: str | Path | None = None) -> FastAPI:
    # 설정이 잘못됐으면 요청 때가 아니라 지금 실패하는 편이 낫다.
    config = load_config(str(settings))
    # trkim 파서를 앞순위 로더로 장착 + Qwen-VL OCR 훅 (3-way 통합).
    # 기본 파서다 — 설정 게이트 없이 항상 앞순위. 표 글꼴·그림 메타 부족분은
    # parser_bridge.TrkimLoader.load 가 legacy 파서로 보충한다.
    from .parser_bridge import install_trkim_parser
    install_trkim_parser(config.vlm_base_url, config.vlm_model, config.llm_api_key)
    _sweep_stale_uploads()
    app = FastAPI(title="DocReview")
    # 씨앗 프리셋(공통·팀별) 디렉터리. 주입 없으면 repo 의 presets/criteria.
    seed_root = Path(seed_dir) if seed_dir else _SEED_DIR
    history = HistoryStore(
        Path(history_dir) if history_dir else _REPO_ROOT / ".docreview" / "history")

    # 업로드 기준(3층 중 셋째). 공통·팀별은 repo 의 presets/criteria 에 있고,
    # 이것만 사용자가 올린 것이라 여기 떨어진다 — 자리를 나눠 층이 눈에 보이게 한다.
    checklists = ChecklistStore(
        (Path(history_dir).parent if history_dir else _REPO_ROOT / ".docreview")
        / "criteria" / "uploads")

    def _teams() -> list[dict]:
        """고를 수 있는 검토 기준 = 팀 프리셋.

        공통 기준은 목록에 없다 — 고르고 말고 할 것 없이 늘 포함되기 때문이다
        (`resolve_criteria`: 공통 → 팀 → 업로드). 업로드 기준은 별도 API 로
        관리한다(/api/checklists).

        예전에는 이 목록이 `presets/checklists/*.yaml` 이었다. 그 파일들은 검토
        기준이 아니라 **검사 설정**(요건 ID 정규식 등)이었고, 값은 개발 중에
        실제 문서를 보고 거꾸로 뽑은 것이었다 — 문서에서 뽑은 잣대로 그 문서를
        재면 틀릴 수가 없다. 기준은 3층(공통·팀별·업로드)에서만 온다.
        """
        return [{"id": p.id, "name": p.name or p.id, "doc_type": ""}
                for p in load_presets(seed_root) if p.scope == "팀별"]

    def _criteria_for(team: str, uploaded=None):
        """고른 팀 → 이번 검토에 적용할 기준 = 공통 ∪ 팀 ∪ 업로드.

        브라우저가 보낸 문자열을 경로로 그대로 쓰면 서버의 아무 파일이나 읽게
        된다(../../etc/passwd). 그래서 경로를 만들지 않고 열거한 목록에서 찾는다.
        """
        if team and team not in {t["id"] for t in _teams()}:
            raise HTTPException(
                status_code=400, detail=f"그런 팀 기준이 없습니다: {team}")
        return compose_review_preset(seed_root, uploaded, team=team or None)

    def _output_key_for(team: str, filename: str) -> str:
        """파일명 → 팀 기준의 산출물 key. 못 가리면 "".

        추측하지 않는다. 못 가린 채 아무 key 나 주면 `applies_to` 를 적은 기준이
        엉뚱하게 해당없음으로 빠져 조용히 검사되지 않는다.
        """
        if not team:
            return ""
        from .case import output_spec_for  # noqa: PLC0415
        spec, _why = output_spec_for(filename, _team_preset(team))
        return str((spec or {}).get("key", ""))

    def _presence_fields_for(team: str, filename: str):
        """기준이 `check: field_presence` 로 골라 쓸 칸 규격. (규격, 못 낸 이유)."""
        if not team:
            return (), ""
        from .case import presence_fields_for  # noqa: PLC0415
        return presence_fields_for(filename, _team_preset(team))

    def _supplemental_for(team: str, filename: str):
        """기준 항목 밖의 고정 문구·서명·글꼴 검사기. (검사기, 못 건 이유)."""
        if not team:
            return (), ""
        from .case import supplemental_checkers_for  # noqa: PLC0415
        checkers, why = supplemental_checkers_for(filename, _team_preset(team))
        return tuple(checkers), why

    def _config_for(team: str):
        """고른 기준이 검사 매개변수를 정한다(id_pattern·필수 절 등).

        기준이 안 적어두면 비어 있는 채로 둔다 — 코드가 지어내지 않는다.
        추적성처럼 매개변수가 있어야 도는 검사는 그때 "기준 없음"으로 남는다.
        """
        base = load_config(str(settings))
        return replace(base, review=apply_criteria_params(
            base.review, _criteria_for(team).items))

    def _with_llm(choice: str, checklist: str = ""):
        """이번 검토에 쓸 설정.

        LLM 은 켜고 끄는 것만 고를 수 있다. provider 를 클라이언트가 고르게 두면
        안 된다 — "claude"는 외부 API 이고, 여기 올라오는 문서는 밖으로 나가면 안
        되는 문서다. 어떤 모델을 쓸지는 서버 설정(settings.toml)이 정한다.

        체크리스트는 다르다. 어떤 잣대로 잴지는 검토자가 정하는 게 맞다. 다만
        경로가 아니라 **열거된 목록의 id 로만** 받는다(_criteria_for 참고).
        """
        if choice == "on":
            cfg = config
        elif choice == "off":
            cfg = _rules_only(config)   # 룰만 돈다. 빠르다.
        else:
            raise HTTPException(
                status_code=400,
                detail="llm은 'on' 또는 'off'만 됩니다. 어떤 모델을 쓸지는 서버가 정합니다.")

        if not checklist:
            return cfg
        # 잣대를 바꾸면 id 패턴·필수 섹션이 통째로 달라진다. 설정을 다시 읽어
        # 그 잣대로 세운다(부분만 갈아끼우면 두 기준이 섞인다).
        fresh = _config_for(checklist)
        return fresh if choice == "on" else _rules_only(fresh)

    def _remember(kind: str, payload: dict,
                  *, original: tuple[str, bytes] | None = None) -> dict:
        """결과를 이력에 남기고, 화면이 쓸 id를 payload에 얹어 돌려준다.

        저장에 실패해도 검토 결과는 돌려준다 — 방금 한 검토를 통째로 버리는 것보다
        "이력에 못 남겼다"고 말하는 편이 낫다. original을 주면(단일 검토) 원본 문서도
        최근 몇 건만 함께 보관한다 — 이력에서 다시 열 때 뷰어로 보여주기 위함이다.
        원본 저장 실패는 조용히 넘긴다(결과는 이미 남았다).
        """
        try:
            entry = history.save(kind, payload)
        except (HistoryError, OSError) as exc:
            return {**payload, "history": {"saved": False, "error": str(exc)}}
        if original is not None:
            try:
                history.save_original(entry.id, original[0], original[1])
            except (HistoryError, OSError):
                pass
        return {**payload, "history": {"saved": True, "id": entry.id, "at": entry.at}}

    @app.post("/api/compare")
    async def compare(parent: UploadFile = File(...),
                      child: UploadFile = File(...),
                      llm: str = Form("on"),
                      checklist: str = Form("")) -> dict:
        cfg = _with_llm(llm, checklist)
        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            tmp_path = Path(tmp)
            # 같은 이름으로 올라와도 덮어쓰지 않도록 슬롯별 하위 디렉터리에 둔다.
            parent_path = await _save_upload(parent, tmp_path / "parent")
            child_path = await _save_upload(child, tmp_path / "child")
            try:
                # LLM이 붙으면 연결된 ID 수만큼 호출이 돌아 수 분 걸린다.
                # 이벤트 루프 위에서 돌리면 그동안 서버 전체가 멈춘다.
                result = await run_in_threadpool(
                    review_documents, parent_path, child_path, cfg)
            except (UnsupportedFormatError, NotImplementedError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"검토할 수 없습니다: {exc}") from exc
            # 임시 경로 대신 사용자가 올린 원래 이름을 보여준다.
            payload = to_ui_payload(result.rtm, result.findings,
                                    parent_path.name, child_path.name)
        # 업로드본은 위 with 블록을 벗어나며 지워진다. 남는 건 결과뿐이다.
        return _remember("compare", payload)

    @app.post("/api/review")
    async def review(file: UploadFile = File(...),
                     llm: str = Form("on"),
                     checklist: str = Form(""),
                     checklist_id: str = Form("")) -> StreamingResponse:
        """검토를 돌리면서 단계 진행을 SSE로 흘린다.

        업로드 검증 실패는 스트림을 열기 전에 HTTP 400/413으로 끝낸다. 스트림이
        열린 뒤에는 상태코드를 고칠 수 없어서, 그 뒤의 실패는 error 이벤트다.
        """
        cfg = _with_llm(llm, checklist)
        # checklist_id 가 있으면 등록된 체크리스트를 미리 찾아둔다 — 없는 id 는
        # 스트림을 열기 전에 404로 끝내야 한다(스트림 연 뒤엔 상태코드를 못 바꾼다).
        picked = None
        if checklist_id:
            try:
                picked = checklists.get(checklist_id)
            except ChecklistError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        # with 블록을 못 쓴다. 검토는 응답이 반환된 뒤에도 스레드에서 계속 돈다 —
        # 여기서 지우면 검토 도중에 원본이 사라진다. 스트림이 끝날 때 지운다.
        tmp = tempfile.TemporaryDirectory(prefix="docreview-")
        try:
            path = await _save_upload(file, Path(tmp.name))
        except BaseException:
            tmp.cleanup()
            raise

        events: queue.Queue = queue.Queue()

        def run() -> None:
            try:
                # 업로드 여부와 무관하게 한 엔진을 쓴다. 기준은 항상
                # 공통 ∪ 팀 ∪ 선택 업로드이고, 엔진이 항목별 판정과 지적의 연결을
                # 만든다. 업로드 기준은 엔진을 바꾸는 스위치가 아니라 셋째 기준층이다.
                from modules.report import to_ui_criteria_review_payload  # noqa: PLC0415

                from .criteria import criteria_for_single_review  # noqa: PLC0415
                from .orchestrator import review_document_by_criteria  # noqa: PLC0415

                items, notices = criteria_for_single_review(
                    seed_root, checklist, uploaded=picked)
                # 합쳐진 기준의 params가 실제 검사 설정(id 패턴·필수 절 등)을 정한다.
                run_cfg = replace(
                    cfg, review=apply_criteria_params(cfg.review, items))
                specs, spec_why = _presence_fields_for(checklist, path.name)
                supplemental, supplemental_why = _supplemental_for(
                    checklist, path.name)
                result = review_document_by_criteria(
                    path, items, run_cfg, on_progress=events.put,
                    field_specs=specs,
                    output_key=_output_key_for(checklist, path.name),
                    extra_checkers=supplemental)
                result.findings.extend(notices)
                structure_why = spec_why or supplemental_why
                if structure_why:
                    from modules.shared import Anchor, Finding, Severity  # noqa: PLC0415
                    result.findings.append(Finding(
                        checker="completeness", severity=Severity.INFO,
                        message=structure_why,
                        anchor=Anchor(page=None, section=None),
                        suggestion="파일명에 양식번호를 넣거나 폴더 검토를 쓰세요.",
                        unreviewed=True))
                payload = to_ui_criteria_review_payload(
                    result, path.name, as_checklist=picked is not None)

                if picked is None:
                    # 회신본이면(파일명이 이전 검토를 가리키면) 반영 확인을 곁들인다.
                    # 이전 지적과 새 검토를 규칙으로 대조해 닫힘/열림/신규 초안을 낸다.
                    from modules.agent_history import (  # noqa: PLC0415
                        carry_verdicts,
                        find_prior,
                        guess_original_name,
                        incomplete_checkers,
                        match_findings,
                        verdict_key,
                    )
                    prior = find_prior(
                        [e.as_dict() for e in history.list(limit=200)],
                        guess_original_name(path.name))
                    if prior:
                        before = (history.get(prior["id"]) or {}).get("payload", {})
                        prior_findings = before.get("findings", [])
                        # 이번에 제 몫을 다 못 한 검사기가 낸 지적은 "사라졌다"고
                        # 말할 수 없다 — 애초에 안 봤으니까(match_findings 의 blind).
                        lin = match_findings(
                            prior_findings, payload["findings"],
                            blind=incomplete_checkers(payload["findings"]))
                        payload["lineage_candidate"] = {
                            "id": prior["id"], "title": prior["title"], "at": prior["at"]}
                        payload["lineage"] = {
                            "parent_id": prior["id"],
                            # key 는 판정을 어느 지적에 붙였는지다. 순번은 그
                            # 검토 안에서만 뜻이 있어 다음 검토로 못 잇는다.
                            "items": [{"finding": it.finding, "status": it.status,
                                       "key": verdict_key(it.finding),
                                       # 화면이 이걸로 문서의 그 자리를 연다.
                                       "match_id": it.match_id}
                                      for it in lin.items],
                            "new_findings": lin.new_findings}
                        # 지난 검토에서 "해당없음"이라 한 지적은 다시 묻지 않는다.
                        # 검사기는 다음에도 똑같이 내므로, 안 이으면 검토자가 매번
                        # 같은 것을 다시 눌러야 한다.
                        carried = carry_verdicts(
                            before.get("lineageVerdicts") or {}, lin.items)
                        if carried:
                            payload["lineageVerdicts"] = carried
                            # 어느 것을 무슨 값으로 이어받았는지 밝힌다. 안 밝히면
                            # 검토자가 기계가 정한 판정으로 오해한다. **값까지** 담는
                            # 이유는 검토자가 덮어쓰면 더 이상 이어받은 것이 아니어서,
                            # 그때 태그를 떼려면 원래 값을 알아야 하기 때문이다.
                            payload["lineageCarried"] = dict(carried)
                try:
                    orig = (path.name, path.read_bytes())
                except OSError:
                    orig = None
                events.put({"event": "done",
                            "payload": _remember("review", payload, original=orig)})
            except (UnsupportedFormatError, NotImplementedError) as exc:
                events.put({"event": "error", "message": f"검토할 수 없습니다: {exc}"})
            except Exception as exc:  # noqa: BLE001 — 스레드에서 죽으면 화면이 영영 기다린다
                events.put({"event": "error", "message": f"검토 중 오류: {exc}"})
            finally:
                events.put(_DONE)

        def stream():
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                while True:
                    ev = events.get()
                    if ev is _DONE:
                        break
                    # orchestrator는 단계만 말한다. 봉투는 여기서 씌운다.
                    if "event" not in ev:
                        ev = {"event": "stage", **ev}
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            finally:
                # 수정 2026-08-06: 무기한 join 은 클라이언트가 끊겨도 검토가 끝날
                # 때까지(수 분) Starlette 스레드풀 토큰을 점유한다 — 새로고침 몇 번에
                # 풀(기본 40)이 고갈돼 전 엔드포인트가 멈춘다. 토큰은 즉시 반납하고
                # 임시 파일 뒷정리는 청소 스레드가 검토 종료를 기다렸다가 한다.
                worker.join(timeout=5)
                if worker.is_alive():
                    def _cleanup(w=worker, t=tmp):
                        w.join()
                        t.cleanup()
                    threading.Thread(target=_cleanup, daemon=True).start()
                else:
                    tmp.cleanup()

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _team_preset(choice: str) -> dict:
        """고른 팀 id → 기준 파일 내용. 목록에 없는 이름은 거절한다.

        브라우저가 보낸 문자열을 경로로 그대로 쓰면 서버의 아무 파일이나 읽게 된다
        (../../etc/passwd). 그래서 경로를 만들지 않고 열거한 목록에서 찾는다 —
        _criteria_for 와 같은 방어다.
        """
        import yaml  # noqa: PLC0415
        for f in sorted((seed_root / "teams").glob("*.y*ml")):
            if f.stem == choice:
                return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        raise HTTPException(status_code=404, detail=f"그런 팀 기준이 없습니다: {choice}")

    def _case_spec(team: str) -> dict:
        """폴더 검토용 팀 기준. 산출물 목록이 없으면 그 사실을 말한다.

        `outputs` 는 xlsx 에서 안 나온다 — 사람이 실제 문서를 열어보고 "어느
        산출물의 어느 칸을 어떻게 뽑나"를 채운 절이다(presets/README.md). 그래서
        팀 기준이 있어도 이 절은 없을 수 있고, 지금 7팀 중 하나만 갖고 있다.

        없는 채로 돌리면 모든 파일이 **조용히 "미분류"** 로 떨어진다. 검토자는
        자기가 파일을 잘못 올렸다고 생각하지, 기준이 없다고는 생각하지 않는다.
        """
        spec = _team_preset(team)
        if not spec.get("outputs"):
            raise HTTPException(
                status_code=400,
                detail=f"{spec.get('name', team)}은 폴더 검토 기준(산출물 목록)이 "
                       "아직 없습니다. 단일 검토나 비교 검토를 쓰거나, 팀 기준에 "
                       "산출물 목록을 먼저 채워야 합니다.")
        return spec

    @app.get("/api/teams/{team}/criteria")
    async def team_criteria(team: str) -> dict:
        """이 팀의 검토 기준. 판정에 쓰이는 그대로 내려준다.

        리포트가 "시험항목명 0/4" 라고만 말하면 검토자는 어느 4곳을 봐야 했는지,
        어느 라벨을 찾다 실패했는지 모른다 — 그 답이 여기 있다.

        읽기 전용이다. 고치기는 미리보기가 함께 있어야 열 수 있다(roadmap 참고) —
        라벨 한 글자만 틀려도 그 필드가 통째로 미검토가 된다.
        """
        from .case import to_ui_criteria_payload  # noqa: PLC0415
        spec = _team_preset(team)
        return to_ui_criteria_payload(spec)

    @app.post("/api/history/{entry_id}/confirm")
    async def confirm_case(entry_id: str, body: dict = Body(...)) -> dict:
        """산출물 세트 검토의 "직접 확인" 결과를 이력에 남긴다.

        문서 간 md §4 의 3항목(접수번호 · 접수일↔works · 의뢰기관명↔사업자등록증)은
        문서 대조로 판정할 수 없다. 사람이 외부 원천을 보고 확인한 뒤 눌러야 점검이
        끝난다 — 그 표시가 브라우저에만 있으면 나중에 기록을 열었을 때 "이 건은
        발급했나" 를 알 수 없다.

        payload 를 통째로 받지 않는다. 브라우저가 보낸 것이 검사 결과를 덮어쓰면
        안 된다 — 확인 표시는 사람이 정하지만 지적은 도구가 정한다.
        """
        ids = body.get("checked", [])
        parsed_inputs = body.get("inputs", {})
        if not isinstance(ids, list):
            raise HTTPException(status_code=400, detail="확인 목록이 배열이 아닙니다.")
        if not isinstance(parsed_inputs, dict):
            raise HTTPException(status_code=400, detail="직접 입력값이 객체가 아닙니다.")
        try:
            before = history.get(entry_id)
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if before.get("kind") != "case":
            raise HTTPException(status_code=400, detail="폴더 검토 이력이 아닙니다.")
        payload = dict(before.get("payload") or {})
        allowed = {str(m.get("id")) for m in payload.get("manual", [])}
        unknown = ({str(i) for i in ids} | {str(k) for k in parsed_inputs}) - allowed
        if unknown:
            raise HTTPException(status_code=400,
                                detail="알 수 없는 직접 확인 항목입니다: "
                                       f"{', '.join(sorted(unknown))}")
        if any(not isinstance(v, str) or len(v) > 1000 for v in parsed_inputs.values()):
            raise HTTPException(status_code=400,
                                detail="직접 입력값은 1000자 이하 문자열이어야 합니다.")
        from .manual_review import manual_review_patch  # noqa: PLC0415
        patch = manual_review_patch(payload, [str(i) for i in ids], parsed_inputs)
        patch["confirmedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            record = history.update_payload(entry_id, patch, refresh_summary=True)
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.get("payload", {})

    @app.post("/api/history/{entry_id}/lineage")
    async def confirm_lineage(entry_id: str, verdicts: str = Form(...)) -> dict:
        """재검토의 "반영 확인" 판정을 이력에 남긴다.

        지난번 지적마다 붙는 열림·닫힘은 **기계가 규칙으로 본 것**이다(인용문이
        이번 검토에도 나왔나). 검토자가 그것을 보고 실제 판정을 내리는데, 그 값이
        브라우저에만 있으면 새로고침 한 번에 사라진다 — 27건을 하나씩 확인해도
        남는 것이 없다. 화면은 고칠 수 있다고 보여주면서 실제로는 못 고쳤다.

        **기계 판정을 덮지 않고 따로 담는다**(`lineageVerdicts`). 덮으면 판정 근거가
        사라져 검토자가 자동 판정을 믿을지 판단할 수 없고, 다시 검토해 기계 판정이
        새로 계산될 때 사람이 한 일까지 같이 지워진다. confirm_case 가 `manualChecked`
        를 따로 두는 것과 같은 이유다 — 확인 표시는 사람이 정하지만 지적은 도구가
        정한다.

        열쇠는 **지적의 신원**이다(`lineage.items[].key` = agent_history.verdict_key).
        순번은 그 검토 안에서만 뜻이 있어 다음 검토의 3번째는 다른 지적이다 —
        `해당없음` 을 물려주려면 무엇에 대한 판정인지가 남아야 한다. 옛 기록은
        순번으로 저장돼 있고 화면이 그것도 읽는다(views.js 의 `saved[String(i)]`).
        """
        try:
            parsed = json.loads(verdicts) if verdicts else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400,
                                detail=f"판정을 읽지 못했습니다: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="판정은 객체여야 합니다.")

        from modules.agent_history import STATUSES  # noqa: PLC0415
        bad = sorted({v for v in parsed.values() if v not in STATUSES})
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"모르는 판정입니다: {', '.join(map(str, bad))}")
        try:
            saved = {str(k): str(v) for k, v in parsed.items()}
            # 검토자가 덮어쓴 것은 더 이상 "지난 판정"이 아니다. 안 떼면 이번에
            # 자기가 바꿔놓고도 지난번 것을 물려받은 줄 안다 — 실측으로 그렇게
            # 남아 있었다(이어받은 값 `해당없음`, 저장된 값 `미반영`, 태그는 그대로).
            before = (history.get(entry_id) or {}).get("payload", {})
            carried = {k: v for k, v in (before.get("lineageCarried") or {}).items()
                       if saved.get(k) == v}
            record = history.update_payload(entry_id, {
                "lineageVerdicts": saved,
                "lineageCarried": carried,
                "lineageConfirmedAt":
                    datetime.now(UTC).isoformat(timespec="seconds"),
            })
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.get("payload", {})

    @app.post("/api/classify-case")
    async def classify_case(names: str = Form(...), team: str = Form(...)) -> dict:
        """파일명만으로 산출물을 판별한다. 업로드 전에 확인받기 위한 것이다.

        업로드는 수십 MB 인데 판별 근거는 파일명의 양식번호뿐이다 — 무엇이 무엇인지
        확인받는 데 파일을 다 올릴 이유가 없다.

        확인을 받는 이유: 양식번호가 없는 파일을 추측으로 배정하면 엉뚱한 필드맵으로
        검사해 거짓 지적이 난다. 사람이 지정하거나 제외해야 한다.
        """
        from .case import classify_names  # noqa: PLC0415
        spec = _case_spec(team)
        try:
            parsed = json.loads(names)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400,
                                detail=f"파일 이름 목록을 읽지 못했습니다: {exc}") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="파일 이름 목록이 배열이 아닙니다.")
        return classify_names([str(n) for n in parsed], spec,
                              team_name=spec.get("name", team))

    @app.post("/api/review-case")
    async def review_case_endpoint(files: list[UploadFile] = File(...),
                                   team: str = Form(...)) -> StreamingResponse:
        """산출물 세트를 한 번에 검토하고 진행을 SSE 로 흘린다.

        업로드·팀 검증 실패는 스트림을 열기 전에 끝낸다 — 스트림이 열린 뒤에는
        상태코드를 고칠 수 없다(/api/review 와 같은 사정).
        """
        spec = _case_spec(team)
        if not files:
            raise HTTPException(status_code=400, detail="파일이 없습니다.")

        # 검토는 응답이 반환된 뒤에도 스레드에서 돈다. 여기서 지우면 검토 도중에
        # 원본이 사라진다 — 스트림이 끝날 때 지운다.
        tmp = tempfile.TemporaryDirectory(prefix="docreview-case-")
        try:
            saved = [await _save_upload(f, Path(tmp.name)) for f in files]
        except BaseException:
            tmp.cleanup()
            raise

        events: queue.Queue = queue.Queue()

        def run() -> None:
            try:
                from .case import review_case, to_ui_case_payload  # noqa: PLC0415
                result = review_case(saved, spec, on_progress=events.put)
                payload = to_ui_case_payload(result, spec.get("name", team))
                events.put({"event": "done",
                            "payload": _remember("case", payload)})
            except Exception as exc:  # noqa: BLE001 — 스레드에서 죽으면 화면이 영영 기다린다
                events.put({"event": "error", "message": f"검토 중 오류: {exc}"})
            finally:
                events.put(_DONE)

        def stream():
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                while True:
                    ev = events.get()
                    if ev is _DONE:
                        break
                    if "event" not in ev:
                        ev = {"event": "stage", **ev}
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            finally:
                # 수정 2026-08-06: 무기한 join 은 클라이언트가 끊겨도 검토가 끝날
                # 때까지(수 분) Starlette 스레드풀 토큰을 점유한다 — 새로고침 몇 번에
                # 풀(기본 40)이 고갈돼 전 엔드포인트가 멈춘다. 토큰은 즉시 반납하고
                # 임시 파일 뒷정리는 청소 스레드가 검토 종료를 기다렸다가 한다.
                worker.join(timeout=5)
                if worker.is_alive():
                    def _cleanup(w=worker, t=tmp):
                        w.join()
                        t.cleanup()
                    threading.Thread(target=_cleanup, daemon=True).start()
                else:
                    tmp.cleanup()

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/locate")
    async def locate_findings(file: UploadFile = File(...),
                              findings: str = Form(...),
                              images: str = Form("[]")) -> dict:
        """지적이 PDF의 어디에 있는지 좌표로 돌려준다(JSON).

        화면 뷰어가 지적 위치로 스크롤하고 형광펜을 얹는 데 쓴다. /api/annotate와
        입력이 같고 출력만 JSON이다 — 굽지 않으므로 훨씬 싸고, 화면은 원본을
        그대로 그린다(요약 페이지 오프셋 보정이 사라진다).

        원본을 서버에 보관하지 않는다. 브라우저가 들고 있는 파일을 그때 올린다.

        images(번호·원본 크기)를 함께 주면 **그림 설명에서 나온 지적**도 짚는다.
        그 설명은 파싱 본문에만 있고 PDF 텍스트 레이어에는 없어서 인용문으로는
        영원히 못 찾는다. 화면은 검토 payload 의 images 를 그대로 되돌려보낸다.
        """
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="PDF만 좌표를 찾을 수 있습니다.")
        try:
            items = json.loads(findings)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400,
                                detail=f"findings를 읽지 못했습니다: {exc}") from exc
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="findings는 배열이어야 합니다.")

        try:
            image_meta = json.loads(images)
        except json.JSONDecodeError:
            image_meta = []          # 그림 좌표만 못 짚는다. 검토는 그대로 돌아간다.
        if not isinstance(image_meta, list):
            image_meta = []

        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            path = await _save_upload(file, Path(tmp))
            data = path.read_bytes()

        try:
            return locate(data, items, images=image_meta)
        except Exception as exc:  # noqa: BLE001 — 깨진 PDF가 서버를 죽이지 않게
            raise HTTPException(
                status_code=400, detail=f"좌표를 찾지 못했습니다: {exc}") from exc

    @app.post("/api/annotate")
    async def annotate_pdf(file: UploadFile = File(...),
                           findings: str = Form(...)) -> Response:
        """원본 PDF에 지적을 형광펜으로 표시해 돌려준다.

        원본을 서버에 보관하지 않는다. 검토 직후라면 브라우저가 그 파일을 아직
        들고 있으므로 다시 올리면 된다 — 보관 정책을 뒤집지 않고도 같은 일을 한다.

        표시하지 못한 지적은 헤더로 알린다. 응답 본문은 PDF라서 여기 말고는
        말할 자리가 없고, 조용히 넘기면 "형광펜이 없다 = 지적이 없다"가 된다.
        """
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail="PDF만 표시할 수 있습니다.")
        try:
            items = json.loads(findings)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400,
                                detail=f"findings를 읽지 못했습니다: {exc}") from exc
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="findings는 배열이어야 합니다.")

        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            path = await _save_upload(file, Path(tmp))
            data = path.read_bytes()

        try:
            marked = annotate(data, items, doc_name=file.filename or "",
                              brand="DocSuree · 문서 일관성 검토 Agent")
        except Exception as exc:  # noqa: BLE001 — 깨진 PDF가 서버를 죽이지 않게
            raise HTTPException(
                status_code=400, detail=f"PDF에 표시하지 못했습니다: {exc}") from exc

        stem = Path(file.filename).stem
        return Response(
            content=marked.pdf, media_type="application/pdf",
            headers={
                # 헤더는 ASCII만 안전하다. 개수만 보내고, 무엇이 빠졌는지는
                # 화면이 이미 들고 있는 findings에서 id로 찾는다.
                "X-Marked-Count": str(marked.marked),
                "X-Unmarked-Count": str(len(marked.unmarked)),
                "X-Unmarked-Ids": ",".join(
                    str(u.get("id") or "") for u in marked.unmarked),
                # 요약 페이지는 한글 폰트가 있어야 넣는다. 못 넣었으면 화면이
                # 그 사실을 말한다 — 조용히 빠지면 그런 페이지가 있다는 것도 모른다.
                "X-Summary": "1" if marked.summary else "0",
                # 표시본 앞에 삽입된 요약 페이지 수. 화면이 지적 page로 점프할 때
                # 이만큼 밀어 보정한다(요약을 못 넣었으면 0).
                "X-Summary-Pages": str(marked.summary_pages),
                # 지적 id → 지면에 찍힌 번호. 화면 카드가 같은 번호를 달아야
                # "3번 지적"이 표시본과 화면에서 같은 것을 가리킨다. id도 번호도
                # ASCII라 헤더에 안전하다(한글은 여기 실을 수 없다).
                "X-Numbers": json.dumps(marked.numbers, ensure_ascii=True),
                "Access-Control-Expose-Headers":
                    "X-Marked-Count, X-Unmarked-Count, X-Unmarked-Ids, "
                    "X-Summary, X-Summary-Pages, X-Numbers",
                "Content-Disposition": _disposition(f"{stem}.marked.pdf"),
            })

    @app.post("/api/suggest")
    def suggest(message: str = Form(...), quote: str = Form(""),
                criterion: str = Form(""), llm: str = Form("on"),
                others: str = Form("")) -> dict:
        """지적 하나에 대한 수정안. 검토자가 그 지적을 눌렀을 때만 부른다.

        검토 전체에 걸어두지 않는다 — 지적 대부분은 읽고 넘기는 것이라,
        매번 문장을 새로 짓게 하면 검토가 느려지고 비싸진다.

        문서 본문이 아니라 그 지적의 근거 인용만 보낸다. 고쳐 쓸 대상이
        그 문장이고, 문서 전체를 매번 모델에 넣을 이유가 없다.

        criterion 은 그 지적을 낸 기준의 본문이다. 화면이 역맵에서 꺼내 보낸다 —
        기준을 모르면 어느 방향으로 고칠지 알 수 없다(SI 단위계는 "5kg" 가 아니라
        "5 kg" 가 맞는데, "띄어쓰기 오류"만 주면 반대로 붙여놓을 수 있다).
        기준 없는 일반 검토면 빈 문자열이고, 그때는 기준 절을 만들지 않는다.

        못 만들면 ok=false로 답한다. 여기서 그럴듯한 문장을 지어내면
        검토자가 원문을 안 보고 갈아끼운다.
        """
        cfg = _with_llm(llm)
        # others 는 같은 지적이 함께 든 다른 인용(줄바꿈으로 구분). 모순 지적은
        # 두 곳이 어긋나 나오는데, 한 곳만 주면 모델이 다른 쪽을 정답으로 삼아
        # 이쪽을 거기 맞춰 고쳐 쓴다 — 어느 쪽이 사실인지 아무도 안 봤는데도.
        out = suggest_revision(build_llm(cfg), message, quote, criterion,
                               others=others.splitlines())
        return {"ok": out.ok, "original": out.original,
                "revised": out.revised, "reason": out.reason}

    @app.post("/api/render-pdf")
    async def render_pdf(file: UploadFile = File(...)) -> Response:
        """비-PDF 업로드를 PDF로 변환해 돌려준다(뷰어가 PDF만 다루게).

        docx는 진짜 원본, hwpx는 재현. 원본을 서버에 남기지 않는다 — 검토 직후면
        브라우저가 파일을 아직 들고 있어 다시 올리면 된다(annotate와 같은 방식).
        """
        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            path = await _save_upload(file, Path(tmp))
            try:
                pdf = to_pdf(path)
            except (UnsupportedFormatError, NotImplementedError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"이 형식은 변환할 수 없습니다: {exc}") from exc
            except ConvertUnavailable as exc:
                raise HTTPException(status_code=501, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — 변환 실패가 서버를 죽이지 않게
                raise HTTPException(
                    status_code=400, detail=f"변환하지 못했습니다: {exc}") from exc
        return Response(content=pdf, media_type="application/pdf")

    @app.post("/api/detect")
    async def detect(file: UploadFile = File(...)) -> dict:
        """업로드 문서를 체크리스트마다 재서 요건 ID가 몇 개 걸리는지 돌려준다.

        **잘못된 체크리스트의 실패는 에러가 아니라 조용한 0건이다.** 패턴이 안
        맞으면 ID를 한 개도 못 찾고, 화면에는 "지적 없음"이 뜬다 — 검토를 통과한
        것처럼 보인다. 실측에서 두 번 겪었다(SKN56 문서에 SHN34 패턴을 쓴 경우,
        실문서에 데모 체크리스트를 쓴 경우). 그래서 고르기 **전에** 재서 알려준다.

        LLM을 부르지 않는다. 정규식 매칭이라 빠르고 결정적이다.

        아무것도 안 맞으면 best 는 None 이다 — 지어낸 추천은 이 기능이 막으려던
        바로 그 사고를 다시 만든다.
        """
        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            path = await _save_upload(file, Path(tmp))
            try:
                doc = normalize(load_document(path))
            except (UnsupportedFormatError, NotImplementedError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"읽을 수 없는 형식입니다: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 — 깨진 파일이 서버를 죽이지 않게
                raise HTTPException(
                    status_code=400, detail=f"문서를 읽지 못했습니다: {exc}") from exc

        detected = []
        for meta in _teams():
            review = _config_for(meta["id"]).review
            detected.append({
                **meta,
                # 화면에 정규식을 띄울 수는 없다. 체크리스트가 적어둔 예시를 쓴다.
                "id_example": review.id_example,
                # 패턴이 아예 없는 체크리스트와 "패턴은 있는데 0개"는 다른 상태다.
                "has_pattern": bool(review.id_pattern),
                "matches": len(extract_id_anchors(doc, review.id_pattern)),
            })
        detected.sort(key=lambda d: -d["matches"])
        best = detected[0]["id"] if detected and detected[0]["matches"] else None
        return {"detected": detected, "best": best}

    @app.get("/api/history")
    def history_list(limit: int = 20) -> dict:
        limit = max(1, min(limit, 100))
        return {"entries": [e.as_dict() for e in history.list(limit)]}

    @app.get("/api/history/{entry_id}")
    def history_get(entry_id: str) -> dict:
        try:
            record = history.get(entry_id)
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if record.get("kind") == "checklist":
            # 체크리스트 실행 결과는 payload 로 감싸지 않고 최상위로 펼쳐 준다 —
            # compare/review 화면이 이미 "payload" 한 겹을 벗겨 쓰는 관례가 있어
            # 그대로 따르면 화면마다 다시 감싸는 코드를 새로 짜야 한다.
            return {**record, **record["payload"]}
        return record

    @app.get("/api/history/{entry_id}/original")
    def history_original(entry_id: str) -> Response:
        """이력에 함께 보관한 원본 문서를 돌려준다(뷰어용). 없으면 404 → 텍스트 폴백."""
        try:
            got = history.original(entry_id)
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if got is None:
            raise HTTPException(
                status_code=404,
                detail="보관된 원본이 없습니다(개수 제한으로 밀렸거나 미저장).")
        fname, data = got
        ctype = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".hwpx": "application/octet-stream",
        }.get(Path(fname).suffix.lower(), "application/octet-stream")
        return Response(content=data, media_type=ctype)

    @app.delete("/api/history/{entry_id}")
    def history_delete(entry_id: str) -> dict:
        try:
            history.delete(entry_id)
        except HistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": entry_id}

    async def _tables_of(file: UploadFile) -> list:
        """업로드에서 표를 뽑는다. 형식 오류는 400 으로 돌린다."""
        with tempfile.TemporaryDirectory(prefix="docreview-") as tmp:
            path = await _save_upload(file, Path(tmp))
            data = path.read_bytes()
        try:
            return extract_tables(file.filename or "", data)
        except UnsupportedChecklistFormat as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 깨진 파일이 서버를 죽이지 않게
            raise HTTPException(
                status_code=400, detail=f"체크리스트를 읽지 못했습니다: {exc}") from exc

    @app.post("/api/checklists/preview")
    async def checklist_preview(file: UploadFile = File(...)) -> dict:
        """등록 전에 무엇으로 읽었는지 보여준다.

        열 추측이 틀렸는데 조용히 등록되면 엉뚱한 항목으로 검토하게 된다.
        그래서 반드시 사람이 한 번 본다.
        """
        out = []
        for i, table in enumerate(await _tables_of(file)):
            head = find_header(table.rows)
            cols = guess_columns(table.rows[head]) if head is not None else {
                r: None for r in ("no", "text", "group", "note")}
            items = build_items(table.rows, head, cols) if head is not None else []
            out.append({
                "index": i,
                "label": table.label,
                "header": list(table.rows[head]) if head is not None else [],
                "header_row": head,
                "columns": cols,
                "item_count": len(items),
                # 미리보기 몇 줄. 전부 보내면 IS22 는 응답이 수 MB 가 된다.
                "sample": [{"no": it.no, "text": it.text, "group": it.group}
                           for it in items[:5]],
            })
        return {"tables": out}

    @app.post("/api/checklists")
    async def checklist_register(file: UploadFile = File(...),
                                 name: str = Form(""),
                                 table_index: int = Form(0),
                                 columns: str = Form("")) -> dict:
        tables = await _tables_of(file)
        if not 0 <= table_index < len(tables):
            raise HTTPException(status_code=400, detail="그런 표가 없습니다.")
        table = tables[table_index]
        try:
            picked = json.loads(columns) if columns else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"columns 를 읽지 못했습니다: {exc}") from exc
        if not isinstance(picked, dict) or picked.get("text") is None:
            raise HTTPException(
                status_code=400,
                detail="'항목 내용' 열을 골라야 합니다. 내용 없이는 체크할 것이 없습니다.")

        head = find_header(table.rows)
        # 헤더를 못 찾았어도 사람이 열을 골랐으면 첫 행을 헤더로 보고 진행한다.
        items = build_items(table.rows, head if head is not None else 0, picked)
        try:
            saved = checklists.save(name, file.filename or "", picked, items)
        except ChecklistError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": saved.id, "name": saved.name, "item_count": len(saved.items)}

    @app.get("/api/criteria")
    def criteria_layers(team: str = "") -> dict:
        """검토 기준 3층을 층째로. 화면이 "무엇으로 재는지"를 보여주는 자리다.

        `/api/teams/{team}/criteria` 와 다르다. 그쪽은 폴더 검토가 쓰는 **구조
        절**(어느 산출물의 어느 칸을 어떻게 뽑나)을 내고 items 는 개수만 낸다.
        여기서는 items 전문이 목적이다 — 검토자가 "이 기준이 실제로 검사되나"를
        알아야 한다.

        **howChecked 가 이 화면의 값어치다.** 기준은 수십 건인데 검사기가 받는
        것은 그중 일부고, 지금 그 차이가 아무 데도 안 보인다. 팀에 "이건 됩니다 /
        이건 사람이 봐야 합니다"를 이 화면 하나로 말할 수 있어야 한다.
        """
        from modules.agent_checklist import check_name, mode_for  # noqa: PLC0415
        if team and team not in {t["id"] for t in _teams()}:
            raise HTTPException(
                status_code=400, detail=f"그런 팀 기준이 없습니다: {team}")

        def item(c) -> dict:
            mode = mode_for(c)
            check = check_name(c)
            # "규칙"이라고 적혀 있어도 그 기준을 볼 검사기가 없으면 자동이 아니다.
            # 예전에는 mode 만 보고 "규칙 · 자동"이라 적어서, 검사기가 둘뿐인데
            # 규칙 기준 서른 개가 전부 자동으로 검사되는 것처럼 보였다.
            automatic = mode != "사람" and (mode != "규칙" or bool(check))
            return {
                "no": c.no, "text": c.text, "group": c.group, "note": c.note,
                "agent": c.agent, "source": c.source,
                "mode": mode,
                # 어느 검사가 보는지. 비면 아직 그 검사가 없다는 뜻이다.
                "check": check,
                # 어휘를 화면 말로. "LLM-조각"·"LLM-문서"는 한 번에 얼마를 묻는지의
                # 차이라 검토자에게는 같은 뜻이다(둘 다 자동이고 근거를 대야 한다).
                "howChecked": ("규칙 · 자동" if mode == "규칙" and check
                               else "LLM · 자동" if automatic
                               else "사람이 확인"),
            }

        layers = []
        for p in load_presets(seed_root):
            if p.scope == "공통":
                layers.append({"scope": "공통", "id": p.id,
                               "name": p.name or "공통 기준", "editable": False,
                               "items": [item(c) for c in p.items]})
            elif p.scope == "팀별" and team and p.id == team:
                layers.append({"scope": "팀별", "id": p.id, "name": p.name or p.id,
                               "editable": False,
                               "items": [item(c) for c in p.items]})
        for c in checklists.list():
            # list() 는 깨진 파일 하나가 목록을 죽이지 않게 건너뛰지만 get() 은
            # 던진다. 여기서 안 받으면 못 읽는 업로드 하나가 공통·팀 층까지 통째로
            # 500 으로 날린다 — 이 화면은 진입할 때마다 부른다.
            try:
                items = [item(x) for x in checklists.get(c.id).items]
                error = ""
            except ChecklistError as exc:
                items, error = [], str(exc)
            layers.append({"scope": "업로드", "id": c.id, "name": c.name,
                           "editable": True, "error": error, "items": items})
        return {"team": team, "layers": layers}

    @app.get("/api/checklists")
    def checklist_list() -> dict:
        return {"checklists": [
            {"id": c.id, "name": c.name, "source_filename": c.source_filename,
             "registered_at": c.registered_at, "item_count": c.item_count}
            for c in checklists.list()]}

    @app.get("/api/checklists/{checklist_id}")
    def checklist_get(checklist_id: str) -> dict:
        try:
            c = checklists.get(checklist_id)
        except ChecklistError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"id": c.id, "name": c.name, "registered_at": c.registered_at,
                "columns": c.columns,
                "items": [{"no": i.no, "text": i.text, "group": i.group,
                           "note": i.note} for i in c.items]}

    @app.delete("/api/checklists/{checklist_id}")
    def checklist_delete(checklist_id: str) -> dict:
        try:
            checklists.delete(checklist_id)
        except ChecklistError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": checklist_id}

    @app.post("/api/checklists/{checklist_id}/run")
    def checklist_run(checklist_id: str, document_name: str = Form(""),
                      results: str = Form("")) -> dict:
        """채운 결과를 기록에 남긴다.

        기존 HistoryStore 를 kind="checklist" 로 쓴다 — 기록 화면·목록·삭제가
        그대로 재사용된다. 미판정 항목도 세어서 함께 남긴다: 나중에 기록을
        열었을 때 "몇 개를 안 봤는지"가 사라지면 다 본 것처럼 읽힌다.
        """
        try:
            c = checklists.get(checklist_id)
        except ChecklistError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            parsed = json.loads(results) if results else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"results 를 읽지 못했습니다: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="results 는 객체여야 합니다.")

        # 결과는 no 가 아니라 위치 인덱스(문자열)로 찾는다 — no 는 등록 시 열을
        # 고르지 않으면 전부 "" 이고, 구간별 1,2,3 재시작이면 겹친다. no 를
        # 키로 쓰면 같은 no 를 가진 다른 항목까지 함께 판정된 것처럼 보인다.
        unjudged = sum(1 for i, it in enumerate(c.items)
                       if not (parsed.get(str(i)) or {}).get("verdict"))
        payload = {
            "checklist_id": c.id, "checklist_name": c.name,
            "document_name": document_name,
            "total": len(c.items), "unjudged": unjudged,
            "results": [{"no": it.no, "text": it.text, "group": it.group,
                         "verdict": (parsed.get(str(i)) or {}).get("verdict"),
                         "reason": (parsed.get(str(i)) or {}).get("reason", "")}
                        for i, it in enumerate(c.items)],
        }
        return _remember("checklist", payload)

    @app.post("/api/checklists/{checklist_id}/csv")
    def checklist_csv(checklist_id: str, results: str = Form("")) -> Response:
        try:
            c = checklists.get(checklist_id)
        except ChecklistError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            parsed = json.loads(results) if results else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"results 를 읽지 못했습니다: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="results 는 객체여야 합니다.")
        # BOM 을 붙인다 — 엑셀이 UTF-8 CSV 를 BOM 없이는 깨서 연다(윈도우 한글 mojibake 방지).
        # BOM은 응답 바이트에 "﻿"로 실려 있다. media_type의 charset은 표준 토큰이어야
        # 하므로(IANA/WHATWG) utf-8-sig 코덱 별칭을 쓰면 안 되고, 표준 charset=utf-8을 쓴다.
        body = "﻿" + to_csv(c, parsed)
        # c.name 은 업로드된 파일에서 온 이름이라 신뢰할 수 없다. _disposition은
        # 비-ASCII만 걷어내고 큰따옴표는 그대로 두므로, 이름에 "가 있으면
        # filename="..." 안에서 따옴표가 일찍 닫혀 헤더가 깨진다(제어 문자도 같은
        # 이유로 함께 없앤다). _disposition 자체를 바꾸면 마킹된 PDF 호출부의
        # 동작까지 바뀌므로 여기서만 이름을 다듬는다.
        safe_name = "".join(ch for ch in c.name if ch != '"' and ch.isprintable())
        return Response(content=body.encode("utf-8"),
                        media_type="text/csv",
                        headers={"Content-Disposition":
                                 _disposition(f"{safe_name}.checklist.csv")})

    @app.get("/api/health")
    def health(checklist: str = "") -> dict:
        # 화면이 "지금 무슨 잣대로 재는 중인지"를 말할 수 있어야 한다. 이게 없으면
        # 데모용 체크리스트로 실제 문서를 검토하고도 사용자는 그저 "0건"만 본다.
        # 실제로 그렇게 한나절을 날렸다.
        # 기준을 고를 수 있게 된 뒤로, 기본값의 잣대를 그대로 답하면 안 된다.
        # 화면은 이 값으로 "지금 무슨 잣대로 재는지"를 말하는데, 고른 것과 다른
        # 잣대를 보여주면 이 패널이 막으려던 바로 그 사고가 된다.
        shown = _config_for(checklist) if checklist else config
        review = shown.review
        return {
            "status": "ok",
            "settings": str(settings),
            # 팀 기준 계통으로 잰 경우 읽은 파일이 없다 — 고른 id 를 그대로 답한다.
            "checklist": Path(shown.checklist_path).name or checklist,
            # 고를 수 있는 목록과 지금 서버 기본값. 화면이 임의 목록을 지어내지
            # 않도록 여기서 내려준다 — 예전엔 화면에 실제로 없는 이름(PRD 등)이
            # 박혀 있었고, 골라도 서버에 전달되지 않았다.
            "checklists": _teams(),
            "checklist_id": Path(shown.checklist_path).stem or checklist,
            "doc_type": review.doc_type,
            "id_pattern": review.id_pattern,
            "id_example": review.id_example,
            "scope_pattern": review.scope_pattern,
            "scope_label": review.scope_label,
            "required_sections": list(review.required_sections),
            "placeholder_markers": list(review.placeholder_markers),
            "llm_provider": config.llm_provider,
            "llm_model": config.llm_model,
            # 화면에 뜨는 이름. 서버가 받는 별칭("qwen")은 사람에게 뜻이 없어
            # 설정의 model_label 을 쓴다. 없으면 별칭을 그대로 보여준다 —
            # 지어내지 않는다.
            "llm_label": config.llm_label or config.llm_model,
            # 그림 해석용 비전 모델은 별도 엔드포인트다. 검토자가 "그림을 읽었는지"를
            # 알아야 결과를 옳게 읽는다 — 안 읽었으면 그림 안의 표·구성도는 검토되지
            # 않은 것이다. 주소는 내려보내지 않는다(사내 주소를 화면에 뿌릴 이유가 없다).
            "vlm_enabled": bool(config.vlm_base_url),
            "vlm_model": config.vlm_model if config.vlm_base_url else "",
        }

    static_dir = Path(frontend_dir) if frontend_dir else _REPO_ROOT / "web"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app

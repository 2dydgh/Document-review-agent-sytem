"""설정 로더: settings.toml + 체크리스트 YAML → Config.

스키마(Config·ReviewConfig)는 modules.shared에 있다.
여기(app)는 배포 설정 파일을 읽어 그 스키마로 채우는 조립 책임만 진다.

LLM 서버 주소는 환경변수가 설정 파일을 **덮는다**:

    LLM_QWEN_URL   문서 검사용 (없으면 [llm].base_url)
    LLM_OCR_URL    그림 해석용 VLM (없으면 [llm].vlm_base_url, 비면 그림 해석 안 함)
    LLM_API_KEY    서버가 인증을 켰을 때

서버 주소는 배포마다 다르고, 배포판 저장소에 사내 주소를 박을 수 없다 — 코드도
설정 파일도 아니라 배포 환경이 정해야 한다. 팀 LLM 서버 안내 문서도 같은 이름을
쓰므로, 거기 적힌 두 줄을 그대로 export 하면 붙는다.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import replace
from pathlib import Path

import yaml

from modules.shared import Config, ReviewConfig

#: 기준이 정할 수 있는 검사 매개변수. 여기 없는 키는 무시한다 — 오타 하나가
#: 조용히 ReviewConfig 를 덮으면 어느 기준으로 쟀는지 알 수 없다.
_CRITERION_PARAMS = ("required_sections", "id_pattern", "id_example",
                     "id_rollup_separator", "scope_pattern", "scope_label",
                     "placeholder_markers")


def apply_criteria_params(review: ReviewConfig, criteria) -> ReviewConfig:
    """검토 기준이 검사 매개변수를 정한다.

    기준 항목의 `params` 절에 적힌 값만 쓴다. 3층(공통·팀별·업로드) 어디에
    적혀 있든 `compose_review_preset` 이 합쳐서 넘겨준다.

    **적혀 있지 않으면 그대로 둔다 — 코드가 지어내지 않는다.** 예전에는
    `presets/checklists/*.yaml` 이 요건 ID 정규식을 갖고 있었는데, 그 값은
    개발 중에 실제 문서를 보고 거꾸로 뽑은 것이었다(문서에서 뽑은 잣대로 그
    문서를 재면 틀릴 수가 없다). 어느 팀 기준도 ID 형식을 적지 않는다 — 전부
    "요구사항 ID 목록을 추출한다"까지만 말한다. 그래서 기본값은 비어 있고,
    추적성은 기준이 형식을 적어줄 때만 돈다.

    같은 키가 여러 기준에 있으면 **먼저 온 것**을 쓴다 — `resolve_criteria` 가
    공통 → 팀 → 업로드 순으로 합치고 중복도 같은 규칙으로 거른다.
    """
    picked: dict = {}
    for c in criteria:
        for key, value in (getattr(c, "params", None) or {}).items():
            if key in _CRITERION_PARAMS and key not in picked and value:
                picked[key] = value
    if not picked:
        return review
    for key in ("required_sections", "placeholder_markers"):
        if key in picked:
            picked[key] = list(picked[key])
    return replace(review, **picked)


def _env(name: str) -> str:
    """환경변수를 읽되 공백만 든 값은 없는 것으로 본다.

    `LLM_QWEN_URL=` 처럼 비워 두고 export 하는 일이 흔하다. 빈 문자열을 주소로
    받으면 설정 파일의 값을 덮어 아무 데도 못 붙는다.
    """
    return os.environ.get(name, "").strip()


def load_config(settings_path: str | Path,
                checklist_path: str | Path | None = None) -> Config:
    """설정을 읽는다. checklist_path 를 주면 [review].checklist 대신 그것을 쓴다.

    검토자가 화면에서 기준을 고를 수 있어야 해서 열어둔 구멍이다. 다만 경로를
    그대로 받는 자리이므로, **호출하는 쪽이 먼저 허용 목록과 대조해야 한다** —
    브라우저가 보낸 문자열을 여기 그대로 흘리면 서버의 아무 파일이나 열게 된다.
    """
    settings_path = Path(settings_path)
    with settings_path.open("rb") as fh:
        data = tomllib.load(fh)

    llm = data.get("llm", {})
    llm_provider = llm.get("provider", "echo")
    llm_model = llm.get("model", "")
    llm_base_url = _env("LLM_QWEN_URL") or llm.get("base_url", "http://127.0.0.1:11434/v1")
    llm_timeout = float(llm.get("timeout", 120.0))
    llm_api_key = _env("LLM_API_KEY") or llm.get("api_key", "")
    llm_thinking = bool(llm.get("thinking", False))
    llm_max_tokens = int(llm.get("max_tokens", 1024))
    # 1 이하는 순차로 본다 — 0 이나 음수가 들어와 아무것도 안 돌지 않게.
    llm_concurrency = max(1, int(llm.get("concurrency", 8)))
    llm_rescue_max = max(0, int(llm.get("rescue_max", 10)))
    # 표시용 이름. 환경변수가 이긴다 — 주소를 환경변수로 받으면 설정 파일의
    # 라벨도 다른 서버 것일 수 있다(모델명과 같은 사정).
    llm_label = _env("LLM_QWEN_LABEL") or llm.get("model_label", "")
    vlm_base_url = _env("LLM_OCR_URL") or llm.get("vlm_base_url", "")
    vlm_model = llm.get("vlm_model", "ocr")

    # 환경변수로 주소를 받으면 **설정 파일의 모델명은 다른 서버 것**이다. 그대로
    # 쓰면 그 이름을 서비스하지 않는 서버에 물어 404 가 난다 — 실제로 그랬다
    # (toml 의 "Qwen/Qwen3.6-27B" 를 별칭 "qwen" 만 받는 서버에 보냈다).
    # 서버가 --served-model-name 으로 별칭을 고정하므로 주소만 주면 붙는 것이 맞다.
    # 별칭이 다르면 LLM_QWEN_MODEL 로 준다.
    if _env("LLM_QWEN_URL"):
        llm_provider = "local" if llm_provider == "echo" else llm_provider
        llm_model = _env("LLM_QWEN_MODEL") or "qwen"
    chunk_max_chars = int(data.get("chunking", {}).get("max_chars", 4000))
    checklist_rel = data.get("review", {}).get("checklist", "")

    # 체크리스트는 없어도 된다. 예전엔 필수라 `[review] checklist` 를 비우면
    # settings 디렉터리를 파일로 열어 IsADirectoryError 로 서버가 뜨지도 않았다.
    # 그래서 "아무거나 하나"를 가리켜야 했고, 그 아무거나가 한 번 올라온 문서에서
    # 뽑은 잣대(shn34-esf-ccs.yaml)였다 — 다른 문서에는 한 개도 안 걸리는데
    # 그 실패가 에러가 아니라 조용한 "0건"으로 보인다.
    # 기준은 팀 프리셋과 화면 선택(POST /api/detect)이 주입한다. 없으면 없는 대로
    # ReviewConfig 기본값으로 돈다.
    if checklist_path or checklist_rel:
        checklist_path = (Path(checklist_path) if checklist_path
                          else settings_path.parent / checklist_rel).resolve()
        with checklist_path.open("r", encoding="utf-8") as fh:
            cl = yaml.safe_load(fh) or {}
    else:
        checklist_path, cl = None, {}

    review = ReviewConfig(
        doc_type=cl.get("doc_type", "generic"),
        required_sections=list(cl.get("required_sections", [])),
        id_pattern=cl.get("id_pattern", ""),
        id_example=cl.get("id_example", ""),
        scope_label=cl.get("scope_label", ""),
        scope_pattern=cl.get("scope_pattern", ""),
        id_rollup_separator=str(cl.get("id_rollup_separator", "") or ""),
        # 키가 아예 없으면 기본(TBD). 빈 목록을 명시하면 검사를 끈다.
        placeholder_markers=list(cl.get("placeholder_markers", ["TBD"])),
    )
    return Config(
        llm_provider=llm_provider,
        chunk_max_chars=chunk_max_chars,
        review=review,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_timeout=llm_timeout,
        llm_api_key=llm_api_key,
        llm_thinking=llm_thinking,
        llm_max_tokens=llm_max_tokens,
        llm_concurrency=llm_concurrency,
        llm_rescue_max=llm_rescue_max,
        llm_label=llm_label,
        vlm_base_url=vlm_base_url,
        vlm_model=vlm_model,
        checklist_path=str(checklist_path) if checklist_path else "",
    )

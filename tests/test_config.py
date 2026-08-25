from app.config import load_config
from modules.shared import Config


def test_load_config_reads_settings_and_checklist(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        "doc_type: generic\nrequired_sections:\n  - 개요\n  - 요구사항\n",
        encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\nmodel = "claude-x"\n\n'
        '[chunking]\nmax_chars = 1234\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n',
        encoding="utf-8")

    cfg = load_config(tmp_path / "settings.toml")
    assert isinstance(cfg, Config)
    assert cfg.llm_provider == "echo"
    assert cfg.llm_model == "claude-x"
    assert cfg.chunk_max_chars == 1234
    assert cfg.review.doc_type == "generic"
    assert cfg.review.required_sections == ["개요", "요구사항"]


def test_load_config_reads_id_pattern(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "settings.toml")
    assert cfg.review.id_pattern == r"SR-\d+"


def test_load_config_reads_scope_pattern(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n'
        'scope_pattern: "SR-PR-\\\\d+"\n', encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "settings.toml")
    assert cfg.review.scope_pattern == r"SR-PR-\d+"


def test_load_config_scope_pattern_defaults_empty(tmp_path):
    """비면 상위 요건 전부가 대상이다 (기존 동작)."""
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        "doc_type: generic\n", encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    assert load_config(tmp_path / "settings.toml").review.scope_pattern == ""


def test_load_config_id_pattern_defaults_empty(tmp_path):
    (tmp_path / "checklists").mkdir()
    (tmp_path / "checklists" / "cl.yaml").write_text(
        "doc_type: generic\nrequired_sections: []\n", encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "settings.toml")
    assert cfg.review.id_pattern == ""


def test_체크리스트의_예시_ID를_읽는다(tmp_path):
    # 화면에 정규식을 던지면 검토자는 못 읽는다. 예시를 보여줘야 한다.
    # 다만 정규식에서 예시를 지어내면 틀릴 수 있으니, 체크리스트에 적힌 것만 쓴다.
    (tmp_path / "cl.yaml").write_text(
        'doc_type: generic\n'
        'id_pattern: "RQ-[A-Z]{3}-\\\\d{3}"\n'
        'id_example: "RQ-SFR-001"\n', encoding="utf-8")
    (tmp_path / "s.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[review]\nchecklist = "cl.yaml"\n', encoding="utf-8")

    cfg = load_config(tmp_path / "s.toml")

    assert cfg.review.id_example == "RQ-SFR-001"


def test_예시가_없으면_빈값이다(tmp_path):
    (tmp_path / "cl.yaml").write_text(
        'doc_type: generic\nid_pattern: "SR-\\\\d+"\n', encoding="utf-8")
    (tmp_path / "s.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[review]\nchecklist = "cl.yaml"\n', encoding="utf-8")

    assert load_config(tmp_path / "s.toml").review.id_example == ""


def test_담당_범위의_사람말_이름을_읽는다(tmp_path):
    (tmp_path / "cl.yaml").write_text(
        'doc_type: generic\n'
        'scope_pattern: "RQ-[A-Z]{3}-PR-01-\\\\d{3}"\n'
        'scope_label: "PR-01 구성"\n', encoding="utf-8")
    (tmp_path / "s.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[review]\nchecklist = "cl.yaml"\n', encoding="utf-8")

    assert load_config(tmp_path / "s.toml").review.scope_label == "PR-01 구성"


def test_load_config_reads_id_rollup_separator(tmp_path):
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n[chunking]\nmax_chars = 100\n'
        '[review]\nchecklist = "cl.yaml"\n', encoding="utf-8")
    (tmp_path / "cl.yaml").write_text(
        'doc_type: srs\nid_rollup_separator: "_"\n', encoding="utf-8")
    assert load_config(tmp_path / "settings.toml").review.id_rollup_separator == "_"


def test_id_rollup_separator_defaults_to_off(tmp_path):
    """켜지 않은 문서쌍의 판정을 조용히 바꾸면 안 된다."""
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n[chunking]\nmax_chars = 100\n'
        '[review]\nchecklist = "cl.yaml"\n', encoding="utf-8")
    (tmp_path / "cl.yaml").write_text('doc_type: srs\n', encoding="utf-8")
    assert load_config(tmp_path / "settings.toml").review.id_rollup_separator == ""


# ── LLM 서버 주소: 환경변수가 설정 파일을 덮는다 ─────────────────────────────
# 사내·팀 서버 주소는 배포마다 다르고 배포판 저장소에 박을 수 없다. 그래서 코드도
# 설정 파일도 아니라 배포 환경이 정한다(app/config.py 모듈 주석 참고).

def _settings(tmp_path, llm_block: str):
    (tmp_path / "checklists").mkdir(exist_ok=True)
    (tmp_path / "checklists" / "cl.yaml").write_text("doc_type: generic\n", encoding="utf-8")
    (tmp_path / "settings.toml").write_text(
        f"[llm]\n{llm_block}\n\n[chunking]\nmax_chars = 4000\n\n"
        '[review]\nchecklist = "checklists/cl.yaml"\n', encoding="utf-8")
    return tmp_path / "settings.toml"


def test_env_overrides_llm_and_vlm_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    monkeypatch.setenv("LLM_OCR_URL", "http://gpu:9002/v1")
    p = _settings(tmp_path, 'provider = "local"\nbase_url = "http://설정파일:1/v1"')

    cfg = load_config(p)

    assert cfg.llm_base_url == "http://gpu:9001/v1"
    assert cfg.vlm_base_url == "http://gpu:9002/v1"
    assert cfg.vlm_model == "ocr"      # 서버가 별칭으로 고정한 이름


def test_qwen_url_promotes_echo_to_local(tmp_path, monkeypatch):
    """주소만 주고 설정은 echo 인 경우(배포판 기본)에도 LLM 을 부른다.

    안 승격시키면 주소를 제대로 줬는데도 규칙 검사만 돌고, 사용자는 왜 LLM 결과가
    없는지 알 수 없다.
    """
    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    p = _settings(tmp_path, 'provider = "echo"')

    assert load_config(p).llm_provider == "local"


def test_blank_env_does_not_override(tmp_path, monkeypatch):
    """`export LLM_QWEN_URL=` 로 비워 둔 값이 설정 파일을 덮으면 아무 데도 못 붙는다."""
    monkeypatch.setenv("LLM_QWEN_URL", "   ")
    p = _settings(tmp_path, 'provider = "local"\nbase_url = "http://설정파일:1/v1"')

    cfg = load_config(p)

    assert cfg.llm_base_url == "http://설정파일:1/v1"
    assert cfg.llm_provider == "local"


def test_load_config_reads_rescue_max(tmp_path):
    """`[llm] rescue_max` 가 `Config.llm_rescue_max` 로 들어와야 한다."""
    p = _settings(tmp_path, 'provider = "echo"\nrescue_max = 3')

    assert load_config(p).llm_rescue_max == 3


def test_vlm_url_defaults_to_empty(tmp_path):
    """그림 해석 주소가 없으면 빈 값이다 — 없는 기능을 있는 척하지 않는다."""
    assert load_config(_settings(tmp_path, 'provider = "echo"')).vlm_base_url == ""


def test_qwen_url_alone_is_enough_to_build_a_client(tmp_path, monkeypatch):
    """주소만 export 하면 붙어야 한다 — 팀 LLM 서버 안내가 그 두 줄만 알려준다.

    모델명을 안 채우면 LocalClient 가 "model 이 비어 있습니다"로 죽었다. 서버가
    --served-model-name 으로 별칭을 고정하므로 주소만 주면 되는 것이 맞다.
    """
    from modules.llm_client import build_llm

    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    cfg = load_config(_settings(tmp_path, 'provider = "echo"'))

    assert cfg.llm_model == "qwen"
    client = build_llm(cfg)          # 예외 없이 만들어져야 한다
    assert client.base_url == "http://gpu:9001/v1"


def test_env_url_ignores_the_model_name_in_the_file(tmp_path, monkeypatch):
    """주소를 환경변수로 받았으면 설정 파일의 모델명은 **다른 서버 것**이다.

    실제로 그렇게 404 가 났다: toml 의 "Qwen/Qwen3.6-27B" 를 별칭 "qwen" 만
    서비스하는 서버에 보냈고, 83개 청크가 전부 실패했다. 서버가
    --served-model-name 으로 별칭을 고정하므로 주소만 주면 붙는 것이 맞다.
    """
    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    cfg = load_config(_settings(tmp_path, 'provider = "local"\nmodel = "Qwen/Qwen3.6-27B"'))

    assert cfg.llm_model == "qwen"


def test_env_model_overrides_the_alias(tmp_path, monkeypatch):
    """별칭이 qwen 이 아닌 서버는 LLM_QWEN_MODEL 로 준다."""
    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    monkeypatch.setenv("LLM_QWEN_MODEL", "my-model")

    assert load_config(_settings(tmp_path, 'provider = "echo"')).llm_model == "my-model"


def test_file_model_is_used_when_no_env_url(tmp_path):
    """환경변수가 없으면 설정 파일이 정한다 — 사내 서버는 전체 이름을 쓴다."""
    cfg = load_config(_settings(
        tmp_path, 'provider = "local"\nmodel = "Qwen/Qwen3.6-27B"\nbase_url = "http://x:1/v1"'))

    assert cfg.llm_model == "Qwen/Qwen3.6-27B"


def test_display_label_is_separate_from_the_model_name(tmp_path):
    """화면 이름과 호출용 이름은 다른 값이다.

    서버는 별칭("qwen")만 받는데 사람에게는 뜻이 없다. 라벨을 호출에 쓰면 404 가
    나고, 별칭을 화면에 쓰면 검토자가 무슨 모델인지 모른다.
    """
    p = _settings(tmp_path, 'provider = "local"\nmodel = "qwen"\n'
                            'model_label = "Qwen3.6-27B"\nbase_url = "http://x:1/v1"')

    cfg = load_config(p)

    assert cfg.llm_model == "qwen"          # 호출에 쓰는 값
    assert cfg.llm_label == "Qwen3.6-27B"   # 화면에 쓰는 값


def test_env_label_overrides_the_file(tmp_path, monkeypatch):
    """주소를 환경변수로 받으면 파일의 라벨도 다른 서버 것일 수 있다."""
    monkeypatch.setenv("LLM_QWEN_URL", "http://gpu:9001/v1")
    monkeypatch.setenv("LLM_QWEN_LABEL", "Qwen3.6-27B (팀서버)")
    p = _settings(tmp_path, 'provider = "echo"\nmodel_label = "옛 서버"')

    assert load_config(p).llm_label == "Qwen3.6-27B (팀서버)"


def test_no_label_falls_back_to_the_model_name(tmp_path):
    """라벨이 없으면 지어내지 않고 별칭을 그대로 보여준다."""
    p = _settings(tmp_path, 'provider = "local"\nmodel = "qwen"\nbase_url = "http://x:1/v1"')

    assert load_config(p).llm_label == ""    # health 가 llm_model 로 대체한다


def test_load_config_without_checklist(tmp_path):
    """`[review] checklist` 가 없어도 뜬다 — 기준은 팀 프리셋·화면 선택이 준다.

    예전엔 필수라 비우면 settings 디렉터리를 파일로 열어 IsADirectoryError 로
    죽었고, 그래서 한 문서에서 뽑은 잣대를 기본값으로 박아둘 수밖에 없었다.
    """
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n',
        encoding="utf-8")

    cfg = load_config(tmp_path / "settings.toml")
    assert cfg.checklist_path == ""
    assert cfg.review.doc_type == "generic"
    assert cfg.review.id_pattern == ""
    assert cfg.review.required_sections == []
    # 키가 아예 없을 때의 기본은 유지된다(TBD 검사는 계속 돈다).
    assert cfg.review.placeholder_markers == ["TBD"]


def test_load_config_empty_checklist_value(tmp_path):
    """`checklist = ""` 로 비워둔 것도 '없음'으로 본다."""
    (tmp_path / "settings.toml").write_text(
        '[llm]\nprovider = "echo"\n\n[chunking]\nmax_chars = 4000\n\n'
        '[review]\nchecklist = ""\n', encoding="utf-8")

    cfg = load_config(tmp_path / "settings.toml")
    assert cfg.checklist_path == ""
    assert cfg.review.doc_type == "generic"

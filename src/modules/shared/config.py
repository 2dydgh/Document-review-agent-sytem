"""검토 설정 스키마 (값 타입). 로딩은 app이 한다 — 모듈은 이 타입만 안다.

기준은 코드에 박지 않고 주입받는다. 이 dataclass들은 그 주입 형태다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewConfig:
    doc_type: str
    required_sections: list[str] = field(default_factory=list)
    id_pattern: str = ""
    # 화면용 예시 ID. 검토자에게 정규식을 보여줄 수는 없다. 정규식에서 예시를
    # 지어내면 틀릴 수 있으니 체크리스트에 적힌 것만 쓴다. 없으면 안 보여준다.
    id_example: str = ""
    # 하위문서가 책임지는 상위 요건의 범위. 비면 상위 요건 전부가 대상이다.
    # 부분 설계서(예: 한 구성만 담당)와 전체 요구사항명세서를 비교할 때,
    # 남의 몫까지 "누락"으로 세는 것을 막는다.
    scope_pattern: str = ""
    # 담당 범위를 사람 말로. 화면에 정규식을 띄우지 않으려는 것이다.
    scope_label: str = ""
    # 하위요건 ID(FR-CCG_01_01)를 부모(FR-CCG_01)로 한 단계 접어 대조할 구분자.
    # 상위문서가 요건을 더 잘게 쪼개 쓰고 하위문서는 부모 수준에서만 검증하는
    # 문서쌍에서 켠다. 실측(SHN34 SRS↔RVVR): 이게 없으면 누락 54건 중 46건이
    # 오탐이다. 접는 규칙은 문서마다 다르므로 코드가 아니라 여기서 정한다.
    # 빈 값이면 끈다 — 켜지 않은 문서쌍의 판정을 조용히 바꾸면 안 된다.
    id_rollup_separator: str = ""
    # 배포 문서에 남으면 안 되는 자리표시자. 빈 목록이면 검사하지 않는다.
    placeholder_markers: list[str] = field(default_factory=lambda: ["TBD"])


@dataclass
class Config:
    llm_provider: str
    chunk_max_chars: int
    review: ReviewConfig
    llm_model: str = ""
    # provider="local"일 때 쓰는 OpenAI 호환 엔드포인트 (vLLM/Ollama/사내 서버)
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_timeout: float = 120.0
    llm_api_key: str = ""
    # 사고(reasoning)는 판정 정확도를 높이지 않으면서 시간을 크게 먹는다.
    llm_thinking: bool = False
    llm_max_tokens: int = 1024
    # 청크를 한 번에 몇 개씩 물어볼지. vLLM 은 요청을 배치로 묶어 처리하도록
    # 만들어져, 하나씩 보내면 GPU 가 계속 대기한다. 실측(27B, L40S x2):
    #   순차 4건 145.0초(36.2초/건) · 동시 4건 46.2초(11.5초/건) · 동시 8건 33.3초(4.2초/건)
    # 8이면 8.7배다 — 청크 83개 문서가 9분 39초에서 1분 안쪽이 된다.
    # 코드에 박지 않는 이유는 여러 사람이 동시에 검토하면 이 수가 곱해지기
    # 때문이다. 서버 여력에 맞춰 배포 설정이 정한다(루트 CLAUDE.md).
    llm_concurrency: int = 8
    # 문서를 **통째로** 한 프롬프트에 넣을 때 허용할 본문 글자수. 이걸 넘으면
    # 조각으로 내려간다(그 사실은 화면에 밝힌다 — 조용히 내려가면 "전체를 봤다"가
    # 거짓이 된다).
    #
    # 토큰이 아니라 글자로 재는 이유: 토크나이저를 들이지 않으려는 것이다. 실측
    # (2026-08-03, 사내 vLLM /tokenize, Qwen3.6-27B): 한국어 2,000자 → 1,159토큰
    # ≈ 1.73자/토큰. 서버 max_model_len 102,000 토큰 ≈ 17.6만 자.
    # 기본값은 그 3분의 2다 — 지시문·기준 본문·응답이 같은 창을 나눠 쓰고,
    # 표가 많은 문서는 자당 토큰이 더 든다.
    #
    # **모델·서버 설정이 바뀌면 이 값도 바꾼다.** max_model_len 은 vLLM 을 띄울 때
    # 정하는 값이라 모델 고유 상수가 아니다(루트 CLAUDE.md: 배포 설정으로만 결정).
    llm_doc_max_chars: int = 120_000
    # 원문 대조에 실패한 지적 후보를 버리기 전에 LLM 재질의로 재확인할
    # **검사기당** 상한이다(문서당이 아니다 — 조각 단위 ChunkCriteriaChecker 와
    # 문서 전체 단위 WholeDocCriteriaChecker 가 각자 이 상한을 쓴다). 후보당 호출
    # 최대 2회라 최악 추가 비용은 검사기 두 개 × rescue_max(10) × 2호출 =
    # 40호출이다. llm_concurrency=8 이면 1분 미만이라 5분 예산 안에 든다
    # (공유 카운터는 만들지 않는다 — 그럴 필요가 없다).
    # 0 이면 끈다(즉시 폐기 — 예전 동작).
    llm_rescue_max: int = 10
    # 화면에 보여줄 이름. **호출에는 쓰지 않는다** — 서버는 별칭(qwen)만 받고,
    # 사람에게 "qwen"은 아무 뜻이 없다. 비면 llm_model 을 그대로 보여준다.
    # 서버 모델을 바꾸면 이 값도 같이 고쳐야 한다(자동으로 알 방법이 없다 —
    # vLLM /v1/models 도 별칭만 답한다).
    llm_label: str = ""
    # 그림·다이어그램 해석용 VLM. 문서 검사용(llm_base_url)과 **다른 엔드포인트**다 —
    # 서버가 문서용(qwen)과 비전용(ocr)을 GPU 배치까지 달리해 따로 띄운다.
    # 비어 있으면 그림 해석을 하지 않는다. 없는 기능을 있는 척하지 않는다.
    vlm_base_url: str = ""
    # 서버가 --served-model-name 으로 고정한 별칭. 서버 쪽 모델이 교체돼도
    # 클라이언트는 그대로 둔다.
    vlm_model: str = "ocr"
    # 어떤 체크리스트를 읽었는지. 화면이 "지금 무슨 잣대로 재는 중"인지 밝히는 데 쓴다.
    checklist_path: str = ""
    # 이번 실행에서 LLM 검사를 실제로 돌릴지. provider="echo"는 테스트·오프라인
    # 대체 구현으로도 쓰여 "사용자가 AI 검토를 껐다"는 뜻을 표현하지 못한다.
    llm_enabled: bool = True

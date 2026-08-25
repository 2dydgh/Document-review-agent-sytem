"""프리셋 라이브러리 모델.

판정 어휘(VERDICTS)는 지어낸 것이 아니다 — RVVR 부록(채워진 체크리스트)에 실제로
찍혀 있는 말을 그대로 쓴다. O/X 로 바꾸면 산출물이 기존 문서와 말이 달라져 검토자가
다시 옮겨 적어야 한다.

프리셋은 3층이다: 공통(모든 팀) · 팀별 · 업로드(문서별 임시). 셋 다 같은 Preset 모양.
기준(Criterion)마다 어느 Agent 소속인지(agent) 라벨이 붙는다 — 큐레이트 프리셋은
데이터에 박혀 있고, 업로드는 검토 때 추론하거나 비운다(→ 사람 확인).
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERDICTS = ("Satisfied", "Modification Required", "Not Satisfied", "N/A")
# 검사 관점 6종. 앞 4개만 checker 가 있고 뒤 2개(생성·이력)는 미구현이지만
# 프리셋엔 들어오므로 어휘엔 둔다 — agent 는 라벨일 뿐, checker 유무는 별개다.
AGENTS = ("형식·완전성", "표현·내용품질", "정합성·추적성",
          "표준·체크리스트", "문서작성·생성", "검토의견·이력")
# 기준 하나를 **무엇이** 검사하는가.
#   규칙      코드가 검사한다. LLM 을 안 부른다 (필수 장절·미작성 표시 등)
#   LLM-조각  문서를 청크로 잘라 조각마다 묻는다 (오탈자·맞춤법 — 문장 단위)
#   LLM-문서  문서를 통째로 한 번 묻는다 (표·그림 참조, 약어 목록과 사용처처럼
#             **멀리 떨어진 두 곳을 맞대야** 하는 것. 조각으로는 원리상 못 잡는다)
#   사람      도구가 판정할 수 없다. 정답이 문서 밖에 있다 (works·사업자등록증 등)
#
# 이름에 LLM 을 드러내는 이유: "조각"·"전체"만으로는 둘 다 LLM 이라는 것도,
# 규칙과 무엇이 다른지도 안 읽힌다.
#
# 문서가 창을 넘으면 LLM-문서 는 조각으로 내려가되 그 사실을 밝힌다
# (WholeDocCriteriaChecker). 조용히 내려가면 "전체를 봤다"가 거짓이 된다.
MODES = ("규칙", "LLM-조각", "LLM-문서", "사람")
SCOPES = ("공통", "팀별", "업로드")


@dataclass
class Criterion:
    """검토 기준 한 줄.

    raw 를 남기는 이유: 열 추측이 틀렸을 때 되짚을 수 있고, 자동 판정에서 다른
    열(IS22 의 '평가 관점' 같은)이 필요해진다. 버리면 다시 업로드해야 한다.
    """
    no: str = ""
    text: str = ""
    group: str = ""
    note: str = ""
    raw: list[str] = field(default_factory=list)
    agent: str = ""            # AGENTS 중 하나 또는 "" (미지정 → 사람 확인)
    mode: str = ""             # MODES 중 하나 또는 "" (비면 agent 라벨이 정한다)
    # mode 가 "규칙" 일 때 **어느 검사가** 이 기준을 보는가. 이름은 RULE_CHECKS
    # (agent_checklist) 의 열쇠다. 비어 있으면 이 기준을 검사하는 규칙이 아직
    # 없다는 뜻이고, 그때는 사람 몫으로 떨어진다 — 조용히 통과시키지 않는다.
    #
    # agent 라벨로 잇던 예전 방식은 라벨 하나에 기준 수십 개가 달려서, 규칙
    # 검사기 두 개가 낸 지적이 그 라벨을 단 기준 **전부**에 복사됐다(EV2 는 15개).
    # 실제로 검사되는 것은 두 개뿐인데 열다섯 개가 검사된 것처럼 보였다.
    check: str = ""
    source: str = ""           # 출처(근거): "문서검증 No.3" 등, 되짚기용
    params: dict = field(default_factory=dict)  # 추적성 매개변수 {id_pattern:...}
    # 어느 층에서 온 기준인가(공통/팀별/업로드). 검토 합성(resolve_criteria)이
    # 찍는다 — 공통·팀은 늘 돌지만 업로드는 검토자가 고른 것이라, 지적의 출처를
    # 화면이 말하려면 합친 뒤에도 층이 남아 있어야 한다.
    layer: str = ""
    # **이 기준이 어느 산출물을 볼 때만 적용되는가.** 팀 기준 outputs 절의 key 를
    # 적는다(["갑지"]). 비어 있으면 문서를 가리지 않는다 — 대부분의 기준이 그렇다.
    #
    # 없을 때 무슨 일이 났나: AI시험인증1팀은 산출물이 10종인데 "갑지의 비고문구
    # 4개가 그대로인가" 같은 기준이 **시험의뢰서를 검토할 때도** 화면에 떴다.
    # 적을 칸이 없어 text 앞에 "갑지 — " 를 붙여 사람이 읽고 거르게 해뒀는데,
    # 그건 검토자에게 무시할 항목을 스무 개씩 세게 하는 것이다.
    #
    # 대상이 아니면 `na`(해당없음)로 떨어진다 — `manual`(사람이 봐야 함)과
    # 갈라야 한다. 앞은 정상이고 뒤는 할 일이 남은 것이다.
    applies_to: list[str] = field(default_factory=list)


@dataclass
class Preset:
    id: str
    name: str
    source_filename: str
    registered_at: str
    # 어느 열을 무엇으로 읽었는지. 나중에 사람이 되짚을 수 있어야 한다.
    columns: dict = field(default_factory=dict)
    items: list[Criterion] = field(default_factory=list)
    # 목록 응답 전용. 항목을 싣지 않을 때 개수만 알린다.
    item_count: int = 0
    scope: str = "업로드"      # SCOPES 중 하나. 업로드가 기본(하위호환).
    team: str = ""             # scope == "팀별" 일 때만

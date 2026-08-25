"""검토 엔진 기반: Context, Checker 프로토콜."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from modules.llm_client import LLMClient

from .models import Chunk, Document, Finding


@dataclass
class Context:
    review: object          # required_sections / id_pattern 등을 가진 ReviewConfig
    llm: LLMClient
    chunks: list[Chunk] = field(default_factory=list)
    other: Document | None = None
    # 진행 보고. 오래 걸리는 체커는 여기로 진척을 알린다 — 안 그러면 화면이
    # 수십 초 동안 "RUNNING"에서 멈춰 선 것처럼 보인다. 기본은 아무것도 안 한다.
    on_progress: Callable[[dict], None] = field(default=lambda ev: None)
    # LLM 을 한 번에 몇 개씩 부를지. 기본 1(순차) — 직접 Context 를 만드는 쪽이
    # 아무 설정도 안 했으면 옛 동작 그대로다. 조립 계층이 Config 에서 채운다.
    llm_concurrency: int = 1
    # 대조 실패한 지적 후보를 버리기 전에 재확인(구조)할 **검사기당** 상한이다
    # (문서당이 아니다 — ChunkCriteriaChecker·WholeDocCriteriaChecker 가 각자 쓴다).
    # 기본 0(끔) — llm_concurrency 와 같은 이유로, 직접 Context 를 만드는 쪽이
    # 아무 설정도 안 했으면 옛 동작(즉시 폐기) 그대로다. 배포 기본(10)은
    # 조립 계층이 Config.llm_rescue_max 에서 채운다.
    rescue_max: int = 0


class Checker(Protocol):
    name: str

    def check(self, doc: Document, ctx: Context) -> list[Finding]: ...

    # 선택. 작업 단위가 있는 체커만 구현한다(청크·그룹 등). orchestrator는
    # getattr로 있는지만 보고, 없는 체커는 작업량을 신고하지 않는 것으로
    # 다룬다 — 그래서 이 메서드가 없어도 기존 체커는 깨지지 않는다.
    # 반환: {"kind": "chunk"|"rule"|"rescue", "total": int, "label": str} 또는
    # 작업량이 없으면 None. label은 화면이 그대로 그리는 레인 이름이다 —
    # kind→이름 매핑을 프론트에 하드코딩하지 않으려고 여기서 실어 보낸다.
    def plan(self, doc: Document, ctx: Context) -> dict | None: ...

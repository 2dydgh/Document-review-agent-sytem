"""업로드 기준 저장소. JSON 파일 하나에 하나씩.

검토 기준 3층 중 **셋째 층**이다. 공통·팀별은 repo 파일(`presets/criteria/`)이라
`library.py` 가 읽고, 이 층만 사용자가 올린 것이라 별도 저장소가 필요하다 —
id 가 브라우저에서 오므로 경로 검증(`_path`)이 여기에만 있다.

`.docreview/criteria/uploads/<id>.json` 에 둔다(자리는 app 이 주입한다).
검토 결과(ChecklistRun)는 여기가 아니라 기존 HistoryStore 에 kind="checklist" 로
들어간다 — 기록 화면을 그대로 재사용하기 위해서다.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import Preset, Criterion


class ChecklistError(Exception):
    """없는 체크리스트, 잘못된 id, 빈 항목 등."""


# 파일 이름으로 쓸 수 있는 id 만 받는다. 브라우저가 보낸 문자열을 경로로 그대로
# 쓰면 서버의 아무 파일이나 열게 된다("../../etc/passwd").
_ID = re.compile(r"^[a-z0-9]{8,32}$")

#: 옛 이름 → 지금 이름. 저장된 파일은 저장 당시의 필드 이름을 그대로 갖고 있어서,
#: 필드를 갈면 `Criterion(**i)` 가 TypeError 로 죽는다 — 이미 등록해 둔 101개짜리
#: 체크리스트를 배포 한 번에 못 열게 된다(다시 올리는 것 말고는 복구 수단이 없다).
_RENAMED = {"verdict_method": "mode"}


def _migrate(item: dict) -> dict:
    """저장된 기준 한 줄을 지금 필드 이름으로 옮긴다."""
    return {_RENAMED.get(k, k): v for k, v in item.items()}


class ChecklistStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, checklist_id: str) -> Path:
        if not _ID.match(str(checklist_id or "")):
            raise ChecklistError(f"잘못된 체크리스트 id 입니다: {checklist_id!r}")
        return self.root / f"{checklist_id}.json"

    def save(self, name: str, source_filename: str,
             columns: dict, items: list[Criterion],
             scope: str = "업로드", team: str = "") -> Preset:
        if not items:
            raise ChecklistError(
                "항목이 하나도 없습니다. 항목 내용 열을 골랐는지 확인하세요.")
        entry = Preset(
            # JSON 본문에도 id 를 적어 두지만(사람이 파일을 직접 열어봤을 때
            # 알아보기 위한 용도일 뿐) get()/list() 는 이 값을 절대 읽지 않고
            # 파일명만 신뢰한다 — 본문 쪽을 신뢰하게 하면 파일이 복사·변조돼
            # 둘이 어긋났을 때 조용히 되돌아가는 회귀가 된다(이미 한 번 겪었다).
            id=uuid.uuid4().hex[:16],
            name=(name or "").strip() or source_filename or "체크리스트",
            source_filename=source_filename or "",
            # 초 단위(isoformat(timespec="seconds"))로 자르면 연달아 저장한
            # 두 체크리스트가 같은 registered_at 값을 갖게 되어 list() 의
            # "최신 순" 정렬이 무너진다. 마이크로초까지 남기면 save() 사이에
            # 실제 파일시스템 I/O 가 끼어드는 정상적인 사용에서는 값이 자연히
            # 갈라진다 — 정렬 키를 만들려고 클래스 변수 시계를 흉내 내던 예전
            # 구현은 서로 무관한 저장소끼리, 그리고(장차 HTTP 서버가 되면) 서로
            # 다른 워커 프로세스끼리 상태를 공유하는 부작용이 있어 걷어냈다.
            # 그래도 남는 동률 가능성은 상태 없이 list() 의 정렬 키 쪽에서
            # (registered_at, id) 전순서로 해소한다.
            registered_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            columns=dict(columns or {}),
            items=list(items),
            item_count=len(items),
            scope=scope,
            team=team,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(entry.id).write_text(
            json.dumps(asdict(entry), ensure_ascii=False, indent=2),
            encoding="utf-8")
        return entry

    def get(self, checklist_id: str) -> Preset:
        path = self._path(checklist_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChecklistError(
                f"체크리스트를 읽지 못했습니다: {checklist_id}") from exc
        try:
            items = [Criterion(**_migrate(i)) for i in raw.get("items", [])]
            # id 는 JSON 안의 값이 아니라 파일명에서 가져온다 — list()/delete() 도
            # 파일명으로 찾으므로, 파일이 복사·변조돼 안의 id 가 어긋나 있어도
            # 세 메서드가 같은 id 를 말하게 하기 위해서다.
            return Preset(id=path.stem, name=raw.get("name", ""),
                             source_filename=raw.get("source_filename", ""),
                             registered_at=raw.get("registered_at", ""),
                             columns=raw.get("columns", {}), items=items,
                             scope=raw.get("scope", "업로드"),
                             team=raw.get("team", ""))
        except (TypeError, AttributeError) as exc:
            # 여기서 실제로 던져질 수 있는 예외만 잡는다: Preset(...) 의
            # 필드는 전부 raw.get(키, 기본값) 이라 KeyError 는 날 수 없고, 여기서
            # 하는 변환 중 ValueError 를 일으킬 만한 것도 없다 — 남겨두면 나중에
            # 누군가 int(raw["no"]) 같은 진짜 검증을 추가했을 때 그 ValueError
            # 까지 여기서 조용히 "파일 구조가 이상하다"로 둔갑해 버린다. 실제로
            # 나는 것은 Criterion(**i) 에 딕셔너리가 아닌 값이나 알 수 없는
            # 키가 들어왔을 때의 TypeError, 그리고 raw 자체가 딕셔너리가 아닐 때
            # (raw.get 이 없는 타입, 예: JSON 최상위가 배열인 경우)의
            # AttributeError 뿐이다.
            raise ChecklistError(
                f"체크리스트 파일 구조가 올바르지 않습니다: {path.name}") from exc

    def list(self) -> list[Preset]:
        """최신 순. 항목은 싣지 않고 개수만 준다 — 101개를 목록마다 보낼 이유가 없다."""
        out: list[Preset] = []
        if not self.root.is_dir():
            return out
        for path in self.root.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # 깨진 파일 하나가 목록을 죽이지 않게
            # id 는 항상 파일명에서 가져온다(raw 안의 id 는 신뢰하지 않는다) —
            # get()/delete() 도 파일명으로 찾으므로, 여기서 다른 값을 내보내면
            # 목록에는 보이는데 클릭하면 못 찾는 항목이 생긴다.
            entry = Preset(id=path.stem,
                              name=raw.get("name", ""),
                              source_filename=raw.get("source_filename", ""),
                              registered_at=raw.get("registered_at", ""),
                              columns=raw.get("columns", {}), items=[],
                              scope=raw.get("scope", "업로드"),
                              team=raw.get("team", ""))
            entry.item_count = len(raw.get("items", []))
            out.append(entry)
        # registered_at 만으로는 전순서가 아니다(마이크로초까지 찍어도 동률이
        # 이론적으로 가능하다) — id 를 2차 키로 더해 동률일 때도 항상 같은
        # 결과가 나오게 한다. 상태(예: 클래스 변수 시계) 없이 결정적이어야
        # list() 호출 두 번이 서로 다른 순서를 내놓지 않는다.
        out.sort(key=lambda c: (c.registered_at, c.id), reverse=True)
        return out

    def delete(self, checklist_id: str) -> None:
        path = self._path(checklist_id)
        if not path.exists():
            raise ChecklistError(f"그런 체크리스트가 없습니다: {checklist_id}")
        path.unlink()

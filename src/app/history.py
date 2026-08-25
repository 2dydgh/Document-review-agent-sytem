"""검토 이력 저장소 — 결과를 디스크에 JSON으로 남긴다.

원본 문서는 보관하지 않는다. 고객 문서가 서버에 쌓이는 것보다, 결과만 남기고
업로드본은 지우는 편이 안전하다(업로드는 지금도 임시 디렉터리에서 처리된다).

파일 하나에 검토 하나. DB를 들이지 않은 이유는 이력이 "최근 것 몇 건 다시 보기"
용도라서다. 파일이 부족해지면 그때 옮긴다.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 이력이 무한정 쌓이면 목록 조회가 느려지고 디스크를 먹는다. 오래된 것부터 지운다.
MAX_ENTRIES = 200

# 원본 문서(뷰어용)는 최근 이 개수만 보관한다 — 결과(JSON)보다 훨씬 무거우니 용량을
# 묶어둔다. 넘겨서 밀려난 이력을 다시 열면 원본이 없어 텍스트 폴백으로 degrade한다.
MAX_ORIGINALS = 20

# 파일 이름으로 쓰는 ID. 바깥에서 들어온 ID를 그대로 경로에 붙이면
# "../../etc/passwd" 같은 값으로 아무 파일이나 읽거나 지울 수 있다.
# 저장할 때 이 형식으로만 만들고, 읽을 때 이 형식만 받아준다.
#
# 시각 부분이 마이크로초까지인 이유: 초 단위로 끊으면 같은 초에 저장된 두 건의
# 순서가 뒤의 무작위 해시로 갈려 "최신순"이 뒤집힌다(실제로 뒤집혔다).
_ID_RE = re.compile(r"^\d{8}T\d{12}-[0-9a-f]{8}$")


class HistoryError(Exception):
    """이력을 찾을 수 없거나 ID가 올바르지 않다."""


@dataclass(frozen=True)
class Entry:
    """목록에 보여줄 요약. 결과 전체(payload)는 따로 get()으로 읽는다."""
    id: str
    kind: str          # "compare" | "review" | "checklist"
    at: str            # ISO8601 (초 단위)
    title: str         # 예: "ACMD-AN-002.hwpx ↔ ACMD-DS-005.hwpx"
    findings: int

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "at": self.at,
                "title": self.title, "findings": self.findings}


def _new_id(now: datetime) -> str:
    # 시각(마이크로초까지)을 앞에 둬서 파일 이름만 정렬해도 시간순이 된다.
    # 뒤의 무작위 8자는 정렬용이 아니라 충돌 방지용이다.
    return f"{now:%Y%m%dT%H%M%S%f}-{uuid.uuid4().hex[:8]}"


def _summarize(kind: str, payload: dict) -> tuple[str, int]:
    """목록에 쓸 제목과 지적사항 수를 결과에서 뽑는다."""
    findings = len(payload.get("findings") or [])
    if kind == "compare":
        a = (payload.get("docA") or {}).get("name") or "?"
        b = (payload.get("docB") or {}).get("name") or "?"
        return f"{a} ↔ {b}", findings
    if kind == "case":
        # 산출물 세트 검토. 제목은 의뢰번호이고, 세는 것은 "막는 것"이다 —
        # 미검토는 지적이 아니라서 이 수에 넣지 않는다(목록에서 둘이 섞이면
        # "지적 0건" 이 "다 봤고 이상 없다"로 읽힌다).
        blocking = len([f for f in (payload.get("findings") or [])
                        if not f.get("unreviewed")])
        return payload.get("caseId") or "?", blocking
    if kind == "checklist":
        # 체크리스트 실행은 findings가 아니라 문서 대비 미판정 개수로 본다 —
        # 목록에서 "몇 건 안 봤는지"가 여기서도 드러나야 한다.
        title = payload.get("document_name") or payload.get("checklist_name") or "?"
        return title, int(payload.get("unjudged") or 0)
    return (payload.get("doc") or {}).get("name") or "?", findings


class HistoryStore:
    def __init__(self, root: str | Path, max_entries: int = MAX_ENTRIES) -> None:
        self.root = Path(root)
        self.max_entries = max_entries

    # ---- 쓰기 ------------------------------------------------------------
    def save(self, kind: str, payload: dict, *, now: datetime | None = None) -> Entry:
        if kind not in ("compare", "review", "checklist", "case"):
            raise HistoryError(f"알 수 없는 검토 종류: {kind}")
        now = now or datetime.now()
        entry_id = _new_id(now)
        title, findings = _summarize(kind, payload)
        entry = Entry(id=entry_id, kind=kind, at=now.isoformat(timespec="seconds"),
                      title=title, findings=findings)

        self.root.mkdir(parents=True, exist_ok=True)
        record = {**entry.as_dict(), "payload": payload}
        dest = self.root / f"{entry_id}.json"
        # 쓰다 만 파일이 남으면 목록 전체가 깨진다. 임시 파일에 다 쓰고 바꿔 끼운다.
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, dest)
        self._prune()
        return entry

    def _prune(self) -> None:
        paths = sorted(self.root.glob("*.json"), reverse=True)
        for stale in paths[self.max_entries:]:
            stale.unlink(missing_ok=True)

    # ---- 읽기 ------------------------------------------------------------
    def list(self, limit: int = 20) -> list[Entry]:
        if not self.root.is_dir():
            return []
        entries: list[Entry] = []
        # 파일 이름이 시각으로 시작하므로 이름 역순 = 최신순.
        for path in sorted(self.root.glob("*.json"), reverse=True):
            if len(entries) >= limit:
                break
            record = _read(path)
            # 깨진 파일 하나 때문에 목록 전체가 죽으면 안 된다. 건너뛴다.
            if record is None:
                continue
            entries.append(Entry(
                id=record.get("id", path.stem),
                kind=record.get("kind", "review"),
                at=record.get("at", ""),
                title=record.get("title", ""),
                findings=int(record.get("findings", 0)),
            ))
        return entries

    def get(self, entry_id: str) -> dict:
        """저장된 결과 전체(payload)를 돌려준다."""
        record = _read(self._path(entry_id))
        if record is None:
            raise HistoryError(f"이력을 찾을 수 없습니다: {entry_id}")
        return record

    def update_payload(self, entry_id: str, patch: dict, *,
                       refresh_summary: bool = False) -> dict:
        """저장된 결과의 payload 일부를 갈아끼운다.

        산출물 세트 검토가 "직접 확인 3건을 사람이 눌렀다"를 남기려면 필요하다. 결과는
        이미 저장돼 있는데 확인 표시만 브라우저에 있으면, 나중에 그 기록을 열었을 때
        "이 건은 발급했나" 를 알 수 없다 — 점검의 결론이 통째로 사라진다.

        payload 를 통째로 받지 않고 **일부만** 받는다. 통째로 받으면 브라우저가
        보낸 것이 검사 결과를 덮어쓸 수 있다 — 확인 표시는 사람이 정하지만 지적은
        도구가 정한다.
        """
        record = _read(self._path(entry_id))
        if record is None:
            raise HistoryError(f"이력을 찾을 수 없습니다: {entry_id}")
        payload = dict(record.get("payload") or {})
        payload.update(patch)
        record["payload"] = payload
        if refresh_summary:
            title, findings = _summarize(str(record.get("kind", "review")), payload)
            record["title"] = title
            record["findings"] = findings
        path = self._path(entry_id)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return record

    def delete(self, entry_id: str) -> None:
        path = self._path(entry_id)
        if not path.is_file():
            raise HistoryError(f"이력을 찾을 수 없습니다: {entry_id}")
        path.unlink()
        self._delete_original(entry_id)   # 결과를 지우면 원본도 함께 지운다

    # ---- 원본 문서(뷰어용) ------------------------------------------------
    # 결과만 남기던 정책에서, "이력에서도 원본을 다시 보기" 위해 최근 MAX_ORIGINALS개만
    # 원본을 함께 보관한다. 파일 이름이 id(=시각)로 시작하므로 이름 역순이 최신순이다.
    def _orig_dir(self) -> Path:
        return self.root / "originals"

    def save_original(self, entry_id: str, filename: str, data: bytes,
                      *, keep: int = MAX_ORIGINALS) -> None:
        if not _ID_RE.match(entry_id or ""):
            raise HistoryError(f"올바르지 않은 이력 ID: {entry_id}")
        ext = Path(filename or "").suffix.lower()
        if ext not in (".pdf", ".docx", ".hwpx"):
            return          # 뷰어가 못 여는 포맷은 원본을 남길 이유가 없다
        d = self._orig_dir()
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{entry_id}{ext}"
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        self._prune_originals(keep)

    def _prune_originals(self, keep: int) -> None:
        d = self._orig_dir()
        if not d.is_dir():
            return
        kept = sorted((p for p in d.iterdir()
                       if p.is_file() and not p.name.endswith(".tmp")), reverse=True)
        for stale in kept[keep:]:
            stale.unlink(missing_ok=True)

    def original(self, entry_id: str) -> tuple[str, bytes] | None:
        """보관 중인 원본이 있으면 (파일명, 바이트), 없으면 None."""
        if not _ID_RE.match(entry_id or ""):
            raise HistoryError(f"올바르지 않은 이력 ID: {entry_id}")
        d = self._orig_dir()
        if not d.is_dir():
            return None
        for p in sorted(d.glob(f"{entry_id}.*")):
            if p.name.endswith(".tmp"):
                continue
            try:
                return p.name, p.read_bytes()
            except OSError:
                return None
        return None

    def _delete_original(self, entry_id: str) -> None:
        d = self._orig_dir()
        if not d.is_dir():
            return
        for p in d.glob(f"{entry_id}.*"):
            p.unlink(missing_ok=True)

    def _path(self, entry_id: str) -> Path:
        if not _ID_RE.match(entry_id or ""):
            # 경로 탈출 시도든 오타든, 여기서 끊는다.
            raise HistoryError(f"올바르지 않은 이력 ID: {entry_id}")
        return self.root / f"{entry_id}.json"


def _read(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None

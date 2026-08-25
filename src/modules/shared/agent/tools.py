"""근거 재확인이 쓰는 읽기 전용 문서 검색 도구."""
from __future__ import annotations

from ..models import Document

# 한 번의 도구 결과가 컨텍스트를 다 먹지 않게 하는 상한.
_MAX_CHARS = 2000
_MAX_HITS = 30


def _clip(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    return text[:_MAX_CHARS] + f"\n…(생략 — 전체 {len(text)}자)"


class DocTools:
    SPECS = [
        {"name": "find_term", "args": {"term": "str"},
         "desc": "그 낱말이 나오는 모든 줄과 위치를 찾는다."},
    ]

    def __init__(self, doc: Document) -> None:
        self._sections = list(doc.iter_sections())

    def find_term(self, term: str) -> str:
        if not term:
            return "term 인자가 필요합니다."
        hits = []
        for s in self._sections:
            for line in (s.text or "").split("\n"):
                line = line.strip()
                if line and term in line:
                    hits.append(f"[{s.title} / {s.id}] {line}")
        if not hits:
            return f"'{term}' 은(는) 문서에 없습니다."
        shown = hits[:_MAX_HITS]
        out = "\n".join(shown)
        if len(hits) > _MAX_HITS:
            out += f"\n…({len(hits)}곳 중 {_MAX_HITS}곳만 표시)"
        return _clip(out)

    def run(self, name: str, args: dict) -> str:
        try:
            if name == "find_term":
                return self.find_term(args["term"])
        except KeyError as exc:
            return f"인자가 빠졌습니다: {exc.args[0]}"
        except Exception as exc:
            # 검색 후보 하나의 잘못된 인자가 재확인 라운드 전체를 죽이지 않게 한다.
            return f"인자가 잘못됐습니다: {exc}"
        return (f"알 수 없는 도구입니다: {name}. "
                f"쓸 수 있는 도구: {', '.join(s['name'] for s in self.SPECS)}")

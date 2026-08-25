"""씨앗 프리셋 로더 + 검토 구성(composition).

씨앗은 신뢰된 repo 파일이라 store 의 id 경로검증을 쓰지 않는다 — 파일명이 사람이
읽는 이름(common.yaml)이어도 된다. 브라우저가 주는 값이 아니므로 경로 주입 위험이 없다.

층은 **파일 위치**가 정한다:

    criteria/common.yaml      공통 기준 — 모든 팀·문서에 항상 적용
    criteria/teams/<팀>.yaml  팀 기준 — 수정·추가 가능

파일 안의 scope 값은 읽지 않는다. teams/ 에 둔 파일이 `scope: 공통` 이라고 적혀
있으면 그건 실수이고, 그 실수가 조용히 통하면 공통 기준이 한 팀에서만 도는 것을
아무도 눈치채지 못한다. 위치가 진실이다.

세 번째 층(업로드 기준)은 여기가 아니라 store 가 다룬다 — repo 파일이 아니라
사용자가 올린 것이라 경로 검증이 필요하다.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path

import yaml

from .models import Criterion, Preset


def _block_str(dumper, data):
    """여러 줄 문자열은 블록(|) 으로. 한 줄로 접히면 사람이 못 고친다."""
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, _block_str)


def _leading_comment(text: str) -> str:
    """파일 머리의 주석 블록. 파일을 새로 쓸 때(items 절이 없을 때)만 쓴다."""
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("#") or not line.strip():
            out.append(line)
        else:
            break
    return "".join(out)


def _items_span(lines: list[str]) -> tuple[int, int] | None:
    """원문에서 `items:` 절이 차지하는 줄 범위 [시작, 끝).

    끝은 다음 최상위 키다. 그 키 바로 위에 붙은 주석은 **그 키의 것**이라 범위에서
    뺀다 — 안 그러면 items 를 갈아끼울 때 다음 절의 설명이 같이 지워진다.
    """
    start = next((i for i, ln in enumerate(lines) if ln.startswith("items:")), None)
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln[:1].isalpha() or ln[:1] == "_":     # 최상위 키 (들여쓰기 0)
            end = i
            break
    while end - 1 > start and lines[end - 1].lstrip().startswith("#"):
        end -= 1
    return start, end


def _splice_items(text: str, items_yaml: str) -> str | None:
    """원문의 items 절만 갈아끼운다. 나머지 줄은 한 글자도 건드리지 않는다.

    yaml.safe_load → yaml.dump 왕복을 쓰면 주석이 전부 죽는다. 손으로 쓴 절
    (outputs·case_wide·pairs)에 "왜 이 문서를 뺐나" 같은 실측 근거가 주석으로
    달려 있고, 그게 이 파일에서 제일 비싼 정보다 — 실제로 한 번 날아갔다.
    """
    lines = text.splitlines(keepends=True)
    span = _items_span(lines)
    if span is None:
        return None
    start, end = span
    return "".join(lines[:start]) + items_yaml + "".join(lines[end:])


def _set_scalar(text: str, key: str, value: str) -> str:
    """최상위 스칼라 키 하나를 제자리에서 고친다. 없으면 items 앞에 끼운다."""
    line = yaml.dump({key: value}, Dumper=_Dumper, allow_unicode=True,
                     sort_keys=False, width=100)
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith(f"{key}:"):
            if ln == line:
                return text
            lines[i] = line
            return "".join(lines)
    at = next((i for i, ln in enumerate(lines) if ln.startswith("items:")), len(lines))
    return "".join(lines[:at]) + line + "".join(lines[at:])


def save_seed_items(path: str | Path, *, name: str, team: str,
                    items: Sequence[Criterion], source_filename: str = "") -> None:
    """씨앗 파일의 items 만 갈아끼운다. 다른 절은 그대로 남긴다.

    xlsx 에서 나오는 것은 items 뿐이다. outputs(어느 문서의 어느 칸에서 값을 뽑나)는
    사람이 문서 구조를 보고 정하는 값이라 스크립트가 만들 수 없다 — 재생성이 그걸
    지우면 그 작업물이 통째로 날아간다. 그래서 덮어쓰지 않고 병합한다.

    scope 는 쓰지 않는다. 층은 파일 위치가 정한다(load_presets 참고).
    """
    path = Path(path)
    rows = [{k: v for k, v in asdict(c).items() if v not in ("", [], {}, None)}
            for c in items]
    items_yaml = yaml.dump({"items": rows}, Dumper=_Dumper, allow_unicode=True,
                           sort_keys=False, width=100, indent=2)

    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    spliced = _splice_items(old, items_yaml) if old else None
    if spliced is not None:
        # 기존 파일 — items 절만 갈아끼우고 나머지 줄(주석 포함)은 그대로 둔다.
        text = _set_scalar(spliced, "name", name)
        if team:
            text = _set_scalar(text, "team", team)
        # 항목이 어디서 왔는지. 문서에서 거꾸로 뽑은 기준인지 팀 규정에서 온
        # 것인지를 나중에 되짚으려면 이게 있어야 한다(presets/README.md 참고).
        if source_filename:
            text = _set_scalar(text, "source_filename", source_filename)
    else:
        # 새 파일이거나 items 절이 없는 파일 — 통째로 짓는다.
        body: dict = yaml.safe_load(old) or {} if old else {}
        body["name"] = name
        if team:
            body["team"] = team
        if source_filename:
            body["source_filename"] = source_filename
        body["items"] = rows
        text = _leading_comment(old) + yaml.dump(
            body, Dumper=_Dumper, allow_unicode=True, sort_keys=False,
            width=100, indent=2)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path: Path, scope: str) -> Preset:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # 수정 2026-08-06: 팀 YAML 의 오타 키 하나(Criterion(**i) TypeError)가
    # load_presets 전체 → /api/health 포함 대부분의 API 를 500 으로 만들었다.
    # 모르는 키는 버리되 조용히 넘어가지 않고 note 에 흔적을 남긴다
    # (store.py 의 _migrate 와 같은 처방).
    fields = {f.name for f in dataclasses.fields(Criterion)}
    items = []
    for i in raw.get("items", []):
        if not isinstance(i, dict):
            continue
        # 키를 str 로 눕혀서 센다. YAML 1.1 은 따옴표 없는 `no:` 를 **불리언 False**
        # 로 읽어서(yes·on·off 도 같다), 손으로 쓴 기준 파일 하나가 sorted() 의
        # 타입 비교나 join() 에서 터졌다 — /api/review 전체가 "검토 중 오류:
        # sequence item 0: expected str instance, bool found" 로 죽었다.
        # (생성기는 `'no':` 로 따옴표를 붙여 쓴다 — 손으로 쓸 때도 그래야 한다.)
        unknown = sorted(str(k) for k in set(i) - fields)
        c = Criterion(**{k: v for k, v in i.items() if k in fields})
        if unknown:
            c.note = (c.note + " " if c.note else "") + f"[무시된 키: {', '.join(unknown)}]"
        items.append(c)
    return Preset(
        id=path.stem,
        name=raw.get("name", ""),
        source_filename=raw.get("source_filename", ""),
        registered_at=raw.get("registered_at", ""),
        columns=raw.get("columns", {}),
        items=items,
        item_count=len(items),
        scope=scope,
        team=raw.get("team", ""),
    )


def load_presets(directory: str | Path) -> list[Preset]:
    """공통 + 팀 기준을 Preset 목록으로 읽는다. id 는 파일명(stem).

    공통을 먼저 담는다 — compose_review_preset 이 공통 → 팀 순으로 합치므로
    순서가 뜻을 갖는다.
    """
    root = Path(directory)
    out: list[Preset] = []
    common = root / "common.yaml"
    if common.is_file():
        out.append(_read(common, scope="공통"))
    for path in sorted((root / "teams").glob("*.yaml")):
        out.append(_read(path, scope="팀별"))
    return out


def resolve_criteria(common: Preset | None,
                     team: Preset | None,
                     upload: Preset | None) -> list[Criterion]:
    """한 검토에 적용할 기준 = 공통 ∪ 팀 ∪ 업로드.

    text 로 중복 제거하되 먼저 온 것을 유지한다(공통 → 팀 → 업로드 순) — 같은
    기준이 공통과 팀에 겹치면 공통 쪽을 남긴다. 공통은 팀 선택과 무관하게 항상
    포함되고, 팀·업로드는 없으면(None) 건너뛴다.

    `no` 는 **파일 안에서만** 유일하다. 합치면 공통 16번과 팀 16번이 나란히 서는데
    (실측: ai-test-cert-1 은 16 도 13 도 겹친다), 검토 파이프라인은 no 를 열쇠로
    판정과 지적을 나눠 준다 — 겹치면 한쪽 기준의 판정이 다른 쪽에 얹힌다. 그래서
    뒤에 오는 층의 번호에 층 이름을 달아 갈라 놓는다. 번호는 화면에 그대로 보이는
    값이라 지우거나 다시 매기지 않는다 — "16(팀별)" 이면 원본 16번을 되짚을 수 있다.
    """
    out: list[Criterion] = []
    seen: set[str] = set()
    used_no: set[str] = set()
    for preset in (common, team, upload):
        if preset is None:
            continue
        for c in preset.items:
            key = c.text.strip()
            if key in seen:
                continue
            seen.add(key)
            no = str(c.no or "")
            if no and no in used_no:
                no = f"{no}({preset.scope})"
            used_no.add(no)
            # 층을 찍는다 — 합친 뒤에도 "이 기준이 어디서 왔나"를 화면이 말할 수
            # 있게. 특히 업로드는 검토자가 고른 층이라 출처 표시가 의미를 갖는다.
            out.append(replace(c, no=no, layer=preset.scope))
    return out


def compose_review_preset(seed_dir, uploaded: Preset | None,
                          team: str | None = None) -> Preset:
    """검토에 적용할 프리셋 하나 = 공통 ∪ 팀 ∪ 업로드.

    seed_dir 의 씨앗(공통·팀별)을 읽어 고른 팀·업로드와 합친다. 씨앗이 없으면
    업로드만(하위호환). review_document_by_criteria 는 .items 를 받으므로 합친
    items 를 담은 Preset 하나를 돌려준다.

    팀은 **id(파일명) 또는 team 값** 어느 쪽으로도 찾는다. 둘이 다른 파일이 있다
    (`ai-test-cert-1.yaml` 의 team 은 "AI시험인증1팀"). API 와 화면은 id 를 쓰는데
    team 값으로만 찾으면 그 팀 기준이 조용히 안 붙어 공통 기준만으로 검토한다 —
    "기준을 골랐는데 안 걸렸다"가 되고, 그건 이 프로젝트가 계속 막으려던
    조용한 0건이다.
    """
    seeds = load_presets(seed_dir)
    common = next((p for p in seeds if p.scope == "공통"), None)
    team_preset = None
    if team:
        team_preset = next(
            (p for p in seeds if p.scope == "팀별" and team in (p.id, p.team)), None)
    items = resolve_criteria(common, team_preset, uploaded)
    name = uploaded.name if uploaded else (team or "검토")
    return Preset(id="검토", name=name, source_filename="", registered_at="",
                  items=items, item_count=len(items), scope="업로드", team=team or "")

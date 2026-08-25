"""파서가 문서의 표를 어떤 `| 칸 | 칸 |` 줄로 읽는지 그대로 찍는다.

칸 값 검사가 "비어 있습니다"·"찾지 못했습니다" 를 낼 때, 문서가 잘못인지 기준의
labels·at 이 표 모양과 어긋난 것인지는 **파서가 본 줄**을 봐야 갈린다. 추측으로
엔진을 고치면 진짜 지적까지 같이 사라진다(실측: 여백 칸을 건너뛰게 했더니
`| 작성자 : |  | Date : |` 에서 안 채운 칸이 조용히 통과했다).

문서는 로컬에서만 읽고 화면에만 찍는다 — 아무 데도 보내지 않는다.

    uv run python scripts/dump_fields.py "<문서 경로>" [찾을 라벨 ...]

라벨을 주면 그 라벨이 있는 줄과 추출 결과만, 안 주면 표 전체를 찍는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modules.doc_parser import load_document, normalize  # noqa: E402
from modules.doc_parser.fields.extract import (  # noqa: E402
    FieldSpec,
    _squash,
    _tables,
    extract_fields,
)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    path = Path(argv[0])
    if not path.exists():
        print(f"파일이 없습니다: {path}")
        return 2
    labels = argv[1:]

    doc = normalize(load_document(path))
    tables = _tables(doc)
    print(f"# {path.name} — 표 {len(tables)}개\n")

    for table in tables:
        hits = [
            i for i, row in enumerate(table.rows)
            if not labels or any(_squash(label) in _squash(cell)
                                 for cell in row for label in labels)
        ]
        if not hits:
            continue
        print(f"## 표{table.no} ({len(table.rows)}행)")
        # 라벨을 준 경우 그 줄 앞뒤 한 줄까지 — 값이 아래 칸에 있는 표를 보려면 필요하다.
        show = sorted({j for i in hits for j in (i - 1, i, i + 1)
                       if 0 <= j < len(table.rows)})
        last = -1
        for i in show:
            if last >= 0 and i > last + 1:
                print("   …")
            cells = " | ".join(f"[{c}]" for c in table.rows[i])
            print(f"  {i + 1}행: {cells}")
            last = i
        print()

    if labels:
        print("# 지금 기준으로 뽑으면")
        specs = [FieldSpec(name=label, labels=(label,)) for label in labels]
        for name, got in extract_fields(doc, specs).items():
            if not got.found:
                print(f"  {name}: 못 찾음 (라벨이 문서와 다릅니다)")
            else:
                state = "비어 있음" if not _squash(got.value or "") else repr(got.value)
                print(f"  {name}: {state}  @{got.anchor.section}")
        print("\n  값이 라벨의 **오른쪽 칸**이 아니라 아래 칸에 있으면 기준에 at: below,")
        print("  라벨 글자가 다르면 labels 를 문서에 맞게 고칩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""체크 결과 → CSV.

실무가 "복사 가능한 형태로 엑셀에 넣어놓고 수식으로 매핑"하는 방식이라 CSV 면
충분하다. xlsx 네이티브 생성은 의존성이 늘어나므로 필요해지면 그때 한다.
"""
from __future__ import annotations

import csv
import io

from .models import Preset

# 판정하지 않은 항목의 표기. 빈칸으로 두면 "봤는데 적을 게 없었다"로 읽힌다.
UNJUDGED = "미판정"

HEADER = ("번호", "분류", "항목", "판정", "이유")


def to_csv(checklist: Preset, results: dict[str, dict]) -> str:
    """체크리스트의 **모든** 항목을 내보낸다.

    판정한 것만 내보내면 받아 본 사람은 그게 전부라고 읽는다 — 안 본 항목이
    조용히 사라지는 것이 이 기능에서 가장 위험한 실패다.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for i, item in enumerate(checklist.items):
        # 결과는 no 가 아니라 항목의 위치(i)로 찾는다 — no 는 등록 시 선택하지
        # 않으면 전부 "" 이고, 구간별로 1,2,3 을 재사용하면 겹친다. no 를 키로
        # 쓰면 같은 no 를 가진 다른 항목의 판정이 뒤섞여 버린다.
        got = results.get(str(i)) or {}
        verdict = got.get("verdict") or UNJUDGED
        writer.writerow([item.no, item.group, item.text,
                         verdict, got.get("reason", "")])
    return buf.getvalue()

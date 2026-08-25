"""원본 PDF에 지적을 형광펜으로 표시한다.

에너지인프라실이 PDF를 주로 쓴다. hwpx는 브라우저로도 렌더가 안 되고 원본에
표시할 방법도 사실상 없지만(OWPML을 손으로 짜야 한다), PDF는 좌표만 알면
표준 주석으로 얹을 수 있다.

좌표는 pdfplumber가 준다. 예전에는 "검토 엔진에는 좌표가 필요 없다(줄 단위로
대조한다)"며 web extra에만 두고 여기서 지연 임포트했다. 그 전제가 바뀌었다 —
엔진이 표 bbox로 쪽을 밴드로 나누고 글자 좌표로 도면 라벨을 묶는다. pdfplumber는
이제 core라 평범하게 임포트한다.

**공백을 통째로 지우고 대조한다.** 한글 PDF는 자간 때문에 한 낱말이 여러 word로
쪼개지는 일이 흔하다("예측 응답시간" → "예 측 응답시간"). 공백을 남긴 채 맞추면
원문에 분명히 있는 인용을 못 찾는다. verify_quotes는 공백을 한 칸으로 누르는
것으로 충분했지만(추출 텍스트끼리의 대조였다), 여기서는 pypdf가 뽑은 인용과
pdfplumber가 본 낱말을 맞춰야 해서 더 세게 눌러야 한다.

못 찾은 인용은 조용히 버리지 않는다. 표시되지 않은 지적을 돌려주고, 화면이
그것을 말한다 — 안 그러면 "PDF에 표시가 없다 = 문제가 없다"로 읽힌다.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight, Text
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

from .pdf_summary import FontMissing, find_font, number_overlay, summary_pdf

# 심각도 → 형광펜 색. 화면의 SEV 팔레트와 같은 계열이다.
_COLOR = {
    "major": "ffa94d",
    "minor": "ffd43b",
    "info": "74c0fc",
}


@dataclass
class Marked:
    pdf: bytes
    marked: int = 0
    # 표시하지 못한 지적. [{id, message, reason}]
    unmarked: list[dict] = field(default_factory=list)
    # 요약 페이지를 넣었나. 한글 폰트가 없으면 못 넣는다 — 조용히 빠지면
    # 사용자는 그런 페이지가 있다는 것도 모른다.
    summary: bool = False
    # 표시본 앞에 삽입된 요약 페이지 수. 화면이 지적 page로 점프할 때 이만큼 민다.
    summary_pages: int = 0
    # 지적 id → 지면에 찍힌 번호("1", "1, 2"). 화면이 카드에 같은 번호를 달아
    # "3번 지적"이 표시본과 화면에서 같은 것을 가리키게 한다. 번호는 형광펜에
    # 매달리므로 근거가 없거나 본문에서 못 찾은 지적은 여기 없다.
    numbers: dict[str, str] = field(default_factory=dict)
    note: str = ""


def _squash(text: str) -> str:
    """공백을 전부 지운다. 자간으로 쪼개진 낱말까지 맞추려면 이 수준이어야 한다.

    파이프(|)도 지운다 — 파서가 표 행을 `| 셀 | 셀 |` 로 직렬화해서 표에서 나온
    인용에는 |가 섞이는데, PDF 텍스트 레이어에는 그 글자가 없다. 안 지우면 표
    인용은 전부 unlocated 로 떨어져 "이 인용이 문서 어디인지" 를 영영 못 짚는다
    (실측: `| LIST OF TABLES |`). 색인(_page_index)과 바늘이 같은 함수를 쓰므로
    지우는 쪽도 짝이 맞는다.
    """
    return "".join(str(text or "").split()).replace("|", "")


def _page_index(words: list[dict]) -> tuple[str, list[int]]:
    """페이지의 모든 낱말을 공백 없는 한 줄로 잇고, 글자마다 어느 낱말인지 남긴다."""
    chars: list[str] = []
    owner: list[int] = []
    for i, w in enumerate(words):
        for ch in _squash(w.get("text", "")):
            chars.append(ch)
            owner.append(i)
    return "".join(chars), owner


def _quads(words: list[dict], page_height: float) -> tuple[list[float], list[float]]:
    """낱말들의 상자 → (quad_points, 전체 rect).

    pdfplumber는 위에서 아래로(top) 재고 PDF 주석은 아래에서 위로(y) 잰다.
    같은 줄끼리 묶어 줄마다 사각형 하나를 만든다 — 두 줄에 걸친 인용도 각 줄이
    제 모양대로 칠해진다.
    """
    lines: dict[int, list[dict]] = {}
    for w in words:
        # top이 1pt 안쪽으로 다른 낱말은 같은 줄로 본다(자간·기울기 보정).
        key = int(round(float(w["top"])))
        lines.setdefault(key, []).append(w)

    quads: list[float] = []
    x0s, y0s, x1s, y1s = [], [], [], []
    for key in sorted(lines):
        row = lines[key]
        x0 = min(float(w["x0"]) for w in row)
        x1 = max(float(w["x1"]) for w in row)
        top = min(float(w["top"]) for w in row)
        bottom = max(float(w["bottom"]) for w in row)
        y1 = page_height - top      # 위쪽 모서리
        y0 = page_height - bottom   # 아래쪽 모서리
        # quad 순서: 좌상, 우상, 좌하, 우하 (PDF 스펙)
        quads += [x0, y1, x1, y1, x0, y0, x1, y0]
        x0s.append(x0)
        x1s.append(x1)
        y0s.append(y0)
        y1s.append(y1)

    rect = [min(x0s), min(y0s), max(x1s), max(y1s)]
    return quads, rect


#: 라벨을 뗀 값만으로 다시 찾을 때 요구하는 최소 길이. 짧은 값(`1.0`)은 문서
#: 아무 데나 있어 엉뚱한 곳에 형광펜을 얹는다 — 그건 형광펜이 없는 것보다 나쁘다.
#: 근거 판정의 문턱(_MIN_QUOTE = 4)보다 높게 잡는다: 저기는 "지적을 살릴지"이고
#: 여기는 "어디에 표시할지"라, 잘못 짚는 대가가 더 크다.
_MIN_VALUE_RETRY = 6


def _label_stripped(quote: str) -> str:
    """`라벨 | 값` 에서 값만. 그 꼴이 아니거나 값이 너무 짧으면 "".

    칸 값 검사와 문서 간 대조는 인용을 `f"{라벨} | {값}"` 으로 만든다
    (agent_trace/field_match.py). **세로 표**(라벨 오른쪽이 값)에서는 PDF 에도 둘이
    나란히 있어 붙여서 찾힌다. 그런데 **가로 표**(라벨 행 / 값 행, 팀 기준의
    `at: below`)에서는 PDF 에서 라벨 다음에 오는 것이 옆 칸 라벨이라 `라벨+값`
    이라는 문자열이 문서에 존재하지 않는다.

    실측(을지, SST-K-TI-03-04): `at: below` 인 필드 4개(의뢰번호·성적서번호·
    시험기간·의뢰기관명)가 **전부** 위치를 못 찾았고, `at: right` 인 2개는 전부
    찾았다. 을지는 주요 필드가 거의 below 라 형광펜이 사실상 하나도 안 떴다.
    """
    if "|" not in quote:
        return ""
    value = quote.rsplit("|", 1)[-1].strip()
    if len(_squash(value)) < _MIN_VALUE_RETRY:
        return ""
    return value


def _find(quote: str, index: tuple[str, list[int]], words: list[dict]) -> list[dict] | None:
    """인용문의 위치. 못 찾으면 라벨을 떼고 값만으로 한 번 더 본다.

    순서가 중요하다 — 라벨까지 붙은 쪽을 **먼저** 찾는다. 그래야 같은 값이 여러 번
    나오는 문서에서 제 칸을 짚는다(`1.0` 이 날짜 `2026. 01. 02.` 보다 먼저 걸리는
    것을 막으려고 라벨을 붙였다). 재시도는 그 방어가 통하지 않는 가로 표에서만
    실제로 쓰인다.
    """
    haystack, owner = index
    for candidate in (quote, _label_stripped(quote)):
        needle = _squash(candidate)
        if not needle:
            continue
        at = haystack.find(needle)
        if at < 0:
            continue
        first, last = owner[at], owner[at + len(needle) - 1]
        return words[first:last + 1]
    return None


def _boxes(words: list[dict], page_height: float) -> list[tuple[float, float, float, float]]:
    """낱말들 → 줄마다 사각형 하나. PDF 사용자 공간(왼쪽 아래 원점).

    화면 오버레이는 줄마다 상자가 따로 있어야 한다. 두 줄 인용을 감싸는 큰
    사각형 하나로 칠하면 첫 줄 끝과 둘째 줄 시작 사이 여백까지 덮는다.
    """
    lines: dict[int, list[dict]] = {}
    for w in words:
        key = int(round(float(w["top"])))   # top 1pt 안쪽은 같은 줄
        lines.setdefault(key, []).append(w)
    out: list[tuple[float, float, float, float]] = []
    for key in sorted(lines):
        row = lines[key]
        x0 = min(float(w["x0"]) for w in row)
        x1 = max(float(w["x1"]) for w in row)
        top = min(float(w["top"]) for w in row)
        bottom = max(float(w["bottom"]) for w in row)
        out.append((x0, page_height - bottom, x1, page_height - top))
    return out


# 원본 크기와 PDF 안 크기가 정확히 같지 않다. LibreOffice 가 리샘플하면서 한두 픽셀이
# 어긋난다 — 실측: 515→514, 388→387, 1410→1397(0~1%). 2% 면 그 흔들림을 담는다.
_SIZE_TOLERANCE = 0.02
# 균일 축소도 한다 — 실측: 1563x925 → 1438x851(배율 0.920/0.920),
# 2091x302 → 1772x256(0.848/0.848). 크기는 크게 달라지지만 **종횡비는 남는다.**
_RATIO_TOLERANCE = 0.01


def match_images(pdf, images: list[dict]) -> dict[int, dict]:
    """{그림 번호: {"page": 1-based, "rect": [x0,y0,x1,y1]}}. 못 짝지으면 빼놓는다.

    문서의 그림 N 이 뷰어용 PDF 의 어느 이미지인지 알아야 형광펜을 얹을 수 있다.
    **순서만으로는 못 짝짓는다** — LibreOffice 가 도형을 이미지로 렌더해 개수가
    어긋나는 문서가 있다(실측: 파싱 6장 vs PDF 7장). 그 여분이 중간에 끼면 뒤쪽
    그림이 한 칸씩 밀린다.

    두 단계로 짝짓는다.

    1) **크기**(2% 안). 강한 신호다. 대부분 여기서 붙는다.
    2) 남은 것을 **종횡비**(1% 안)로. LibreOffice 가 균일 축소한 경우다 — 크기는
       8~15% 줄어도 비율은 남는다. 실측으로 이 단계가 3장을 더 붙였고, 그중 하나는
       눈으로 확인했다(같은 SURESOFT 로고가 30% 크기로 들어가 있었다).

    같은 값이 여럿이면 쪽·위 순서로 앞것부터 쓴다. 짝이 없으면 **빼놓는다** —
    엉뚱한 곳에 형광펜을 얹는 것보다 안 얹는 편이 낫다.
    """
    slots: list[dict] = []
    for pno, page in enumerate(pdf.pages, 1):
        height = float(page.height)
        for im in sorted(page.images, key=lambda i: (i.get("top") or 0)):
            size = im.get("srcsize")
            if not size or not (size[0] and size[1]):
                continue
            slots.append({
                "page": pno,
                # pdfplumber 의 top 은 위에서 재고, PDF 좌표는 아래에서 잰다.
                "rect": [float(im["x0"]), height - float(im["bottom"]),
                         float(im["x1"]), height - float(im["top"])],
                "w": int(size[0]), "h": int(size[1]), "used": False,
            })

    sized = [(int(m["no"]), int(m.get("width") or 0), int(m.get("height") or 0))
             for m in images]
    sized = [(no, w, h) for no, w, h in sized if w and h]
    out: dict[int, dict] = {}

    def take(no: int, slot: dict) -> None:
        slot["used"] = True
        out[no] = {"page": slot["page"], "rect": slot["rect"]}

    # 1단계 — 크기
    for no, w, h in sized:
        for slot in slots:
            if slot["used"]:
                continue
            if (abs(slot["w"] - w) / w <= _SIZE_TOLERANCE
                    and abs(slot["h"] - h) / h <= _SIZE_TOLERANCE):
                take(no, slot)
                break

    # 2단계 — 종횡비(균일 축소)
    for no, w, h in sized:
        if no in out:
            continue
        want = w / h
        for slot in slots:
            if slot["used"]:
                continue
            if abs(slot["w"] / slot["h"] - want) / want <= _RATIO_TOLERANCE:
                take(no, slot)
                break
    return out


def locate(pdf_bytes: bytes, findings: list[dict],
           images: list[dict] | None = None) -> dict:
    """인용문이 PDF 어디에 있는지 좌표로 돌려준다. PDF를 만들지 않는다.

    화면 뷰어가 지적 위치로 스크롤하고 형광펜을 얹는 데 쓴다. annotate가 좌표를
    알고도 PDF 안에만 남겨서, 화면은 체커가 주장한 쪽으로 점프했다 — 실측 39건 중
    5건이 그래서 엉뚱한 쪽으로 갔다. 여기서는 실제로 찾아낸 쪽·좌표를 밖으로 낸다.

    반환(모든 쪽 번호 1-based, rect 는 PDF 사용자 공간 줄 단위 상자):
      {pages, items:[{id, no, page, sev, marks:[{page, rect:[x0,y0,x1,y1]}]}], unlocated:[...]}

    images(번호·원본 크기)를 주면 **그림 설명에서 나온 근거**도 짚는다. 그 설명은
    파싱 본문에만 있고 PDF 텍스트 레이어에는 없어서(거기엔 이미지가 있다) 인용문으로는
    영원히 못 찾는다 — 근거의 image_no 를 보고 그림 자체에 사각형을 얹는다.
    """
    items: list[dict] = []
    unlocated: list[dict] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        image_marks = match_images(pdf, images or [])
        cache: dict[int, tuple[list[dict], tuple[str, list[int]], float]] = {}

        def page_data(pno: int):
            if pno not in cache:
                page = pdf.pages[pno]
                words = page.extract_words(use_text_flow=True)
                cache[pno] = (words, _page_index(words), float(page.height))
            return cache[pno]

        # 인용 → 좌표. **번호가 아니라 위치만** 공유한다(같은 글자를 두 번 뒤지지
        # 않으려는 캐시다).
        #
        # 예전에는 번호까지 공유했다. 한 낱말을 여러 지적이 각각 근거로 대는 일이
        # 흔해서다 — 실측(SKN56 RVVR): `운영파일` 하나를 세 지적이 물었다(용어 혼용
        # ·띄어쓰기·표기 불일치). 그러면 카드 번호가 `36, 29` 처럼 겹쳐 보이고,
        # 형광펜을 눌렀을 때 어느 카드로 갈지가 안 정해지며, 반영 확인에서 하나를
        # 정리해도 그 자리가 안 지워진다. 지적마다 제 번호를 준다.
        seen: dict[str, list[dict]] = {}
        next_no = 1
        for f in findings:
            marks: list[dict] = []
            nums: list[int] = []
            # 인용별 번호(evidence 와 같은 순서, 못 찾은 인용은 None). 카드가
            # "이 인용이 몇 번 형광펜인가"를 달 수 있게 — 같은 절의 인용이 둘이면
            # (실측: '운영권 조정'/'운영권조정' 모순) 번호 없이는 둘째를 못 찾는다.
            quote_nos: list[int | None] = []
            for e in (f.get("evidence") or []):
                quote = e.get("quote") or ""
                key = _squash(quote)
                if key and key in seen:
                    no = next_no
                    next_no += 1
                    nums.append(no)
                    quote_nos.append(no)
                    marks.extend([{**b, "no": no} for b in seen[key]])
                    continue
                # 본문 밖에서 나온 근거(머릿말·꼬리말)는 **찾지 않는다.** 파서가
                # 본문에서 빼고 meta 로 옮긴 글이라, 본문을 뒤지면 우연히 같은
                # 글자가 있는 곳을 짚는다 — 실측(제출물 확인증)에서 머릿말의
                # `제출물 확인증` 이 본문 표의 같은 글자에 형광펜을 얹어 문서
                # 제목이 지적받은 것처럼 보였다.
                if e.get("source"):
                    unlocated.append({
                        "id": f.get("id"), "message": f.get("message"),
                        "quote": quote,
                        "reason": f"이 근거는 {e['source']}에서 나왔습니다 — "
                                  "본문이 아니라 뷰어에서 짚을 자리가 없습니다.",
                    })
                    quote_nos.append(None)
                    continue
                hit = None
                for pno in _candidate_pages(e, f, len(pdf.pages)):
                    words, index, height = page_data(pno)
                    found = _find(quote, index, words)
                    if found:
                        hit = (pno, found, height)
                        break
                if hit is None:
                    # 그림 설명에서 나온 근거면 그림 자체를 짚는다. 짝을 못 지었으면
                    # (크기로도 종횡비로도 못 찾았으면) 아래로 떨어져 unlocated 가
                    # 된다 — 엉뚱한 곳에 얹지 않는다.
                    at = image_marks.get(e.get("image_no")) if e.get("image_no") else None
                    if at:
                        no = next_no
                        next_no += 1
                        boxes = [{"page": at["page"], "rect": list(at["rect"])}]
                        if key:
                            seen[key] = boxes
                        these = [{**b, "no": no} for b in boxes]
                        nums.append(no)
                        quote_nos.append(no)
                        marks.extend(these)
                        continue
                    unlocated.append({
                        "id": f.get("id"), "message": f.get("message"),
                        "quote": quote,
                        "reason": ("이 근거는 그림 설명에서 나왔지만 뷰어 PDF 에서 그 "
                                   "그림을 찾지 못했습니다." if e.get("image_no")
                                   else "이 인용을 PDF 본문에서 찾지 못했습니다."),
                    })
                    quote_nos.append(None)
                    continue
                pno, found, height = hit
                no = next_no
                next_no += 1
                # 마크마다 **자기 번호**를 단다. 예전에는 지적에만 `"1, 2, 3"` 을
                # 달아, 뷰어가 첫 형광펜에만 `1` 을 그리고 나머지 둘은 번호 없이
                # 칠해졌다 — 카드는 셋이라는데 문서엔 하나만 보였다.
                boxes = [{"page": pno + 1, "rect": list(b)}
                         for b in _boxes(found, height)]
                if key:
                    seen[key] = boxes
                these = [{**b, "no": no} for b in boxes]
                nums.append(no)
                quote_nos.append(no)
                marks.extend(these)
            items.append({
                "id": f.get("id"),
                "no": ", ".join(str(n) for n in dict.fromkeys(nums)) or None,
                # 실제로 찾아낸 쪽(첫 마크). 체커가 주장한 쪽이 아니다.
                "page": marks[0]["page"] if marks else None,
                "sev": f.get("sev", "info"),
                "marks": marks,
                "quote_nos": quote_nos,
            })
        return {"pages": len(pdf.pages), "items": items, "unlocated": unlocated}


def annotate(pdf_bytes: bytes, findings: list[dict],
             doc_name: str = "", brand: str = "문서 검토") -> Marked:
    """PDF 원본 + 지적 → 형광펜·번호·요약 페이지가 얹힌 PDF.

    findings는 to_ui_review_payload가 낸 모양 그대로다
    ({id, sev, message, section, page, evidence: [{quote, page}]}).
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)

    result = Marked(pdf=b"", marked=0)
    items: list[dict] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # 페이지별 낱말 색인은 비싸다. 필요한 페이지만, 한 번만 만든다.
        cache: dict[int, tuple[list[dict], tuple[str, list[int]], float]] = {}

        def page_data(pno: int):
            if pno not in cache:
                page = pdf.pages[pno]
                words = page.extract_words(use_text_flow=True)
                cache[pno] = (words, _page_index(words), float(page.height))
            return cache[pno]

        # 같은 문장을 두 번 칠하지 않는다. 표현 점검(consistency)과 일관성 agent가
        # 같은 불일치를 각각 찾아 같은 근거를 대는 일이 흔하다 — 그대로 얹으면
        # 형광펜이 겹쳐 색만 진해지고, 뷰어에서 주석 두 개가 포개진다.
        #
        # 다만 번호는 인용에 매단다. 두 지적이 같은 인용을 근거로 들면 요약에서
        # 둘 다 같은 번호를 가리킨다 — 뒤에 온 지적이 번호 없는 고아가 되지 않는다.
        # 인용 → (번호, 쪽). 쪽도 함께 기억한다 — 뒤에 온 지적이 같은 인용을
        # 근거로 들면 번호뿐 아니라 위치도 물려받아야 요약에 쪽이 뜬다.
        numbers: dict[str, tuple[int, int]] = {}
        labels: dict[int, list[tuple[int, float, float, str]]] = {}
        next_no = 1

        for f in findings:
            evidence = f.get("evidence") or []
            mine: list[int] = []
            # 지적이 실제로 앉은 쪽. PDF의 절 id는 쪽 기반이라 §0처럼 쓸모없이
            # 나온다 — 형광펜이 찍힌 쪽을 그대로 쓰는 편이 검토자에게 유용하다.
            first_page: int | None = None

            for e in evidence:
                quote = e.get("quote") or ""
                key = _squash(quote)
                if key and key in numbers:
                    no, pg = numbers[key]
                    mine.append(no)
                    if first_page is None:
                        first_page = pg
                    continue
                pages = _candidate_pages(e, f, len(pdf.pages))
                hit = None
                for pno in pages:
                    words, index, height = page_data(pno)
                    found = _find(quote, index, words)
                    if found:
                        hit = (pno, found, height)
                        break

                if hit is None:
                    result.unmarked.append({
                        "id": f.get("id"), "message": f.get("message"),
                        "quote": quote,
                        "reason": "이 인용을 PDF 본문에서 찾지 못했습니다.",
                    })
                    continue

                pno, found, height = hit
                quads, rect = _quads(found, height)
                sev = f.get("sev", "info")
                annot = Highlight(
                    rect=tuple(rect),
                    quad_points=ArrayObject([FloatObject(v) for v in quads]),
                    highlight_color=_COLOR.get(sev, "ffd43b"),
                    printing=True,
                )
                # Acrobat·한컴에서 형광펜을 누르면 지적이 뜬다. 다만 크롬 기본
                # 뷰어는 이 팝업의 한글을 못 찍는다 — 그래서 요약 페이지를 따로
                # 그린다(pdf_summary). 팝업은 그것대로 쓰는 사람이 있으니 남긴다.
                annot[NameObject("/Contents")] = TextStringObject(
                    f"[{sev}] {f.get('message', '')}")
                annot[NameObject("/T")] = TextStringObject(brand)
                writer.add_annotation(page_number=pno, annotation=annot)

                no = next_no
                next_no += 1
                numbers[key] = (no, pno + 1)
                mine.append(no)
                if first_page is None:
                    first_page = pno + 1
                # 번호표는 형광펜 왼쪽에. rect는 아래에서 잰 좌표라 위에서 잰 값으로 돌린다.
                labels.setdefault(pno, []).append((no, rect[0], height - rect[3], sev))
                result.marked += 1

            # 근거가 여럿이면 번호도 여럿이다("1, 2"). 하나만 보여주면
            # 나머지 형광펜은 요약에서 짝을 잃는다.
            no = ", ".join(str(n) for n in dict.fromkeys(mine)) or None
            # 화면 카드도 같은 번호를 달 수 있게 id로 되짚을 표를 남긴다.
            fid = f.get("id")
            if no and fid:
                result.numbers[str(fid)] = no

            items.append({
                "no": no,
                "sev": f.get("sev", "info"),
                "page": first_page or f.get("page"),
                "section": f.get("section"),
                "message": f.get("message", ""),
                "quotes": [e.get("quote", "") for e in evidence],
                "suggestion": f.get("suggestion", ""),
            })

        _draw(writer, labels)

    # 요약 페이지를 맨 앞에 붙인다. 크롬 기본 뷰어는 주석 팝업의 한글을 못 찍고,
    # 인쇄하면 팝업은 아예 사라진다 — 지적 내용을 뷰어에 맡기면 안 된다.
    # 지면에 그린 글자는 어디서 열든, 인쇄해도 똑같이 보인다.
    if items:
        try:
            font = find_font()
        except FontMissing as exc:
            result.note = str(exc)
        else:
            size = _page_size(writer.pages[0])
            data = summary_pdf(doc_name or "문서", items, size, font, result.unmarked, brand)
            inserted = 0
            for i, page in enumerate(PdfReader(io.BytesIO(data)).pages):
                writer.insert_page(page, i)
                inserted += 1
            result.summary = True
            result.summary_pages = inserted

    # 요약을 못 넣었을 때만 옛 방식(1쪽 메모)으로 알린다. 조용히 넘기면
    # "표시가 없다 = 이상 없다"로 읽힌다.
    if result.unmarked and not result.summary and len(writer.pages) > 0:
        lines = "\n".join(f"- {u['message']}" for u in result.unmarked[:20])
        more = "" if len(result.unmarked) <= 20 else f"\n… 외 {len(result.unmarked) - 20}건"
        note = Text(
            rect=(10, 10, 30, 30),
            text=(f"{brand} — 아래 지적은 본문에서 위치를 찾지 못해 표시하지 못했습니다. "
                  "이 PDF에 형광펜이 없다고 해서 지적이 없는 것이 아닙니다.\n\n"
                  f"{lines}{more}"),
            open=False,
        )
        note[NameObject("/T")] = TextStringObject(f"{brand} — 표시하지 못한 지적")
        writer.add_annotation(page_number=0, annotation=note)

    out = io.BytesIO()
    writer.write(out)
    result.pdf = out.getvalue()
    return result


def _page_size(page) -> tuple[float, float]:
    box = page.mediabox
    return (float(box.width), float(box.height))


def _draw(writer: PdfWriter, labels: dict[int, list[tuple[int, float, float, str]]]) -> None:
    """형광펜 옆 번호표를 지면에 그린다.

    주석이 아니라 페이지 내용이다 — 뷰어가 주석을 안 그려도, 인쇄를 해도 남는다.
    번호는 숫자라 한글 폰트가 없어도 찍힌다.
    """
    for pno, marks in labels.items():
        page = writer.pages[pno]
        overlay = number_overlay(_page_size(page), marks)
        page.merge_page(PdfReader(io.BytesIO(overlay)).pages[0])


def _candidate_pages(evidence: dict, finding: dict, total: int) -> list[int]:
    """어느 쪽을 뒤질까. 쪽 번호가 있으면 거기부터, 없으면 전부."""
    page = evidence.get("page") or finding.get("page")
    if isinstance(page, int) and 1 <= page <= total:
        # 그 쪽에서 못 찾으면 나머지도 본다 — 추출 단계의 쪽 계산이 어긋날 수 있다.
        rest = [p for p in range(total) if p != page - 1]
        return [page - 1] + rest
    return list(range(total))

"""텍스트 엔진 폴백 게이트: pdf-inspector 한글(CID 폰트) 추출 품질 검증.

대표 문서에서 pdf-inspector 추출 텍스트와 PyMuPDF 추출 텍스트를 비교해,
pdf-inspector 의 한글 추출이 충분한지 판정한다. 실패 시 pdf_backend.TEXT_ENGINE 을
"pymupdf" 로 바꾸면 텍스트 추출만 교체되고 라우팅 구조는 유지된다.

**측정 대상은 `extract_pages_markdown()` 이다** — 본선(`pdf_backend._parse_pdf_in`)이
실제로 쓰는 API 와 같은 것을 재야 하기 때문이다. 예전에는 `extract_text()`(문서 전체 평문)
를 쟀는데, 실측(2026-08-06, `99. 일반성적서 예시.pdf`)에서 **같은 문서·같은 라이브러리인데
`extract_text()` 는 한글 2794자를 100% 뽑고(ratio 1.0 PASS) `extract_pages_markdown()` 은
10쪽 중 6쪽을 빈 문자열로 돌려주는** 상황이 나왔다. 게이트가 본선이 안 쓰는 API 를 재고
있어서 본선의 실패를 구조적으로 못 보던 것이다.

판정 기준(휴리스틱):
  - 한글 음절(가-힣) 개수가 PyMuPDF 대비 일정 비율(기본 0.8) 이상이면 PASS
  - PyMuPDF 로는 한글이 나오는데 마크다운은 0자인 페이지는 `empty_md_pages` 로 따로
    집계한다 — 문서 전체 비율만 보면 소수 페이지 실패가 묻히기 때문.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import fitz
import pdf_inspector as pi

_HANGUL = re.compile(r"[가-힣]")


def _hangul_count(s: str) -> int:
    """문자열 내 한글 완성형 음절 개수. pdf-inspector 와 PyMuPDF 추출량을 비교하는 척도."""
    return len(_HANGUL.findall(s or ""))


@dataclass
class GateResult:
    passed: bool
    detail: list[dict]
    ratio: float

    def to_dict(self) -> dict:
        """run_poc.py 콘솔 출력용 요약 dict."""
        return {"passed": self.passed, "ratio": round(self.ratio, 3), "detail": self.detail}


def check_cid_quality(pdf_paths: list[str], min_ratio: float = 0.8) -> GateResult:
    """대표 PDF들에서 pdf-inspector(pi.extract_text) 와 PyMuPDF(fitz) 로 각각 텍스트를
    뽑아 한글 음절 수를 비교한다 — 이것이 "텍스트 엔진 폴백 게이트" 본체.

    호출 흐름: run_poc.py → check_cid_quality() → (FAIL 시) __init__.set_text_engine("pymupdf")
    → pdf_backend.TEXT_ENGINE 전환. pdf-inspector 가 실패해도 PyMuPDF 는 항상 정상
    추출된다는 전제(사전정의 CJK CMap 이슈, README 알려진 이슈 참조)로 폴백 기준을 삼는다.

    비교는 **페이지 단위**로 한다 — 본선이 페이지 단위로 라우팅하므로, 어느 페이지가
    비었는지가 그대로 진단 정보가 된다(`empty_md_pages`).
    """
    detail = []
    tot_pi = tot_mu = 0
    for p in pdf_paths:
        doc = fitz.open(p)
        # PyMuPDF 대조군 — 페이지별
        mu_pages = [(doc[i].get_text("text") or "") for i in range(doc.page_count)]
        doc.close()
        try:
            # 본선(pdf_backend)이 실제로 쓰는 API 로 잰다. pg.page 는 0-indexed.
            md_pages = {pg.page: (pg.markdown or "")
                        for pg in pi.extract_pages_markdown(p).pages}
        except Exception as e:  # noqa
            md_pages = {}
            detail.append({"file": p, "error": str(e)})
        h_pi = sum(_hangul_count(md_pages.get(i, "")) for i in range(len(mu_pages)))
        h_mu = sum(_hangul_count(t) for t in mu_pages)
        # PyMuPDF 로는 한글이 나오는데 마크다운은 0자인 페이지 = 본선이 스캔으로 오인하는 지점
        empty_md = [i for i, t in enumerate(mu_pages)
                    if _hangul_count(t) and not _hangul_count(md_pages.get(i, ""))]
        tot_pi += h_pi
        tot_mu += h_mu
        detail.append({"file": p.split("/")[-1].split("\\")[-1],
                       "hangul_pdfinspector": h_pi, "hangul_pymupdf": h_mu,
                       "ratio": round(h_pi / h_mu, 3) if h_mu else None,
                       "empty_md_pages": empty_md})
    ratio = (tot_pi / tot_mu) if tot_mu else 1.0   # 전체 합산 비율(파일별 비율의 평균이 아님)
    passed = ratio >= min_ratio
    return GateResult(passed, detail, ratio)

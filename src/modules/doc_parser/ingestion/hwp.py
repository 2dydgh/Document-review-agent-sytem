"""구형 한글(.hwp) 로더.

.hwp는 OLE 복합문서 바이너리다(.hwpx는 ZIP+XML이라 다르다). rhwp가 이 바이너리를
직접 읽고 .hwpx로 다시 써주므로, 표·개요 처리가 이미 들어 있는 HwpxLoader에 넘긴다.
.hwpx 쪽 로직은 hwpx.py 참고.

뷰어용 PDF는 convert.to_pdf가 따로 만든다 — 파싱과 뷰잉은 별개 경로다. 예전에는
네이티브 파서가 없어 뷰어용 변환 PDF를 파싱에도 재활용했는데, 그 탓에 페이지 번호와
폼피드(\\x0c)가 본문에 섞이고 문장이 PDF 줄바꿈에서 잘렸다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .base import RawDoc


class HwpParseUnavailable(Exception):
    """rhwp를 쓸 수 없다. 조치 방법을 그대로 띄운다."""


def to_hwpx_bytes(path: Path) -> bytes:
    """.hwp → .hwpx 바이트. rhwp가 없거나 깨져 있으면 조치법을 알려준다."""
    try:
        import rhwp
    except ImportError as exc:  # 대개 휠이 번들한 낡은 freetype 문제다
        raise HwpParseUnavailable(
            f"rhwp를 불러올 수 없습니다({exc}). "
            "설치: uv sync && ./scripts/fix-rhwp-freetype.sh") from exc

    return rhwp.parse(str(path)).to_hwpx_bytes()


class HwpLoader:
    extensions = (".hwp",)

    def load(self, path: Path) -> RawDoc:
        # 지연 import — ingestion 안에서의 순환 import를 피한다.
        from .hwpx import HwpxLoader

        path = Path(path)
        hwpx = to_hwpx_bytes(path)
        with tempfile.TemporaryDirectory(prefix="docreview-hwp-") as tmp:
            out = Path(tmp) / "converted.hwpx"
            out.write_bytes(hwpx)
            raw = HwpxLoader().load(out)

        # source_path는 임시 파일이 아니라 원본이어야 한다 — 리포트가 이 값을 문서
        # 이름으로 쓴다. meta의 format도 실제 입력 형식(hwp)으로 되돌린다.
        #
        # meta["images"] 의 part 는 변환된 hwpx 안의 경로(BinData/…)다. 그 hwpx 는
        # 위 임시 디렉터리와 함께 지워지므로, 그림 바이트가 필요하면 to_hwpx_bytes()
        # 를 다시 불러 ZIP 을 열어야 한다 — 같은 입력에 같은 결과이고 0.1초다.
        # 바이트를 meta 에 담지 않는 이유는 RawDoc 이 JSON 직렬화 가능해야 하기 때문이다.
        return RawDoc(source_path=str(path), text=raw.text,
                      meta={**raw.meta, "format": "hwp", "via": "hwpx"})

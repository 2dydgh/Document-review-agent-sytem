"""파싱된 문서의 그림 바이트를 꺼낸다.

`RawDoc.meta["images"]` 의 `part` 는 ZIP 내부 경로일 뿐이다 — 바이트는 담지 않는다
(RawDoc 은 JSON 직렬화 가능해야 한다). 그림을 실제로 봐야 하는 쪽이 여기로 꺼낸다.

포맷을 아는 것은 doc_parser 의 몫이므로 여기 둔다. **LLM 은 부르지 않는다** —
그림을 해석하는 것은 조립 계층(src/app)이 llm_client 로 하는 일이다.
"""
from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

from .base import RawDoc


class ImageUnavailable(Exception):
    """그림 바이트를 얻을 수 없다. 조용히 빈 값을 주지 않는다 — 그림을 못 읽은
    것과 그림이 비어 있는 것은 다르다."""


def _archive(raw: RawDoc) -> zipfile.ZipFile:
    """그림이 들어 있는 ZIP. .hwp 는 다시 변환해서 만든다."""
    fmt = raw.meta.get("format", "")
    path = Path(raw.source_path)

    if fmt == "hwp":
        # part 가 가리키던 변환본은 임시 디렉터리와 함께 지워졌다. 같은 입력에
        # 같은 결과이고 0.1초라 다시 만드는 편이 바이트를 들고 다니는 것보다 낫다.
        from .hwp import to_hwpx_bytes
        return zipfile.ZipFile(io.BytesIO(to_hwpx_bytes(path)))

    if fmt in ("hwpx", "docx"):
        return zipfile.ZipFile(path)

    raise ImageUnavailable(f"그림을 꺼낼 수 없는 형식입니다: {fmt or '알 수 없음'}")


def image_bytes(raw: RawDoc, part: str) -> bytes:
    """`meta["images"]` 의 part 하나를 바이트로. 없으면 ImageUnavailable."""
    if not part:
        raise ImageUnavailable("part 가 비어 있습니다 (이미지가 없는 도형일 수 있음)")
    try:
        with _archive(raw) as archive:
            return archive.read(part)
    except ImageUnavailable:
        raise
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ImageUnavailable(f"{part}: {exc}") from exc


def iter_images(raw: RawDoc):
    """(meta 항목, 바이트) 를 차례로 낸다. 못 읽은 것은 바이트 자리에 None.

    None 을 건너뛰지 않고 그대로 내는 이유는, 부르는 쪽이 "그림 N 을 못 읽었다"를
    결과에 남길 수 있게 하기 위함이다. 조용히 빼면 그림이 없었던 것처럼 보인다.

    ZIP 은 **한 번만** 연다. 그림마다 열면 .hwp 는 rhwp 파싱을 그림 수만큼
    되풀이한다(그림 4장이면 네 번). 게다가 rhwp 는 Document 를 단일 스레드 모델로
    다루므로(상류 KNOWN_ISSUES) 여러 스레드에서 부르는 것도 피해야 한다.
    """
    metas = raw.meta.get("images") or []
    if not metas:
        return
    try:
        archive = _archive(raw)
    except ImageUnavailable:
        # 형식 자체가 그림을 못 내는 경우다(예: pdf). 하나하나 실패로 낸다 —
        # 조용히 빈 목록을 주면 그림이 없었던 것처럼 보인다.
        for meta in metas:
            yield meta, None
        return

    with archive:
        for meta in metas:
            part = meta.get("part", "")
            if not part:
                yield meta, None          # 이미지가 없는 도형
                continue
            try:
                yield meta, archive.read(part)
            except (KeyError, OSError, zipfile.BadZipFile):
                yield meta, None

def image_size(data: bytes) -> tuple[int, int] | None:
    """이미지 바이트 → (가로, 세로). 모르는 형식이면 None.

    표준 라이브러리만 쓴다(pillow 를 core 의존성으로 올리지 않는다). 이 값은 뷰어용
    PDF 안의 이미지와 문서의 그림을 **짝짓는 열쇠**다 — LibreOffice 가 도형을 이미지로
    렌더해 개수가 어긋나는 문서가 있어(실측: 파싱 6장 vs PDF 7장) 순서만으로는 못 짝짓는다.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])

    if data[:2] == b"\xff\xd8":                     # JPEG: SOF 마커를 찾는다
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return (width, height)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return None

    if data[:2] == b"BM" and len(data) >= 26:      # BMP: 높이는 음수일 수 있다
        width, height = struct.unpack("<ii", data[18:26])
        return (abs(width), abs(height))

    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])

    return None

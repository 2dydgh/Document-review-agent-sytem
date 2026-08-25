from pathlib import Path

import pytest

from modules.doc_parser import RawDoc, UnsupportedFormatError, load_document


def test_load_markdown_returns_rawdoc(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 제목\n본문", encoding="utf-8")
    raw = load_document(p)
    assert isinstance(raw, RawDoc)
    assert "본문" in raw.text
    assert raw.source_path == str(p)


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "d.zip"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        load_document(p)


# (구 test_stub_loader_raises_not_implemented 제거: HwpLoader는 이제 스텁이 아니라
#  H2Orestart로 변환→PDF추출한다. 동작은 tests/test_ingestion_hwp.py 가 커버한다.)

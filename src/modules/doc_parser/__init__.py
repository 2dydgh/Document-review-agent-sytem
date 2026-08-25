"""doc_parser — PDF·Word·HWP를 공통 문서 모델로 변환한다.

파이프라인: load_document(원본 → RawDoc) → normalize(RawDoc → Document) → chunk.
HWP/HWPX/DOCX→PDF 변환은 to_pdf. 다른 모듈은 이 공개 인터페이스만 쓴다.
"""
from __future__ import annotations

from .chunking.chunker import chunk
from .convert import ConvertUnavailable, build_html, to_pdf
from .fields import FieldSpec, FieldValue, TableRow, extract_fields
from .ingestion.base import RawDoc, UnsupportedFormatError, load_document
from .ingestion.docx import DocxLoader
from .ingestion.hwp import HwpLoader
from .ingestion.hwpx import HwpxLoader
from .ingestion.images import ImageUnavailable, image_bytes, iter_images
from .ingestion.pdf_digital import PAGE_BREAK, PdfDigitalLoader
from .ingestion.pdf_ocr import PdfOcrLoader
from .ingestion.text import TextLoader
from .normalize.normalizer import normalize

__all__ = [
    "RawDoc",
    "UnsupportedFormatError",
    "load_document",
    "DocxLoader",
    "HwpLoader",
    "HwpxLoader",
    "image_bytes",
    "iter_images",
    "ImageUnavailable",
    "PdfDigitalLoader",
    "PAGE_BREAK",
    "PdfOcrLoader",
    "TextLoader",
    "normalize",
    "chunk",
    "FieldSpec",
    "FieldValue",
    "TableRow",
    "extract_fields",
    "to_pdf",
    "build_html",
    "ConvertUnavailable",
]

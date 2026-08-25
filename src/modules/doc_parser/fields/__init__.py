"""라벨 기반 필드 추출. 공개 인터페이스만 내보낸다."""
from .extract import FieldSpec, FieldValue, TableRow, extract_fields

__all__ = ["FieldSpec", "FieldValue", "TableRow", "extract_fields"]

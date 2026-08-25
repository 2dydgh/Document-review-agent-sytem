from modules.report import (REVIEW_STAGES, fmt_chars, fmt_chunks,
                                     fmt_findings, fmt_sections, review_stages)


def test_stage_keys_are_the_pipeline_in_order():
    assert [s["key"] for s in REVIEW_STAGES] == [
        "ingestion", "normalize", "chunking", "review", "report"]


def test_formats_are_the_single_source_of_the_wording():
    assert fmt_chars(6180) == "6,180 chars"
    assert fmt_sections(9) == "9 sections"
    assert fmt_chunks(12) == "12 chunks"
    assert fmt_findings(6) == "6 findings"


def test_review_stages_fills_detail_for_every_stage():
    stages = review_stages(chars=6180, sections=9, chunks=12, n_findings=6)
    detail = {s["key"]: s["detail"] for s in stages}
    assert detail["ingestion"] == "6,180 chars"
    assert detail["normalize"] == "9 sections"
    assert detail["chunking"] == "12 chunks"
    assert detail["report"] == "6 findings"
    assert all(s["label"] and s["desc"] for s in stages)

"""DocSuree CLI 진입점."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from modules.doc_parser import UnsupportedFormatError
from modules.report import (
    render_json,
    render_markdown,
    render_review_ui_js,
    render_rtm_json,
    render_rtm_markdown,
    render_ui_js,
    to_ui_payload,
    to_ui_review_payload,
)

from .config import apply_criteria_params, load_config
from .criteria import UnknownTeam, for_single_review
from .orchestrator import review_document, review_documents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsuree",
        description="DocSuree — 문서 일관성 검토 Agent",
    )
    sub = parser.add_subparsers(dest="command")

    review = sub.add_parser("review", help="문서를 검토한다")
    review.add_argument("file", help="검토할 문서 경로")
    review.add_argument("--settings", default="config/settings.toml",
                        help="설정 파일 경로 (기본: config/settings.toml)")
    review.add_argument("--team", default="",
                        help="팀 기준 id (presets/criteria/teams/<id>.yaml). "
                             "안 주면 공통 기준만 적용한다")
    review.add_argument("--out", default=None,
                        help="리포트 출력 파일 경로 (없으면 stdout)")
    review.add_argument("--format", choices=["markdown", "json"],
                        default="markdown", help="출력 형식 (기본: markdown)")
    review.add_argument("--emit-ui", default=None, metavar="PATH",
                        help="결과를 웹 UI가 읽는 JS 파일로 내보낸다 "
                             "(예: web/docreview-review-result.js)")

    compare = sub.add_parser("compare", help="상위/하위 문서의 추적성을 비교한다")
    compare.add_argument("--parent", required=True, help="상위문서 경로 (예: SRS)")
    compare.add_argument("--child", required=True, help="하위문서 경로 (예: SDD)")
    compare.add_argument("--settings", default="config/settings.toml",
                         help="설정 파일 경로 (기본: config/settings.toml)")
    compare.add_argument("--out", default=None,
                         help="리포트 출력 파일 경로 (없으면 stdout)")
    compare.add_argument("--format", choices=["markdown", "json"],
                         default="markdown", help="출력 형식 (기본: markdown)")
    compare.add_argument("--emit-ui", default=None, metavar="PATH",
                         help="결과를 웹 UI가 읽는 JS 파일로 내보낸다 "
                              "(예: web/docreview-result.js)")

    serve = sub.add_parser("serve", help="웹 UI를 로컬 서버로 띄운다")
    serve.add_argument("--settings", default="config/settings.toml",
                       help="설정 파일 경로 (기본: config/settings.toml)")
    serve.add_argument("--host", default="127.0.0.1",
                       help="바인드 주소 (기본: 127.0.0.1, 로컬 전용)")
    serve.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
    return parser


def _emit(findings, source_path, args) -> int:
    if args.format == "json":
        report = render_json(findings, source_path)
    else:
        report = render_markdown(findings, source_path)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


_SEED_DIR = Path(__file__).resolve().parents[2] / "presets" / "criteria"


def _run_review(args) -> int:
    config = load_config(args.settings)
    from .parser_bridge import install_trkim_parser
    install_trkim_parser(config.vlm_base_url, config.vlm_model, config.llm_api_key)
    # 기준 조립은 웹과 같은 함수가 한다(app.criteria). 전에는 여기서 team=None 을
    # 박아 CLI 가 팀 기준을 영영 못 받았고, 같은 문서가 경로마다 다른 결과를 냈다.
    # 배포판에 presets/ 가 없으면(도메인 데이터) 빈 목록이 되고 규칙 검사만 남는다.
    try:
        items, extra, notices = for_single_review(
            _SEED_DIR, args.team, Path(args.file).name)
    except UnknownTeam as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    # 기준이 검사 매개변수(요건 ID 형식 등)를 정한다 — 서버도 같이 한다.
    config = replace(config, review=apply_criteria_params(config.review, items))
    try:
        result = review_document(args.file, config, criteria=items,
                                 extra_checkers=extra)
    except (UnsupportedFormatError, NotImplementedError) as exc:
        print(f"검토할 수 없습니다: {exc}", file=sys.stderr)
        return 2
    result.findings.extend(notices)
    rc = _emit(result.findings, result.source_path, args)
    if args.emit_ui:
        payload = to_ui_review_payload(
            result.findings, result.source_path, images=result.images,
            sections=result.section_count, chunks=result.chunk_count,
            chars=result.char_count, document=result.document)
        Path(args.emit_ui).write_text(render_review_ui_js(payload), encoding="utf-8")
        print(f"UI 데이터를 {args.emit_ui} 에 썼습니다.", file=sys.stderr)
    return rc


def _run_compare(args) -> int:
    config = load_config(args.settings)
    from .parser_bridge import install_trkim_parser
    install_trkim_parser(config.vlm_base_url, config.vlm_model, config.llm_api_key)
    try:
        result = review_documents(args.parent, args.child, config)
    except (UnsupportedFormatError, NotImplementedError) as exc:
        print(f"검토할 수 없습니다: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        report = render_rtm_json(result.rtm, result.findings, result.source_path)
    else:
        report = render_rtm_markdown(result.rtm, result.findings, result.source_path)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.emit_ui:
        payload = to_ui_payload(result.rtm, result.findings, args.parent, args.child)
        Path(args.emit_ui).write_text(render_ui_js(payload), encoding="utf-8")
        print(f"UI 데이터를 {args.emit_ui} 에 썼습니다.", file=sys.stderr)
    return 0


def _run_serve(args) -> int:
    # web은 선택 의존성이다. 없으면 트레이스백 대신 설치법을 알려준다.
    try:
        import uvicorn

        from .server import create_app
    except ImportError as exc:
        print(f"웹 서버 의존성이 없습니다 ({exc.name}). "
              "설치: uv sync --extra web", file=sys.stderr)
        return 2
    app = create_app(settings=args.settings)
    print(f"http://{args.host}:{args.port} 에서 실행 중 (Ctrl+C로 종료)", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "review":
        return _run_review(args)
    if args.command == "compare":
        return _run_compare(args)
    if args.command == "serve":
        return _run_serve(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

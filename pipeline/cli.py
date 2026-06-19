import argparse
import json
from pathlib import Path

from pipeline.lib.venv import ensure_project_venv

ensure_project_venv(module_file=Path(__file__))

from pipeline.lib.env import get_daemon_config, load_env
from pipeline.runner import run_collect, run_pipeline


def main() -> None:
    load_env()
    cfg = get_daemon_config()

    parser = argparse.ArgumentParser(description="devPulse pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect", help="GeekNews RSS 수집")
    collect_parser.add_argument("--limit", type=int, default=20)
    collect_parser.add_argument(
        "--feeds",
        nargs="*",
        default=cfg.feeds,
        help="수집할 피드 유형",
    )
    collect_parser.add_argument("--quiet", action="store_true", help="진행 로그 숨김")
    collect_parser.add_argument("--json", action="store_true", help="결과 JSON 출력")

    run_parser = sub.add_parser("run", help="전체 파이프라인 실행")
    run_parser.add_argument("--limit", type=int, default=cfg.batch_size, help="처리할 글 수")
    run_parser.add_argument("--feeds", nargs="*", default=cfg.feeds)
    run_parser.add_argument("--quiet", action="store_true", help="진행 로그 숨김")
    run_parser.add_argument("--json", action="store_true", help="결과 JSON 출력")

    bundle_parser = sub.add_parser("bundle", help="card_generated 6장 묶어 SNS/영상 생성")
    bundle_parser.add_argument("--quiet", action="store_true")
    bundle_parser.add_argument("--json", action="store_true", help="결과 JSON 출력")

    cleanup_parser = sub.add_parser("cleanup", help="개별(1장) 영상·SNS 삭제")
    cleanup_parser.add_argument("--quiet", action="store_true")
    cleanup_parser.add_argument("--json", action="store_true", help="결과 JSON 출력")

    models_parser = sub.add_parser("models", help="M5 Pro 24GB MLX 모델 프로필 목록")
    models_parser.add_argument("--ram", type=int, default=24, help="통합 메모리 GB (기본 24)")

    dash_parser = sub.add_parser("dashboard", help="웹 대시보드 (로그·카드·번들 영상)")
    dash_parser.add_argument("--host", default=None)
    dash_parser.add_argument("--port", type=int, default=None)

    args = parser.parse_args()
    verbose = not getattr(args, "quiet", False)
    emit_json = getattr(args, "json", False)

    if args.command == "collect":
        result = run_collect(feed_types=args.feeds, limit=args.limit, verbose=verbose)
    elif args.command == "models":
        from pipeline.lib.llm_models import format_profiles_table

        print(format_profiles_table(ram_gb=float(args.ram)))
        return
    elif args.command == "bundle":
        from pipeline.processors.bundle import run_pending_bundles

        result = {"bundles": run_pending_bundles(verbose=verbose)}
    elif args.command == "cleanup":
        from pipeline.processors.cleanup_solo import cleanup_solo_media

        result = cleanup_solo_media(verbose=verbose)
        if emit_json:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return
    elif args.command == "dashboard":
        from pipeline.web.server import run_dashboard

        run_dashboard(host=args.host, port=args.port)
        return
    else:
        result = run_pipeline(limit=args.limit, feed_types=args.feeds, verbose=verbose)

    if emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()

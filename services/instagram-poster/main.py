#!/usr/bin/env python3
import argparse
import logging
import sys

from instagram_poster.config import load_config
from instagram_poster.credentials import format_credential_help, validate_credentials
from instagram_poster.scheduler import Scheduler


def _check_credentials(config) -> int:
  issues = validate_credentials(config)
  if issues:
    for msg in issues:
      logging.error("설정 오류: %s", msg)
    logging.error("%s", format_credential_help())
    return 1

  if config.dry_run:
    logging.info("형식 검증 OK (DRY_RUN=1 — API 호출 생략)")
    return 0

  try:
    from instagram_poster.client import InstagramClient
    from instagram_poster.media_host import publishable_url

    client = InstagramClient(
      access_token=config.access_token,
      ig_user_id=config.ig_user_id,
      app_id=config.app_id,
      graph_version=config.graph_version,
      media_url_for=publishable_url,
      dry_run=False,
    )
    data = client.verify_connection()
    if config.access_token.startswith("IG"):
      api_user_id = str(data.get("user_id", ""))
      if api_user_id and api_user_id != config.ig_user_id:
        logging.warning(
          "IG_USER_ID 불일치: env=%s, API=%s — API 값으로 맞추세요.",
          config.ig_user_id,
          api_user_id,
        )
      logging.info("API 연결 OK — @%s (Instagram Login)", data.get("username"))
    else:
      logging.info("API 연결 OK — @%s (%s)", data.get("username"), data.get("account_type"))
    return 0
  except Exception as exc:
    logging.error("API 연결 실패: %s", exc)
    logging.error("%s", format_credential_help())
    return 1


def main() -> None:
  parser = argparse.ArgumentParser(description="devPulse Instagram 자동 게시")
  parser.add_argument(
    "--once",
    action="store_true",
    help="스케줄 무시, IG_REELS_PER_DAY 만큼 릴스 즉시 업로드 후 종료 (테스트용)",
  )
  parser.add_argument(
    "--check",
    action="store_true",
    help="토큰·App ID 설정만 검증 (업로드 없음)",
  )
  args = parser.parse_args()

  logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
  )
  config = load_config()

  if args.check:
    raise SystemExit(_check_credentials(config))

  issues = validate_credentials(config)
  if issues:
    for msg in issues:
      logging.error("설정 오류: %s", msg)
    logging.error("%s", format_credential_help())
    raise SystemExit(1)

  scheduler = Scheduler(config)
  if args.once:
    scheduler.run_once()
  else:
    scheduler.run_forever()


if __name__ == "__main__":
  main()

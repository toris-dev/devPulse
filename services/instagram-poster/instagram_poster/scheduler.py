import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from instagram_poster.client import InstagramClient, InstagramError
from instagram_poster.config import Config
from instagram_poster.queue import BundleJob, discover_bundles
from instagram_poster.store import StateStore

logger = logging.getLogger(__name__)
KIND = "reel"


def _parse_times(post_times: list[str], tz: ZoneInfo) -> list[tuple[int, int]]:
  parsed: list[tuple[int, int]] = []
  for raw in post_times:
    hour, minute = raw.split(":", 1)
    parsed.append((int(hour), int(minute)))
  return sorted(parsed)


def _slot_index(now: datetime, slots: list[tuple[int, int]]) -> int | None:
  """오늘 지난 슬롯 중 가장 최근 인덱스. 아직 슬롯 전이면 None."""
  current = now.hour * 60 + now.minute
  last_idx = None
  for idx, (h, m) in enumerate(slots):
    if h * 60 + m <= current:
      last_idx = idx
  return last_idx


class Scheduler:
  def __init__(self, config: Config) -> None:
    self.config = config
    self.tz = ZoneInfo(config.timezone)
    self.store = StateStore(config.state_db, config.timezone)
    self.slots = _parse_times(config.post_times, self.tz)
    self.client: InstagramClient | None = None
    self._last_slot_idx: int | None = None
    self._last_slot_day: str | None = None
    jobs = discover_bundles(config.sns_dir, config.output_dir)
    filled = self.store.backfill_content_keys(jobs)
    if filled:
      logger.info("기존 게시 기록 %d건에 content_key 반영", filled)

  def _ensure_client(self) -> InstagramClient:
    if self.client:
      return self.client
    if not self.config.ig_user_id or not self.config.access_token or not self.config.app_id:
      raise InstagramError(
        "IG_USER_ID, IG_ACCESS_TOKEN, IG_APP_ID 가 필요합니다. infra/.env.instagram 를 설정하세요."
      )
    self.client = InstagramClient(
      access_token=self.config.access_token,
      ig_user_id=self.config.ig_user_id,
      app_id=self.config.app_id,
      graph_version=self.config.graph_version,
      media_url_for=self._media_url_for,
      dry_run=self.config.dry_run,
    )
    return self.client

  def _media_url_for(self, path: Path, *, kind: str = "video") -> str:
    from instagram_poster.media_host import publishable_url
    return publishable_url(path, kind=kind)

  def _skip_duplicate_content(self, job: BundleJob) -> bool:
    existing = self.store.find_posted_content(job.content_key, KIND)
    if not existing:
      return False

    self.store.mark_posted(
      job.bundle_id,
      KIND,
      existing.ig_media_id,
      content_key=job.content_key,
    )
    logger.info(
      "중복 릴스 스킵: %s (동일 콘텐츠 → %s, ig=%s)",
      job.bundle_id,
      existing.bundle_id,
      existing.ig_media_id,
    )
    return True

  def _next_job(self) -> BundleJob | None:
    for job in discover_bundles(self.config.sns_dir, self.config.output_dir):
      if self.store.is_posted(job.bundle_id, KIND):
        continue
      if self._skip_duplicate_content(job):
        continue
      return job
    return None

  def _maybe_post(self, limit: int, *, ignore_daily_limit: bool = False) -> bool:
    if not ignore_daily_limit and self.store.count_today(KIND) >= limit:
      return False

    job = self._next_job()
    if not job:
      logger.info("대기 중인 릴스 없음")
      return False

    client = self._ensure_client()
    try:
      logger.info("릴스 업로드: %s", job.bundle_id)
      media_id = client.publish_reel(job.video_path, job.caption)
      self.store.mark_posted(job.bundle_id, KIND, media_id, content_key=job.content_key)
      self.store.increment_today(KIND)
      logger.info("릴스 완료: %s → %s", job.bundle_id, media_id)
      return True
    except Exception as exc:
      logger.error("릴스 실패: %s | %s", job.bundle_id, exc)
      self.store.mark_failed(job.bundle_id, KIND, str(exc))
      return False

  def tick(self) -> None:
    now = datetime.now(self.tz)
    day = now.date().isoformat()
    slot_idx = _slot_index(now, self.slots)

    if slot_idx is None:
      logger.debug("다음 슬롯 대기 중 (%s)", self.config.post_times)
      return

    if self._last_slot_day == day and self._last_slot_idx == slot_idx:
      return

    logger.info(
      "슬롯 %s — 오늘 릴스 %d/%d",
      self.config.post_times[slot_idx],
      self.store.count_today(KIND),
      self.config.reels_per_day,
    )

    posted = self._maybe_post(self.config.reels_per_day)
    if posted or self.store.count_today(KIND) >= self.config.reels_per_day:
      self._last_slot_idx = slot_idx
      self._last_slot_day = day

  def run_once(self) -> None:
    """스케줄 무시 — 릴스 즉시 업로드 후 종료."""
    logger.info("즉시 테스트 업로드 (릴스 %d)", self.config.reels_per_day)
    logger.info(
      "경로: output=%s sns=%s state=%s",
      self.config.output_dir,
      self.config.sns_dir,
      self.config.state_db,
    )
    jobs = discover_bundles(self.config.sns_dir, self.config.output_dir)
    logger.info("번들 큐: %d건 (sns=%s)", len(jobs), self.config.sns_dir)
    if self.config.dry_run:
      logger.info("DRY RUN 모드 — 실제 Instagram 업로드 없음")

    self._maybe_post(self.config.reels_per_day, ignore_daily_limit=True)

  def run_forever(self) -> None:
    logger.info(
      "Instagram poster 시작 — %s 슬롯, 릴스 %d/일, poll %ds",
      ",".join(self.config.post_times),
      self.config.reels_per_day,
      self.config.poll_sec,
    )
    if self.config.dry_run:
      logger.info("DRY RUN 모드 — 실제 업로드 없음")

    while True:
      try:
        self.tick()
      except Exception:
        logger.exception("tick 오류")
      time.sleep(self.config.poll_sec)

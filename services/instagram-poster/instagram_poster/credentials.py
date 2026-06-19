"""Instagram API 자격 증명 검증."""

from __future__ import annotations

import re

from instagram_poster.config import Config

_NUMERIC_ID = re.compile(r"^\d+$")


def validate_credentials(config: Config) -> list[str]:
  """설정 오류 목록. 비어 있으면 형식상 OK (API 검증은 --check)."""
  issues: list[str] = []

  if not config.app_id:
    issues.append("IG_APP_ID 가 비어 있습니다.")
  elif not _NUMERIC_ID.match(config.app_id):
    issues.append(
      f"IG_APP_ID='{config.app_id}' 는 앱 이름입니다. "
      "앱 설정 → 기본 → **앱 ID**(숫자) 를 넣으세요. "
      "Instagram 계정 ID와 다릅니다."
    )

  if not config.ig_user_id:
    issues.append("IG_USER_ID 가 비어 있습니다.")
  elif not _NUMERIC_ID.match(config.ig_user_id):
    issues.append("IG_USER_ID 는 숫자여야 합니다.")

  if not config.access_token:
    issues.append("IG_ACCESS_TOKEN 이 비어 있습니다.")

  return issues


def format_credential_help() -> str:
  return """
토큰은 Meta 콘솔 **Instagram → API 설정** 에서 발급한 것을 쓸 수 있습니다.
(IG... 로 시작해도 됩니다 — Instagram Login 방식)

필수 확인:
1. IG_APP_ID = 앱 설정 → 기본 → **앱 ID** (Instagram 계정 ID 아님!)
2. IG_USER_ID = API 설정 화면에 표시된 Instagram 계정 ID
3. IG_ACCESS_TOKEN = API 설정 1단계에서 생성한 토큰
4. 역할 → Instagram 테스터에 본인 계정 추가 (개발 중 필수)
5. 토큰 권한에 instagram_content_publish 포함

Facebook 페이지 연결 방식을 쓰는 경우:
- Graph API Explorer → 페이지 액세스 토큰(EAA...) 도 사용 가능

토큰은 1~2시간 후 만료될 수 있습니다. 장기 실행 시 Long-lived 토큰으로 교체하세요.
""".strip()

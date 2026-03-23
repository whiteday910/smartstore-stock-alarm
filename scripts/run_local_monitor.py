#!/usr/bin/env python3
"""
로컬 PC에서 15~20분 간격으로 재고 모니터링을 반복합니다.
집/사무실 IP로 네이버에 접속하므로 GitHub Actions 대비 429 차단이 덜합니다.

사전 준비:
  pip install -r scripts/requirements.txt
  playwright install chromium

실행 (프로젝트 루트에서):
  python scripts/run_local_monitor.py

환경변수: 프로젝트 루트의 .env.local (check_stock.py 와 동일)
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

# scripts 디렉터리를 path 에 넣어 check_stock 모듈 import
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> None:
    import check_stock  # noqa: E402 — dotenv 는 check_stock 로드 시 적용됨

    print("=" * 55)
    print("[로컬 모니터] 시작 — 종료: Ctrl+C")
    print("  • .env.local 의 SUPABASE / Gmail 설정을 사용합니다.")
    print("  • 스크래핑은 이 PC의 네트워크(로컬 IP)로 수행됩니다.")
    print("=" * 55)

    while True:
        try:
            check_stock.main()
        except KeyboardInterrupt:
            print("\n[로컬 모니터] 종료합니다.")
            break
        except Exception as e:
            print(f"[로컬 모니터] 이번 주기 오류 (다음 주기 계속): {e!r}")

        wait_sec = random.randint(15 * 60, 20 * 60)
        m, s = divmod(wait_sec, 60)
        print(f"\n[로컬 모니터] {m}분 {s}초 후 다음 확인...\n")
        time.sleep(wait_sec)


if __name__ == "__main__":
    main()

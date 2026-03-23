"""
스마트스토어 재입고 모니터링 스크립트
GitHub Actions 에서 주기적으로 실행됩니다.
"""

import os
import re
import json
import time
import random
import smtplib
import logging
from datetime import datetime, timezone
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ── 로깅 설정 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 환경변수 ────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
BASE_URL = os.environ.get("BASE_URL", "https://localhost:3000")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ── HTTP 요청 헤더 (봇 감지 우회) ───────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


# ── 재귀 JSON 탐색 헬퍼 ─────────────────────────────────────
def find_value_by_key(data, target_key: str, depth: int = 0):
    """중첩 JSON 에서 특정 키를 재귀적으로 탐색합니다."""
    if depth > 15:
        return None
    if isinstance(data, dict):
        if target_key in data and data[target_key]:
            return data[target_key]
        for v in data.values():
            result = find_value_by_key(v, target_key, depth + 1)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_value_by_key(item, target_key, depth + 1)
            if result is not None:
                return result
    return None


# ── 재고 상태 확인 ───────────────────────────────────────────
def check_stock_status(url: str) -> dict:
    """
    스마트스토어 상품 URL 의 재고 상태를 확인합니다.
    반환값: {"status": "IN_STOCK"|"OUT_OF_STOCK"|"UNKNOWN"|"ERROR", "product_name": str|None}
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        resp = session.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        product_name: Optional[str] = None

        # ── 방법 1: __NEXT_DATA__ JSON 파싱 ──────────────────
        next_data_match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>',
            html,
        )
        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))

                # 상품명 추출
                name_val = find_value_by_key(next_data, "name")
                if name_val and isinstance(name_val, str) and len(name_val) > 1:
                    product_name = name_val

                # statusType 추출: SALE / OUTOFSTOCK / SUSPENSION / CLOSE
                status_val = find_value_by_key(next_data, "statusType")
                if status_val and isinstance(status_val, str):
                    status_val = status_val.upper()
                    logger.info(f"  statusType={status_val}")
                    if status_val == "SALE":
                        return {"status": "IN_STOCK", "product_name": product_name}
                    if status_val in ("OUTOFSTOCK", "SUSPENSION", "CLOSE", "SOLDOUT"):
                        return {"status": "OUT_OF_STOCK", "product_name": product_name}

                # stockQuantity 로 재고 판단 (0이면 품절)
                qty = find_value_by_key(next_data, "stockQuantity")
                if qty is not None:
                    try:
                        if int(qty) > 0:
                            return {"status": "IN_STOCK", "product_name": product_name}
                        else:
                            return {"status": "OUT_OF_STOCK", "product_name": product_name}
                    except (ValueError, TypeError):
                        pass

            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"  __NEXT_DATA__ 파싱 실패: {e}")

        # ── 방법 2: HTML 텍스트 패턴 매칭 (fallback) ─────────
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text()

        # og:title 에서 상품명 추출
        if not product_name:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                product_name = str(og_title["content"])

        # 품절 지표 텍스트
        out_of_stock_signals = [
            "구매하실 수 없는 상품",
            "현재 구매하실 수 없",
            "재입고 시 구매가능",
            "품절",
        ]
        for signal in out_of_stock_signals:
            if signal in page_text:
                logger.info(f"  품절 텍스트 감지: '{signal}'")
                return {"status": "OUT_OF_STOCK", "product_name": product_name}

        # 구매 가능 지표 텍스트
        in_stock_signals = ["구매하기", "장바구니 담기", "바로구매"]
        for signal in in_stock_signals:
            if signal in page_text:
                logger.info(f"  구매 가능 텍스트 감지: '{signal}'")
                return {"status": "IN_STOCK", "product_name": product_name}

        logger.warning(f"  상태를 판별할 수 없습니다.")
        return {"status": "UNKNOWN", "product_name": product_name}

    except requests.exceptions.Timeout:
        logger.error(f"  요청 타임아웃: {url}")
        return {"status": "ERROR", "product_name": None}
    except requests.exceptions.HTTPError as e:
        logger.error(f"  HTTP 오류 {e.response.status_code}: {url}")
        return {"status": "ERROR", "product_name": None}
    except Exception as e:
        logger.error(f"  예상치 못한 오류: {e}")
        return {"status": "ERROR", "product_name": None}


# ── 재입고 알림 이메일 발송 ──────────────────────────────────
def send_restock_email(
    email: str,
    url: str,
    product_name: Optional[str],
    unsubscribe_token: str,
) -> bool:
    product_display = product_name or "모니터링 중이던 상품"
    unsubscribe_url = f"{BASE_URL}/api/unsubscribe/{unsubscribe_token}"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <div style="background: linear-gradient(135deg, #03C75A, #02A449); color: white; padding: 28px; border-radius: 12px 12px 0 0; text-align: center;">
    <div style="font-size: 48px; margin-bottom: 8px;">🎉</div>
    <h1 style="margin: 0; font-size: 22px;">재입고 알림</h1>
  </div>
  <div style="background: #ffffff; padding: 32px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
    <p style="font-size: 17px; font-weight: 600; color: #111; margin-top: 0;">
      기다리시던 상품이 재입고되었습니다!
    </p>
    <p style="color: #555; line-height: 1.7; font-size: 15px;">
      관심 상품 <strong style="color: #03C75A;">{product_display}</strong>이(가)
      재입고되어 지금 구매 가능한 상태입니다.
      재고가 소진되기 전에 빠르게 구매하세요!
    </p>
    <div style="text-align: center; margin: 28px 0;">
      <a href="{url}"
         style="background: #03C75A; color: white; padding: 14px 32px; text-decoration: none;
                border-radius: 8px; font-size: 16px; font-weight: 700; display: inline-block;">
        지금 바로 구매하기 →
      </a>
    </div>
    <div style="background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px;">
      <p style="margin: 0; font-size: 13px; color: #9a3412;">
        ⚡ 인기 상품은 빠르게 품절될 수 있습니다. 서두르세요!
      </p>
    </div>
    <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 20px 0;">
    <p style="font-size: 12px; color: #9ca3af; margin: 0; line-height: 1.6;">
      이 알림은 <strong>{email}</strong>로 발송되었습니다.<br>
      더 이상 알림을 받고 싶지 않다면
      <a href="{unsubscribe_url}" style="color: #9ca3af; text-decoration: underline;">여기</a>를 클릭하여 구독을 취소하세요.
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[재입고 알림] {product_display}이(가) 재입고되었습니다!"
    msg["From"] = f"스마트스토어 재입고 알리미 <{GMAIL_USER}>"
    msg["To"] = email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, email, msg.as_string())
        logger.info(f"  📧 알림 이메일 발송 완료: {email}")
        return True
    except Exception as e:
        logger.error(f"  이메일 발송 실패 ({email}): {e}")
        return False


# ── 메인 로직 ────────────────────────────────────────────────
def main():
    # GitHub Actions cron 은 15분 간격으로 실행되며,
    # 여기서 0~300초(0~5분) 랜덤 딜레이를 추가해 실질적으로 15~20분 간격이 됩니다.
    delay_seconds = random.randint(0, 300)
    logger.info(f"랜덤 딜레이 {delay_seconds}초 대기 중...")
    time.sleep(delay_seconds)

    logger.info("=" * 50)
    logger.info("재고 모니터링 시작")
    logger.info("=" * 50)

    # 활성 모니터 목록 조회
    result = supabase.table("monitors").select("*").eq("is_active", True).execute()
    monitors = result.data

    if not monitors:
        logger.info("활성 모니터가 없습니다. 종료합니다.")
        return

    logger.info(f"활성 모니터 {len(monitors)}개 확인")

    # URL 별로 그룹화 (같은 URL 은 한 번만 요청)
    url_map: dict[str, list[dict]] = {}
    for m in monitors:
        url_map.setdefault(m["url"], []).append(m)

    logger.info(f"고유 URL {len(url_map)}개 확인 예정")

    for i, (url, url_monitors) in enumerate(url_map.items()):
        # URL 간 랜덤 딜레이 (3~10초) - 봇 차단 방지
        if i > 0:
            wait = random.uniform(3, 10)
            logger.info(f"다음 URL 요청 전 {wait:.1f}초 대기...")
            time.sleep(wait)

        logger.info(f"\n[{i+1}/{len(url_map)}] {url}")
        check_result = check_stock_status(url)
        current_status: str = check_result["status"]
        product_name: Optional[str] = check_result.get("product_name")
        now = datetime.now(timezone.utc).isoformat()

        logger.info(f"  결과: {current_status}")

        for monitor in url_monitors:
            prev_status = monitor.get("last_status", "UNKNOWN")
            monitor_id = monitor["id"]

            # 재입고 감지: 이전이 OUT_OF_STOCK 이고 현재 IN_STOCK
            if prev_status == "OUT_OF_STOCK" and current_status == "IN_STOCK":
                logger.info(
                    f"  🎉 재입고 감지! {monitor['email']} 에게 알림 발송 중..."
                )
                sent = send_restock_email(
                    email=monitor["email"],
                    url=url,
                    product_name=product_name or monitor.get("product_name"),
                    unsubscribe_token=monitor["unsubscribe_token"],
                )
                update_data = {
                    "last_status": current_status,
                    "last_checked_at": now,
                    "notified_at": now if sent else monitor.get("notified_at"),
                    "product_name": product_name or monitor.get("product_name"),
                }
            else:
                update_data = {
                    "last_status": current_status,
                    "last_checked_at": now,
                    "product_name": product_name or monitor.get("product_name"),
                }

            # DB 업데이트
            supabase.table("monitors").update(update_data).eq(
                "id", monitor_id
            ).execute()

    logger.info("\n" + "=" * 50)
    logger.info("재고 모니터링 완료")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()

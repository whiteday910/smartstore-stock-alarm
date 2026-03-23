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


# ── HTTP 요청 헤더 (브라우저처럼 보이도록) ─────────────────
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

JSON_HEADERS = {
    "User-Agent": BASE_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://smartstore.naver.com/",
    "Origin": "https://smartstore.naver.com",
    "X-Requested-With": "XMLHttpRequest",
}


# ── 재귀 JSON 탐색 ───────────────────────────────────────────
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


# ── Naver 내부 JSON API 시도 ─────────────────────────────────
def _try_internal_api(product_id: str) -> Optional[dict]:
    """
    Naver SmartStore 내부 API (JSON) 로 상품 상태를 직접 조회합니다.
    HTML 렌더링 없이 더 가볍고 차단 가능성이 낮습니다.
    """
    # 시도할 내부 API 엔드포인트 목록
    endpoints = [
        f"https://smartstore.naver.com/i/v1/products/{product_id}",
        f"https://smartstore.naver.com/main/products/{product_id}.json",
    ]

    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, headers=JSON_HEADERS, timeout=15)
            logger.info(f"  [내부API] {endpoint} → HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            # JSON 응답인지 확인
            content_type = resp.headers.get("content-type", "")
            if "json" not in content_type and not resp.text.strip().startswith("{"):
                continue

            data = resp.json()
            status_type = find_value_by_key(data, "statusType")
            name = find_value_by_key(data, "name")

            if status_type:
                logger.info(f"  [내부API] statusType={status_type}, name={name}")
                status_type = status_type.upper()
                if status_type == "SALE":
                    return {"status": "IN_STOCK", "product_name": name}
                if status_type in ("OUTOFSTOCK", "SUSPENSION", "CLOSE", "SOLDOUT"):
                    return {"status": "OUT_OF_STOCK", "product_name": name}

        except Exception as e:
            logger.debug(f"  [내부API] {endpoint} 실패: {e}")

    return None


# ── HTML 파싱으로 재고 확인 ──────────────────────────────────
def _check_via_html(url: str, session: requests.Session) -> dict:
    resp = session.get(url, timeout=30, allow_redirects=True)
    logger.info(f"  [HTML] HTTP {resp.status_code}, 크기 {len(resp.text):,} bytes")
    logger.info(f"  [HTML] 최종 URL: {resp.url}")

    resp.raise_for_status()
    html = resp.text
    product_name: Optional[str] = None

    # __NEXT_DATA__ 가 없으면 차단/이상 응답으로 판단
    if "__NEXT_DATA__" not in html:
        logger.warning("  [HTML] __NEXT_DATA__ 없음 → 차단 또는 비정상 응답")
        # 그래도 텍스트 패턴은 시도
    else:
        # ── __NEXT_DATA__ JSON 파싱 ──
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>',
            html,
        )
        if match:
            try:
                next_data = json.loads(match.group(1))
                name_val = find_value_by_key(next_data, "name")
                if name_val and isinstance(name_val, str) and len(name_val) > 1:
                    product_name = name_val

                status_val = find_value_by_key(next_data, "statusType")
                if status_val and isinstance(status_val, str):
                    status_val = status_val.upper()
                    logger.info(f"  [HTML] statusType={status_val}")
                    if status_val == "SALE":
                        return {"status": "IN_STOCK", "product_name": product_name}
                    if status_val in ("OUTOFSTOCK", "SUSPENSION", "CLOSE", "SOLDOUT"):
                        return {"status": "OUT_OF_STOCK", "product_name": product_name}

                qty = find_value_by_key(next_data, "stockQuantity")
                if qty is not None:
                    try:
                        q = int(qty)
                        logger.info(f"  [HTML] stockQuantity={q}")
                        if q > 0:
                            return {"status": "IN_STOCK", "product_name": product_name}
                        else:
                            return {"status": "OUT_OF_STOCK", "product_name": product_name}
                    except (ValueError, TypeError):
                        pass

            except json.JSONDecodeError as e:
                logger.warning(f"  [HTML] __NEXT_DATA__ JSON 파싱 실패: {e}")

    # ── 텍스트 패턴 fallback ──
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text()

    if not product_name:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            product_name = str(og["content"])

    out_signals = ["구매하실 수 없는 상품", "현재 구매하실 수 없", "재입고 시 구매가능", "품절"]
    for sig in out_signals:
        if sig in page_text:
            logger.info(f"  [HTML] 품절 텍스트 감지: '{sig}'")
            return {"status": "OUT_OF_STOCK", "product_name": product_name}

    in_signals = ["구매하기", "장바구니 담기", "바로구매"]
    for sig in in_signals:
        if sig in page_text:
            logger.info(f"  [HTML] 구매 가능 텍스트 감지: '{sig}'")
            return {"status": "IN_STOCK", "product_name": product_name}

    logger.warning("  [HTML] 상태 판별 불가 → UNKNOWN 반환")
    return {"status": "UNKNOWN", "product_name": product_name}


# ── 메인 재고 확인 함수 (재시도 포함) ────────────────────────
def check_stock_status(url: str) -> dict:
    """
    여러 방법을 순차적으로 시도하여 재고 상태를 확인합니다.
    1. Naver 내부 JSON API (더 가볍고 차단 가능성 낮음)
    2. HTML 스크래핑 (3회 재시도)
    """
    # ── 방법 1: 내부 JSON API ──
    product_id_match = re.search(r"/products/(\d+)", url)
    if product_id_match:
        result = _try_internal_api(product_id_match.group(1))
        if result:
            logger.info(f"  내부 API 성공: {result['status']}")
            return result

    # ── 방법 2: HTML 스크래핑 (3회 재시도) ──
    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    for attempt in range(1, 4):
        try:
            logger.info(f"  HTML 스크래핑 시도 {attempt}/3 ...")
            return _check_via_html(url, session)

        except requests.exceptions.Timeout:
            logger.error(f"  시도 {attempt}/3 타임아웃")
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "?"
            logger.error(f"  시도 {attempt}/3 HTTP {status_code} 오류")
            # 4xx는 재시도해도 의미 없음
            if e.response and 400 <= e.response.status_code < 500:
                break
        except Exception as e:
            logger.error(f"  시도 {attempt}/3 예외: {type(e).__name__}: {e}")

        if attempt < 3:
            wait = random.uniform(3, 7)
            logger.info(f"  {wait:.1f}초 후 재시도...")
            time.sleep(wait)

    logger.error(f"  모든 시도 실패 → ERROR")
    return {"status": "ERROR", "product_name": None}


# ── 재입고 알림 이메일 ───────────────────────────────────────
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
      재입고되어 지금 구매 가능한 상태입니다. 재고가 소진되기 전에 빠르게 구매하세요!
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


# ── 메인 ─────────────────────────────────────────────────────
def main():
    # 0~300초 랜덤 딜레이 (15분 cron + 0~5분 딜레이 = 실질적 15~20분 간격)
    delay_seconds = random.randint(0, 300)
    logger.info(f"랜덤 딜레이 {delay_seconds}초 대기 중...")
    time.sleep(delay_seconds)

    logger.info("=" * 55)
    logger.info("재고 모니터링 시작")
    logger.info("=" * 55)

    result = supabase.table("monitors").select("*").eq("is_active", True).execute()
    monitors = result.data

    if not monitors:
        logger.info("활성 모니터가 없습니다. 종료합니다.")
        return

    logger.info(f"활성 모니터 {len(monitors)}개")

    # URL 별로 그룹화 (동일 URL 은 한 번만 요청)
    url_map: dict[str, list[dict]] = {}
    for m in monitors:
        url_map.setdefault(m["url"], []).append(m)

    logger.info(f"고유 URL {len(url_map)}개 확인 예정\n")

    for i, (url, url_monitors) in enumerate(url_map.items()):
        if i > 0:
            wait = random.uniform(5, 12)
            logger.info(f"다음 URL 요청 전 {wait:.1f}초 대기...\n")
            time.sleep(wait)

        logger.info(f"[{i+1}/{len(url_map)}] {url}")
        check_result = check_stock_status(url)
        current_status: str = check_result["status"]
        product_name: Optional[str] = check_result.get("product_name")
        now = datetime.now(timezone.utc).isoformat()

        logger.info(f"  최종 상태: {current_status}\n")

        for monitor in url_monitors:
            prev_status = monitor.get("last_status", "UNKNOWN")
            monitor_id = monitor["id"]

            if prev_status == "OUT_OF_STOCK" and current_status == "IN_STOCK":
                logger.info(f"  🎉 재입고 감지! → {monitor['email']} 알림 발송 중...")
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

            supabase.table("monitors").update(update_data).eq("id", monitor_id).execute()

    logger.info("=" * 55)
    logger.info("재고 모니터링 완료")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

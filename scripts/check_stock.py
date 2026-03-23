"""
스마트스토어 재입고 모니터링 스크립트
GitHub Actions 에서 주기적으로 실행됩니다.

재고 확인 전략 (순서대로 시도):
  1. Playwright 헤드리스 브라우저 (실제 Chrome 으로 봇 감지 우회)
  2. requests fallback (Playwright 실패 시)
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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
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
BASE_URL = os.environ.get("BASE_URL", "")
CHECK_API_SECRET = os.environ.get("CHECK_API_SECRET", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ── JSON 재귀 탐색 ──────────────────────────────────────────
def find_value_by_key(data, target_key: str, depth: int = 0):
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


# ── HTML 파싱 공통 로직 ─────────────────────────────────────
def _parse_stock_from_html(html: str, source: str = "") -> dict:
    """
    HTML 문자열에서 재고 상태와 상품명을 추출합니다.
    __NEXT_DATA__ JSON 파싱 → 텍스트 패턴 순서로 시도합니다.
    """
    product_name: Optional[str] = None

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
                logger.info(f"  [{source}] statusType={status_val}, name={product_name}")
                if status_val == "SALE":
                    return {"status": "IN_STOCK", "product_name": product_name}
                if status_val in ("OUTOFSTOCK", "SUSPENSION", "CLOSE", "SOLDOUT"):
                    return {"status": "OUT_OF_STOCK", "product_name": product_name}

            qty = find_value_by_key(next_data, "stockQuantity")
            if qty is not None:
                try:
                    q = int(qty)
                    logger.info(f"  [{source}] stockQuantity={q}")
                    return {"status": "IN_STOCK" if q > 0 else "OUT_OF_STOCK", "product_name": product_name}
                except (ValueError, TypeError):
                    pass

        except json.JSONDecodeError as e:
            logger.warning(f"  [{source}] __NEXT_DATA__ 파싱 실패: {e}")
    else:
        logger.warning(f"  [{source}] __NEXT_DATA__ 없음")

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
            logger.info(f"  [{source}] 품절 텍스트 감지: '{sig}'")
            return {"status": "OUT_OF_STOCK", "product_name": product_name}

    in_signals = ["구매하기", "장바구니 담기", "바로구매"]
    for sig in in_signals:
        if sig in page_text:
            logger.info(f"  [{source}] 구매가능 텍스트 감지: '{sig}'")
            return {"status": "IN_STOCK", "product_name": product_name}

    logger.warning(f"  [{source}] 상태 판별 불가 → UNKNOWN")
    return {"status": "UNKNOWN", "product_name": product_name}


# ── 방법 1: Playwright 헤드리스 브라우저 ────────────────────
def _check_via_playwright(url: str) -> Optional[dict]:
    """
    실제 Chrome 브라우저(헤드리스)를 사용해 봇 감지를 우회합니다.
    webdriver 속성을 숨기고 한국어 로케일을 설정합니다.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                },
            )

            # webdriver 탐지 회피
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                http_status = response.status if response else "?"
                logger.info(f"  [Playwright] HTTP {http_status}")

                if http_status == 429:
                    logger.warning("  [Playwright] HTTP 429 — IP 차단됨")
                    return None

                # JS 실행 완료 대기 (동적 렌더링 반영)
                page.wait_for_timeout(3000)

                content = page.content()
                logger.info(f"  [Playwright] 페이지 크기: {len(content):,} bytes")

                return _parse_stock_from_html(content, source="Playwright")

            except PlaywrightTimeoutError:
                logger.error("  [Playwright] 타임아웃")
                return None
            finally:
                browser.close()

    except Exception as e:
        logger.error(f"  [Playwright] 예외: {type(e).__name__}: {e}")
        return None


# ── 방법 2: requests fallback ────────────────────────────────
def _check_via_requests(url: str) -> Optional[dict]:
    """requests 로 HTML 직접 요청 (Playwright 실패 시 fallback)"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            logger.info(f"  [requests] 시도 {attempt}/3 → HTTP {resp.status_code}, {len(resp.text):,} bytes")

            if resp.status_code == 429:
                logger.warning("  [requests] HTTP 429 — 차단됨")
                break  # 재시도해도 의미 없음

            resp.raise_for_status()
            return _parse_stock_from_html(resp.text, source="requests")

        except requests.exceptions.HTTPError:
            pass
        except Exception as e:
            logger.error(f"  [requests] 시도 {attempt}/3 예외: {type(e).__name__}: {e}")

        if attempt < 3:
            wait = random.uniform(3, 7)
            logger.info(f"  {wait:.1f}초 후 재시도...")
            time.sleep(wait)

    return None


# ── 방법 0: Vercel 프록시 ────────────────────────────────────
def _check_via_vercel_proxy(url: str) -> Optional[dict]:
    """
    배포된 Vercel 앱을 프록시로 사용합니다.
    GitHub Actions(Azure IP)는 Naver에 차단되지만,
    Vercel(Cloudflare IP)은 차단되지 않을 가능성이 높습니다.
    """
    if not BASE_URL or not CHECK_API_SECRET:
        logger.info("  [Vercel] BASE_URL 또는 CHECK_API_SECRET 미설정 → 건너뜀")
        return None

    try:
        proxy_url = f"{BASE_URL}/api/check-url"
        resp = requests.get(
            proxy_url,
            params={"url": url},
            headers={"x-check-secret": CHECK_API_SECRET},
            timeout=30,
        )
        logger.info(f"  [Vercel] HTTP {resp.status_code}")

        if resp.status_code == 401:
            logger.error("  [Vercel] 인증 실패 — CHECK_API_SECRET 확인 필요")
            return None

        if resp.status_code != 200:
            logger.warning(f"  [Vercel] 응답 오류: {resp.status_code}")
            return None

        data = resp.json()
        status = data.get("status")
        product_name = data.get("product_name")
        http_status = data.get("http_status", "?")
        html_size = data.get("html_size", 0)

        logger.info(
            f"  [Vercel] Naver HTTP={http_status}, "
            f"status={status}, name={product_name}, html={html_size:,}bytes"
        )

        if status in ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"):
            return {"status": status, "product_name": product_name}

        if data.get("error"):
            logger.warning(f"  [Vercel] 오류: {data['error']}")

    except Exception as e:
        logger.error(f"  [Vercel] 예외: {type(e).__name__}: {e}")

    return None


# ── 메인 재고 확인 함수 ──────────────────────────────────────
def check_stock_status(url: str) -> dict:
    """
    1. Vercel 프록시 (Cloudflare IP — 네이버 차단 우회 가능)
    2. Playwright 헤드리스 브라우저
    3. requests fallback
    """
    result = _check_via_vercel_proxy(url)
    if result is not None:
        return result

    logger.info("  Vercel 프록시 실패 → Playwright 시도...")
    result = _check_via_playwright(url)
    if result is not None:
        return result

    logger.info("  Playwright 실패 → requests fallback 시도...")
    result = _check_via_requests(url)
    if result is not None:
        return result

    logger.error("  모든 방법 실패 → ERROR")
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

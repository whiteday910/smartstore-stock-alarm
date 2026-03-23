"""
스마트스토어 재입고 모니터링 스크립트

• GitHub Actions: Vercel 프록시 → Playwright → requests
• 로컬(PC): .env.local 로드 후 Playwright → requests (Vercel 생략, 가정용 IP 사용)
"""

import os
import re
import json
import time
import random
import smtplib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── 프로젝트 루트 .env / .env.local 로드 (로컬 실행용) ─────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

# GitHub Actions 에서만 True (Azure IP → 네이버 429)
RUNNING_IN_CI = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

# ── 로깅 설정 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _public_base_url() -> str:
    """구독취소 링크 등에 사용 (로컬은 NEXT_PUBLIC_BASE_URL 또는 localhost)."""
    u = (
        os.environ.get("BASE_URL")
        or os.environ.get("NEXT_PUBLIC_BASE_URL")
        or "http://localhost:3000"
    ).strip()
    return u.rstrip("/")


# ── 환경변수 ────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# CI 에서만 Vercel 프록시용 (로컬은 보통 비워 둠)
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
CHECK_API_SECRET = os.environ.get("CHECK_API_SECRET", "")


def _sb_headers() -> dict:
    """Supabase PostgREST 공통 헤더 (supabase-py 없이 requests 만 사용)."""
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def fetch_active_monitors() -> list:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/monitors"
    r = requests.get(
        url,
        headers=_sb_headers(),
        params={"select": "*", "is_active": "eq.true"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def patch_monitor(monitor_id: str, data: dict) -> None:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/monitors"
    r = requests.patch(
        url,
        headers=_sb_headers(),
        params={"id": f"eq.{monitor_id}"},
        json=data,
        timeout=60,
    )
    r.raise_for_status()


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
    # <script> 안의 JSON(예: __NEXT_DATA__) 은 get_text() 에 안 잡히므로 원본 html 도 검사
    combined_text = page_text + "\n" + html

    if not product_name:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            product_name = str(og["content"])

    out_signals = ["구매하실 수 없는 상품", "현재 구매하실 수 없", "재입고 시 구매가능", "품절"]
    for sig in out_signals:
        if sig in combined_text:
            logger.info(f"  [{source}] 품절 텍스트 감지: '{sig}'")
            return {"status": "OUT_OF_STOCK", "product_name": product_name}

    in_signals = ["구매하기", "장바구니 담기", "바로구매"]
    for sig in in_signals:
        if sig in combined_text:
            logger.info(f"  [{source}] 구매가능 텍스트 감지: '{sig}'")
            return {"status": "IN_STOCK", "product_name": product_name}

    logger.warning(f"  [{source}] 상태 판별 불가 → UNKNOWN")
    return {"status": "UNKNOWN", "product_name": product_name}


# ── 스크래핑 성공 여부 (HTTP 490 등 + 본문 마커) ─────────────
def _detect_product_page_markers(html: str) -> list[str]:
    """실제 상품 영역이 로드됐는지 판별하는 대표 문구들."""
    keys = [
        "재입고 시 구매가능",
        "이 상품은 현재 구매하실 수 없는",
        "구매하실 수 없는 상품",
        "구매하기",
        "장바구니 담기",
        "바로구매",
        "총 상품 금액",
    ]
    return [k for k in keys if k in html]


def finalize_scrape_result(
    parsed: dict,
    http_status: Optional[int],
    html: str,
    source: str = "",
) -> dict:
    """
    파싱 결과 + HTTP 코드 + 원문 HTML 로 스크래핑 성공 여부를 정리합니다.
    네이버가 490 등 비표준 코드를 주어도 '재입고 시 구매가능' 이 있으면 페이지 로드 성공으로 봅니다.
    """
    markers = _detect_product_page_markers(html)
    has_next = "__NEXT_DATA__" in html
    page_looks_ok = bool(markers) or has_next

    st = parsed.get("status", "UNKNOWN")
    pn = parsed.get("product_name")

    if st == "UNKNOWN":
        if (
            "재입고 시 구매가능" in html
            or "이 상품은 현재 구매하실 수 없는" in html
            or "구매하실 수 없는 상품" in html
        ):
            st = "OUT_OF_STOCK"
            logger.info(
                f"  [{source}] finalize: 품절/재입고 안내 문구로 OUT_OF_STOCK 보정"
            )
        elif "구매하기" in html or "장바구니 담기" in html or "바로구매" in html:
            st = "IN_STOCK"
            logger.info(f"  [{source}] finalize: 구매 UI 문구로 IN_STOCK 보정")

    scrape_success = False
    scrape_note = ""

    if http_status == 429:
        scrape_note = "HTTP 429 — IP/요청 차단"
    elif st == "ERROR":
        scrape_note = "스크래핑 실패 (모든 방법 무응답)"
    elif st in ("IN_STOCK", "OUT_OF_STOCK"):
        scrape_success = True
        scrape_note = f"재고 상태 확인 OK ({st})"
        if http_status is not None and http_status != 200:
            scrape_note += f" | 응답 HTTP {http_status}"
    elif page_looks_ok:
        scrape_success = True
        if markers:
            scrape_note = (
                f"상품 페이지 로드 확인 (키워드: {', '.join(markers[:4])}"
                + ("…" if len(markers) > 4 else "")
                + ")"
            )
        else:
            scrape_note = "__NEXT_DATA__ 존재 — 페이지 로드로 간주"
        if http_status is not None and http_status != 200:
            scrape_note += f" | HTTP {http_status}"
        if st == "UNKNOWN":
            scrape_note += " | 재고만 추가 파싱 필요할 수 있음"
    else:
        scrape_note = "상품 페이지로 식별 불가 (차단/빈 응답 가능)"
        if http_status is not None:
            scrape_note += f" | HTTP {http_status}"

    logger.info(f"  [스크래핑] 성공={scrape_success} | {scrape_note}")

    return {
        "status": st,
        "product_name": pn,
        "scrape_success": scrape_success,
        "scrape_note": scrape_note,
        "last_http_status": http_status,
    }


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
                response = page.goto(url, wait_until="load", timeout=45000)
                http_status: Optional[int] = (
                    int(response.status) if response and response.status else None
                )
                logger.info(f"  [Playwright] HTTP {http_status}")

                if http_status == 429:
                    logger.warning("  [Playwright] HTTP 429 — IP 차단됨")
                    return None

                # Next.js 가 __NEXT_DATA__ 를 주입할 때까지 대기 (없으면 추가 대기)
                try:
                    page.wait_for_selector("script#__NEXT_DATA__", timeout=25000)
                except PlaywrightTimeoutError:
                    logger.warning("  [Playwright] __NEXT_DATA__ 대기 타임아웃 — 추가 5초 대기")
                    page.wait_for_timeout(5000)

                content = page.content()
                logger.info(f"  [Playwright] 페이지 크기: {len(content):,} bytes")

                parsed = _parse_stock_from_html(content, source="Playwright")
                return finalize_scrape_result(
                    parsed, http_status, content, source="Playwright"
                )

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
            logger.info(
                f"  [requests] 시도 {attempt}/3 → HTTP {resp.status_code}, {len(resp.text):,} bytes"
            )

            if resp.status_code == 429:
                logger.warning("  [requests] HTTP 429 — 차단됨")
                break

            # 490 등 비정상 코드도 본문에 상품 UI 가 있을 수 있음
            if resp.status_code >= 500:
                logger.warning(f"  [requests] HTTP {resp.status_code} — 서버 오류, 재시도")
            else:
                parsed = _parse_stock_from_html(resp.text, source="requests")
                return finalize_scrape_result(
                    parsed, resp.status_code, resp.text, source="requests"
                )

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
            hs = http_status if isinstance(http_status, int) else None
            parsed = {"status": status, "product_name": product_name}
            # Vercel 경유 시 HTML 없음 — 상태만으로 성공 여부
            hint = ""
            if status == "OUT_OF_STOCK":
                hint = "재입고 시 구매가능"
            elif status == "IN_STOCK":
                hint = "구매하기"
            return finalize_scrape_result(parsed, hs, hint, source="Vercel")

        if data.get("error"):
            logger.warning(f"  [Vercel] 오류: {data['error']}")

    except Exception as e:
        logger.error(f"  [Vercel] 예외: {type(e).__name__}: {e}")

    return None


# ── 메인 재고 확인 함수 ──────────────────────────────────────
def check_stock_status(url: str) -> dict:
    """
    CI(GitHub Actions): Vercel 프록시 → Playwright → requests
    로컬: Playwright → requests (가정/사무실 IP, Vercel 생략)
    """
    if RUNNING_IN_CI:
        result = _check_via_vercel_proxy(url)
        if result is not None:
            return result
        logger.info("  Vercel 프록시 실패 → Playwright 시도...")
    else:
        logger.info("  [로컬] Vercel 프록시 생략 → 이 PC IP로 Playwright 시도...")

    result = _check_via_playwright(url)
    if result is not None:
        return result

    logger.info("  Playwright 실패 → requests fallback 시도...")
    result = _check_via_requests(url)
    if result is not None:
        return result

    logger.error("  모든 방법 실패 → ERROR")
    return {
        "status": "ERROR",
        "product_name": None,
        "scrape_success": False,
        "scrape_note": "모든 스크래핑 방법 실패 (429/타임아웃 등)",
        "last_http_status": None,
    }


# ── 재입고 알림 이메일 ───────────────────────────────────────
def send_restock_email(
    email: str,
    url: str,
    product_name: Optional[str],
    unsubscribe_token: str,
) -> bool:
    product_display = product_name or "모니터링 중이던 상품"
    unsubscribe_url = f"{_public_base_url()}/api/unsubscribe/{unsubscribe_token}"

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
    # CI 만 0~5분 랜덤 지연 (cron 과 겹쳐 실질 15~20분 간격). 로컬은 바로 실행.
    if RUNNING_IN_CI:
        delay_seconds = random.randint(0, 300)
        logger.info(f"랜덤 딜레이 {delay_seconds}초 대기 중...")
        time.sleep(delay_seconds)
    else:
        logger.info("[로컬] 시작 지연 없음 — 즉시 모니터링")

    logger.info("=" * 55)
    logger.info("재고 모니터링 시작")
    logger.info("=" * 55)

    monitors = fetch_active_monitors()

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

        scrape_ok = check_result.get("scrape_success")
        scrape_note = check_result.get("scrape_note")
        http_st = check_result.get("last_http_status")

        logger.info(f"  최종 상태: {current_status}")
        logger.info(
            f"  스크래핑: {'성공' if scrape_ok else '실패/불명'} | {scrape_note}\n"
        )

        for monitor in url_monitors:
            prev_status = monitor.get("last_status", "UNKNOWN")
            monitor_id = monitor["id"]

            meta = {
                "last_scrape_ok": scrape_ok,
                "last_scrape_note": scrape_note,
                "last_http_status": http_st,
            }

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
                    **meta,
                }
            else:
                update_data = {
                    "last_status": current_status,
                    "last_checked_at": now,
                    "product_name": product_name or monitor.get("product_name"),
                    **meta,
                }

            patch_monitor(monitor_id, update_data)

    logger.info("=" * 55)
    logger.info("재고 모니터링 완료")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()

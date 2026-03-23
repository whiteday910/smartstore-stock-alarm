import { NextRequest, NextResponse } from "next/server";

// ── JSON 재귀 탐색 ──────────────────────────────────────────
function findValueByKey(obj: unknown, key: string, depth = 0): string | null {
  if (depth > 12 || typeof obj !== "object" || obj === null) return null;
  if (Array.isArray(obj)) {
    for (const item of obj) {
      const r = findValueByKey(item, key, depth + 1);
      if (r) return r;
    }
    return null;
  }
  const record = obj as Record<string, unknown>;
  if (key in record && record[key]) return String(record[key]);
  for (const val of Object.values(record)) {
    const r = findValueByKey(val, key, depth + 1);
    if (r) return r;
  }
  return null;
}

// ── HTML 재고 상태 파싱 ─────────────────────────────────────
function parseStockFromHtml(html: string): {
  status: "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN";
  productName: string | null;
} {
  let productName: string | null = null;

  // __NEXT_DATA__ JSON 파싱
  const m = html.match(
    /<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/
  );
  if (m) {
    try {
      const data = JSON.parse(m[1]);

      const nameVal = findValueByKey(data, "name");
      if (nameVal && nameVal.length > 1) productName = nameVal;

      const statusType = findValueByKey(data, "statusType");
      if (statusType) {
        const s = statusType.toUpperCase();
        if (s === "SALE") return { status: "IN_STOCK", productName };
        if (["OUTOFSTOCK", "SUSPENSION", "CLOSE", "SOLDOUT"].includes(s))
          return { status: "OUT_OF_STOCK", productName };
      }

      const qty = findValueByKey(data, "stockQuantity");
      if (qty !== null) {
        const q = parseInt(qty, 10);
        if (!isNaN(q))
          return { status: q > 0 ? "IN_STOCK" : "OUT_OF_STOCK", productName };
      }
    } catch {}
  }

  // 텍스트 패턴 fallback
  if (
    html.includes("구매하실 수 없는 상품") ||
    html.includes("재입고 시 구매가능")
  )
    return { status: "OUT_OF_STOCK", productName };

  if (html.includes("구매하기") || html.includes("장바구니 담기"))
    return { status: "IN_STOCK", productName };

  return { status: "UNKNOWN", productName };
}

// ── GET /api/check-url?url=... ──────────────────────────────
export async function GET(req: NextRequest) {
  // 인증: x-check-secret 헤더 확인
  const secret = req.headers.get("x-check-secret");
  const expected = process.env.CHECK_API_SECRET;
  if (!expected || secret !== expected) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const url = req.nextUrl.searchParams.get("url") ?? "";
  if (!url.startsWith("https://smartstore.naver.com/")) {
    return NextResponse.json({ error: "Invalid URL" }, { status: 400 });
  }

  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        Accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
      },
      signal: AbortSignal.timeout(9000),
    });

    const httpStatus = response.status;

    if (httpStatus === 429) {
      return NextResponse.json(
        { error: "Naver returned 429 (Vercel IP also blocked)", status: "ERROR" },
        { status: 200 } // 스크립트에서 처리할 수 있도록 200 반환
      );
    }

    const html = await response.text();
    const result = parseStockFromHtml(html);

    return NextResponse.json({
      status: result.status,
      product_name: result.productName,
      http_status: httpStatus,
      html_size: html.length,
    });
  } catch (err) {
    return NextResponse.json(
      { error: String(err), status: "ERROR" },
      { status: 200 }
    );
  }
}

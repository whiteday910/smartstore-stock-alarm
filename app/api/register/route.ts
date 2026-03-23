import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { sendConfirmationEmail } from "@/lib/email";

const SMARTSTORE_URL_PATTERN =
  /^https:\/\/smartstore\.naver\.com\/[^/]+\/products\/\d+/;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const url: string = (body.url || "").trim();
    const email: string = (body.email || "").trim().toLowerCase();

    // --- 유효성 검증 ---
    if (!url || !email) {
      return NextResponse.json(
        { message: "URL과 이메일을 모두 입력해주세요." },
        { status: 400 }
      );
    }
    if (!SMARTSTORE_URL_PATTERN.test(url)) {
      return NextResponse.json(
        { message: "네이버 스마트스토어 상품 URL만 등록 가능합니다." },
        { status: 400 }
      );
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return NextResponse.json(
        { message: "올바른 이메일 주소를 입력해주세요." },
        { status: 400 }
      );
    }

    // URL 정규화 (쿼리스트링 제거)
    const cleanUrl = url.split("?")[0].replace(/\/$/, "");

    // --- 중복 등록 확인 ---
    const { data: existing } = await supabase
      .from("monitors")
      .select("id")
      .eq("email", email)
      .eq("url", cleanUrl)
      .eq("is_active", true)
      .maybeSingle();

    if (existing) {
      return NextResponse.json(
        {
          message:
            "이미 동일한 상품으로 알림이 등록되어 있습니다. 재입고 시 이메일을 보내드립니다.",
        },
        { status: 409 }
      );
    }

    // --- 상품명 추출 시도 (실패해도 등록은 진행) ---
    let productName: string | null = null;
    try {
      productName = await fetchProductName(cleanUrl);
    } catch {
      // 상품명 조회 실패는 무시
    }

    // --- DB 저장 ---
    const { data: monitor, error } = await supabase
      .from("monitors")
      .insert({
        email,
        url: cleanUrl,
        product_name: productName,
        last_status: "UNKNOWN",
        is_active: true,
      })
      .select()
      .single();

    if (error || !monitor) {
      console.error("DB insert error:", error);
      return NextResponse.json(
        { message: "등록 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요." },
        { status: 500 }
      );
    }

    // --- 확인 이메일 발송 ---
    const baseUrl =
      process.env.NEXT_PUBLIC_BASE_URL ||
      `https://${req.headers.get("host")}`;

    try {
      await sendConfirmationEmail({
        to: email,
        url: cleanUrl,
        productName,
        unsubscribeToken: monitor.unsubscribe_token,
        baseUrl,
      });
    } catch (emailError) {
      console.error("Confirmation email failed:", emailError);
      // 이메일 실패해도 등록은 성공으로 처리
    }

    return NextResponse.json(
      {
        message: `알림이 등록되었습니다! 확인 이메일을 발송했습니다.\n재입고 감지 시 ${email}로 알려드리겠습니다.`,
        id: monitor.id,
      },
      { status: 201 }
    );
  } catch (err) {
    console.error("Unhandled error:", err);
    return NextResponse.json(
      { message: "서버 오류가 발생했습니다." },
      { status: 500 }
    );
  }
}

async function fetchProductName(url: string): Promise<string | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);

  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
      },
    });

    if (!res.ok) return null;
    const html = await res.text();

    // __NEXT_DATA__ JSON에서 상품명 추출
    const nextDataMatch = html.match(
      /<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/
    );
    if (nextDataMatch) {
      try {
        const json = JSON.parse(nextDataMatch[1]);
        const name = findValueByKey(json, "name");
        if (name && typeof name === "string" && name.length > 1) return name;
      } catch {
        // ignore
      }
    }

    // og:title 메타태그 fallback
    const ogMatch = html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]+)"/);
    if (ogMatch) return ogMatch[1];

    // <title> 태그 fallback
    const titleMatch = html.match(/<title>([^<]+)<\/title>/);
    if (titleMatch) return titleMatch[1].replace(/ : 네이버 쇼핑$/, "").trim();

    return null;
  } finally {
    clearTimeout(timeout);
  }
}

// JSON 내 특정 키를 재귀적으로 탐색
function findValueByKey(obj: unknown, key: string): unknown {
  if (typeof obj !== "object" || obj === null) return undefined;
  if (Array.isArray(obj)) {
    for (const item of obj) {
      const result = findValueByKey(item, key);
      if (result) return result;
    }
    return undefined;
  }
  const record = obj as Record<string, unknown>;
  if (key in record && record[key]) return record[key];
  for (const val of Object.values(record)) {
    const result = findValueByKey(val, key);
    if (result) return result;
  }
  return undefined;
}

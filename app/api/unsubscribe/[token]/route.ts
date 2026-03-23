import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export async function GET(
  _req: NextRequest,
  { params }: { params: { token: string } }
) {
  const token = params.token;

  if (!token || !/^[0-9a-f-]{36}$/.test(token)) {
    return new NextResponse(renderPage("오류", "유효하지 않은 구독취소 링크입니다.", false), {
      headers: { "Content-Type": "text/html; charset=utf-8" },
      status: 400,
    });
  }

  const { data: monitor, error } = await supabase
    .from("monitors")
    .select("id, email, url, product_name, is_active")
    .eq("unsubscribe_token", token)
    .maybeSingle();

  if (error || !monitor) {
    return new NextResponse(renderPage("오류", "구독 정보를 찾을 수 없습니다.", false), {
      headers: { "Content-Type": "text/html; charset=utf-8" },
      status: 404,
    });
  }

  if (!monitor.is_active) {
    return new NextResponse(
      renderPage(
        "이미 취소됨",
        "이미 구독이 취소된 알림입니다.",
        false,
        monitor
      ),
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }

  const { error: updateError } = await supabase
    .from("monitors")
    .update({ is_active: false })
    .eq("id", monitor.id);

  if (updateError) {
    return new NextResponse(
      renderPage("오류", "구독 취소 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", false),
      {
        headers: { "Content-Type": "text/html; charset=utf-8" },
        status: 500,
      }
    );
  }

  return new NextResponse(
    renderPage("구독 취소 완료", "재입고 알림 구독이 취소되었습니다.", true, monitor),
    { headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
}

type MonitorInfo = {
  email?: string;
  url?: string;
  product_name?: string | null;
};

function renderPage(
  title: string,
  message: string,
  success: boolean,
  monitor?: MonitorInfo
) {
  const productDisplay = monitor?.product_name || monitor?.url || "";
  const accentColor = success ? "#03C75A" : "#ef4444";
  const icon = success ? "✅" : "❌";

  return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title} — 스마트스토어 재입고 알리미</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f9fafb; color: #111; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px; }
    .card { background: #fff; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); padding: 40px 32px; max-width: 440px; width: 100%; text-align: center; }
    .icon { font-size: 48px; margin-bottom: 16px; }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 12px; color: ${accentColor}; }
    p { font-size: 15px; color: #6b7280; line-height: 1.6; margin-bottom: 8px; }
    .product { background: #f9fafb; border-radius: 8px; padding: 12px 16px; margin: 16px 0; font-size: 13px; color: #374151; word-break: break-all; }
    a.btn { display: inline-block; margin-top: 20px; background: ${accentColor}; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; font-size: 14px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">${icon}</div>
    <h1>${title}</h1>
    <p>${message}</p>
    ${productDisplay ? `<div class="product">${productDisplay}</div>` : ""}
    <a href="/" class="btn">홈으로 돌아가기</a>
  </div>
</body>
</html>`;
}

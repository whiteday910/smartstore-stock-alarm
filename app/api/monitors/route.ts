import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export async function GET(req: NextRequest) {
  const email = req.nextUrl.searchParams.get("email")?.trim().toLowerCase();

  if (!email) {
    return NextResponse.json(
      { message: "이메일 주소를 입력해주세요." },
      { status: 400 }
    );
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json(
      { message: "올바른 이메일 주소를 입력해주세요." },
      { status: 400 }
    );
  }

  const { data, error } = await supabase
    .from("monitors")
    .select(
      "id, url, product_name, last_status, last_checked_at, notified_at, is_active, unsubscribe_token, created_at"
    )
    .eq("email", email)
    .eq("is_active", true)
    .order("created_at", { ascending: false });

  if (error) {
    console.error("DB error:", error);
    return NextResponse.json(
      { message: "데이터 조회 중 오류가 발생했습니다." },
      { status: 500 }
    );
  }

  return NextResponse.json({ monitors: data || [] });
}

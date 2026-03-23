import { createClient, SupabaseClient } from "@supabase/supabase-js";

// 빌드 타임이 아닌 런타임에만 클라이언트를 생성합니다.
let _supabase: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (_supabase) return _supabase;
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) {
    throw new Error("SUPABASE_URL 또는 SUPABASE_SERVICE_KEY 환경변수가 설정되지 않았습니다.");
  }
  _supabase = createClient(url, key, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  return _supabase;
}

// 편의를 위한 proxy 객체 — 실제 호출 시점에 초기화됩니다.
export const supabase = new Proxy({} as SupabaseClient, {
  get(_target, prop) {
    return getSupabase()[prop as keyof SupabaseClient];
  },
});

export type Monitor = {
  id: string;
  email: string;
  url: string;
  product_name: string | null;
  last_status: "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN" | "ERROR";
  last_checked_at: string | null;
  notified_at: string | null;
  is_active: boolean;
  unsubscribe_token: string;
  created_at: string;
};

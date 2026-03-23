"use client";

import { useState } from "react";

type FormStatus = "idle" | "loading" | "success" | "error" | "duplicate";
type MonitorStatus = "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN" | "ERROR";

type Monitor = {
  id: string;
  url: string;
  product_name: string | null;
  last_status: MonitorStatus;
  last_checked_at: string | null;
  notified_at: string | null;
  unsubscribe_token: string;
  created_at: string;
};

const SMARTSTORE_URL_PATTERN =
  /^https:\/\/smartstore\.naver\.com\/[^/]+\/products\/\d+/;

const STATUS_CONFIG: Record<
  MonitorStatus,
  { label: string; color: string; bg: string; dot: string }
> = {
  IN_STOCK: {
    label: "구매 가능",
    color: "text-green-700",
    bg: "bg-green-50 border-green-200",
    dot: "bg-green-500",
  },
  OUT_OF_STOCK: {
    label: "품절",
    color: "text-red-600",
    bg: "bg-red-50 border-red-200",
    dot: "bg-red-500",
  },
  UNKNOWN: {
    label: "확인 중",
    color: "text-yellow-600",
    bg: "bg-yellow-50 border-yellow-200",
    dot: "bg-yellow-400",
  },
  ERROR: {
    label: "오류",
    color: "text-gray-500",
    bg: "bg-gray-50 border-gray-200",
    dot: "bg-gray-400",
  },
};

function formatDate(iso: string | null): string {
  if (!iso) return "아직 확인 전";
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortenUrl(url: string): string {
  return url.length > 50 ? url.slice(0, 50) + "..." : url;
}

export default function Home() {
  // ── 등록 폼 상태 ──────────────────────────────────────────
  const [url, setUrl] = useState("");
  const [email, setEmail] = useState("");
  const [formStatus, setFormStatus] = useState<FormStatus>("idle");
  const [formMessage, setFormMessage] = useState("");
  const [urlError, setUrlError] = useState("");
  const [emailError, setEmailError] = useState("");

  // ── 현황 조회 상태 ────────────────────────────────────────
  const [queryEmail, setQueryEmail] = useState("");
  const [queryEmailError, setQueryEmailError] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [monitors, setMonitors] = useState<Monitor[] | null>(null);
  const [queryMessage, setQueryMessage] = useState("");
  const [unsubscribing, setUnsubscribing] = useState<string | null>(null);

  // ── 유효성 검사 ───────────────────────────────────────────
  const validateUrl = (value: string) => {
    if (!value) return "상품 URL을 입력해주세요.";
    if (!SMARTSTORE_URL_PATTERN.test(value))
      return "네이버 스마트스토어 상품 URL만 등록 가능합니다.\n예) https://smartstore.naver.com/storename/products/1234567890";
    return "";
  };
  const validateEmail = (value: string) => {
    if (!value) return "이메일 주소를 입력해주세요.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))
      return "올바른 이메일 주소를 입력해주세요.";
    return "";
  };

  // ── 알림 등록 ─────────────────────────────────────────────
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const uErr = validateUrl(url);
    const eErr = validateEmail(email);
    setUrlError(uErr);
    setEmailError(eErr);
    if (uErr || eErr) return;

    setFormStatus("loading");
    setFormMessage("");

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), email: email.trim() }),
      });
      const data = await res.json();

      if (res.ok) {
        setFormStatus("success");
        setFormMessage(data.message || "알림이 등록되었습니다.");
        setUrl("");
        setEmail("");
        // 현황 조회 섹션을 등록한 이메일로 자동 업데이트
        if (queryEmail === email.trim()) {
          handleQueryMonitors(email.trim());
        }
      } else if (res.status === 409) {
        setFormStatus("duplicate");
        setFormMessage(data.message || "이미 등록된 URL과 이메일 조합입니다.");
      } else {
        setFormStatus("error");
        setFormMessage(data.message || "등록 중 오류가 발생했습니다.");
      }
    } catch {
      setFormStatus("error");
      setFormMessage("네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  // ── 현황 조회 ─────────────────────────────────────────────
  const handleQueryMonitors = async (overrideEmail?: string) => {
    const targetEmail = (overrideEmail ?? queryEmail).trim();
    const eErr = validateEmail(targetEmail);
    if (!overrideEmail) setQueryEmailError(eErr);
    if (eErr) return;

    setQueryLoading(true);
    setQueryMessage("");
    setMonitors(null);

    try {
      const res = await fetch(
        `/api/monitors?email=${encodeURIComponent(targetEmail)}`
      );
      const data = await res.json();

      if (!res.ok) {
        setQueryMessage(data.message || "조회 중 오류가 발생했습니다.");
      } else if (data.monitors.length === 0) {
        setQueryMessage("등록된 알림이 없습니다.");
        setMonitors([]);
      } else {
        setMonitors(data.monitors);
      }
    } catch {
      setQueryMessage("네트워크 오류가 발생했습니다.");
    } finally {
      setQueryLoading(false);
    }
  };

  // ── 구독 취소 ─────────────────────────────────────────────
  const handleUnsubscribe = async (token: string, monitorId: string) => {
    if (!confirm("이 상품의 재입고 알림을 취소하시겠습니까?")) return;
    setUnsubscribing(monitorId);

    try {
      const res = await fetch(`/api/unsubscribe/${token}`);
      if (res.ok || res.status === 200) {
        setMonitors((prev) =>
          prev ? prev.filter((m) => m.id !== monitorId) : prev
        );
      }
    } catch {
      alert("취소 중 오류가 발생했습니다.");
    } finally {
      setUnsubscribing(null);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Header ──────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-2">
          <span className="text-2xl">🛍️</span>
          <span className="font-bold text-gray-900 text-lg">
            스마트스토어 재입고 알리미
          </span>
        </div>
      </header>

      <main className="flex-1">
        {/* ── Hero ────────────────────────────────────────── */}
        <section className="bg-gradient-to-br from-naver-green to-naver-dark text-white py-16 px-4">
          <div className="max-w-3xl mx-auto text-center">
            <div className="text-5xl mb-6">📦</div>
            <h1 className="text-3xl md:text-4xl font-bold mb-4 leading-tight">
              품절된 상품이 재입고되면
              <br />
              <span className="text-green-100">이메일로 즉시 알려드립니다</span>
            </h1>
            <p className="text-green-50 text-lg md:text-xl">
              상품 URL과 이메일만 등록하면 끝 — 15~20분 간격으로 자동 모니터링
            </p>
          </div>
        </section>

        {/* ── 등록 폼 + 현황 조회 (나란히) ─────────────────── */}
        <section className="py-12 px-4 -mt-6">
          <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* 등록 폼 */}
            <div className="card p-8">
              <h2 className="text-xl font-bold text-gray-900 mb-6 text-center">
                재입고 알림 등록
              </h2>

              {formStatus === "success" ? (
                <div className="text-center py-6">
                  <div className="text-5xl mb-4">✅</div>
                  <p className="text-lg font-semibold text-gray-900 mb-2">
                    알림 등록 완료!
                  </p>
                  <p className="text-gray-500 text-sm mb-6 whitespace-pre-line">
                    {formMessage}
                  </p>
                  <button
                    onClick={() => setFormStatus("idle")}
                    className="btn-primary"
                  >
                    다른 상품 등록하기
                  </button>
                </div>
              ) : (
                <form onSubmit={handleSubmit} noValidate className="space-y-5">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      상품 URL
                    </label>
                    <input
                      type="url"
                      value={url}
                      onChange={(e) => {
                        setUrl(e.target.value);
                        if (urlError) setUrlError(validateUrl(e.target.value));
                      }}
                      placeholder="https://smartstore.naver.com/storename/products/..."
                      className={`input-field ${urlError ? "border-red-400 focus:ring-red-400" : ""}`}
                    />
                    {urlError && (
                      <p className="text-red-500 text-xs mt-1.5 whitespace-pre-line">
                        {urlError}
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      이메일 주소
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (emailError) setEmailError(validateEmail(e.target.value));
                      }}
                      placeholder="your@email.com"
                      className={`input-field ${emailError ? "border-red-400 focus:ring-red-400" : ""}`}
                    />
                    {emailError && (
                      <p className="text-red-500 text-xs mt-1.5">{emailError}</p>
                    )}
                  </div>

                  {(formStatus === "error" || formStatus === "duplicate") &&
                    formMessage && (
                      <div
                        className={`p-3 rounded-lg text-sm ${
                          formStatus === "duplicate"
                            ? "bg-yellow-50 text-yellow-700 border border-yellow-200"
                            : "bg-red-50 text-red-600 border border-red-200"
                        }`}
                      >
                        {formMessage}
                      </div>
                    )}

                  <button
                    type="submit"
                    disabled={formStatus === "loading"}
                    className="btn-primary w-full flex items-center justify-center gap-2"
                  >
                    {formStatus === "loading" ? (
                      <>
                        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        등록 중...
                      </>
                    ) : (
                      "알림 등록하기"
                    )}
                  </button>

                  <p className="text-xs text-gray-400 text-center">
                    재입고 알림 발송 후에도 계속 모니터링합니다.
                    <br />
                    이메일의 구독취소 링크로 언제든지 해제 가능합니다.
                  </p>
                </form>
              )}
            </div>

            {/* 내 알림 현황 */}
            <div className="card p-8">
              <h2 className="text-xl font-bold text-gray-900 mb-6 text-center">
                내 알림 현황
              </h2>

              <div className="flex gap-2 mb-5">
                <input
                  type="email"
                  value={queryEmail}
                  onChange={(e) => {
                    setQueryEmail(e.target.value);
                    if (queryEmailError)
                      setQueryEmailError(validateEmail(e.target.value));
                  }}
                  onKeyDown={(e) =>
                    e.key === "Enter" && handleQueryMonitors()
                  }
                  placeholder="등록한 이메일 주소"
                  className={`input-field flex-1 ${queryEmailError ? "border-red-400" : ""}`}
                />
                <button
                  onClick={() => handleQueryMonitors()}
                  disabled={queryLoading}
                  className="btn-primary shrink-0 flex items-center gap-1"
                >
                  {queryLoading ? (
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    "조회"
                  )}
                </button>
              </div>
              {queryEmailError && (
                <p className="text-red-500 text-xs mb-3">{queryEmailError}</p>
              )}

              {/* 결과 영역 */}
              {monitors === null && !queryMessage && (
                <div className="text-center py-10 text-gray-400 text-sm">
                  <div className="text-4xl mb-3">📋</div>
                  이메일을 입력하고 조회 버튼을 클릭하세요
                </div>
              )}

              {queryMessage && (
                <div className="text-center py-8 text-gray-500 text-sm">
                  {queryMessage}
                </div>
              )}

              {monitors && monitors.length > 0 && (
                <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
                  {monitors.map((m) => {
                    const sc = STATUS_CONFIG[m.last_status] ?? STATUS_CONFIG.UNKNOWN;
                    return (
                      <div
                        key={m.id}
                        className={`border rounded-xl p-4 ${sc.bg}`}
                      >
                        {/* 상품명 / URL */}
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex-1 min-w-0">
                            {m.product_name ? (
                              <p className="font-medium text-gray-900 text-sm truncate">
                                {m.product_name}
                              </p>
                            ) : null}
                            <a
                              href={m.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-blue-500 hover:underline break-all"
                            >
                              {shortenUrl(m.url)}
                            </a>
                          </div>
                          {/* 상태 뱃지 */}
                          <span
                            className={`shrink-0 flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full border ${sc.bg} ${sc.color}`}
                          >
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${sc.dot}`}
                            />
                            {sc.label}
                          </span>
                        </div>

                        {/* 마지막 확인 시각 */}
                        <div className="flex items-center justify-between mt-2">
                          <p className="text-xs text-gray-400">
                            마지막 확인:{" "}
                            <span className="text-gray-500">
                              {formatDate(m.last_checked_at)}
                            </span>
                          </p>
                          <button
                            onClick={() =>
                              handleUnsubscribe(m.unsubscribe_token, m.id)
                            }
                            disabled={unsubscribing === m.id}
                            className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                          >
                            {unsubscribing === m.id ? "취소 중..." : "알림 해제"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── How It Works ─────────────────────────────────── */}
        <section className="py-12 px-4 bg-white">
          <div className="max-w-4xl mx-auto">
            <h2 className="text-2xl font-bold text-gray-900 text-center mb-10">
              이용 방법
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {[
                {
                  step: "01",
                  icon: "🔗",
                  title: "URL 등록",
                  desc: "품절된 스마트스토어 상품의 URL과 알림받을 이메일을 입력합니다.",
                },
                {
                  step: "02",
                  icon: "👁️",
                  title: "자동 모니터링",
                  desc: "15~20분 간격으로 상품 페이지를 자동으로 확인합니다. PC가 꺼져 있어도 24시간 작동합니다.",
                },
                {
                  step: "03",
                  icon: "📧",
                  title: "즉시 알림",
                  desc: "재입고가 감지되면 즉시 이메일로 알림을 보내드립니다. 구매 링크가 포함되어 바로 이동할 수 있습니다.",
                },
              ].map(({ step, icon, title, desc }) => (
                <div key={step} className="text-center">
                  <div className="inline-flex items-center justify-center w-16 h-16 bg-green-50 rounded-2xl text-3xl mb-4">
                    {icon}
                  </div>
                  <div className="text-xs font-bold text-naver-green mb-2 tracking-widest">
                    STEP {step}
                  </div>
                  <h3 className="text-lg font-bold text-gray-900 mb-2">{title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed">{desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── FAQ ──────────────────────────────────────────── */}
        <section className="py-12 px-4 bg-gray-50">
          <div className="max-w-2xl mx-auto">
            <h2 className="text-2xl font-bold text-gray-900 text-center mb-8">
              자주 묻는 질문
            </h2>
            <div className="space-y-4">
              {[
                {
                  q: "어떤 상품을 등록할 수 있나요?",
                  a: "네이버 스마트스토어의 상품만 등록할 수 있습니다. URL 형식은 https://smartstore.naver.com/[스토어명]/products/[상품번호] 이어야 합니다.",
                },
                {
                  q: "알림은 얼마나 빨리 받을 수 있나요?",
                  a: "15~20분 간격으로 모니터링하므로, 재입고 후 최대 20분 이내에 알림 이메일이 발송됩니다.",
                },
                {
                  q: "알림을 그만 받고 싶으면 어떻게 하나요?",
                  a: "알림 이메일 하단의 '구독취소' 링크를 클릭하거나, '내 알림 현황' 섹션에서 '알림 해제' 버튼을 클릭하면 됩니다.",
                },
                {
                  q: "하나의 이메일로 여러 상품을 등록할 수 있나요?",
                  a: "네, 가능합니다. 상품별로 개별 등록하면 각 상품의 재입고 시 따로 알림이 발송됩니다.",
                },
              ].map(({ q, a }) => (
                <div key={q} className="card p-5">
                  <p className="font-semibold text-gray-900 mb-2">Q. {q}</p>
                  <p className="text-gray-500 text-sm leading-relaxed">A. {a}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ───────────────────────────────────────── */}
      <footer className="bg-white border-t border-gray-200 py-6 px-4">
        <div className="max-w-5xl mx-auto text-center text-sm text-gray-400">
          <p>스마트스토어 재입고 알리미 — 네이버와 무관한 독립 서비스입니다.</p>
        </div>
      </footer>
    </div>
  );
}

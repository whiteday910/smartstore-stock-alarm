"use client";

import { useState } from "react";

type FormStatus = "idle" | "loading" | "success" | "error" | "duplicate";

const SMARTSTORE_URL_PATTERN =
  /^https:\/\/smartstore\.naver\.com\/[^/]+\/products\/\d+/;

export default function Home() {
  const [url, setUrl] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<FormStatus>("idle");
  const [message, setMessage] = useState("");
  const [urlError, setUrlError] = useState("");
  const [emailError, setEmailError] = useState("");

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const uErr = validateUrl(url);
    const eErr = validateEmail(email);
    setUrlError(uErr);
    setEmailError(eErr);
    if (uErr || eErr) return;

    setStatus("loading");
    setMessage("");

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), email: email.trim() }),
      });

      const data = await res.json();

      if (res.ok) {
        setStatus("success");
        setMessage(data.message || "알림이 등록되었습니다.");
        setUrl("");
        setEmail("");
      } else if (res.status === 409) {
        setStatus("duplicate");
        setMessage(data.message || "이미 등록된 URL과 이메일 조합입니다.");
      } else {
        setStatus("error");
        setMessage(data.message || "등록 중 오류가 발생했습니다. 다시 시도해주세요.");
      }
    } catch {
      setStatus("error");
      setMessage("네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-2">
          <span className="text-2xl">🛍️</span>
          <span className="font-bold text-gray-900 text-lg">
            스마트스토어 재입고 알리미
          </span>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero */}
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

        {/* Registration Form */}
        <section className="py-12 px-4 -mt-6">
          <div className="max-w-xl mx-auto">
            <div className="card p-8">
              <h2 className="text-xl font-bold text-gray-900 mb-6 text-center">
                재입고 알림 등록
              </h2>

              {status === "success" ? (
                <div className="text-center py-6">
                  <div className="text-5xl mb-4">✅</div>
                  <p className="text-lg font-semibold text-gray-900 mb-2">
                    알림 등록 완료!
                  </p>
                  <p className="text-gray-500 text-sm mb-6">{message}</p>
                  <button
                    onClick={() => setStatus("idle")}
                    className="btn-primary"
                  >
                    다른 상품 등록하기
                  </button>
                </div>
              ) : (
                <form onSubmit={handleSubmit} noValidate className="space-y-5">
                  {/* URL Input */}
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
                      placeholder="https://smartstore.naver.com/storename/products/1234567890"
                      className={`input-field ${urlError ? "border-red-400 focus:ring-red-400" : ""}`}
                    />
                    {urlError && (
                      <p className="text-red-500 text-xs mt-1.5 whitespace-pre-line">
                        {urlError}
                      </p>
                    )}
                  </div>

                  {/* Email Input */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      이메일 주소
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (emailError)
                          setEmailError(validateEmail(e.target.value));
                      }}
                      placeholder="your@email.com"
                      className={`input-field ${emailError ? "border-red-400 focus:ring-red-400" : ""}`}
                    />
                    {emailError && (
                      <p className="text-red-500 text-xs mt-1.5">{emailError}</p>
                    )}
                  </div>

                  {/* Error / Duplicate Message */}
                  {(status === "error" || status === "duplicate") && message && (
                    <div
                      className={`p-3 rounded-lg text-sm ${
                        status === "duplicate"
                          ? "bg-yellow-50 text-yellow-700 border border-yellow-200"
                          : "bg-red-50 text-red-600 border border-red-200"
                      }`}
                    >
                      {message}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={status === "loading"}
                    className="btn-primary w-full flex items-center justify-center gap-2"
                  >
                    {status === "loading" ? (
                      <>
                        <svg
                          className="animate-spin h-4 w-4"
                          viewBox="0 0 24 24"
                          fill="none"
                        >
                          <circle
                            className="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            strokeWidth="4"
                          />
                          <path
                            className="opacity-75"
                            fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                          />
                        </svg>
                        등록 중...
                      </>
                    ) : (
                      "알림 등록하기"
                    )}
                  </button>

                  <p className="text-xs text-gray-400 text-center">
                    재입고 알림 1회 발송 후에도 계속 모니터링합니다.
                    <br />
                    알림 이메일의 구독취소 링크로 언제든지 해제할 수 있습니다.
                  </p>
                </form>
              )}
            </div>
          </div>
        </section>

        {/* How It Works */}
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
                  desc: "품절된 스마트스토어 상품의 URL과 알림받을 이메일 주소를 입력합니다.",
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

        {/* FAQ */}
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
                  a: "알림 이메일 하단의 '구독취소' 링크를 클릭하면 즉시 모니터링이 중단됩니다.",
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

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 py-6 px-4">
        <div className="max-w-5xl mx-auto text-center text-sm text-gray-400">
          <p>스마트스토어 재입고 알리미 — 네이버와 무관한 독립 서비스입니다.</p>
        </div>
      </footer>
    </div>
  );
}

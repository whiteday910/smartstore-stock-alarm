import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "스마트스토어 재입고 알리미",
  description: "네이버 스마트스토어 품절 상품이 재입고되면 이메일로 즉시 알려드립니다.",
  openGraph: {
    title: "스마트스토어 재입고 알리미",
    description: "품절 상품이 재입고되면 이메일로 즉시 알려드립니다.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}

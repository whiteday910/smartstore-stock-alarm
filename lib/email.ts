import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({
  service: "gmail",
  auth: {
    user: process.env.GMAIL_USER,
    pass: process.env.GMAIL_APP_PASSWORD,
  },
});

export async function sendConfirmationEmail({
  to,
  url,
  productName,
  unsubscribeToken,
  baseUrl,
}: {
  to: string;
  url: string;
  productName?: string | null;
  unsubscribeToken: string;
  baseUrl: string;
}) {
  const productDisplay = productName || "등록한 상품";
  const unsubscribeUrl = `${baseUrl}/api/unsubscribe/${unsubscribeToken}`;
  const shortUrl =
    url.length > 60 ? url.substring(0, 60) + "..." : url;

  const html = `
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <div style="background: #03C75A; color: white; padding: 24px 28px; border-radius: 12px 12px 0 0;">
    <h1 style="margin: 0; font-size: 20px;">🛍️ 재입고 알림 등록 완료</h1>
  </div>
  <div style="background: #ffffff; padding: 28px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
    <p style="font-size: 16px; margin-top: 0;">안녕하세요!</p>
    <p style="color: #555; line-height: 1.6;">
      아래 상품의 재입고 알림이 정상적으로 등록되었습니다.<br>
      재입고가 감지되면 즉시 이메일로 알려드리겠습니다.
    </p>
    <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 20px 0;">
      <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">모니터링 상품</p>
      <p style="margin: 0; font-weight: 600; color: #111;">${productDisplay}</p>
      <p style="margin: 6px 0 0; font-size: 12px; color: #9ca3af; word-break: break-all;">${shortUrl}</p>
    </div>
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-bottom: 20px;">
      <p style="margin: 0; font-size: 14px; color: #166534;">
        ✅ 15~20분 간격으로 자동 모니터링이 시작되었습니다.
      </p>
    </div>
    <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 20px 0;">
    <p style="font-size: 12px; color: #9ca3af; margin: 0;">
      알림을 더 이상 받고 싶지 않다면 <a href="${unsubscribeUrl}" style="color: #9ca3af;">여기</a>를 클릭하여 구독을 취소하세요.
    </p>
  </div>
</body>
</html>
  `.trim();

  await transporter.sendMail({
    from: `"스마트스토어 재입고 알리미" <${process.env.GMAIL_USER}>`,
    to,
    subject: `[재입고 알리미] ${productDisplay} 모니터링 등록 완료`,
    html,
  });
}

import { NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";

const TIMEOUT_MS = 180_000;

function isScrapeUiAllowed(): boolean {
  if (process.env.ENABLE_SCRAPE_UI === "true") return true;
  return process.env.NODE_ENV !== "production";
}

/**
 * 로컬 개발용: Python check_stock.py 를 실행하고 stdout/stderr 로그를 반환합니다.
 * 프로덕션에서는 ENABLE_SCRAPE_UI=true 일 때만 허용합니다.
 */
export async function POST() {
  if (!isScrapeUiAllowed()) {
    return NextResponse.json(
      { error: "이 API는 로컬 개발 또는 ENABLE_SCRAPE_UI 설정 시에만 사용할 수 있습니다." },
      { status: 403 }
    );
  }

  const root = process.cwd();
  const scriptPath = path.join(root, "scripts", "check_stock.py");

  const log = await new Promise<string>((resolve, reject) => {
    const child = spawn("python", [scriptPath], {
      cwd: root,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        FORCE_COLOR: "0",
      },
      windowsHide: true,
    });

    const chunks: Buffer[] = [];
    child.stdout?.on("data", (d: Buffer) => chunks.push(d));
    child.stderr?.on("data", (d: Buffer) => chunks.push(d));

    const t = setTimeout(() => {
      try {
        child.kill("SIGTERM");
      } catch {
        /* ignore */
      }
    }, TIMEOUT_MS);

    child.on("error", (err) => {
      clearTimeout(t);
      reject(err);
    });

    child.on("close", (code) => {
      clearTimeout(t);
      const text = Buffer.concat(chunks).toString("utf8");
      resolve(
        text +
          (code !== 0
            ? `\n\n[프로세스 종료 코드: ${code}]`
            : `\n\n[프로세스 정상 종료]`)
      );
    });
  }).catch((err: Error) => {
    return `실행 오류: ${err.message}\n(Windows 에서는 터미널에서 'python scripts/check_stock.py' 가 되는지 확인하세요.)`;
  });

  return NextResponse.json({ log });
}

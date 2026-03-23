# 🛍️ 스마트스토어 재입고 알리미

네이버 스마트스토어 품절 상품이 재입고되면 이메일로 즉시 알려주는 웹 서비스입니다.

## 아키텍처

```
[Next.js 웹 앱 — Vercel]   ← 사용자 URL/이메일 등록
        ↓
[Supabase — PostgreSQL]    ← 등록 정보 저장
        ↑
[GitHub Actions — Python]  ← 15~20분 간격 자동 모니터링
        ↓
[Gmail SMTP]               ← 재입고 시 이메일 알림 발송
```

## 설치 및 배포 가이드

### 1단계 — Supabase 데이터베이스 설정

1. [supabase.com](https://supabase.com) 에서 무료 계정 생성
2. 새 프로젝트 생성
3. **SQL Editor** 에서 `supabase/schema.sql` 내용을 붙여넣고 실행
4. **Settings > API** 에서 아래 값을 복사해둡니다:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` 키 → `SUPABASE_SERVICE_KEY`

### 2단계 — Gmail 앱 비밀번호 발급

1. [Google 계정](https://myaccount.google.com) 접속
2. **보안** > **2단계 인증** 활성화
3. **보안** > **앱 비밀번호** > 앱 선택: "메일", 기기: "Windows 컴퓨터"
4. 생성된 16자리 비밀번호를 복사해둡니다 → `GMAIL_APP_PASSWORD`

### 3단계 — GitHub 저장소 설정

1. GitHub 에서 새 저장소 생성 (public 권장: Actions 무제한 무료)
2. 이 코드를 해당 저장소에 push

```bash
git init
git add .
git commit -m "초기 커밋"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

3. **Settings > Secrets and variables > Actions** 에서 아래 Secrets 추가:

| Secret 이름 | 값 |
|------------|-----|
| `SUPABASE_URL` | Supabase Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 |
| `GMAIL_USER` | 발신 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 |
| `BASE_URL` | Vercel 배포 URL (예: `https://your-app.vercel.app`) |

### 4단계 — Vercel 배포

1. [vercel.com](https://vercel.com) 에서 GitHub 저장소 연결
2. **Environment Variables** 에 아래 값 추가:

| 변수명 | 값 |
|--------|-----|
| `SUPABASE_URL` | Supabase Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 |
| `GMAIL_USER` | 발신 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 |
| `NEXT_PUBLIC_BASE_URL` | Vercel 배포 URL |

3. **Deploy** 클릭

### 5단계 — 동작 확인

1. Vercel 배포 URL 접속하여 상품 URL + 이메일 등록
2. GitHub **Actions** 탭에서 워크플로우가 15분마다 실행되는지 확인
3. 수동 실행: Actions > "재고 모니터링" > "Run workflow"

## 로컬 개발

네이버는 **데이터센터 IP**(GitHub Actions, Vercel 등)를 차단하는 경우가 많습니다.  
**집·사무실 PC**에서 Python 스크립트를 돌리면 `429` 없이 스크래핑될 가능성이 높습니다.

### 웹 UI + 환경변수

```bash
npm install
cp .env.example .env.local   # 값 수정
npm run dev                  # http://localhost:3000
```

`.env.local` 에 `SUPABASE_*`, `GMAIL_*`, `NEXT_PUBLIC_BASE_URL=http://localhost:3000` 를 넣습니다.  
Python 스크립트는 **프로젝트 루트의 `.env.local`** 을 자동으로 읽습니다.

> Python 쪽 DB 접속은 `supabase` 패키지 대신 **PostgREST + `requests`** 만 사용합니다.  
> (Windows 에서 최신 `supabase-py` 가 `pyiceberg` C++ 빌드를 요구해 설치가 실패하는 경우가 있어 제거했습니다.)

### 재고 확인 (1회)

```bash
pip install -r scripts/requirements.txt
playwright install chromium
npm run monitor:once
# 또는: python scripts/check_stock.py
```

### 재고 확인 (15~20분 간격 반복)

```bash
npm run monitor:local
# 또는: python scripts/run_local_monitor.py
```

터미널 2개 권장: 하나는 `npm run dev`, 다른 하나는 `npm run monitor:local`.

## 파일 구조

```
smartstore-stock-alarm/
├── .github/workflows/
│   └── check_stock.yml        # GitHub Actions 스케줄러
├── app/
│   ├── api/
│   │   ├── register/route.ts  # 알림 등록 API
│   │   └── unsubscribe/[token]/route.ts  # 구독취소 API
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx               # 메인 페이지
├── lib/
│   ├── supabase.ts            # Supabase 클라이언트
│   └── email.ts               # 이메일 전송 (nodemailer)
├── scripts/
│   ├── check_stock.py         # 재고 확인 (CI / 로컬 공통)
│   ├── run_local_monitor.py   # 로컬 15~20분 반복 모니터링
│   └── requirements.txt
├── supabase/
│   └── schema.sql             # DB 스키마
└── .env.example               # 환경변수 예시
```

## 주의사항

- 네이버 스마트스토어 URL (`smartstore.naver.com`) 만 등록 가능합니다.
- 15~20분 간격으로 모니터링하므로 재입고 후 최대 20분 이내에 알림이 발송됩니다.
- Gmail은 하루 약 500~2,000건의 발송 한도가 있습니다. 대규모 서비스라면 SendGrid 등 전문 이메일 서비스 도입을 검토하세요.
- 이 서비스는 네이버와 무관한 독립 서비스입니다.

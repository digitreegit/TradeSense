# TradeSense v2

**쌀 때 사고, 비쌀 때 판다.** — $3,000 소액 계좌를 위한 일봉 기반 자동매매.

## 계정 / 프로젝트 매핑

| 구분 | GitHub | Vercel 팀 | 비고 |
|------|--------|-----------|------|
| **TradeSense** (이 프로젝트) | `digitreegit/TradeSense` | `digitreegits-projects` | 개인 |
| RuleFive | `digitreegit/rulefive` | `digitreegits-projects` | 개인 |
| MyPasswordVault | `digitreegit/...` | `digitreegits-projects` | 개인, Supabase는 SKYFACE 유료 |
| Iris ID | `hoyong-irisid/...` | 별도 | 회사 — 여기와 섞지 말 것 |

**Supabase**: TradeSense 상태 저장은 **Supabase Postgres** (`tradesense` / `brrkttqxtacivbfaitbe`).
Vercel에서는 `DATABASE_URL`(Transaction pooler URI)이 **필수** — 없으면 대시보드에
저장소 오류가 표시되고 상태가 유지되지 않습니다. (Blob 백엔드는 제거됨.)
SKYFACE 유료(`hoyong@skyface.com`)는 MyPasswordVault 전용.

---

## 전략 (3 슬리브)

| 슬리브 | 로직 | 빈도 |
|---|---|---|
| 모멘텀 로테이션 | ETF·메가캡 3개월 수익률 상위 3개 | 주 1회 |
| 딥바이 | 200일선 위 + RSI(2)<10 과매도 | 매일 |
| 방어 추세 | GLD/TLT/IEF 50EMA 추세 (크립토 비활성 기본값) | 매일 |

---

## 배포 (Vercel + cron-job.org)

RuleFive와 **동일 패턴**. Vercel 내장 크론은 Hobby에서 제한이 있어서 쓰지 않음.

### 1) Alpaca 키
- **실거래 전용** — 라이브 키(`AK…`)만 사용. 페이퍼 키(`PK…`)는 거부됨
- 발급: https://app.alpaca.markets/dashboard/overview → API Keys
- **$99 데이터 구독 불필요** — IEX 무료 피드 사용

### 2) Vercel (digitreegit 팀)
```bash
cd v2
npx vercel link --project tradesense --scope digitreegits-projects
npx vercel env add ALPACA_API_KEY production
npx vercel env add ALPACA_SECRET_KEY production
npx vercel env add CRON_SECRET production      # openssl rand -hex 32
npx vercel env add ADMIN_TOKEN production      # 대시보드 접속 토큰 (openssl rand -hex 16)
# Supabase → Project Settings → Database → URI (Transaction pooler, port 6543)
npx vercel env add DATABASE_URL production
npx vercel deploy --prod --yes
```

`DATABASE_URL`은 Vercel에서 필수입니다 (로컬은 SQLite 자동 사용).
대시보드·설정 API는 `ADMIN_TOKEN`으로 보호되며, 첫 접속 시 브라우저가 토큰을 물어봅니다.

### 3) 스케줄러 — cron-job.org (무료, RuleFive와 동일)
- https://cron-job.org → Create cronjob
- URL: `https://tradesense.skyface.com/api/cron/run` (도메인 연결 전: `https://tradesense-lyart.vercel.app/api/cron/run`)
- 주기: **매 15분**
- Headers: `Authorization: Bearer <CRON_SECRET>`
- Test run → 200 + `{"ok":true,"results":{...}}` 확인

### 4) 도메인 (tradesense.skyface.com)
```bash
npx vercel domains add tradesense.skyface.com
# DNS: tradesense CNAME → cname.vercel-dns.com
```

### 5) 로컬 개발
```bash
cd v2
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8000
```
로컬은 APScheduler가 잡을 직접 실행, 상태는 SQLite.

---

## 백테스트

```bash
.venv/bin/python scripts/run_backtest.py --start 2015-06-01 --trade-start 2016-06-01
# 크립토 허용 지역의 대체 슬리브
.venv/bin/python scripts/run_backtest.py --crypto
```

기본 백테스트는 라이브 기본값과 동일하게 크립토 없이 방어 슬리브를 사용합니다.
Yahoo 조정주가·현재 유니버스를 사용하므로 생존편향이 있고, 과거 성과는 미래를
보장하지 않습니다. 배포 전 여러 시작 연도와 SPY 벤치마크를 함께 비교하세요.

---

## 구조

```
v2/
  app/
    main.py       # FastAPI + /api/cron/run (RuleFive 패턴)
    engine.py     # 매매 잡
    decisions.py  # 백테스트·라이브 공용 의사결정
    broker.py     # Alpaca
    state.py      # Supabase Postgres (프로덕션) / SQLite (로컬)
  api/index.py    # Vercel serverless 진입점
  vercel.json
  scripts/run_backtest.py
```

**삭제할 것**: `hoyong-irisid/tradesense-scheduler` — 잘못 만든 별도 레포. GitHub에서 삭제.

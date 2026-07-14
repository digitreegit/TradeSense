# TradeSense v2

**쌀 때 사고, 비쌀 때 판다.** — $3,000 소액 계좌를 위한 일봉 기반 자동매매.

## 계정 / 프로젝트 매핑

| 구분 | GitHub | Vercel 팀 | 비고 |
|------|--------|-----------|------|
| **TradeSense** (이 프로젝트) | `digitreegit/TradeSense` | `digitreegits-projects` | 개인 |
| RuleFive | `digitreegit/rulefive` | `digitreegits-projects` | 개인 |
| MyPasswordVault | `digitreegit/...` | `digitreegits-projects` | 개인, Supabase는 SKYFACE 유료 |
| Iris ID | `hoyong-irisid/...` | 별도 | 회사 — 여기와 섞지 말 것 |

**Supabase**: TradeSense는 Vercel Blob으로 상태 저장(무료, 이미 연결됨).
RuleFive/MyPasswordVault처럼 Postgres가 필요하면 `hoyongsupa@gmail.com` 무료 Supabase를 쓰면 됨.
SKYFACE 유료(`hoyong@skyface.com`)는 MyPasswordVault 전용.

---

## 전략 (3 슬리브)

| 슬리브 | 로직 | 빈도 |
|---|---|---|
| 모멘텀 로테이션 | ETF·메가캡·금·채권 유니버스 상위 3개 | 주 1회 |
| 딥바이 | 200일선 위 + RSI(2)<10 과매도 | 매일 |
| 크립토 추세 | BTC/ETH 50EMA 위 | 매시간 |

---

## 배포 (Vercel + cron-job.org)

RuleFive와 **동일 패턴**. Vercel 내장 크론은 Hobby에서 제한이 있어서 쓰지 않음.

### 1) Alpaca 키
- 페이퍼: https://app.alpaca.markets/paper/dashboard/overview → API Keys
- **$99 데이터 구독 불필요** — IEX 무료 피드 사용

### 2) Vercel (digitreegit 팀)
```bash
cd v2
npx vercel link --project tradesense --scope digitreegits-projects
npx vercel env add ALPACA_API_KEY production
npx vercel env add ALPACA_SECRET_KEY production
npx vercel env add CRON_SECRET production      # openssl rand -hex 32
npx vercel env add TRADING_MODE production     # paper
npx vercel deploy --prod --yes
```

`BLOB_READ_WRITE_TOKEN`은 Vercel Blob 스토어 연결 시 자동 주입됨.

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
```

2016~2026, $3K 시작: CAGR 27.3%, MDD -22.8%, Sharpe 1.37 (SPY 대비 우수).
과거 성과 ≠ 미래 보장.

---

## 현재 장애: `broker unavailable: unauthorized`

Vercel에 올라간 Alpaca 키가 **만료/무효** 상태입니다.
페이퍼 대시보드에서 키를 재발급한 뒤 Vercel env를 갱신하고 재배포하세요.

```bash
npx vercel env rm ALPACA_API_KEY production -y && npx vercel env add ALPACA_API_KEY production
npx vercel env rm ALPACA_SECRET_KEY production -y && npx vercel env add ALPACA_SECRET_KEY production
npx vercel deploy --prod --yes
```

---

## 구조

```
v2/
  app/
    main.py       # FastAPI + /api/cron/run (RuleFive 패턴)
    engine.py     # 매매 잡
    decisions.py  # 백테스트·라이브 공용 의사결정
    broker.py     # Alpaca
    state.py      # Vercel Blob (프로덕션) / SQLite (로컬)
  api/index.py    # Vercel serverless 진입점
  vercel.json
  scripts/run_backtest.py
```

**삭제할 것**: `hoyong-irisid/tradesense-scheduler` — 잘못 만든 별도 레포. GitHub에서 삭제.

# TradeSense v3

**쌀 때 사고, 비쌀 때 판다.** — 주식은 Alpaca 자동매매, 크립토는 Robinhood 수동·승인 후 API 주문·자동 주문 + 분석 가이드.

## v3 변경점

- 대시보드 **탭 UI**: 기본 탭 **크립토 · 로빈후드** (풀화면), **주식 · Alpaca 자동** 탭은 equity/positions
- 로빈후드 **스크린샷 업로드** → AI가 보유·현금을 읽고 매수/매도 가이드 생성 (`OPENAI_API_KEY` 또는 `GOOGLE_API_KEY`)
- 거래 실행만 사용자, 확인 버튼으로 장부 반영

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
| 모멘텀 로테이션 | ETF·개별주 3개월 수익률 상위 3개, 2× 거래량+긴 윗꼬리 시 청산 | 주 1회 |
| 딥바이 | 200일선 위 + RSI(2)<10 + 평균 이상 거래량, 반등 4% 익절 | 매일 |
| 방어 추세 | GLD/TLT/IEF 50EMA 추세 (크립토 비활성 기본값) | 매일 |

개별주 유니버스는 메가캡 8개 + 고변동성 5개(AMD/PLTR/COIN/MSTR/SMCI)이며
ETF 슬롯의 65%로 운용합니다. 고변동성 종목 추가는 2018/2020/2022/2023 시작
워크포워드에서 메가캡 단독 대비 CAGR·샤프를 개선했습니다
(`scripts/compare_universe.py`). 같은 종목에 대한 ±1% 그리드(RuleFive식
역행매매)는 모든 기간에서 손실이라 기각했습니다(`scripts/grid_sim.py`).

장중 신규 진입은 하지 않고 전일 종가 신호를 다음 정규장 개장 후 실행하므로,
09:30 전 추격매수와 점심시간 횡보 매매는 구조적으로 배제됩니다. 뉴스는 신규
매수 크기/회피에만 사용하며, 확인되지 않은 헤드라인만으로 보유 포지션을 강제
청산하지 않습니다.

### 크립토 어드바이저 (Robinhood · 수동 / semi / auto)

Robinhood 공식 Crypto Trading API가 연결되어 있으면 다음 실행 모드를 지원합니다.

- `manual`: 안내를 보고 Robinhood에서 직접 거래한 뒤 체결 확인.
- `semi`: TradeSense에서 승인하면 API로 주문.
- `auto`: 스케줄러가 매도 우선으로 회당 최대 매도 2개·매수 1개를 실행.

[Robinhood 공식 안내](https://robinhood.com/us/en/support/articles/crypto-api/)에 따라
웹 classic의 crypto account settings에서 조회 및 주문 권한이 있는 키를 만들고
TradeSense 설정에서 연결합니다. 비밀 키는 채팅이나 소스 코드에 넣지 않습니다.
계좌와 코인별 API 지원을 확인하며, 앱에서 거래 가능한 코인도 API에서는 제한될 수
있습니다. v1과 v2는 주문 비용·거래량 집계 방식이 다릅니다.

뉴저지에서 자동거래가 일괄 금지된다는 설명은 부정확합니다. Alpaca 공식 자료도
[시작 안내](https://alpaca.markets/learn/getting-started-with-alpaca-crypto-api)에는 NJ를
포함하지만 오래된 지원 FAQ에는 누락되어 있어, 본인 계좌의 crypto 승인 상태를
확인해야 합니다. `CRYPTO_ENABLED`는 계좌 자격 확인 후에만 변경합니다.

점검은 24시간 15분 간격의 스케줄러 tick 기준입니다. Telegram만 00–06시 ET에
조용하게 유지합니다. 거래소에 상주하는 손절 주문이나 연속 감시를 의미하지 않습니다.

로직: 일차 목표는 원금 회복. 상승 추세 코인 중 30일 수익률(상대강도) 상위,
RuleFive식 step 운영 — 평단 대비 15% 이상 손실이면 물타기 금지, 편중(35%+)은
단계적 축소 후 상대강도 재배치, 현금 15% 유지.

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

## 2026-09-06 전략 실행 수정

- 주식의 주간 경계를 ISO 주차로 계산: 월요일 휴장 시 화요일 개장 주문도 생성.
- 휴장일·지연 데이터로 당일 SPY 일봉이 없으면 기존 주문 대기열과 보유 일수를 보존.
- 크립토는 완료된 UTC 일봉으로 추세 지표 계산. 실시간 가격은 별도로 사용.
- 추가 매수와 최소 주문액에도 코인별 35% 비중 상한 적용.
- 일봉이 없는 보유 코인도 신선한 Robinhood 시세가 있으면 손절·추적 손절 검사.

검증: `python -m pytest tests -q`. 과거 데이터는 현재 유니버스와 Yahoo 조정주가를
사용하며, 실계좌의 실제 체결·입출금·스프레드를 대체하지 않습니다. 이 수정은
주문 누락과 위험 통제 오류를 해결하며 승률이나 수익 향상을 보장하지 않습니다.

### 크립토 자동 운용 준비 및 오프라인 검증

신규·추가·재배치 매수 모두 상승 추세, 양수 30일 수익률, 현재가가 50EMA 위,
RSI 75 미만을 요구합니다. 실행 모드는 자동으로 바뀌지 않습니다.

캐시된 BTC/ETH만으로 다음 개장가 체결과 비용을 확인하는 도구:

```bash
python scripts/check_crypto_strategy.py --start 2024-01-01 --cost-bps 50
python scripts/check_crypto_strategy.py --start 2022-01-01 --cost-bps 100
# 연구 전용 비교: 단계별 그리드 익절 없이 추세 보유
python scripts/check_crypto_strategy.py --start 2024-01-01 --cost-bps 50 --hold-trend
```

`--hold-trend`는 해당 오프라인 프로세스에서만 적용됩니다. 라이브 기본값은 유지합니다.
이 도구는 15분 리스크 점검, 실제 호가/체결 지연, 확인 쿨다운, 다른 보유 코인을
재현하지 않습니다. 승률은 부분 매도를 포함한 매도 체결별 비율이며, 실제 계좌
승률이나 전략의 검증 완료를 뜻하지 않습니다. 비용은 가정값이지 Robinhood의
실제 계좌별 요율이 아닙니다. 단일 구간 결과로 라이브 파라미터를 선택하지 않습니다.

### 주문 History와 전체 잔고 대조

크립토 탭 하단에 Robinhood 최근 주문(v1/v2 중복 제거), TradeSense 추천 상태,
자동 점검 활동을 펼쳐 표시합니다. 부분 체결은 실제 체결분만 금액에 포함합니다.
`GET /api/crypto/activity`는 주문을 생성하지 않는 조회 전용 API입니다.

Crypto API의 합계는 크립토 보유 + Buying power입니다. Individual 전체 잔고에는
주식·기타 계좌 항목이 포함될 수 있으므로 동일한 값이 아닙니다. '전체 잔고 맞추기'에
같은 시점의 Individual 잔고, 크립토 운용 합계, 주식 평가액을 입력하면 차액을
분류 미확인 항목으로 저장하고 전체 추정 잔고를 표시합니다. 대조 후 크립토 합계는
API와 함께 변하지만 주식·차액은 고정값이므로 해당 항목 변경 시 다시 대조해야 합니다.
이 값은 표시 전용이며 `crypto_book`의 cash, 주문 크기, 위험 계산에는 사용하지 않습니다.

### 주식 실행 점검 ($500)

Alpaca 일봉은 `adjustment=all`로 요청해 분할·배당으로 인한 지표 왜곡을 방지합니다.
개장 매수에서 일봉 또는 ATR이 없으면 주문을 삭제하지 않고 다음 tick에 재시도합니다.
백테스트 결과에는 평균 현금 비중(`avg_cash_weight`)도 포함합니다.

빈 모멘텀 자리를 매일 채우는 안은 연구용으로만 남겨 기본값은 끕니다.
캐시된 현재 유니버스, 초기 $500, 편도 비용 5bps 기준으로 2018/2022/2024/2026
시작 구간 모두 기존 주간 진입보다 최종 평가액이 낮았습니다. 2026-01-02부터
2026-08-13까지 기존은 $580.20, 매일 보충은 $559.98, SPY는 $571.77입니다.
기존 방식의 해당 구간 평균 현금 비중은 27.70%입니다.

```bash
python scripts/compare_equity_refill.py
python scripts/compare_equity_refill.py --starts 2024-01-01 2026-01-01 --cost-bps 20
```

과거 캐시는 실계좌 체결 기록이 아닙니다. 현재 종목 구성의 생존편향, Yahoo/IEX
시세 차이, 실제 스프레드·개장 체결 지연·장중 손절·뉴스 제한 등 때문에 실거래와
달라질 수 있습니다. 이번 실행 오류 수정 자체의 수익 개선량은 이 비교로 측정하지
못합니다. 실계좌가 정체된 원인 확정에는 실제 계좌·주문 기록이 필요합니다.

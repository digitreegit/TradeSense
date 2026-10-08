# TradeSense v5

**주식: x% 내리면 1칸 사고, x% 오르면 1칸 판다. 크립토: 24h 고점 대비 x% 내린 코인을 $N 사고, +x%에 판다. 반복.**
— 크립토는 Robinhood, 주식은 Alpaca, 전부 자동.

## 규칙을 바꾸는 방법 (v5.1 — 감이 아니라 근거로)

[bennyjo/phil](https://github.com/bennyjo/phil)에서 가져온 네 가지 습관. 전략은 가져오지 않았다
(예측시장 베팅이고, 70일 성적이 −6.8%·시장 대비 뒤처짐).

1. **기준선 대비 채점.** 대시보드 "채점표"는 같은 기간의 전략 수익률을 **그냥 보유(BTC/ETH, SPY)**·현금(0%)과 나란히 놓는다.
   전략이 보유보다 못하면 규칙이 아니라 시장이 번 것이다.
2. **운 보정.** 실현 손익 중 상위 2건의 비중을 표시한다. 50%를 넘으면 그 결과로 아무것도 결론 내리지 않는다.
3. **같은 데이터로 스윕 후 변경.** 간격·하락 %·매수 금액을 바꾸기 전에 `scripts/dip_replay.py`(크립토 180일 시간봉 / 주식 365일 일봉)로
   3/5/8/10%와 후보 변형을 돌리고, 세 구간(앞/중/뒤)에서 **모두** 버티는 쪽을 고른다. 전체 합계가 가장 큰 쪽이 아니라.
4. **보호된 엔진 vs 편집 가능한 파라미터.** 화면에서 바꿀 수 있는 건 간격·하락 %·매수 금액뿐이고, 저장할 때 **근거를 반드시 적는다**
   (`/api/grid/settings`의 `reason`, 설정 탭 "파라미터 변경 기록"). 칸 수·체결 방식·틱당 매수 상한·잔량 처리 같은 엔진은
   코드에 고정되어 있고, 바꾸려면 재생 결과를 이 README의 결정 기록에 먼저 남긴다.
   모든 체결에는 당시 파라미터 해시 `rev`가 찍히고, 채점표가 rev별 실현 손익을 나눠 보여 준다.

### 결정 기록

**2026-10-08 — 현재 숫자의 근거 (`scripts/dip_replay.py crypto`, 21코인 시간봉 2026-04-11→10-08, 왕복 1% 비용, 매도는 호가가 목표가에 닿아야 체결)**

| 변형 (하락 5%) | 180일 | maxDD | 세 구간 | 미결 랏 최악 | 비고 |
|---|---|---|---|---|---|
| 지금 규칙(보유) | +56% | −26% | −4 / +2 / **+61** | −25% | 수익이 마지막 구간 랠리에 몰림 |
| 하락 8% | +48% | −25% | −13 / +8 / +58 | −22% | 5%보다 모든 창에서 뒤짐 |
| −10%면 기준가 재설정(reanchor10) | +47% | −23% | +5 / +17 / +20 | −12% | 세 구간 모두 +, 추가 주문 없음 |
| −10% 손절 후 재무장(stop10) | +48% | −23% | +6 / +21 / +16 | −9% | reanchor와 같은 효과, 왕복 비용 1% 추가 |
| 14일 지나면 정리(time14) | +54% | −23% | +1 / +20 / +28 | −19% | |
| 투입 50% 상한(cap50) | +27% | −16% | −4 / +12 / +18 | −25% | 낙폭은 줄지만 수익 절반 |
| BTC 7일선 위에서만(regime7) | +42% | −22% | −11 / +6 / +50 | −25% | 필터 효과 없음 |
| 같은 기간 동일가중 보유 | +18.5% | | | | BTC +13% · ETH +13% |

매수 금액 $500/$1,000/$1,500/$2,000(time14 기준): +33 / **+54** / +36 / +55 — $1,000 유지.
라이브와 같은 최근 6일(10-02→10-08)은 시장 −6.8%에 규칙 +0.6%; 실제 계좌는 −10%라 **차이 원인(소형 코인 LIT 등, 15분 간격 매수 속도) 대조 중**.

**주식 (`scripts/dip_replay.py stocks --grid`, 365일 일봉, $1,050)**

| 유니버스 | 보유(동일가중) | v4 그리드 5% | 하락매수 5% reanchor10 |
|---|---|---|---|
| 현재 (AMD/COIN/MSTR/SMCI/PLTR/TSLA) | +5.8% | **−8.9%** (maxDD −28%) | −21% |
| 대형주 10 (AAPL…NVDA) | +24.5% | +9.9% (maxDD −7%) | +21.5% (maxDD −10%) |
| ETF 7 (TQQQ/SOXL/SPY/QQQ…) | +59.8% | +11.3% (maxDD −8%) | +20.6% (maxDD −22%) |

주식 정체의 원인은 간격이 아니라 **유니버스**(COIN·MSTR −54%). 어떤 간격으로도 현재 유니버스는 마이너스.

채택/기각은 사용자 결정 후 여기에 추가한다.

## v4 변경점

- 전략을 **단일 규칙 그리드**로 교체. 모멘텀/딥바이/방어추세, 크립토 어드바이저(승인·반자동)는 스케줄에서 내렸다.
- 사용자 설정은 **간격(step) 하나**. 매수·매도 공용, 대시보드에서 1~25% 사이로 변경.
- 대시보드는 **그리드 / 설정** 두 탭. 종목별 사다리(칸 수, 다음 매수·매도가, 실현/미실현), 체결 내역, 활동 로그.
- Robinhood API로 주문할 수 없는 코인(예: XRP)은 그리드에서 제외하고 “수동 보유”로만 표시.

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

## 전략 (v4 그리드)

코드: `app/grid.py`(규칙) · `app/grid_engine.py`(청산→시딩→운영 틱, 브로커 어댑터).

- 종목별 자본을 **5칸**으로 나눈다(`unit_dollars`, 시작 시 현금의 95%를 종목 수 × 5로 분할).
- 시작: **3칸** 시장가 매수 → 기준가 = 체결가.
- 보유 중: 현재가 ≥ 기준가×(1+step)이면 **최근 칸 1개 매도**, 현재가 ≤ 기준가×(1−step)이면 **1칸 매수**(5칸까지). 체결마다 기준가 갱신.
- 전량 매도 후: 기준가는 마지막 매도가에 머물고, 거기서 step 아래로 내려오면 다시 1칸 매수(RuleFive 원형. `grid.FOLLOW_HIGH=True`로 바꾸면 신고가 추종).
- 틱마다 종목당 1건, 매도 먼저(현금 확보 후 매수). 15분 간격, 주식은 장중만, 크립토는 24시간.
- 앱에서 수동 매도하면 사다리를 위에서부터 줄이고, 장부에 없는 수량은 현재가 1칸으로 편입한다(`grid.reconcile`).

유니버스: 크립토 `BTC/ETH/SOL`(Robinhood `is_api_tradable`인 것만), 주식 `AMD/COIN/MSTR/SMCI/PLTR/TSLA`(Alpaca fractionable인 것만).

### 재생 결과 (`scripts/grid_replay.py`, 일봉·하루 1건·보수적 비용)

2024-09 시작, 크립토 $8,000 / 주식 $500:

| step | 크립토 총수익 | 크립토 maxDD | 주식 총수익 | 주식 maxDD |
|---|---|---|---|---|
| 5% | +17% | −14% | +24% | −8.5% |
| 8% | +21% | −14% | +31% | −8.2% |
| 10% | +23% | −12% | +30% | −8.4% |

같은 기간 동일가중 보유는 크립토 −14.5%, 주식 +127%. 그리드는 횡보·왕복 구간에서 벌고
한 방향 추세에서는 보유보다 뒤진다. 2025-09처럼 시작 직후 −50% 급락이 오면 5칸이 다 채워진 채
−40% 근처까지 밀린다(장기 보유형 손실 상한 = 배분 자본). 기본 step은 8%.

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

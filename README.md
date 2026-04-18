# TradeSense 🚀
## AI-Powered Quant Trading Platform

TradeSense는 AI 기반 주식 분석 및 자동 퀀트 트레이딩 웹 플랫폼입니다.

### ✨ 주요 기능
- **📊 실시간 차트**: 캔들스틱 차트 + 기술적 지표 (MA, RSI, MACD, BB)
- **🤖 AI 분석 에이전트**: GPT-4o / Gemini 기반 주식 분석
- **⚡ 자동 트레이딩**: 퀀트 전략 기반 자동매매 봇
- **💼 포트폴리오 관리**: 실시간 포지션 추적 및 P&L 모니터링
- **📝 Paper Trading**: Alpaca Markets API를 통한 안전한 가상매매

### 🛠️ 기술 스택
- **Frontend**: React 18 + Vite + TypeScript
- **Backend**: Python FastAPI
- **Trading API**: Alpaca Markets (Paper Trading)
- **AI**: OpenAI GPT-4o / Google Gemini
- **State**: Zustand

---

## 🚀 Quick Start

### 1. 환경 설정
```bash
# .env 파일 생성
cp .env.example backend/.env

# API 키 설정 (편집기로 열어서 수정)
# - ALPACA_API_KEY / ALPACA_SECRET_KEY
# - OPENAI_API_KEY 또는 GOOGLE_API_KEY
```

### 2. Backend 실행
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend 실행
```bash
cd frontend
npm install
npm run dev
```

### 4. 브라우저에서 접속
```
http://localhost:5173
```

---

## ⚠️ Important Notes
- **Paper Trading Only**: 반드시 API 키가 Paper Trading 모드인지 확인하세요
- **PDT Rule**: $25,000 미만 계좌는 5일간 3회 이상 당일매매 불가
- **Risk**: 자동매매는 항상 위험을 수반합니다. 충분한 테스트 후 사용하세요

## ⚙️ Scalping safeguards (v4)

실거래 전 반드시 확인:

- **Cash-account GFV tracking** — `compliance_service` tags every buy and blocks
  sells of lots bought with unsettled proceeds. Rolling 12-month GFV counter
  exposed at `/api/regime/status` (`gfv_level`: OK → NOTICE → WARNING → RESTRICTED).
- **Wash-sale cooldown** — 30-day block on re-entering the same symbol after a
  realized loss. Realized trades are persisted as JSONL to `TRADESENSE_LOG_DIR`
  for 1099-B reconciliation.
- **Event blackout** — hard-coded 2026 FOMC / CPI / NFP schedule in
  `event_calendar`, plus opening-auction (9:30–9:35 ET) and closing-auction
  (15:58–16:00 ET) no-entry windows.
- **Quantitative Market Status** — `regime_service` pulls VIXY / TLT / UUP / GLD /
  XLE / BITO / SPY bars and emits a composite 0–100 score that deterministically
  maps to a risk preset (see `core.risk_presets`).
- **Risk presets** — Conservative / Moderate / Aggressive, driven by Market
  Status score. Override at `POST /api/trading/bot/start` with
  `{"risk_level": "conservative"}`.
- **Trailing high-water mark** — per-position peak P&L kept in-memory so a move
  from +0.7 % back to +0.3 % triggers a trail exit (didn't previously).
- **Marketable-limit orders + spread filter** — every outgoing order goes
  through `execution_service`; symbols wider than the preset's
  `spread_filter_percent` are skipped.
- **Loss-streak cooldown** — 3 consecutive losses → 15-minute pause on new
  entries.
- **Streaming scaffold** — `streaming_service.start_streaming(...)` wires
  Alpaca's WebSocket trades into an in-memory `LATEST` map. Enable once
  deployed to `us-east` and running against the SIP feed to hit the 100 ms
  latency target.

새 엔드포인트:

- `GET /api/regime/status` — 종합 Market Status + 활성 preset + compliance
- `GET /api/regime/presets` — 세 프리셋 전체 파라미터 표

## 📄 License
MIT

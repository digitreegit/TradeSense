# TradeSense — 개발 메모 (한 곳에서 확인)

이 파일에 **최근에 무엇이 바뀌었는지**, **환경 변수를 어디에 두는지**, **로컬에서 어떻게 검증하는지**만 모아 둡니다.

---

## 최근 변경 요약 (`cursor/notify-telegram-whatsapp-e1e8`)

| 날짜 (대략) | 내용 |
|-------------|------|
| 2026-04 | **라이브 잔고 불가 ↔ 사이드바 “연결됨” 불일치 수정** — PR #11 (`cursor/fix-live-connection-status-144a`) 내용을 이 브랜치에 **머지**함. `/api/account`가 `live_balances_unavailable: true`를 주면 `useMarketData`가 전역 `connected`를 `false`로 둠 (`frontend/src/hooks/useMarketData.ts`). |
| 2026-04 | **Vite `VITE_*` 이중 로드** — `frontend/vite.config.ts`에서 `loadEnv`로 **레포 루트 + `frontend/`** 둘 다 읽고 합침(같은 키면 `frontend/` 우선). 루트에만 두거나 `frontend/.env`에만 둬도 동작함. |
| 2026-04 | **`frontend/.gitignore` / `.env.example`** — 로컬 시크릿은 커밋하지 않도록 명시, 예시 파일에 주석 보강. |

---

## 환경 변수 (`VITE_*`는 루트 또는 `frontend/`)

1. 보통은 루트 `.env.example` → **프로젝트 루트** `.env` 한 번에 맞춤.  
   (`VITE_*`만 예전처럼 **`frontend/.env`**에만 있어도 됨 — 빌드가 양쪽을 합칩니다.)
2. **프론트 (브라우저)**  
   - `VITE_SUPABASE_URL`  
   - `VITE_SUPABASE_ANON_KEY`  
   → Supabase 대시보드 **Project Settings → API**의 URL / **anon public** 키와 **동일한 값**이면 됨 (`SUPABASE_URL` / `SUPABASE_ANON_KEY`와 같아도 됨).
3. **백엔드 (서버)**  
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, (선택) `SUPABASE_JWT_AUD`  
   - **`SUPABASE_JWT_SECRET`은 절대 `VITE_`로 넣지 말 것** — 클라이언트 번들에 노출되면 안 됨.

백엔드는 `backend/.env` 또는 **루트 `.env`** 중 먼저 찾은 파일을 읽습니다 (`backend/app/core/config.py`).

### 새 클론 / GitHub Codespaces / Cursor Cloud

- `.env`는 Git에 없음 → **반드시 로컬에서 `.env.example` → `.env` 복사 후 값 채우기.**  
- 그렇지 않으면 프론트에서 `supabase-url is required` 같은 오류가 날 수 있음.

### `frontend/.env`만 쓰는 경우

- 괜찮습니다. 루트 `.env`가 없어도 `VITE_*`는 `frontend/.env`에서 로드됩니다.  
- 루트에도 같은 키가 있으면 **`frontend/.env` 값이 우선**합니다.

---

## 검증 (로컬)

1. **프론트 타입·빌드**  
   `cd frontend && npm install && npm run build`
2. **백엔드 기동** (키가 있을 때)  
   `cd backend && … && uvicorn app.main:app --reload --port 8000`
3. **수동 스모크**  
   - 로그인 후 Settings에서 라이브 모드 선택 시, 잔고를 못 가져오면 경고 문구가 뜨고 사이드바는 **연결 끊김**으로 맞춰짐.

자동 E2E 테스트 스위트는 아직 없음; 위가 최소 검증 절차입니다.

---

## 관련 PR / 브랜치

- **PR #11** (`cursor/fix-live-connection-status-144a`): 위 라이브 잔고·연결 상태 수정의 원본 브랜치. 내용은 **`cursor/notify-telegram-whatsapp-e1e8`에 머지됨.**

문서나 설정을 바꿀 때 이 파일을 함께 업데이트하면 “한 곳에서” 히스토리를 추적하기 쉽습니다.

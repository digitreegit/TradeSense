import type { AppLocale } from '../stores/types';

export type UiStrings = {
  nav: { dashboard: string; chart: string; agent: string; trading: string; portfolio: string; history: string; settings: string };
  header: { marketOpen: string; marketClosed: string; paperTrading: string; signIn: string };
  sidebar: {
    tagline: string;
    sectionOverview: string; sectionMarket: string; sectionIntel: string; sectionAccount: string;
    signInRequired: string; keysRequired: string; connected: string; disconnected: string;
    apiQuotaError: string; resetIn: (s: number) => string;
  };
  userMenu: { account: string; settings: string; signOut: string };
  common: { loading: string; cancel: string; viewAll: string; manage: string; fullChart: string };
  auth: {
    title: string; subtitle: string; continueGoogle: string; redirecting: string;
    signInFailedGeneric: string; redirectingProgress: string;
  };
  dashboard: {
    regimeTitle: string; lastUpdated: string; reasoning: string; strategy: string; marketStatus: string;
    riskSetting: string; stopLoss: string; dailyPnL: string; focusSectors: string; fedPolicy: string; geopolitical: string;
    entryBlackout: (reason: string) => string; gfv: (level: string, count: string) => string;
    cooldown: (s: number, streak: number) => string; unsettled: (n: string) => string;
    portfolioValue: string; cashAvailable: string; buyingPower: string; activePositions: string; strategiesActive: (n: string) => string;
    botStatus: string; active: string; idle: string; eventsLogged: (n: string) => string; dailyScalping: string;
    performanceTitle: string; starting: (v: string) => string; todaysReturn: string;
    initialCapital: string; totalPL: string; openPositions: string; botActivity: string; running: string; stopped: string;
    stop: string; start: string; watchlist: string; activeStrategies: string; winRate: (n: string) => string;
    noPositionsBot: { title: string; sub: string };
    noPositions: { title: string; sub: string; cta: string };
    tableSymbol: string; tableQty: string; tableAvg: string; tableCurrent: string; tablePL: string;
  };
  trading: {
    title: string; subtitle: (eq: string) => string; running: string; stopped: string; idleLine: string; startBot: string; stopBot: string;
    strategies: string; manual: string; auto: string; autoHelp: string; activityLog: string; events: (n: string) => string;
    riskSettings: string; riskLocked: string; riskSaveHint: string; riskRunHint: string;
    riskLevel: string; conservative: string; moderate: string; aggressive: string; maxPos: (pct: string, cur: string) => string;
    stopLossL: (pct: string) => string; takeProfitL: (pct: string) => string; resetDefaults: string;
    configSummary: string; cap: string; strategyLine: (auto: string, s: string) => string; maxPer: string; sl: string; tp: string; rr: string; liveLockNote: string;
    sessionStats: string; totalTrades: string; winRate: string; winTrades: string; loseTrades: string; totalPnl: string;
    statusActive: string; statusIdle: string; statusManual: string; statusDisabled: string; manualPending: string; activeNow: string; winRateL: (n: string) => string;
  };
  portfolio: {
    totalEquity: string; cash: string; buyingPower: string; dailyPL: string; holdings: string; positions: (n: string) => string;
    noHoldings: { title: string; text: (amt: string) => string };
    thSymbol: string; thSide: string; thQty: string; thAvg: string; thCurrent: string; thMkt: string; thUnr: string; thPct: string;
    allocation: string; performance: string; cashLabel: string; totReturn: string; totPL: string; initCap: string; winR: string;
    avgWin: string; avgLoss: string; profitFactor: string; sharpe: string; pctCash: (p: string) => string;
  };
  history: { title: string; orders: (n: string) => string; emptyTitle: string; emptyText: string; thDate: string; thSymbol: string; thSide: string; thType: string; thQty: string; thPrice: string; thStatus: string; };
  chart: { loading: string; noData: string; };
  agent: { title: string; analyzeSym: (s: string) => string; marketOverview: string; tradingSignal: string; portfolioReview: string; riskReport: string; analyzing: string; placeholder: string; send: string; };
  settings: {
    settingsTitle: string; languageLabel: string; languageDescription: string; english: string; korean: string; languageEnglishSub: string; languageKoreanSub: string;
    appearanceLabel: string; appearanceDescription: string; dark: string; darkSub: string; light: string; lightSub: string; brokerSectionTitle: string;
    connectIntro: string; paperLink: string; liveLink: string; signedIn: string; keysOnFile: string; keysNotConfig: string; deleteKeys: string; deleting: string;
    tradingMode: string; tradingModeDesc: string; paperMoney: string; paperSub: string; realMoney: string; realSub: string; keysHintInactive: string;
    keyId: string; secret: string; saveKeys: string; saving: string; keysOnFileNote: string; liveAccount: string; loadingBalances: string; equity: string; cash: string; buyPower: string; portValue: string; liveLoadErr: string;
    capitalScale: string; capitalScaleDesc: string; telegram: string; telegramPStart: string; telegramPMid: string; telegramSetup: string; telegramPEnd: string; tgNotConfig: string; sendTg: string; telegramChatId: string; telegramChatPlaceholder: string; saveAlerts: string; sendTest: string; signOut: string; sending: string;
    deleteModalTitle: string; deleteModalBody: string; errSaveFirst: string; errPaperOnly: string; errDeleteFirst: string; errBothKeys: string; errKeysLocked: string; msgSwitchedPaper: string; msgSwitchedLive: string; modeChangeFail: string; notifSaved: string; notifSaveFail: string; testSent: (m: string) => string; testFail: string; scaleSwitched: (s: string, l: string) => string; scaleFail: string; keysSaved: string; saveFail: string; keysDeleted: string; deleteFail: string;
  };
  scale3k: { title: string; cap: string };
  scale10k: { title: string; cap: string };
  scale30k: { title: string; cap: string };
};

const en: UiStrings = {
  nav: { dashboard: 'Dashboard', chart: 'Live Chart', agent: 'AI Agent', trading: 'Trading Bot', portfolio: 'Portfolio', history: 'History', settings: 'Settings' },
  header: { marketOpen: 'Market Open', marketClosed: 'Market Closed', paperTrading: 'Paper Trading', signIn: 'Sign in' },
  sidebar: {
    tagline: 'AI Quant Trading',
    sectionOverview: 'OVERVIEW', sectionMarket: 'MARKET', sectionIntel: 'INTELLIGENCE', sectionAccount: 'ACCOUNT',
    signInRequired: 'Sign in required', keysRequired: 'Alpaca keys required', connected: 'Connected to Alpaca', disconnected: 'Disconnected',
    apiQuotaError: 'API quota: error (hover)', resetIn: (s) => ` · reset ~${s}s`,
  },
  userMenu: { account: 'Account', settings: 'Settings', signOut: 'Sign out' },
  common: { loading: 'Loading…', cancel: 'Cancel', viewAll: 'View all', manage: 'Manage', fullChart: 'Full chart' },
  auth: {
    title: 'Welcome to TradeSense',
    subtitle: 'Sign in with Google to continue',
    continueGoogle: 'Continue with Google',
    redirecting: 'Redirecting…',
    signInFailedGeneric: 'Google sign-in failed',
    redirectingProgress: 'Redirecting to Google…',
  },
  dashboard: {
    regimeTitle: 'AI Market Adaptive System', lastUpdated: 'Last updated:', reasoning: 'Reasoning:', strategy: 'Strategy:', marketStatus: 'Market status:', riskSetting: 'Risk setting:',
    stopLoss: 'Stop loss:', dailyPnL: 'Daily P&L:', focusSectors: 'Focus sectors:', fedPolicy: 'Fed policy', geopolitical: 'Geopolitical',
    entryBlackout: (r) => `⏸ Entry blackout: ${r || 'active'}`,
    gfv: (level, c) => `GFV ${level} (${c}/3 in 12mo)`,
    cooldown: (s, st) => `⏲ Cooldown ${s}s (loss streak ${st})`,
    unsettled: (n) => `Unsettled $${n} · T+1`,
    portfolioValue: 'Portfolio value', cashAvailable: 'Cash available', buyingPower: 'Buying power', activePositions: 'Active positions',
    strategiesActive: (n) => `${n} strategies active`, botStatus: 'Bot status', active: 'ACTIVE', idle: 'IDLE',
    eventsLogged: (n) => `${n} events logged`, dailyScalping: 'Daily scalping:',
    performanceTitle: 'Portfolio performance', starting: (v) => `Starting: ${v}`, todaysReturn: "Today's return",
    initialCapital: 'Initial capital', totalPL: 'Total P&L', openPositions: 'Open positions', botActivity: 'Trading bot activity', running: '● Running', stopped: '○ Stopped', stop: 'Stop', start: 'Start', watchlist: 'Watchlist', activeStrategies: 'Active strategies', winRate: (n) => `WR: ${n}%`,
    noPositionsBot: { title: 'Bot is running', sub: 'Scanning for entry signals… Positions will appear when opened.' },
    noPositions: { title: 'No open positions', sub: 'Start the trading bot or place a trade to open positions.', cta: '⚡ Start trading bot' },
    tableSymbol: 'Symbol', tableQty: 'Qty', tableAvg: 'Avg entry', tableCurrent: 'Current', tablePL: 'P&L',
  },
  trading: {
    title: 'TradeSense trading bot', subtitle: (eq) => `Automated quant trading · paper mode · capital: ${eq}`, running: '● Running', stopped: '○ Stopped', idleLine: '○ idle', startBot: 'Start bot', stopBot: 'Stop bot',
    strategies: 'Trading strategies', manual: 'Manual', auto: 'Auto', autoHelp: 'Engine routes playbooks (time + regime). Turn auto off to use only the ticked set below.',
    activityLog: 'Activity log', events: (n) => `${n} events`, riskSettings: 'Risk settings', riskLocked: 'Live (real money) mode: risk is fixed to the moderate server preset. You cannot change it here for safety.',
    riskSaveHint: 'Values are saved in this browser and apply when you start the bot.',
    riskRunHint: ' The running session keeps the previous engine settings — stop, adjust, then start again to apply new numbers.',
    riskLevel: 'Risk level', conservative: 'Conservative', moderate: 'Moderate', aggressive: 'Aggressive', maxPos: (pct, cur) => `Max position size: ${pct}% (${cur})`, stopLossL: (p) => `Stop loss: -${p}%`, takeProfitL: (p) => `Take profit: +${p}%`, resetDefaults: 'Reset to defaults',
    configSummary: 'Configuration summary', cap: 'Capital', strategyLine: (a, s) => `Strategy: ${a} · ${s}`, maxPer: 'Max per trade', sl: 'Stop loss', tp: 'Take profit', rr: 'Risk/reward', liveLockNote: 'Live: engine uses the moderate preset (client changes ignored).',
    sessionStats: 'Session stats', totalTrades: 'Total trades', winRate: 'Win rate', winTrades: 'Winning trades', loseTrades: 'Losing trades', totalPnl: 'Total P&L',
    statusActive: 'Currently active (auto)', statusIdle: 'Not active now (auto enables when conditions match)', statusManual: 'On for manual — click to disable', activeNow: '● Active now', winRateL: (n) => `WR: ${n}%`, statusDisabled: 'Off — click to enable for manual', manualPending: ' · manual queue',
  },
  portfolio: {
    totalEquity: 'Total equity', cash: 'Cash', buyingPower: 'Buying power', dailyPL: 'Daily P&L', holdings: 'Holdings', positions: (n) => (n === '1' ? '1 position' : `${n} positions`),
    noHoldings: { title: 'No holdings', text: (amt) => `Your portfolio is all cash. Start the trading bot for automated paper trading with ${amt}.` },
    thSymbol: 'Symbol', thSide: 'Side', thQty: 'Qty', thAvg: 'Avg entry', thCurrent: 'Current price', thMkt: 'Market value', thUnr: 'Unrealized P&L', thPct: '% change',
    allocation: 'Asset allocation', performance: 'Performance metrics', cashLabel: 'Cash', totReturn: 'Total return', totPL: 'Total P&L', initCap: 'Initial capital', winR: 'Win rate', avgWin: 'Avg win', avgLoss: 'Avg loss', profitFactor: 'Profit factor', sharpe: 'Sharpe ratio', pctCash: (p) => `100% cash — ${p}`,
  },
  history: { title: 'Trade history', orders: (n) => (n === '1' ? '1 order' : `${n} orders`), emptyTitle: 'No trade history', emptyText: 'Executions will appear after the bot trades in paper mode.', thDate: 'Date', thSymbol: 'Symbol', thSide: 'Side', thType: 'Type', thQty: 'Qty', thPrice: 'Price', thStatus: 'Status' },
  chart: { loading: 'Loading chart data from Alpaca…', noData: 'No chart data for this symbol' },
  agent: { title: 'TradeSense AI agent', analyzeSym: (s) => `Analyze ${s}`, marketOverview: 'Market overview', tradingSignal: 'Trading signal', portfolioReview: 'Portfolio review', riskReport: 'Risk report', analyzing: 'Analyzing…', placeholder: 'Ask about stocks, strategies, or the market…', send: 'Send' },
  settings: {
    settingsTitle: 'Settings', languageLabel: 'Language', languageDescription: 'Applies to the whole app in this browser.', english: 'English', korean: 'Korean', languageEnglishSub: 'English interface', languageKoreanSub: 'Korean interface',
    appearanceLabel: 'Appearance', appearanceDescription: 'Theme applies app-wide and is saved in this browser.', dark: 'Dark', darkSub: 'Default dashboard', light: 'Light', lightSub: 'Bright UI for daytime', brokerSectionTitle: 'Broker & API keys',
    connectIntro: 'Connect your Alpaca account (paper or live). Keys are encrypted and only your user can trade with them. Paper keys:', paperLink: 'Alpaca paper', liveLink: 'Alpaca live', signedIn: 'Signed in as', keysOnFile: ' · keys on file', keysNotConfig: ' · keys not configured', deleteKeys: 'Delete keys', deleting: 'Deleting…',
    tradingMode: 'Trading mode', tradingModeDesc: 'Paper (Alpaca paper API) vs real money (live API). Save keys below first, then choose a mode.',
    paperMoney: 'Paper money', paperSub: 'Virtual balances + 3k / 10k / 30k presets', realMoney: 'Real money', realSub: 'Live Alpaca (real orders)', keysHintInactive: 'Save keys first — these stay inactive until a key pair is added.',
    keyId: 'Alpaca API key ID', secret: 'Alpaca secret key', saveKeys: 'Save keys', saving: 'Saving…', keysOnFileNote: 'Keys are saved. Use trading mode above to switch, or delete keys to replace them.',
    liveAccount: 'Live account (Alpaca)', loadingBalances: 'Loading balances…', equity: 'Equity', cash: 'Cash', buyPower: 'Buying power', portValue: 'Portfolio value', liveLoadErr: 'Could not load live balances. Confirm your keys are for a live account.',
    capitalScale: 'Capital scale (paper only)', capitalScaleDesc: 'Swaps the risk preset table in paper mode. PDT does not apply to these cash options.',
    telegram: 'Telegram alerts', telegramPStart: 'Trading alerts (bot start/stop, daily summary, loss limit, target hit, regime) can be sent to Telegram. Add', telegramPMid: 'to server', telegramSetup: 'bot setup', telegramPEnd: 'then paste your chat ID below.', tgNotConfig: 'Telegram is not configured on the server (TELEGRAM_BOT_TOKEN missing).', sendTg: 'Send alerts to Telegram', telegramChatId: 'Telegram chat ID', telegramChatPlaceholder: 'e.g. 123456789', saveAlerts: 'Save alert preferences', sendTest: 'Send test', signOut: 'Sign out', sending: 'Sending…',
    deleteModalTitle: 'Delete stored Alpaca keys?', deleteModalBody: 'This removes your saved key pair. Trading stays off until you add a new pair.',
    errSaveFirst: 'Save Alpaca keys first, then choose paper or live.', errPaperOnly: 'Capital scale applies in paper only. Switch to paper to change it.', errDeleteFirst: 'Delete existing keys first to enter new ones.', errBothKeys: 'Enter both the API key ID and secret.',
    errKeysLocked: 'Delete keys to replace the pair.', modeChangeFail: 'Failed to change mode', notifSaved: 'Notification preferences saved.', notifSaveFail: 'Failed to save notifications', testSent: (m) => m || 'Test message sent.', testFail: 'Test send failed',
    scaleSwitched: (s, l) => `Switched to ${s.toUpperCase()} preset (${l}).`, scaleFail: 'Failed to switch capital scale', keysSaved: 'Alpaca keys saved (encrypted on the server).', saveFail: 'Failed to save', keysDeleted: 'Keys deleted. You can add a new pair now.', deleteFail: 'Failed to delete keys', msgSwitchedPaper: 'Switched to paper API. Capital scale applies.', msgSwitchedLive: 'Switched to live API. Balances are from your live account.',
  },
  scale3k: { title: '$3,000', cap: 'Starter cash scalp · IEX feed' },
  scale10k: { title: '$10,000', cap: 'Cash bridge · no PDT impact' },
  scale30k: { title: '$30,000', cap: 'HFT paper · SIP + us-east-1' },
};

const ko: UiStrings = {
  ...en,
  nav: { dashboard: '대시보드', chart: '실시간 차트', agent: 'AI 에이전트', trading: '트레이딩 봇', portfolio: '포트폴리오', history: '거래 내역', settings: '설정' },
  header: { marketOpen: '장 운영 중', marketClosed: '장 마감', paperTrading: '모의투자', signIn: '로그인' },
  sidebar: {
    tagline: 'AI 퀀트 트레이딩',
    sectionOverview: '개요', sectionMarket: '시장', sectionIntel: '인텔리전스', sectionAccount: '계정',
    signInRequired: '로그인 필요', keysRequired: 'Alpaca API 키 필요', connected: 'Alpaca 연결됨', disconnected: '연결 안 됨',
    apiQuotaError: 'API 할당: 오류(호버)', resetIn: (s) => ` · ~${s}초 후 리셋`,
  },
  userMenu: { account: '계정', settings: '설정', signOut: '로그아웃' },
  common: { loading: '로딩 중…', cancel: '취소', viewAll: '전체 보기', manage: '관리', fullChart: '전체 차트' },
  auth: {
    title: 'TradeSense에 오신 것을 환영합니다',
    subtitle: 'Google로 로그인하여 계속하세요',
    continueGoogle: 'Google로 계속',
    redirecting: '이동 중…',
    signInFailedGeneric: 'Google 로그인에 실패했습니다',
    redirectingProgress: 'Google로 이동 중…',
  },
  dashboard: {
    ...en.dashboard,
    regimeTitle: 'AI 시장 적응 시스템', lastUpdated: '갱신:', reasoning: '근거:', strategy: '전략:', marketStatus: '시장 상태:', riskSetting: '리스크:', stopLoss: '손절:', dailyPnL: '일일 손익:', focusSectors: '집중 섹터:', fedPolicy: '연준 정책', geopolitical: '지정학',
    entryBlackout: (r) => `⏸ 진입 제한: ${r || '진행 중'}`,
    gfv: (level, c) => `GFV ${level} (12개월 ${c}/3)`,
    cooldown: (s, st) => `⏲ 쿨다운 ${s}초 (연속 손실 ${st})`,
    unsettled: (n) => `미결제 $${n} · T+1`,
    portfolioValue: '포트 가치', cashAvailable: '사용 가능 현금', buyingPower: '매수가능', activePositions: '보유 포지션', strategiesActive: (n) => `활성 전략 ${n}개`, botStatus: '봇 상태', active: '가동', idle: '대기', eventsLogged: (n) => `로그 ${n}건`, dailyScalping: '일일 스캘핑:', performanceTitle: '포트 수익', starting: (v) => `시작: ${v}`, todaysReturn: '오늘 수익률', initialCapital: '초기 자본', totalPL: '총 손익', openPositions: '보유 포지션', botActivity: '봇 활동', running: '● 가동', stopped: '○ 정지', stop: '정지', start: '시작', watchlist: '관심종목', activeStrategies: '활성 전략', winRate: (n) => `승률: ${n}%`, noPositionsBot: { title: '봇 가동 중', sub: '진입 신호 스캔 중… 체결되면 여기에 표시됩니다.' }, noPositions: { title: '보유 없음', sub: '봇을 시작하거나 직접 주문해 포지션을 열 수 있습니다.', cta: '⚡ 트레이딩 봇 시작' },
    tableSymbol: '심볼', tableQty: '수량', tableAvg: '평균가', tableCurrent: '현재가', tablePL: '손익',
  },
  trading: {
    title: 'TradeSense 트레이딩 봇', subtitle: (eq) => `퀀트 자동거래 · 모의 · 자본: ${eq}`, running: '● 가동', stopped: '○ 정지', idleLine: '○ 대기', startBot: '봇 시작', stopBot: '봇 정지', strategies: '트레이딩 전략', manual: '수동', auto: '자동', autoHelp: '엔진이 시점·시장에 따라 전략을 배치합니다. 아래에서만 쓰려면 자동을 끄세요.',
    activityLog: '활동 로그', events: (n) => `이벤트 ${n}건`, riskSettings: '리스크 설정', riskLocked: '라이브(실거래) 모드: 리스크는 서버의 보통(moderate) 프리셋으로 고정됩니다. 안전을 위해 앱에서 변경할 수 없습니다.',
    riskSaveHint: '값은 이 브라우저에 저장되며 봇을 시작할 때 적용됩니다.', riskRunHint: ' 이미 가동 중이면 엔진 설정이 유지됩니다. 바꾸려면 정지 → 조정 → 다시 시작하세요.',
    riskLevel: '리스크 수준', conservative: '보수', moderate: '보통', aggressive: '공격', maxPos: (pct, cur) => `최대 포지션: ${pct}% (${cur})`, stopLossL: (p) => `손절: -${p}%`, takeProfitL: (p) => `익절: +${p}%`, resetDefaults: '기본값으로', configSummary: '요약', cap: '자본', strategyLine: (a, s) => `전략: ${a} · ${s}`, maxPer: '건당 최대', sl: '손절', tp: '익절', rr: '리스크/보상', liveLockNote: '라이브: 엔진은 보통 프리셋을 사용(클라이언트 무시).',
    sessionStats: '세션 통계', totalTrades: '총 거래', winRate: '승률', winTrades: '익절', loseTrades: '손절', totalPnl: '총 손익', statusActive: '현재 활성(자동)', statusIdle: '지금은 비활성(조건 맞으면 켜짐)', statusManual: '수동 허용 — 끄려면 클릭', activeNow: '● 지금 활성', winRateL: (n) => `승률: ${n}%`, statusDisabled: '꺼짐 — 켜려면 클릭', manualPending: ' · 수동 대기',
  },
  portfolio: {
    totalEquity: '총 자산', cash: '현금', buyingPower: '매수가능', dailyPL: '일일 손익', holdings: '보유', positions: (n) => `포지션 ${n}개`, noHoldings: { title: '보유 없음', text: (amt) => `전액 현금입니다. 봇을 시작하면 ${amt} 모의로 자동 매매를 시작할 수 있습니다.` },
    thSymbol: '심볼', thSide: '방향', thQty: '수량', thAvg: '평균가', thCurrent: '현재가', thMkt: '평가액', thUnr: '평가손익', thPct: '변동률', allocation: '자산 비중', performance: '성과 지표', cashLabel: '현금', totReturn: '총 수익률', totPL: '총 손익', initCap: '초기 자본', winR: '승률', avgWin: '평균 익', avgLoss: '평균 손', profitFactor: '손익비', sharpe: '샤프', pctCash: (p) => `100% 현금 — ${p}`,
  },
  history: { title: '거래 내역', orders: (n) => `주문 ${n}건`, emptyTitle: '거래 없음', emptyText: '모의 매매로 봇이 체결하면 여기에 표시됩니다.', thDate: '일시', thSymbol: '심볼', thSide: '매매', thType: '유형', thQty: '수량', thPrice: '가격', thStatus: '상태' },
  chart: { loading: 'Alpaca에서 차트 불러오는 중…', noData: '이 심볼에 대한 데이터가 없습니다' },
  agent: { title: 'TradeSense AI 에이전트', analyzeSym: (s) => `${s} 분석`, marketOverview: '시장 개요', tradingSignal: '매매 시그널', portfolioReview: '포트폴리오 점검', riskReport: '리스크 보고', analyzing: '분석 중…', placeholder: '종목, 전략, 시장에 대해 질문하세요…', send: '전송' },
  settings: {
    settingsTitle: '설정', languageLabel: '언어', languageDescription: '이 브라우저에서 앱 전체에 적용됩니다.', english: 'English', korean: '한국어', languageEnglishSub: '영어', languageKoreanSub: '한국어', appearanceLabel: '화면', appearanceDescription: '테마는 앱 전체에 저장됩니다.', dark: '다크', darkSub: '기본 대시보드', light: '라이트', lightSub: '밝은 UI', brokerSectionTitle: '브로커 · API',
    connectIntro: 'Alpaca(모의·실) 계정을 연결하세요. 키는 암호화되어 저장됩니다. 모의 키:', paperLink: 'Alpaca 모의', liveLink: 'Alpaca 실거래', signedIn: '로그인', keysOnFile: ' · 키 저장됨', keysNotConfig: ' · 키 미설정', deleteKeys: '키 삭제', deleting: '삭제 중…',
    tradingMode: '거래 모드', tradingModeDesc: '모의(Alpaca paper) vs 실제(live). 아래에 키를 저장한 뒤 선택하세요.', paperMoney: '모의 자금', paperSub: '가상 잔고 + 3k/10k/30k 프리셋', realMoney: '실제 자금', realSub: 'Alpaca 실계좌(실주문)', keysHintInactive: '키를 먼저 저장하세요. 저장 전에는 비활성입니다.',
    keyId: 'Alpaca API Key ID', secret: 'Alpaca Secret', saveKeys: '키 저장', saving: '저장 중…', keysOnFileNote: '키가 저장되었습니다. 위에서 모의/실을 바꾸거나 삭제 후 재등록하세요.',
    liveAccount: '실계좌 (Alpaca)', loadingBalances: '잔고 불러오는 중…', equity: '자산', cash: '현금', buyPower: '매수가능', portValue: '포트 가치', liveLoadErr: '실계좌 잔고를 불러오지 못했습니다. 실전용 키인지 확인하세요.',
    capitalScale: '자본 규모(모의 전용)', capitalScaleDesc: '모의에서 리스크 프리셋 테이블을 바꿉니다. 전부 현금 기준입니다.',
    telegram: 'Telegram 알림', telegramPStart: '봇 시작/정지, 일일 요약, 손실 한도, 목표 도달, 레짐 변화 등을 Telegram으로 보낼 수 있습니다. 서버', telegramPMid: '에', telegramSetup: '봇 설정', telegramPEnd: '다음에 채팅 ID를 아래에 붙여 넣으세요.', tgNotConfig: '서버에 Telegram이 설정되지 않았습니다(TELEGRAM_BOT_TOKEN 없음).', sendTg: 'Telegram으로 알림 보내기', telegramChatId: 'Telegram 채팅 ID', telegramChatPlaceholder: '예: 123456789', saveAlerts: '알림 저장', sendTest: '테스트', signOut: '로그아웃', sending: '전송 중…',
    deleteModalTitle: '저장된 Alpaca 키를 삭제할까요?', deleteModalBody: '저장된 키 쌍이 삭제됩니다. 새 키를 넣을 때까지 거래는 비활성입니다.',
    errSaveFirst: '먼저 Alpaca 키를 저장한 뒤 모의/실을 고르세요.', errPaperOnly: '자본 규모는 모의에서만 바꿀 수 있습니다. 모의로 전환하세요.', errDeleteFirst: '새 키를 넣으려면 기존 키를 먼저 삭제하세요.', errBothKeys: 'Key ID와 Secret을 모두 입력하세요.',
    errKeysLocked: '키 쌍을 바꾸려면 먼저 삭제하세요.', modeChangeFail: '거래 모드 전환 실패', notifSaved: '알림 설정을 저장했습니다.', notifSaveFail: '알림 저장 실패', testSent: (m) => m || '테스트 메시지를 보냈습니다.', testFail: '테스트 전송 실패', scaleSwitched: (s, l) => `${s.toUpperCase()} 프리셋으로 전환 (${l}).`, scaleFail: '자본 규모 전환 실패', keysSaved: 'Alpaca 키를 저장했습니다(서버 암호화).', saveFail: '저장 실패', keysDeleted: '키를 삭제했습니다. 새 쌍을 등록할 수 있습니다.', deleteFail: '키 삭제 실패', msgSwitchedPaper: '모의 API로 전환했습니다. 자본 프리셋이 적용됩니다.', msgSwitchedLive: '실거래 API로 전환했습니다. 잔고는 실계좌 기준입니다.',
  },
  scale3k: { title: '$3,000', cap: '초기 현금 스캘프 · IEX' },
  scale10k: { title: '$10,000', cap: '현금 전용 · PDT 면제' },
  scale30k: { title: '$30,000', cap: 'HFT 모의 · SIP' },
};

export const uiStrings: Record<AppLocale, UiStrings> = { en, ko };

export function getUiStrings(locale: AppLocale): UiStrings {
  return uiStrings[locale] ?? en;
}

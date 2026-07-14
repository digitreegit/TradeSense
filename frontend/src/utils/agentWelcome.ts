import { formatCurrency } from './helpers';

const PLAYBOOK_EN = `Active playbook ideas:
• RSI oversold bounce scalps (5-min)
• VWAP support / resistance breaks
• AI-driven sector rotation (paid tier)`;

const PLAYBOOK_KO = `활성 플레이북 아이디어:
• RSI 과매도 반등 스캘핑 (5분봉)
• VWAP 지지 / 저항 돌파
• AI 기반 섹터 로테이션 (유료 티어)`;

function formatPctLabel(pct: number, invalidFallback: string): string {
  if (!Number.isFinite(pct) || pct <= 0) return invalidFallback;
  const rounded = Math.round(pct * 1000) / 1000;
  if (Number.isInteger(rounded)) return String(rounded);
  return String(rounded);
}

export function buildAgentWelcomeMessage(options: {
  language: 'en' | 'ko';
  isPaper: boolean;
  capitalUsd: number;
  dailyPct: number;
  dailyLossLimitPct: number;
}): string {
  const { language, isPaper, capitalUsd, dailyPct, dailyLossLimitPct } = options;
  const cap = formatCurrency(Math.max(0, capitalUsd));
  const winLabel = formatPctLabel(dailyPct, '2');
  const lossLabel = formatPctLabel(dailyLossLimitPct, '1');

  if (language === 'ko') {
    const head = '안녕하세요. 저는 TradeSense v3 마이크로 스캘핑 에이전트입니다. ⚡️';
    const goal = isPaper
      ? `**${cap} 페이퍼 기준** — 기본 전략: 하루 **+${winLabel}%** 목표, **−${lossLabel}%** 일일 손실 한도.`
      : `**${cap} 실계좌 에퀴티** — 기본 전략: 하루 **+${winLabel}%** 목표, **−${lossLabel}%** 일일 손실 한도.`;
    return [head, '', goal, '', PLAYBOOK_KO].join('\n');
  }

  const head = "Hi — I'm the TradeSense v3 micro-scalping agent. ⚡️";
  const goal = isPaper
    ? `**${cap} paper account** — default strategy: **+${winLabel}% / day** target, **−${lossLabel}% / day** loss guard.`
    : `**${cap} live equity** — default strategy: **+${winLabel}% / day** target, **−${lossLabel}% / day** loss guard.`;
  return [head, '', goal, '', PLAYBOOK_EN].join('\n');
}

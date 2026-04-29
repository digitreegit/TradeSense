export type StoredRiskLevel = 'conservative' | 'moderate' | 'aggressive';

export interface StoredRiskSettings {
  riskLevel: StoredRiskLevel;
  maxPositionSize: number;
  stopLossPercent: number;
  takeProfitPercent: number;
}

const STORAGE_KEY = 'tradesense-risk-settings';

const DEFAULT: StoredRiskSettings = {
  riskLevel: 'moderate',
  maxPositionSize: 15,
  stopLossPercent: 0.3,
  takeProfitPercent: 0.8,
};

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

export const DEFAULT_RISK_SETTINGS: Readonly<StoredRiskSettings> = DEFAULT;

export function readStoredRiskSettings(): StoredRiskSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT };
    const p = JSON.parse(raw) as Partial<StoredRiskSettings>;
    const riskLevel: StoredRiskLevel = ['conservative', 'moderate', 'aggressive'].includes(
      String(p.riskLevel),
    )
      ? (p.riskLevel as StoredRiskLevel)
      : DEFAULT.riskLevel;
    return {
      riskLevel,
      maxPositionSize: clamp(
        Number.isFinite(Number(p.maxPositionSize)) ? Number(p.maxPositionSize) : DEFAULT.maxPositionSize,
        5,
        25,
      ),
      stopLossPercent: clamp(
        Number.isFinite(Number(p.stopLossPercent)) ? Number(p.stopLossPercent) : DEFAULT.stopLossPercent,
        0.1,
        2.0,
      ),
      takeProfitPercent: clamp(
        Number.isFinite(Number(p.takeProfitPercent))
          ? Number(p.takeProfitPercent)
          : DEFAULT.takeProfitPercent,
        0.2,
        5.0,
      ),
    };
  } catch {
    return { ...DEFAULT };
  }
}

export function persistRiskSettings(s: StoredRiskSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* private mode / quota */
  }
}

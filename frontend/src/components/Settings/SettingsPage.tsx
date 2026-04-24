import React, { useEffect, useState } from 'react';
import api from '../../services/api';
import { useAppStore } from '../../stores/useAppStore';
import { clearToken } from '../../auth/token';
import { supabase } from '../../auth/supabase';

type CapitalScale = '3k' | '10k' | '30k';

const SCALE_OPTIONS: Array<{
  id: CapitalScale;
  title: string;
  caption: string;
}> = [
  {
    id: '3k',
    title: '$3,000',
    caption: 'Starter cash-scalp · IEX feed',
  },
  {
    id: '10k',
    title: '$10,000',
    caption: 'Cash-only bridge · no PDT impact',
  },
  {
    id: '30k',
    title: '$30,000',
    caption: 'HFT paper · SIP feed + us-east-1',
  },
];

type LiveSummary = {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
};

const fmtUsd = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);

const SettingsPage: React.FC = () => {
  const {
    authEmail,
    authAlpacaConfigured,
    authAlpacaPaperTrading,
    setAuthProfile,
    setCurrentPage,
    setAuthMethod,
  } = useAppStore();
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [scale, setScale] = useState<CapitalScale | null>(null);
  const [scaleLoading, setScaleLoading] = useState(false);
  const [scaleMsg, setScaleMsg] = useState<string | null>(null);
  const [modeLoading, setModeLoading] = useState(false);
  const [liveSummary, setLiveSummary] = useState<LiveSummary | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);

  const keysLocked = authAlpacaConfigured;

  useEffect(() => {
    let cancelled = false;
    api
      .getCapitalScale()
      .then((info) => {
        if (!cancelled) setScale(info.scale);
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authEmail || !authAlpacaConfigured || authAlpacaPaperTrading) {
      setLiveSummary(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLiveLoading(true);
      try {
        const acc = await api.getAccount();
        if (cancelled || !acc || 'detail' in acc) return;
        setLiveSummary({
          equity: Number(acc.equity) || 0,
          cash: Number(acc.cash) || 0,
          buying_power: Number(acc.buying_power) || 0,
          portfolio_value: Number(acc.portfolio_value) || 0,
        });
      } catch {
        if (!cancelled) setLiveSummary(null);
      } finally {
        if (!cancelled) setLiveLoading(false);
      }
    };
    void load();
    const t = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [authEmail, authAlpacaConfigured, authAlpacaPaperTrading]);

  const choosePaperOrLive = async (paper: boolean) => {
    if (!authAlpacaConfigured) {
      setErr('Save Alpaca keys first, then choose paper or live.');
      return;
    }
    if (paper === authAlpacaPaperTrading || modeLoading) return;
    setModeLoading(true);
    setErr(null);
    setScaleMsg(null);
    try {
      const info = await api.setTradingMode(paper);
      if (authEmail) {
        setAuthProfile(authEmail, true, Boolean(info.paper_trading));
      }
      setScaleMsg(
        info.paper_trading
          ? 'Switched to paper trading API. Capital scale presets apply.'
          : 'Switched to live trading API. Balances shown are from your live Alpaca account.',
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to change trading mode');
    } finally {
      setModeLoading(false);
    }
  };

  const chooseScale = async (next: CapitalScale) => {
    if (!authAlpacaPaperTrading) {
      setErr('Capital scale presets apply to paper mode only. Switch to paper money to change them.');
      return;
    }
    if (next === scale || scaleLoading) return;
    setScaleLoading(true);
    setScaleMsg(null);
    setErr(null);
    try {
      const info = await api.setCapitalScale(next);
      setScale(info.scale);
      setScaleMsg(`Switched to ${info.scale.toUpperCase()} preset (${info.level}).`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to switch capital scale');
    } finally {
      setScaleLoading(false);
    }
  };

  const saveKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (keysLocked) {
      setErr('Delete existing keys first to enter new keys.');
      return;
    }
    if (!key.trim() || !secret.trim()) {
      setErr('Enter both the API Key ID and Secret Key.');
      return;
    }
    setLoading(true);
    try {
      await api.saveAlpacaKeys(key.trim(), secret.trim());
      setAuthProfile(authEmail, true, true);
      setKey('');
      setSecret('');
      setMsg('Alpaca keys saved (encrypted on the server).');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed to save');
    } finally {
      setLoading(false);
    }
  };

  const deleteKeys = async () => {
    setErr(null);
    setMsg(null);
    setDeleting(true);
    try {
      await api.deleteAlpacaKeys();
      setAuthProfile(authEmail, false);
      setKey('');
      setSecret('');
      setMsg('Stored Alpaca keys were deleted. You can add a new key pair now.');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed to delete keys');
    } finally {
      setDeleting(false);
    }
  };

  const signOut = () => {
    void supabase.auth.signOut();
    clearToken();
    setAuthProfile(null, false);
    setAuthMethod(null);
    setCurrentPage('auth');
  };

  return (
    <div className="page-enter" style={{ maxWidth: 560, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>Settings</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px', lineHeight: 1.5 }}>
          Connect your <strong>Alpaca</strong> account (paper or live). Keys are encrypted and only your user can trade with them.
          Paper keys:{' '}
          <a
            href="https://app.alpaca.markets/paper/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            Alpaca Paper
          </a>
          {' · '}
          Live keys:{' '}
          <a
            href="https://app.alpaca.markets/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            Alpaca Live
          </a>
          .
        </p>
        <p
          style={{
            fontSize: '13px',
            color: 'var(--text-secondary)',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            flexWrap: 'wrap',
          }}
        >
          Signed in as <strong>{authEmail}</strong>
          {authAlpacaConfigured ? ' · keys on file' : ' · keys not configured yet'}
          {authAlpacaConfigured && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setConfirmDeleteOpen(true)}
              disabled={deleting || loading}
            >
              {deleting ? 'Deleting…' : 'Delete Keys'}
            </button>
          )}
        </p>
        {err && <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '8px' }}>{err}</p>}
        {msg && <p style={{ color: 'var(--profit)', fontSize: '13px', marginBottom: '8px' }}>{msg}</p>}

        <div style={{ marginTop: '8px', marginBottom: '8px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            Trading mode
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            <strong>Paper money</strong> (Alpaca paper API) vs <strong>real money</strong> (live API). Save Alpaca keys
            below first, then tap the mode you want.
          </p>
          <div
            role="radiogroup"
            aria-label="Paper or live trading"
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(true)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border: authAlpacaPaperTrading
                  ? '2px solid var(--border-accent, var(--info))'
                  : '1px solid var(--border-secondary)',
                background: authAlpacaPaperTrading
                  ? 'var(--bg-tertiary, rgba(56,132,255,0.12))'
                  : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>Paper money</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                Virtual balances + 3k / 10k / 30k presets
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={!authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(false)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border: !authAlpacaPaperTrading
                  ? '2px solid var(--border-accent, var(--loss))'
                  : '1px solid var(--border-secondary)',
                background: !authAlpacaPaperTrading
                  ? 'var(--bg-tertiary, rgba(239,68,68,0.10))'
                  : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>Real money</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                Live Alpaca account (real orders)
              </div>
            </button>
          </div>
          {!authAlpacaConfigured && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '10px', lineHeight: 1.45 }}>
              Keys not saved yet — both buttons stay inactive until you add your API key pair below.
            </p>
          )}
        </div>

        {!keysLocked && (
          <form onSubmit={saveKeys}>
            <label style={{ fontSize: '12px' }}>Alpaca API Key ID</label>
            <input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="PK…"
              disabled={loading || deleting}
              style={{
                display: 'block',
                width: '100%',
                margin: '6px 0 12px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <label style={{ fontSize: '12px' }}>Alpaca Secret Key</label>
            <input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              disabled={loading || deleting}
              style={{
                display: 'block',
                width: '100%',
                margin: '6px 0 16px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <button type="submit" className="btn-start" disabled={loading || deleting}>
              {loading ? 'Saving…' : 'Save keys'}
            </button>
          </form>
        )}

        {keysLocked && (
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '12px', lineHeight: 1.5 }}>
            Keys are on file. Use <strong>Trading mode</strong> above to switch paper vs live, or delete keys to replace
            them.
          </p>
        )}

        {!authAlpacaPaperTrading && authAlpacaConfigured && (
          <div style={{ marginTop: '24px' }}>
            <label
              style={{
                fontSize: '12px',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                color: 'var(--text-tertiary)',
              }}
            >
              Live account (Alpaca)
            </label>
            {liveLoading && !liveSummary ? (
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '8px' }}>Loading balances…</p>
            ) : liveSummary ? (
              <ul
                style={{
                  listStyle: 'none',
                  padding: 0,
                  margin: '10px 0 0',
                  fontSize: '13px',
                  lineHeight: 1.7,
                  color: 'var(--text-secondary)',
                }}
              >
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>Equity</strong> {fmtUsd(liveSummary.equity)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>Cash</strong> {fmtUsd(liveSummary.cash)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>Buying power</strong>{' '}
                  {fmtUsd(liveSummary.buying_power)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>Portfolio value</strong>{' '}
                  {fmtUsd(liveSummary.portfolio_value)}
                </li>
              </ul>
            ) : (
              <p style={{ fontSize: '12px', color: 'var(--loss)', marginTop: '8px' }}>
                Could not load live balances. Confirm your keys are for a live Alpaca account.
              </p>
            )}
          </div>
        )}

        <div style={{ marginTop: '32px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            Capital scale (paper only)
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            Swaps the active risk preset table when you are in paper mode. PDT rule does not apply to cash accounts —
            all three options are cash-only.
          </p>
          <div
            role="radiogroup"
            aria-label="Capital scale"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '8px',
            }}
          >
            {SCALE_OPTIONS.map((opt) => {
              const selected = scale === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => chooseScale(opt.id)}
                  disabled={scaleLoading || !authAlpacaPaperTrading}
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: selected
                      ? '1px solid var(--border-accent, var(--info))'
                      : '1px solid var(--border-secondary)',
                    background: selected ? 'var(--bg-tertiary, rgba(56,132,255,0.10))' : 'var(--bg-secondary)',
                    color: 'inherit',
                    cursor: scaleLoading || !authAlpacaPaperTrading ? 'not-allowed' : 'pointer',
                    opacity: !authAlpacaPaperTrading ? 0.5 : 1,
                    transition: 'border-color 120ms, background 120ms',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 600 }}>{opt.title}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px', lineHeight: 1.3 }}>
                    {opt.caption}
                  </div>
                </button>
              );
            })}
          </div>
          {scaleMsg && (
            <p style={{ color: 'var(--profit)', fontSize: '12px', marginTop: '8px' }}>{scaleMsg}</p>
          )}
        </div>

        <button
          type="button"
          className="btn btn-danger"
          onClick={signOut}
          style={{ marginTop: '40px', width: '100%' }}
        >
          Sign Out
        </button>
      </div>

      {confirmDeleteOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(3px)',
            WebkitBackdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1200,
            padding: '16px',
          }}
        >
          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '460px',
              padding: '20px',
              borderColor: 'var(--border-accent)',
            }}
          >
            <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>Delete stored Alpaca keys?</h3>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This will remove your currently saved key pair. Trading will stay disabled until you add
              a new key pair.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '18px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={async () => {
                  await deleteKeys();
                  setConfirmDeleteOpen(false);
                }}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete Keys'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsPage;

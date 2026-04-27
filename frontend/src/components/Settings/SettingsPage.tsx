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

const radioOuter: React.CSSProperties = {
  width: 18,
  height: 18,
  borderRadius: '50%',
  border: '2px solid var(--border-secondary)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
  marginTop: 2,
};

const radioInner: React.CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: 'var(--info, #3b82f6)',
};

const SettingsPage: React.FC = () => {
  const {
    authEmail,
    authAlpacaConfigured,
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
  const [displayCapital, setDisplayCapital] = useState<number | null>(null);
  const [scaleLoading, setScaleLoading] = useState(false);
  const [scaleMsg, setScaleMsg] = useState<string | null>(null);

  const keysLocked = authAlpacaConfigured;

  useEffect(() => {
    let cancelled = false;
    api
      .getCapitalScale()
      .then((info) => {
        if (!cancelled) {
          setScale(info.scale);
          if (typeof info.display_capital === 'number') {
            setDisplayCapital(info.display_capital);
          }
        }
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const chooseScale = async (next: CapitalScale) => {
    if (scaleLoading) return;
    setScaleLoading(true);
    setScaleMsg(null);
    setErr(null);
    try {
      const info = await api.setCapitalScale(next);
      setScale(info.scale);
      if (typeof info.display_capital === 'number') {
        setDisplayCapital(info.display_capital);
      }
      setScaleMsg(
        `Switched to ${info.scale.toUpperCase()} — virtual portfolio $${info.display_capital?.toLocaleString() ?? '—'} (${info.level} preset). Dashboard updates on next refresh.`,
      );
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
      setAuthProfile(authEmail, true);
      setKey('');
      setSecret('');
      setMsg('Alpaca paper keys saved (encrypted on the server).');
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
          Connect your <strong>Alpaca paper trading</strong> account. Keys are encrypted and only your user can trade with them.
          Create keys at{' '}
          <a
            href="https://app.alpaca.markets/paper/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            Alpaca (Paper)
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

        <div style={{ marginTop: '32px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            Capital Scale
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            Picks the risk preset table and <strong>virtual starting equity</strong> shown on the dashboard
            ($3k / $10k / $30k). Your Alpaca balance is unchanged; P&amp;L is rebased from now. PDT does not
            apply to cash accounts.
          </p>
          {displayCapital != null && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
              Current virtual anchor: <strong>${displayCapital.toLocaleString()}</strong>
            </p>
          )}
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
              const inputId = `capital-scale-${opt.id}`;
              return (
                <label
                  key={opt.id}
                  htmlFor={inputId}
                  style={{
                    display: 'flex',
                    gap: '10px',
                    alignItems: 'flex-start',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: selected
                      ? '1px solid var(--border-accent, var(--info))'
                      : '1px solid var(--border-secondary)',
                    background: selected ? 'var(--bg-tertiary, rgba(56,132,255,0.10))' : 'var(--bg-secondary)',
                    cursor: scaleLoading ? 'wait' : 'pointer',
                    transition: 'border-color 120ms, background 120ms',
                  }}
                >
                  <input
                    id={inputId}
                    type="radio"
                    name="capital-scale"
                    value={opt.id}
                    checked={selected}
                    onChange={() => chooseScale(opt.id)}
                    disabled={scaleLoading}
                    style={{
                      position: 'absolute',
                      opacity: 0,
                      width: 0,
                      height: 0,
                      pointerEvents: 'none',
                    }}
                  />
                  <span aria-hidden style={selected ? { ...radioOuter, borderColor: 'var(--info, #3b82f6)' } : radioOuter}>
                    {selected ? <span style={radioInner} /> : null}
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>{opt.title}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px', lineHeight: 1.3 }}>
                      {opt.caption}
                    </div>
                  </span>
                </label>
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

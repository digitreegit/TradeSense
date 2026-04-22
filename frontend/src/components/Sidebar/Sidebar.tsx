import React from 'react';
import { LayoutGrid } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import type { AlpacaApiUsage, PageId } from '../../stores/types';

/** shadcn/ui uses Lucide — Dashboard “grid” nav icon */
const DashboardGridIcon = (props: React.ComponentProps<typeof LayoutGrid>) => (
  <LayoutGrid {...props} strokeWidth={1.5} />
);

const ChartIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
  </svg>
);

const ChipIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M12 3v1.5m3.75-1.5v1.5m-9 15V21m4.5-1.5V21m4.5-1.5V21m-9-15h-1.5A2.25 2.25 0 0 0 3 8.25v1.5M3 12h1.5m-1.5 2.25v1.5A2.25 2.25 0 0 0 5.25 18h1.5m10.5-15h1.5a2.25 2.25 0 0 1 2.25 2.25v1.5M21 12h-1.5m1.5 2.25v1.5a2.25 2.25 0 0 1-2.25 2.25h-1.5M7.5 7.5h9v9h-9v-9Z" />
  </svg>
);

const BoltIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
  </svg>
);

const BriefcaseIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 .621-.504 1.125-1.125 1.125H4.875A1.125 1.125 0 0 1 3.75 18.4V14.15m16.5 0a5.122 5.122 0 0 0-4.75-4.65M16.5 14.15m16.5 0a1.125 1.125 0 0 1-1.125 1.125H4.875a1.125 1.125 0 0 1-1.125-1.125m16.5 0h-16.5" />
  </svg>
);

const HistoryIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
  </svg>
);

const CogIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a7.68 7.68 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281Z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
  </svg>
);

type NavIcon = React.ComponentType<React.SVGProps<SVGSVGElement>>;

interface NavItem {
  id: PageId;
  label: string;
  icon: NavIcon;
  section?: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: DashboardGridIcon, section: 'OVERVIEW' },
  { id: 'chart', label: 'Live Chart', icon: ChartIcon, section: 'MARKET' },
  { id: 'agent', label: 'AI Agent', icon: ChipIcon, section: 'INTELLIGENCE' },
  { id: 'trading', label: 'Trading Bot', icon: BoltIcon },
  { id: 'portfolio', label: 'Portfolio', icon: BriefcaseIcon, section: 'ACCOUNT' },
  { id: 'history', label: 'History', icon: HistoryIcon },
  { id: 'settings', label: 'Settings', icon: CogIcon },
];

function formatUsageLine(u: AlpacaApiUsage | null): string | null {
  if (!u || !u.ok) return null;
  if (u.remaining != null && u.limit != null) {
    const pct = u.percent_used != null ? ` · ${u.percent_used}% used` : '';
    return `API ${u.remaining}/${u.limit} left${pct}`;
  }
  if (u.remaining != null) {
    return `API ${u.remaining} left (window)`;
  }
  if (u.note) {
    return u.note.length > 52 ? `${u.note.slice(0, 49)}…` : u.note;
  }
  if (u.headers_available === false) {
    return 'REST OK · rate-limit headers not shown';
  }
  return 'REST OK · no quota headers';
}

const Sidebar: React.FC = () => {
  const {
    currentPage,
    setCurrentPage,
    connected,
    botActive,
    alpacaUsage,
    authEmail,
    authAlpacaConfigured,
  } = useAppStore();
  const showConnected = Boolean(authEmail && authAlpacaConfigured && connected);
  const statusLabel = !authEmail
    ? 'Sign in required'
    : !authAlpacaConfigured
      ? 'Alpaca keys required'
      : showConnected
        ? 'Connected to Alpaca'
        : 'Disconnected';
  const usageLine = formatUsageLine(alpacaUsage);

  let currentSection = '';

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <img src="/logo.svg" alt="TS" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        </div>
        <div className="sidebar-logo-text">
          <h1>TradeSense</h1>
          <span>AI Quant Trading</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const showSection = item.section && item.section !== currentSection;
          if (item.section) currentSection = item.section;

          const IconComponent = item.icon;

          return (
            <React.Fragment key={item.id}>
              {showSection && (
                <div className="sidebar-section-label">{item.section}</div>
              )}
              <button
                className={`sidebar-item ${currentPage === item.id ? 'active' : ''}`}
                onClick={() => setCurrentPage(item.id)}
              >
                <span className="icon">
                  <IconComponent className="w-5 h-5" />
                </span>
                <span>{item.label}</span>
                {item.id === 'trading' && botActive && (
                  <span style={{
                    marginLeft: 'auto',
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: 'var(--profit)',
                    boxShadow: '0 0 8px var(--profit-glow)',
                    animation: 'pulse 2s ease-in-out infinite',
                  }} />
                )}
              </button>
            </React.Fragment>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className={`sidebar-status ${showConnected ? '' : 'disconnected'}`}>
          <span className="status-dot" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 }}>
            <span>{statusLabel}</span>
            {showConnected && usageLine && (
              <span
                style={{
                  fontSize: '10px',
                  lineHeight: 1.35,
                  color: 'rgba(255,255,255,0.72)',
                  fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                  wordBreak: 'break-word',
                }}
                title={
                  [
                    alpacaUsage?.note,
                    alpacaUsage?.http_probe_error
                      ? `HTTP probe: ${alpacaUsage.http_probe_error}`
                      : null,
                    alpacaUsage?.reset_in_seconds != null
                      ? `Resets in ~${alpacaUsage.reset_in_seconds}s`
                      : null,
                  ]
                    .filter(Boolean)
                    .join('\n') || 'Alpaca REST'
                }
              >
                {usageLine}
                {alpacaUsage?.ok &&
                  alpacaUsage.reset_in_seconds != null &&
                  alpacaUsage.reset_in_seconds > 0 &&
                  alpacaUsage.remaining != null &&
                  alpacaUsage.limit != null
                  ? ` · reset ~${alpacaUsage.reset_in_seconds}s`
                  : ''}
              </span>
            )}
            {showConnected && alpacaUsage && !alpacaUsage.ok && (
              <span
                style={{ fontSize: '10px', color: 'rgba(255,255,255,0.65)', opacity: 0.9 }}
                title={alpacaUsage.error}
              >
                API quota: error (hover)
              </span>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;

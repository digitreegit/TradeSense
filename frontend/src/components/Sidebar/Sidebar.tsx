import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import type { PageId } from '../../stores/types';

// Heroicons v2 Outline SVGs directly as components
const SquaresIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
  </svg>
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

interface NavItem {
  id: PageId;
  label: string;
  icon: React.ComponentType<React.ComponentProps<'svg'>>;
  section?: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: SquaresIcon, section: 'OVERVIEW' },
  { id: 'chart', label: 'Live Chart', icon: ChartIcon, section: 'MARKET' },
  { id: 'agent', label: 'AI Agent', icon: ChipIcon, section: 'INTELLIGENCE' },
  { id: 'trading', label: 'Trading Bot', icon: BoltIcon },
  { id: 'portfolio', label: 'Portfolio', icon: BriefcaseIcon, section: 'ACCOUNT' },
  { id: 'history', label: 'History', icon: HistoryIcon },
];

const Sidebar: React.FC = () => {
  const { currentPage, setCurrentPage, connected, botActive } = useAppStore();

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
        <div className={`sidebar-status ${connected ? '' : 'disconnected'}`}>
          <span className="status-dot" />
          <span>{connected ? 'Connected to Alpaca' : 'Disconnected'}</span>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;

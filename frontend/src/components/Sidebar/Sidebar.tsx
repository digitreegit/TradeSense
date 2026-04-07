import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import type { PageId } from '../../stores/types';

interface NavItem {
  id: PageId;
  label: string;
  icon: string;
  section?: string;
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '⊞', section: 'OVERVIEW' },
  { id: 'chart', label: 'Live Chart', icon: '📈', section: 'MARKET' },
  { id: 'agent', label: 'AI Agent', icon: '🤖', section: 'INTELLIGENCE' },
  { id: 'trading', label: 'Trading Bot', icon: '⚡' },
  { id: 'portfolio', label: 'Portfolio', icon: '💼', section: 'ACCOUNT' },
  { id: 'history', label: 'History', icon: '📋' },
];

const Sidebar: React.FC = () => {
  const { currentPage, setCurrentPage, connected, botActive } = useAppStore();

  let currentSection = '';

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">T</div>
        <div className="sidebar-logo-text">
          <h1>TradeSense</h1>
          <span>AI Quant Trading</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const showSection = item.section && item.section !== currentSection;
          if (item.section) currentSection = item.section;

          return (
            <React.Fragment key={item.id}>
              {showSection && (
                <div className="sidebar-section-label">{item.section}</div>
              )}
              <button
                className={`sidebar-item ${currentPage === item.id ? 'active' : ''}`}
                onClick={() => setCurrentPage(item.id)}
              >
                <span className="icon">{item.icon}</span>
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

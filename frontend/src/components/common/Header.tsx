import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { isMarketOpen } from '../../utils/helpers';

const Header: React.FC = () => {
  const { currentPage, marketOpen } = useAppStore();

  const titles: Record<string, string> = {
    dashboard: 'Dashboard',
    chart: 'Live Chart',
    agent: 'AI Analysis Agent',
    trading: 'Trading Bot',
    portfolio: 'Portfolio',
    history: 'Trade History',
  };

  const currentTime = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });

  return (
    <header className="header">
      <div className="header-left">
        <h2 className="header-title">{titles[currentPage] || 'Dashboard'}</h2>
      </div>
      <div className="header-right">
        <div className="market-status">
          <span className={`dot ${isMarketOpen() || marketOpen ? 'open' : 'closed'}`} />
          <span>{isMarketOpen() || marketOpen ? 'Market Open' : 'Market Closed'}</span>
        </div>
        <div className="header-badge paper">
          📝 Paper Trading
        </div>
        <div style={{
          fontSize: '12px',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-mono)',
        }}>
          {currentTime}
        </div>
      </div>
    </header>
  );
};

export default Header;

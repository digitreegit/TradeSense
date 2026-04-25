import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { isMarketOpen } from '../../utils/helpers';
import UserMenu from './UserMenu';

// Heroicons v2 Outline SVGs
const DocumentCheckIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 0 1 9 9v.375M10.125 2.25A3.375 3.375 0 0 1 13.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 0 1 3.375 3.375M9 15l2.25 2.25L15 12" />
  </svg>
);

const Header: React.FC = () => {
  const { currentPage, marketOpen } = useAppStore();
  const [time, setTime] = React.useState(new Date());

  React.useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const titles: Record<string, string> = {
    dashboard: 'Dashboard',
    chart: 'Live Chart',
    agent: 'AI Analysis Agent',
    trading: 'Trading Bot',
    portfolio: 'Portfolio',
    history: 'Trade History',
    auth: 'Sign in',
    settings: 'Settings',
  };

  const currentTime = time.toLocaleTimeString('en-US', {
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
        <div className="header-badge paper" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <DocumentCheckIcon style={{ width: '14px', height: '14px' }} />
          Paper Trading
        </div>
        <div style={{
          fontSize: '12px',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-mono)',
        }}>
          {currentTime}
        </div>
        <UserMenu />
      </div>
    </header>
  );
};

export default Header;

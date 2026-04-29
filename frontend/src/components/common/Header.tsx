import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { isMarketOpen } from '../../utils/helpers';
import { useUiStrings } from '../../hooks/useUiStrings';
import UserMenu from './UserMenu';

// Heroicons v2 Outline SVGs
const DocumentCheckIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 0 1 9 9v.375M10.125 2.25A3.375 3.375 0 0 1 13.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 0 1 3.375 3.375M9 15l2.25 2.25L15 12" />
  </svg>
);

const SunIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z" />
  </svg>
);

const MoonIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z" />
  </svg>
);

const Header: React.FC = () => {
  const t = useUiStrings();
  const { currentPage, marketOpen, appLocale, colorTheme, setColorTheme } = useAppStore();
  const [time, setTime] = React.useState(new Date());

  React.useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const titles: Record<string, string> = {
    dashboard: t.nav.dashboard,
    chart: t.nav.chart,
    agent: t.nav.agent,
    trading: t.nav.trading,
    portfolio: t.nav.portfolio,
    history: t.nav.history,
    auth: t.header.signIn,
    settings: t.nav.settings,
  };

  const timeLocale = appLocale === 'ko' ? 'ko-KR' : 'en-US';
  const currentTime = time.toLocaleTimeString(timeLocale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });

  return (
    <header className="header">
      <div className="header-left">
        <h2 className="header-title">{titles[currentPage] || t.nav.dashboard}</h2>
      </div>
      <div className="header-right">
        <button
          type="button"
          onClick={() => setColorTheme(colorTheme === 'dark' ? 'light' : 'dark')}
          className="btn btn-sm btn-secondary"
          title={colorTheme === 'dark' ? 'Light mode' : 'Dark mode'}
          aria-label={colorTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          style={{ padding: '8px 10px', minWidth: '40px' }}
        >
          {colorTheme === 'dark' ? (
            <SunIcon style={{ width: '18px', height: '18px' }} />
          ) : (
            <MoonIcon style={{ width: '18px', height: '18px' }} />
          )}
        </button>
        <div className="market-status">
          <span className={`dot ${isMarketOpen() || marketOpen ? 'open' : 'closed'}`} />
          <span>{isMarketOpen() || marketOpen ? t.header.marketOpen : t.header.marketClosed}</span>
        </div>
        <div className="header-badge paper" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <DocumentCheckIcon style={{ width: '14px', height: '14px' }} />
          {t.header.paperTrading}
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

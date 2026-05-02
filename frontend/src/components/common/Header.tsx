import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { isMarketOpen } from '../../utils/helpers';
import UserMenu from './UserMenu';
import { useI18n } from '../../i18n';

// Heroicons v2 Outline SVGs
const DocumentCheckIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 0 1 9 9v.375M10.125 2.25A3.375 3.375 0 0 1 13.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 0 1 3.375 3.375M9 15l2.25 2.25L15 12" />
  </svg>
);

const MoonIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z"
    />
  </svg>
);

const SunIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z"
    />
  </svg>
);

const Header: React.FC = () => {
  const {
    currentPage,
    marketOpen,
    colorTheme,
    setColorTheme,
    authEmail,
    authAlpacaConfigured,
    authAlpacaPaperTrading,
  } = useAppStore();
  const { language, t } = useI18n();
  const [time, setTime] = React.useState(new Date());

  // Single source of truth for the mode badge:
  //   - signed-in user with stored Alpaca keys → DB ``alpaca_paper_trading``
  //   - guest / no keys → render as paper (legacy env-based engine cannot
  //     trade live without keys anyway).
  const isLive = Boolean(authEmail && authAlpacaConfigured && !authAlpacaPaperTrading);

  React.useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const titles: Record<string, string> = {
    dashboard: t('dashboard'),
    chart: t('liveChart'),
    agent: t('aiAgent'),
    trading: t('tradingBot'),
    portfolio: t('portfolio'),
    history: t('tradeHistory'),
    auth: t('signIn'),
    settings: t('settings'),
  };

  return (
    <header className="header">
      <div className="header-left">
        <h2 className="header-title">{titles[currentPage] || t('dashboard')}</h2>
      </div>
      <div className="header-right">
        <div className="header-session-meta">
          <div className="market-status">
            <span className={`dot ${isMarketOpen() || marketOpen ? 'open' : 'closed'}`} />
            <span>{isMarketOpen() || marketOpen ? t('marketOpen') : t('marketClosed')}</span>
          </div>
          <div
            className={`header-badge ${isLive ? 'live' : 'paper'}`}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              ...(isLive
                ? {
                    background: 'rgba(223, 72, 76, 0.14)',
                    border: '1px solid rgba(223, 72, 76, 0.42)',
                    color: 'var(--loss)',
                    fontWeight: 700,
                    letterSpacing: '0.02em',
                  }
                : {}),
            }}
            title={isLive ? 'Alpaca live trading API' : 'Alpaca paper trading API'}
          >
            <DocumentCheckIcon style={{ width: '14px', height: '14px' }} />
            {isLive ? t('liveTrading') : t('paperTrading')}
          </div>
          <div className="header-clock">
            {time.toLocaleTimeString(language === 'ko' ? 'ko-KR' : 'en-US', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: language !== 'ko',
            })}
          </div>
        </div>
        <button
          type="button"
          className="header-theme-toggle"
          onClick={() => setColorTheme(colorTheme === 'dark' ? 'light' : 'dark')}
          title={
            language === 'ko'
              ? colorTheme === 'dark'
                ? '라이트 모드로 전환'
                : '다크 모드로 전환'
              : colorTheme === 'dark'
                ? 'Switch to light mode'
                : 'Switch to dark mode'
          }
          aria-label={
            language === 'ko'
              ? colorTheme === 'dark'
                ? '라이트 모드로 전환'
                : '다크 모드로 전환'
              : colorTheme === 'dark'
                ? 'Switch to light mode'
                : 'Switch to dark mode'
          }
          style={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            border: '1px solid var(--border-secondary)',
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
            flexShrink: 0,
          }}
        >
          {colorTheme === 'dark' ? (
            <SunIcon style={{ width: 22, height: 22 }} aria-hidden />
          ) : (
            <MoonIcon style={{ width: 22, height: 22 }} aria-hidden />
          )}
        </button>
        <div className="header-user-menu">
          <UserMenu />
        </div>
      </div>
    </header>
  );
};

export default Header;

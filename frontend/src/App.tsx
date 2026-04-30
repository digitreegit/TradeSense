import React, { useEffect, useState } from 'react';
import Sidebar, { SidebarNavAndFooter } from './components/Sidebar/Sidebar';
import Header from './components/common/Header';
import Dashboard from './components/Dashboard/Dashboard';
import ChartView from './components/Charts/ChartView';
import AgentPanel from './components/Agent/AgentPanel';
import TradingBot from './components/Trading/TradingBot';
import Portfolio from './components/Portfolio/Portfolio';
import History from './components/Portfolio/History';
import AuthPage from './components/Auth/AuthPage';
import SettingsPage from './components/Settings/SettingsPage';
import { useAppStore } from './stores/useAppStore';
import { useMarketData } from './hooks/useMarketData';
import api from './services/api';
import { getLastAuthMethod, setToken } from './auth/token';
import { supabase } from './auth/supabase';
import { useI18n } from './i18n';

const MenuIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden>
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
  </svg>
);

const CloseIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden>
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
  </svg>
);

const MoonIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden>
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z"
    />
  </svg>
);

const SunIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden>
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z"
    />
  </svg>
);

const App: React.FC = () => {
  const {
    currentPage,
    setCurrentPage,
    setAuthProfile,
    setAuthMethod,
    authEmail,
    colorTheme,
    setColorTheme,
  } = useAppStore();
  const [bootstrapped, setBootstrapped] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { t, language } = useI18n();

  useMarketData(); // Poll only when authEmail is set

  useEffect(() => {
    let cancelled = false;

    const syncProfile = async () => {
      try {
        const { data: sessionData } = await supabase.auth.getSession();
        const supaToken = sessionData.session?.access_token ?? null;
        if (supaToken) {
          setToken(supaToken);
        }
        const me = await api.getMe();
        if (cancelled) return;
        if (me.authenticated && me.email) {
          setAuthProfile(
            me.email,
            Boolean(me.alpaca_configured),
            typeof me.alpaca_paper_trading === 'boolean' ? me.alpaca_paper_trading : true,
          );
          setAuthMethod(getLastAuthMethod());
        } else {
          setAuthProfile(null, false);
          setAuthMethod(null);
        }
      } catch {
        if (!cancelled) {
          setAuthProfile(null, false);
          setAuthMethod(null);
        }
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    };

    supabase.auth.getSession().then(() => {
      if (!cancelled) void syncProfile();
    });

    const { data } = supabase.auth.onAuthStateChange(() => {
      if (!cancelled) void syncProfile();
    });

    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, [setAuthProfile, setAuthMethod]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileNavOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (mobileNavOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1025px)');
    const onChange = () => {
      if (mq.matches) setMobileNavOpen(false);
    };
    mq.addEventListener('change', onChange);
    onChange();
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard': return <Dashboard />;
      case 'chart': return <ChartView />;
      case 'agent': return <AgentPanel />;
      case 'trading': return <TradingBot />;
      case 'portfolio': return <Portfolio />;
      case 'history': return <History />;
      case 'settings': return <SettingsPage />;
      default: return <Dashboard />;
    }
  };

  if (!bootstrapped) {
    return (
      <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        {t('loading')}
      </div>
    );
  }

  if (!authEmail) {
    return <AuthPage />;
  }

  const menuLabel = language === 'ko' ? '메뉴' : 'Menu';
  const openMenuLabel = language === 'ko' ? '메뉴 열기' : 'Open menu';
  const closeMenuLabel = language === 'ko' ? '메뉴 닫기' : 'Close menu';

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content">
        <div className="mobile-app-bar">
          <button
            type="button"
            className="mobile-app-bar-brand"
            onClick={() => {
              setCurrentPage('dashboard');
              setMobileNavOpen(false);
            }}
            aria-label="TradeSense — Dashboard"
          >
            <div className="sidebar-logo-icon mobile-app-bar-logo-icon" aria-hidden>
              <img
                src="/sidebar-logo.svg"
                alt=""
                className="sidebar-logo-mark"
                width={32}
                height={32}
                decoding="async"
              />
            </div>
            <span className="mobile-app-bar-title" lang="en">
              TradeSense
            </span>
          </button>
          <div className="mobile-app-bar-end">
            <button
              type="button"
              className="mobile-theme-toggle"
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
            >
              {colorTheme === 'dark' ? (
                <SunIcon width={22} height={22} />
              ) : (
                <MoonIcon width={22} height={22} />
              )}
            </button>
            <button
              type="button"
              className="mobile-menu-button"
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-nav-drawer"
              onClick={() => setMobileNavOpen(true)}
              aria-label={openMenuLabel}
            >
              <MenuIcon width={22} height={22} />
            </button>
          </div>
        </div>
        <Header />
        <main className="main-body">{renderPage()}</main>
      </div>

      {mobileNavOpen ? (
        <>
          <div
            className="nav-drawer-backdrop"
            aria-hidden
            onClick={() => setMobileNavOpen(false)}
          />
          <aside
            id="mobile-nav-drawer"
            className="nav-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={menuLabel}
          >
            <div className="nav-drawer-header">
              <span className="nav-drawer-title">{menuLabel}</span>
              <button
                type="button"
                className="nav-drawer-close"
                onClick={() => setMobileNavOpen(false)}
                aria-label={closeMenuLabel}
              >
                <CloseIcon width={22} height={22} />
              </button>
            </div>
            <SidebarNavAndFooter onNavigate={() => setMobileNavOpen(false)} />
          </aside>
        </>
      ) : null}
    </div>
  );
};

export default App;

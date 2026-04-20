import React, { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar/Sidebar';
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
import { getToken } from './auth/token';

const App: React.FC = () => {
  const { currentPage, setCurrentPage, setAuthProfile } = useAppStore();
  const [authReady, setAuthReady] = useState(false);
  const [needsAlpaca, setNeedsAlpaca] = useState(false);

  useMarketData(); // Poll Alpaca-backed data (~15s)

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const t = getToken();
      if (!t) {
        setAuthReady(true);
        return;
      }
      try {
        const me = await api.getMe();
        if (cancelled) return;
        if (me.authenticated && me.email) {
          setAuthProfile(me.email, Boolean(me.alpaca_configured));
          if (!me.alpaca_configured) {
            setNeedsAlpaca(true);
            setCurrentPage('auth');
          }
        }
      } catch {
        if (!cancelled) setAuthProfile(null, false);
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setAuthProfile, setCurrentPage]);

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard': return <Dashboard />;
      case 'chart': return <ChartView />;
      case 'agent': return <AgentPanel />;
      case 'trading': return <TradingBot />;
      case 'portfolio': return <Portfolio />;
      case 'history': return <History />;
      case 'auth':
        return (
          <AuthPage
            onDone={() => {
              setNeedsAlpaca(false);
              setCurrentPage('dashboard');
            }}
            initialAlpacaStep={needsAlpaca}
          />
        );
      case 'settings': return <SettingsPage />;
      default: return <Dashboard />;
    }
  };

  if (!authReady) {
    return (
      <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content">
        <Header />
        <main className="main-body">
          {renderPage()}
        </main>
      </div>
    </div>
  );
};

export default App;

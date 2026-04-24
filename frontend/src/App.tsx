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
import ProfilePage from './components/Profile/ProfilePage';
import { useAppStore } from './stores/useAppStore';
import { useMarketData } from './hooks/useMarketData';
import api from './services/api';
import { getLastAuthMethod, setToken } from './auth/token';
import { supabase } from './auth/supabase';

const App: React.FC = () => {
  const { currentPage, setCurrentPage, setAuthProfile, setAuthMethod, authEmail } = useAppStore();
  const [bootstrapped, setBootstrapped] = useState(false);

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

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard': return <Dashboard />;
      case 'chart': return <ChartView />;
      case 'agent': return <AgentPanel />;
      case 'trading': return <TradingBot />;
      case 'portfolio': return <Portfolio />;
      case 'history': return <History />;
      case 'settings': return <SettingsPage />;
      case 'profile': return <ProfilePage />;
      default: return <Dashboard />;
    }
  };

  if (!bootstrapped) {
    return (
      <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        Loading…
      </div>
    );
  }

  if (!authEmail) {
    return <AuthPage />;
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

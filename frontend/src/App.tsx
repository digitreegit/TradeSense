import React from 'react';
import Sidebar from './components/Sidebar/Sidebar';
import Header from './components/common/Header';
import Dashboard from './components/Dashboard/Dashboard';
import ChartView from './components/Charts/ChartView';
import AgentPanel from './components/Agent/AgentPanel';
import TradingBot from './components/Trading/TradingBot';
import Portfolio from './components/Portfolio/Portfolio';
import History from './components/Portfolio/History';
import { useAppStore } from './stores/useAppStore';
import { useMarketData } from './hooks/useMarketData';

const App: React.FC = () => {
  const { currentPage } = useAppStore();
  useMarketData(); // ← 실시간 Alpaca 데이터 fetch (15초마다 갱신)

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard': return <Dashboard />;
      case 'chart': return <ChartView />;
      case 'agent': return <AgentPanel />;
      case 'trading': return <TradingBot />;
      case 'portfolio': return <Portfolio />;
      case 'history': return <History />;
      default: return <Dashboard />;
    }
  };

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

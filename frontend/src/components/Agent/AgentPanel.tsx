import React, { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { generateId } from '../../utils/helpers';

const AgentPanel: React.FC = () => {
  const {
    agentMessages,
    addAgentMessage,
    agentLoading,
    setAgentLoading,
    selectedSymbol,
  } = useAppStore();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentMessages]);

  const handleSend = async () => {
    if (!input.trim() || agentLoading) return;

    const userMsg = {
      id: generateId(),
      role: 'user' as const,
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    addAgentMessage(userMsg);
    setInput('');
    setAgentLoading(true);

    // Simulate AI response (will be replaced with actual API call)
    setTimeout(() => {
      const responses = getAIResponse(userMsg.content, selectedSymbol);
      addAgentMessage({
        id: generateId(),
        role: 'ai',
        content: responses,
        timestamp: new Date().toISOString(),
      });
      setAgentLoading(false);
    }, 1500 + Math.random() * 1000);
  };

  const quickActions = [
    { label: `Analyze ${selectedSymbol}`, msg: `${selectedSymbol} 종합 분석해줘` },
    { label: 'Market Overview', msg: '현재 시장 상황 분석해줘' },
    { label: 'Trading Signal', msg: '지금 매매 시그널 있어?' },
    { label: 'Portfolio Review', msg: '내 포트폴리오 리뷰해줘' },
    { label: 'Risk Report', msg: '리스크 리포트 보여줘' },
  ];

  return (
    <div className="page-enter" style={{
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 64px - 48px)',
    }}>
      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="card-header">
          <span className="card-title">
            🤖 TradeSense AI Agent
            <span style={{
              fontSize: '10px',
              padding: '2px 8px',
              background: 'var(--accent-primary-dim)',
              color: 'var(--accent-primary)',
              borderRadius: 'var(--radius-full)',
              fontWeight: 600,
              marginLeft: '8px',
            }}>
              GPT-4o Powered
            </span>
          </span>
          <div style={{ display: 'flex', gap: '8px' }}>
            {quickActions.slice(0, 3).map((action, i) => (
              <button
                key={i}
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  setInput(action.msg);
                }}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>

        <div className="agent-messages" style={{ flex: 1, minHeight: 0 }}>
          {agentMessages.map((msg) => (
            <div key={msg.id} className={`agent-message ${msg.role}`}>
              <div className={`agent-avatar ${msg.role}`}>
                {msg.role === 'ai' ? '🤖' : '👤'}
              </div>
              <div className="agent-bubble">
                {msg.content.split('\n').map((line, i) => (
                  <React.Fragment key={i}>
                    {line}
                    {i < msg.content.split('\n').length - 1 && <br />}
                  </React.Fragment>
                ))}
              </div>
            </div>
          ))}

          {agentLoading && (
            <div className="agent-message ai">
              <div className="agent-avatar ai">🤖</div>
              <div className="agent-bubble" style={{
                display: 'flex',
                gap: '4px',
                alignItems: 'center',
              }}>
                <span className="spinner" style={{ width: 14, height: 14 }} />
                <span style={{ color: 'var(--text-tertiary)', fontSize: '12px', marginLeft: '8px' }}>
                  Analyzing...
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Actions */}
        <div style={{
          display: 'flex',
          gap: '6px',
          padding: '8px 16px 0',
          overflowX: 'auto',
        }}>
          {quickActions.map((action, i) => (
            <button
              key={i}
              onClick={() => setInput(action.msg)}
              style={{
                padding: '4px 12px',
                border: '1px solid var(--border-primary)',
                borderRadius: 'var(--radius-full)',
                background: 'none',
                color: 'var(--text-tertiary)',
                fontSize: '11px',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                fontFamily: 'var(--font-sans)',
                transition: 'all var(--transition-fast)',
              }}
              onMouseOver={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--accent-primary)';
                (e.target as HTMLElement).style.color = 'var(--accent-primary)';
              }}
              onMouseOut={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--border-primary)';
                (e.target as HTMLElement).style.color = 'var(--text-tertiary)';
              }}
            >
              {action.label}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="agent-input-container">
          <input
            className="agent-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask TradeSense AI anything about stocks, strategies, or market..."
            disabled={agentLoading}
          />
          <button
            className="agent-send-btn"
            onClick={handleSend}
            disabled={agentLoading || !input.trim()}
          >
            ▶
          </button>
        </div>
      </div>
    </div>
  );
};

// Mock AI responses (will be replaced with actual LLM API)
function getAIResponse(input: string, symbol: string): string {
  const lower = input.toLowerCase();

  if (lower.includes('분석') || lower.includes('analyze')) {
    return `📊 **${symbol} 종합 분석 리포트**\n\n` +
      `🔹 기술적 분석:\n` +
      `  • RSI (14): 58.3 → 중립 구간\n` +
      `  • MACD: 양의 영역, 시그널선 상회\n` +
      `  • 볼린저밴드: 중간밴드 근처 (±1σ)\n` +
      `  • 20일 MA: 현재가 위에 위치 ✅\n\n` +
      `🔹 추세 분석:\n` +
      `  • 단기(5일): 상승 추세 📈\n` +
      `  • 중기(20일): 횡보\n` +
      `  • 장기(50일): 약세 회복 중\n\n` +
      `🔹 추천:\n` +
      `  • 진입: $${(Math.random() * 10 + 185).toFixed(2)} 부근에서 매수 고려\n` +
      `  • 손절: -2% ($${(Math.random() * 5 + 180).toFixed(2)})\n` +
      `  • 목표: +5% ($${(Math.random() * 10 + 195).toFixed(2)})\n\n` +
      `⚠️ Paper Trading 모드: 실제 자금 위험 없음`;
  }

  if (lower.includes('시장') || lower.includes('market')) {
    return `🌍 **시장 상황 분석**\n\n` +
      `📈 주요 지수:\n` +
      `  • S&P 500: 5,243.77 (+0.45%)\n` +
      `  • NASDAQ: 16,428.82 (+0.72%)\n` +
      `  • DOW: 39,512.84 (+0.21%)\n\n` +
      `🔥 섹터별 흐름:\n` +
      `  • 기술주: 강세 ▲ (AI, 반도체 주도)\n` +
      `  • 헬스케어: 약보합 ▬\n` +
      `  • 에너지: 약세 ▼\n` +
      `  • 금융: 보합 ▬\n\n` +
      `💡 인사이트:\n` +
      `  FOMC 회의 결과 대기 중. 금리 동결 예상이 우세하며,\n` +
      `  AI 관련 종목들이 시장을 주도하고 있습니다.`;
  }

  if (lower.includes('시그널') || lower.includes('signal')) {
    return `⚡ **매매 시그널 리포트**\n\n` +
      `🟢 매수 시그널:\n` +
      `  • AMD: RSI 과매도 반등 + MACD 골든크로스\n` +
      `  • AMZN: 20일선 지지 확인, 거래량 증가\n\n` +
      `🔴 매도 시그널:\n` +
      `  • TSLA: RSI 70 이상 과매수 영역\n` +
      `  • META: 볼린저 상단 터치, 이격도 확대\n\n` +
      `⚪ 관망:\n` +
      `  • AAPL, MSFT: 뚜렷한 방향성 부재\n\n` +
      `📊 현재 전략: 모멘텀 전략 기준\n` +
      `🎯 신뢰도: 72%`;
  }

  if (lower.includes('포트폴리오') || lower.includes('portfolio')) {
    return `💼 **포트폴리오 리뷰**\n\n` +
      `📊 현재 상태:\n` +
      `  • 총 자산: $1,000.00\n` +
      `  • 현금: $1,000.00\n` +
      `  • 포지션: 없음\n\n` +
      `📝 추천:\n` +
      `  $1,000으로 효율적인 트레이딩을 위해:\n` +
      `  1. 포지션당 최대 20% ($200) 투자\n` +
      `  2. 동시 최대 3-4개 포지션\n` +
      `  3. 손절라인: 각 포지션 -3%\n` +
      `  4. 익절라인: +5~8%\n\n` +
      `⚡ Trading Bot을 시작하면 자동으로 분석 및 매매를 시작합니다.`;
  }

  if (lower.includes('리스크') || lower.includes('risk')) {
    return `⚠️ **리스크 리포트**\n\n` +
      `🛡️ 리스크 매트릭스:\n` +
      `  • 포트폴리오 VaR (95%): -$28.50 / day\n` +
      `  • 최대 손실 가능: -$50.00 (5%)\n` +
      `  • 샤프 비율: N/A (거래 이력 부족)\n\n` +
      `📋 리스크 관리 규칙:\n` +
      `  ✅ 단일 종목 최대 비중: 25%\n` +
      `  ✅ 일일 최대 손실: -3% ($30)\n` +
      `  ✅ 자동 손절: 각 포지션 -2%\n` +
      `  ✅ Day Trade 제한: 3회/5일\n\n` +
      `💡 $1,000 계좌는 PDT 규칙에 해당되므로\n` +
      `   5일간 3회 이상 당일 매매를 피해야 합니다.`;
  }

  return `📋 이해했습니다! "${input}"에 대해 분석해 드리겠습니다.\n\n` +
    `현재 ${symbol}을 모니터링 중이며, Paper Trading 모드로 안전하게 테스트하고 있습니다.\n\n` +
    `다음을 시도해보세요:\n` +
    `  • "${symbol} 분석해줘" - 종합 기술적 분석\n` +
    `  • "매매 시그널 있어?" - 현재 매매 기회\n` +
    `  • "시장 상황" - 전체 시장 분석\n` +
    `  • "포트폴리오 리뷰" - 포트폴리오 점검\n` +
    `  • "리스크 리포트" - 위험 분석`;
}

export default AgentPanel;

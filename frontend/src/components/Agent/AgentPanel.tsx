import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { useUiStrings } from '../../hooks/useUiStrings';
import { generateId } from '../../utils/helpers';
import api from '../../services/api';

const AgentPanel: React.FC = () => {
  const t = useUiStrings();
  const a = t.agent;
  const {
    agentMessages,
    addAgentMessage,
    agentLoading,
    setAgentLoading,
    selectedSymbol,
    appLocale,
  } = useAppStore();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentMessages]);

  const handleSend = async () => {
    if (!input.trim() || agentLoading) return;

    const raw = input.trim();
    const queryForApi =
      appLocale === 'ko' ? `다음에 한국어로 답하세요. 전문용어는 필요하면 괄호로 영어를 병기해도 됩니다.\n\n${raw}` : raw;
    const userMsg = {
      id: generateId(),
      role: 'user' as const,
      content: raw,
      timestamp: new Date().toISOString(),
    };

    addAgentMessage(userMsg);
    setInput('');
    setAgentLoading(true);

    try {
      const result = await api.chat(queryForApi) as { response: string };
      let content = result.response || a.noResponse;
      
      // Filter out raw API error dumps from Gemini quota issues
      if (content.includes('RESOURCE_EXHAUSTED') || content.includes('429') || content.includes('quota')) {
        content = a.quotaError;
      }
      
      addAgentMessage({
        id: generateId(),
        role: 'ai',
        content,
        timestamp: new Date().toISOString(),
      });
    } catch (error) {
      console.error('AI Agent Error:', error);
      addAgentMessage({
        id: generateId(),
        role: 'ai',
        content: a.serverError('`cd backend && python -m uvicorn app.main:app --reload`'),
        timestamp: new Date().toISOString(),
      });
    } finally {
      setAgentLoading(false);
    }
  };

  const quickActions = useMemo(
    () => [
      { label: a.analyzeSym(selectedSymbol), msg: a.quickMsgAnalyze(selectedSymbol) },
      { label: a.marketOverview, msg: a.quickMsgMarket },
      { label: a.tradingSignal, msg: a.quickMsgSignal },
      { label: a.portfolioReview, msg: a.quickMsgPortfolio },
      { label: a.riskReport, msg: a.quickMsgRisk },
    ],
    [a, selectedSymbol],
  );

  return (
    <div className="page-enter" style={{
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 64px - 48px)',
    }}>
      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="card-header">
          <span className="card-title">
            🤖 {a.title}
            <span style={{
              fontSize: '10px',
              padding: '2px 8px',
              background: 'var(--accent-primary-dim)',
              color: 'var(--accent-primary)',
              borderRadius: 'var(--radius-full)',
              fontWeight: 600,
              marginLeft: '8px',
              textTransform: 'uppercase'
            }}>
              {import.meta.env.VITE_AI_PROVIDER === 'openai' ? 'GPT-4o' : 'Gemini 2.0'} Powered
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
                  {a.analyzing}
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
                fontSize: '12px',
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
            placeholder={a.placeholder}
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



export default AgentPanel;

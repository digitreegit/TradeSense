import React, { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { generateId } from '../../utils/helpers';
import api from '../../services/api';

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

    const query = input.trim();
    const userMsg = {
      id: generateId(),
      role: 'user' as const,
      content: query,
      timestamp: new Date().toISOString(),
    };

    addAgentMessage(userMsg);
    setInput('');
    setAgentLoading(true);

    try {
      const result = await api.chat(query) as { response: string };
      let content = result.response || "⚠️ 답변을 생성할 수 없습니다.";
      
      // Filter out raw API error dumps from Gemini quota issues
      if (content.includes('RESOURCE_EXHAUSTED') || content.includes('429') || content.includes('quota')) {
        content = "⚠️ AI 분석 요청이 일시적으로 제한되었습니다.\n\n" +
          "Google Gemini 무료 API의 분당 호출 제한에 도달했습니다.\n" +
          "약 1분 후에 다시 시도해 주세요.\n\n" +
          "💡 TIP: Trading Bot이 실행 중이면 봇도 AI를 사용하므로,\n" +
          "채팅 전에 봇을 잠시 멈추면 더 원활하게 대화할 수 있습니다.";
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
        content: "⚠️ 서버와 연결할 수 없습니다.\n\n서버가 실행 중인지 확인해 주세요.\n(터미널에서 backend 폴더로 이동 후 `python -m uvicorn app.main:app --reload` 실행)",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setAgentLoading(false);
    }
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



export default AgentPanel;

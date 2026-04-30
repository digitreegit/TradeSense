import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { generateId } from '../../utils/helpers';
import { buildAgentWelcomeMessage } from '../../utils/agentWelcome';
import { renderLineWithBold } from '../../utils/renderAgentBold';
import api from '../../services/api';
import { useI18n } from '../../i18n';
import { AiAgentIcon } from '../icons/AiAgentIcon';

const AgentPanel: React.FC = () => {
  const {
    agentMessages,
    addAgentMessage,
    agentLoading,
    setAgentLoading,
    selectedSymbol,
    account,
    authAlpacaConfigured,
    authAlpacaPaperTrading,
    agentDailyTargetPct,
    agentDailyLossLimitPct,
    agentPaperCapitalUsd,
    setAgentTradingGoals,
  } = useAppStore();
  const { language, t } = useI18n();

  const isPaper = !authAlpacaConfigured || authAlpacaPaperTrading;
  const introCapitalUsd = useMemo(
    () => (isPaper ? (agentPaperCapitalUsd ?? account.initial_capital) : account.equity),
    [isPaper, agentPaperCapitalUsd, account.initial_capital, account.equity],
  );

  const [draftPaperUsd, setDraftPaperUsd] = useState('');
  const [draftDailyPct, setDraftDailyPct] = useState('');
  const [draftLossPct, setDraftLossPct] = useState('');

  useEffect(() => {
    setDraftPaperUsd(
      String(agentPaperCapitalUsd ?? Math.round(account.initial_capital * 100) / 100),
    );
    setDraftDailyPct(String(agentDailyTargetPct));
    setDraftLossPct(String(agentDailyLossLimitPct));
  }, [agentPaperCapitalUsd, account.initial_capital, agentDailyTargetPct, agentDailyLossLimitPct]);

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [aiModelBadge, setAiModelBadge] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    api.getHealth().then((h) => {
      if (cancelled) return;
      const label = typeof h.ai_model === 'string' && h.ai_model.trim() ? h.ai_model.trim() : '';
      setAiModelBadge(label);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

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
      const localizedQuery = language === 'ko'
        ? `사용자가 한국어 UI를 선택했습니다. 반드시 자연스러운 한국어로 답변하세요. 종목 티커, 지표명, 숫자는 원문을 유지해도 됩니다.\n\n사용자 질문: ${query}`
        : query;
      const result = await api.chat(localizedQuery) as { response: string };
      let content = result.response || (language === 'ko' ? "⚠️ 응답을 생성하지 못했습니다." : "⚠️ Could not generate a response.");
      
      // Filter out raw API error dumps from Gemini quota issues
      if (content.includes('RESOURCE_EXHAUSTED') || content.includes('429') || content.includes('quota')) {
        content = language === 'ko'
          ? "⚠️ AI 요청이 일시적으로 제한되었습니다.\n\nGemini API 사용량 또는 속도 제한에 도달했습니다.\n약 1분 후 다시 시도하세요.\n\n💡 팁: 트레이딩 봇도 AI를 사용하므로, 더 원활한 채팅을 원하면 봇을 잠시 중지하세요."
          : "⚠️ AI requests are temporarily limited.\n\nThe Gemini API rate or quota limit was hit.\nTry again in about a minute.\n\n💡 TIP: If the Trading Bot is running it also uses AI — pause the bot for smoother chat.";
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
        content: language === 'ko'
          ? "⚠️ 서버에 연결할 수 없습니다.\n\n백엔드가 실행 중인지 확인하세요:\n`cd backend && python -m uvicorn app.main:app --reload`"
          : "⚠️ Cannot reach the server.\n\nMake sure the backend is running:\n`cd backend && python -m uvicorn app.main:app --reload`",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setAgentLoading(false);
      void api.getHealth().then((h) => {
        const label = typeof h.ai_model === 'string' && h.ai_model.trim() ? h.ai_model.trim() : '';
        setAiModelBadge(label);
      }).catch(() => {});
    }
  };

  const quickActions = [
    { label: `${t('analyze')} ${selectedSymbol}`, msg: language === 'ko' ? `${selectedSymbol} 전체 분석을 해줘` : `Give a full analysis of ${selectedSymbol}` },
    { label: t('marketOverview'), msg: language === 'ko' ? '현재 시장 상황을 요약해줘' : 'Summarize current market conditions' },
    { label: t('tradingSignal'), msg: language === 'ko' ? '지금 거래 신호가 있어?' : 'Any trading signals right now?' },
    { label: t('portfolioReview'), msg: language === 'ko' ? '내 포트폴리오를 점검해줘' : 'Review my portfolio' },
    { label: t('riskReport'), msg: language === 'ko' ? '리스크 보고서를 보여줘' : 'Show a risk report' },
  ];

  const getMessageBody = (msg: { id: string; content: string }) => {
    if (msg.id === 'welcome') {
      return buildAgentWelcomeMessage({
        language: language === 'ko' ? 'ko' : 'en',
        isPaper,
        capitalUsd: introCapitalUsd,
        dailyPct: agentDailyTargetPct,
        dailyLossLimitPct: agentDailyLossLimitPct,
      });
    }
    return msg.content;
  };

  const commitPaperUsd = () => {
    const n = parseFloat(draftPaperUsd.replace(/,/g, ''));
    if (!Number.isFinite(n) || n < 1) {
      setDraftPaperUsd(String(agentPaperCapitalUsd ?? account.initial_capital));
      return;
    }
    const capped = Math.min(1e9, n);
    const initial = account.initial_capital;
    if (Math.abs(capped - initial) < 0.005) {
      setAgentTradingGoals({ paperCapitalUsd: null });
    } else {
      setAgentTradingGoals({ paperCapitalUsd: capped });
    }
  };

  const commitDailyPct = () => {
    const n = parseFloat(draftDailyPct.replace(/,/g, ''));
    if (Number.isFinite(n) && n > 0) {
      setAgentTradingGoals({ dailyPct: n });
    } else {
      setDraftDailyPct(String(agentDailyTargetPct));
    }
  };

  const commitLossPct = () => {
    const n = parseFloat(draftLossPct.replace(/,/g, ''));
    if (Number.isFinite(n) && n > 0) {
      setAgentTradingGoals({ dailyLossLimitPct: n });
    } else {
      setDraftLossPct(String(agentDailyLossLimitPct));
    }
  };

  return (
    <div className="page-enter" style={{
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 64px - 48px)',
    }}>
      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="card-header">
          <span className="card-title" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <AiAgentIcon className="card-icon" aria-hidden style={{ width: 18, height: 18 }} />
            {t('aiAgentTitle')}
            <span style={{
              fontSize: '10px',
              padding: '2px 8px',
              background: 'var(--accent-primary-dim)',
              color: 'var(--accent-primary)',
              borderRadius: 'var(--radius-full)',
              fontWeight: 600,
              marginLeft: '8px',
            }}>
              {aiModelBadge ? `${aiModelBadge} · ${t('powered')}` : t('loading')}
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

        <div
          className="agent-goals-bar"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '12px',
            padding: '10px 20px',
            borderBottom: '1px solid var(--border-secondary)',
            fontSize: '12px',
            color: 'var(--text-secondary)',
          }}
        >
          <span style={{ fontWeight: 650, color: 'var(--text-primary)' }}>{t('agentGoalsTitle')}</span>
          {isPaper ? (
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              {t('agentGoalPaperUsd')}
              <input
                type="number"
                min={1}
                step="any"
                value={draftPaperUsd}
                onChange={(e) => setDraftPaperUsd(e.target.value)}
                onBlur={commitPaperUsd}
                onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
                style={{
                  width: '100px',
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-primary)',
                  background: 'var(--bg-input)',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                }}
              />
            </label>
          ) : (
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {t('agentGoalLiveEquity')}:{' '}
              {new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              }).format(account.equity)}
            </span>
          )}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            {t('agentGoalDailyPct')}
            <input
              type="number"
              min={0.01}
              step="any"
              value={draftDailyPct}
              onChange={(e) => setDraftDailyPct(e.target.value)}
              onBlur={commitDailyPct}
              onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
              style={{
                width: '72px',
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-primary)',
                background: 'var(--bg-input)',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
              }}
            />
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            {t('agentGoalLossLimitPct')}
            <input
              type="number"
              min={0.01}
              step="any"
              value={draftLossPct}
              onChange={(e) => setDraftLossPct(e.target.value)}
              onBlur={commitLossPct}
              onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
              style={{
                width: '72px',
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-primary)',
                background: 'var(--bg-input)',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
              }}
            />
          </label>
          {isPaper && agentPaperCapitalUsd !== null && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setAgentTradingGoals({ paperCapitalUsd: null });
              }}
            >
              {t('agentGoalResetToInitial')}
            </button>
          )}
          <span style={{ flex: '1 1 160px', opacity: 0.85, lineHeight: 1.35 }}>
            {isPaper ? t('agentGoalsHelpPaper') : t('agentGoalsHelpLive')}
          </span>
        </div>

        <div className="agent-messages" style={{ flex: 1, minHeight: 0 }}>
          {agentMessages.map((msg) => {
            const body = getMessageBody(msg);
            return (
            <div key={msg.id} className={`agent-message ${msg.role}`}>
              <div className={`agent-avatar ${msg.role}`}>
                {msg.role === 'ai' ? (
                  <AiAgentIcon style={{ width: 17, height: 17 }} aria-hidden />
                ) : (
                  '👤'
                )}
              </div>
              <div className="agent-bubble">
                {body.split('\n').map((line, i) => (
                  <React.Fragment key={i}>
                    {renderLineWithBold(line, i)}
                    {i < body.split('\n').length - 1 && <br />}
                  </React.Fragment>
                ))}
              </div>
            </div>
            );
          })}

          {agentLoading && (
            <div className="agent-message ai">
              <div className="agent-avatar ai">
                <AiAgentIcon style={{ width: 17, height: 17 }} aria-hidden />
              </div>
              <div className="agent-bubble" style={{
                display: 'flex',
                gap: '4px',
                alignItems: 'center',
              }}>
                <span className="spinner" style={{ width: 14, height: 14 }} />
                <span style={{ color: 'var(--text-tertiary)', fontSize: '12px', marginLeft: '8px' }}>
                  {t('analyzing')}
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
          marginBottom: 'var(--space-md)',
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
            placeholder={t('askAiPlaceholder')}
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

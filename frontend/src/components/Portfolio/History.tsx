import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency } from '../../utils/helpers';

// Heroicons v2 Outline SVGs
const ListBulletIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 17.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
  </svg>
);

const HistoryIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
  </svg>
);

const History: React.FC = () => {
  const { orders } = useAppStore();

  return (
    <div className="page-enter">
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            <ListBulletIcon className="card-icon" /> Trade History
          </span>
          <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
            {orders.length} order{orders.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div>
          {orders.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">
                <HistoryIcon style={{ width: '48px', height: '48px', color: 'var(--text-tertiary)' }} />
              </div>
              <div className="empty-state-title">No Trade History</div>
              <div className="empty-state-text">
                Your trade history will appear here once the bot starts executing trades in paper trading mode.
              </div>
            </div>
          ) : (
            <table className="positions-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td className="mono" style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                      {new Date(order.submitted_at).toLocaleString()}
                    </td>
                    <td className="symbol">{order.symbol}</td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        fontSize: '10px',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        background: order.side === 'buy' ? 'var(--profit-dim)' : 'var(--loss-dim)',
                        color: order.side === 'buy' ? 'var(--profit)' : 'var(--loss)',
                      }}>
                        {order.side}
                      </span>
                    </td>
                    <td style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                      {order.type}
                    </td>
                    <td className="mono">{order.qty}</td>
                    <td className="mono">
                      {order.filled_avg_price ? formatCurrency(order.filled_avg_price) : '—'}
                    </td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        fontSize: '10px',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        background: order.status === 'filled' ? 'var(--profit-dim)' :
                                   order.status === 'cancelled' ? 'var(--loss-dim)' : 'var(--accent-gold-dim)',
                        color: order.status === 'filled' ? 'var(--profit)' :
                               order.status === 'cancelled' ? 'var(--loss)' : 'var(--accent-gold)',
                      }}>
                        {order.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

export default History;

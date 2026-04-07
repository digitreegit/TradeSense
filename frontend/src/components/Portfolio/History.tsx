import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency } from '../../utils/helpers';

const History: React.FC = () => {
  const { orders } = useAppStore();

  return (
    <div className="page-enter">
      <div className="card">
        <div className="card-header">
          <span className="card-title">📋 Trade History</span>
          <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
            {orders.length} order{orders.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div>
          {orders.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📜</div>
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

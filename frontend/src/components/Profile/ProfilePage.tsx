import React from 'react';
import { useAppStore } from '../../stores/useAppStore';

const ProfilePage: React.FC = () => {
  const { authEmail, authAlpacaConfigured } = useAppStore();

  return (
    <div className="page-enter" style={{ maxWidth: 520, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Profile</h2>
        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Email</span>
          <br />
          <strong>{authEmail || '—'}</strong>
        </p>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginTop: '12px' }}>
          Alpaca paper keys: {authAlpacaConfigured ? 'saved on server (encrypted)' : 'not set — add them in Settings'}
        </p>
      </div>
    </div>
  );
};

export default ProfilePage;

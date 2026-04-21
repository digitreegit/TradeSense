import React, { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { clearToken } from '../../auth/token';
import { supabase } from '../../auth/supabase';

const UserIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A18.933 18.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
  </svg>
);

const UserMenu: React.FC = () => {
  const { authEmail, setAuthProfile, setCurrentPage, setAuthMethod } = useAppStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const logout = () => {
    void supabase.auth.signOut();
    clearToken();
    setAuthProfile(null, false);
    setAuthMethod(null);
    setOpen(false);
  };

  return (
    <div ref={ref} style={{ position: 'relative', zIndex: 1300 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        title="Account"
        style={{
          width: 40,
          height: 40,
          borderRadius: '50%',
          border: '1px solid var(--border-secondary)',
          background: 'var(--bg-secondary)',
          color: 'var(--text-primary)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0,
        }}
      >
        <UserIcon style={{ width: 22, height: 22 }} />
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            right: 0,
            top: 'calc(100% + 8px)',
            minWidth: 200,
            padding: '8px 0',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-secondary)',
            background: 'var(--bg-primary)',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 1400,
          }}
        >
          <div
            style={{
              padding: '8px 14px',
              fontSize: '11px',
              color: 'var(--text-tertiary)',
              borderBottom: '1px solid var(--border-secondary)',
              marginBottom: '4px',
            }}
          >
            {authEmail}
          </div>
          <button
            type="button"
            role="menuitem"
            className="user-menu-item"
            onClick={() => {
              setCurrentPage('profile');
              setOpen(false);
            }}
          >
            Profile
          </button>
          <button
            type="button"
            role="menuitem"
            className="user-menu-item"
            onClick={() => {
              setCurrentPage('settings');
              setOpen(false);
            }}
          >
            Settings
          </button>
          <button type="button" role="menuitem" className="user-menu-item user-menu-item-danger" onClick={logout}>
            Sign Out
          </button>
        </div>
      )}
    </div>
  );
};

export default UserMenu;

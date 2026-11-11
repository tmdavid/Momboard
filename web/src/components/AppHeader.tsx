import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthOptional } from '../App';
import { api } from '../api';

export function AppHeader() {
  const auth = useAuthOptional();
  const initial = auth ? (auth.user.name || auth.user.email)[0].toUpperCase() : '?';
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [term, setTerm] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // "/" focuses the global search (unless typing in a field already).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/') return;
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement ||
        (el instanceof HTMLElement && el.isContentEditable);
      if (!typing) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, [menuOpen]);

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    // Global search reuses the Library search (titles + transcripts); no new API.
    navigate(term.trim() ? `/?q=${encodeURIComponent(term.trim())}` : '/');
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } finally {
      queryClient.setQueryData(['me'], null);
      setMenuOpen(false);
      navigate('/');
    }
  };

  return (
    <header className="h-14 box-border flex items-center gap-6 px-5 bg-surface border-b border-hairline text-ink text-sm flex-none">
      <Link to="/" className="flex items-center gap-2.5 text-ink font-bold text-base no-underline hover:opacity-80">
        <span
          className="w-7 h-7 rounded-[7px] bg-ink text-white grid place-items-center text-sm"
          aria-hidden="true"
        >
          M
        </span>
        MomBoard
      </Link>

      <form onSubmit={submitSearch} className="flex-1 max-w-[520px] min-w-[180px]">
        <label className="flex items-center gap-2 h-9 px-3 rounded-lg bg-sub text-muted focus-within:bg-surface focus-within:border focus-within:border-accent">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
          <input
            ref={searchRef}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search calls, companies and quotes"
            aria-label="Search"
            className="flex-1 bg-transparent border-none outline-none text-ink-2 placeholder:text-muted min-w-0"
          />
          <span className="text-xs border border-hairline rounded px-1.5 bg-surface text-muted">/</span>
        </label>
      </form>

      <div className="ml-auto flex items-center gap-3">
        <NavLink
          to="/simulator"
          className={({ isActive }) =>
            `flex items-center h-9 px-3.5 rounded-lg border font-semibold no-underline ${
              isActive ? 'border-accent text-accent' : 'border-hairline text-ink hover:border-accent'
            }`
          }
        >
          Practice interview
        </NavLink>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            aria-label="Your profile"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="w-8 h-8 rounded-pill bg-accent-soft text-accent-ink grid place-items-center font-bold cursor-pointer border-none hover:opacity-90"
          >
            {initial}
          </button>
          {menuOpen && (
            <div role="menu" className="absolute right-0 mt-2 w-56 bg-surface border border-hairline rounded-xl shadow-lg p-1.5 z-50">
              {auth && (
                <div className="px-2.5 py-2 border-b border-hairline mb-1">
                  <div className="text-sm font-semibold truncate">{auth.user.name || auth.user.email}</div>
                  {auth.user.name && <div className="text-xs text-muted truncate">{auth.user.email}</div>}
                </div>
              )}
              <button
                type="button"
                role="menuitem"
                onClick={handleLogout}
                className="w-full text-left px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-sub"
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

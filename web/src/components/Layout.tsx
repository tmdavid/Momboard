import { useState, useRef, useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuthOptional } from '../App';
import { TAG_META } from '../constants';

// ─── Settings Dropdown (#22) ───

interface SettingsStatus {
  llm: { backend: string; model_normalizer: string; api_key_configured: boolean; api_key_hint: string };
  vexa: { configured: boolean; detail: string };
  gdrive: { configured: boolean; detail: string };
  slack: { configured: boolean; detail: string };
  digest: { slack_configured: boolean; schedule: string };
  taxonomy_count: number;
  active_company_count: number;
}

function SettingsDropdown({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const { data: status } = useQuery<SettingsStatus>({
    queryKey: ['settings-status'],
    queryFn: async () => {
      const res = await fetch('/api/settings/status', { credentials: 'include' });
      if (!res.ok) return null;
      return res.json();
    },
    staleTime: 60_000,
  });

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const stateClass = (ok: boolean) => ok ? 'text-good-text' : 'text-muted';

  return (
    <div
      ref={ref}
      role="menu"
      aria-label="Settings"
      className="absolute top-[46px] right-0 w-[280px] bg-surface border border-hairline rounded-xl shadow-lg p-2 z-30"
    >
      <h4 className="text-[11px] uppercase tracking-wider text-muted px-2.5 pt-2 pb-1 font-semibold">Sources</h4>
      <Link to="/meetings" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        🤖 Meeting bots
        <span className={`text-[11.5px] ${stateClass(status?.vexa?.configured ?? false)}`}>
          {status?.vexa?.configured ? 'connected' : 'not configured'}
        </span>
      </Link>
      <Link to="/settings" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        📁 Google Drive sync
        <span className={`text-[11.5px] ${stateClass(status?.gdrive?.configured ?? false)}`}>
          {status?.gdrive?.configured ? 'connected' : 'not configured'}
        </span>
      </Link>
      <h4 className="text-[11px] uppercase tracking-wider text-muted px-2.5 pt-2 pb-1 font-semibold">Delivery</h4>
      <Link to="/digest" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        📬 Weekly digest
        <span className={`text-[11.5px] ${stateClass(status?.digest?.slack_configured ?? false)}`}>
          {status?.digest?.schedule || 'not configured'}
        </span>
      </Link>
      <h4 className="text-[11px] uppercase tracking-wider text-muted px-2.5 pt-2 pb-1 font-semibold">System</h4>
      <Link to="/settings" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        🔑 LLM &amp; API keys
        <span className={`text-[11.5px] ${stateClass(status?.llm?.api_key_configured ?? false)}`}>
          {status?.llm ? `${status.llm.backend} · ${status.llm.api_key_hint}` : '—'}
        </span>
      </Link>
      <Link to="/settings" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        🏷 Taxonomy
        <span className="text-[11.5px] text-muted">
          {status ? `${status.taxonomy_count} tags` : '—'}
        </span>
      </Link>
      <Link to="/settings" className="flex justify-between items-center px-2.5 py-2 rounded-lg text-[13.5px] text-ink-2 hover:bg-page" onClick={onClose}>
        🏢 Companies &amp; contacts
        <span className="text-[11.5px] text-muted">
          {status ? `${status.active_company_count} active` : '—'}
        </span>
      </Link>
    </div>
  );
}

// ─── Help Popover (#4 preserved) ───

function HelpPopover({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Help — shortcuts and taxonomy"
      className="absolute top-[46px] right-0 w-[280px] bg-surface border border-hairline rounded-xl shadow-lg p-2 z-30"
    >
      <h4 className="text-[11px] uppercase tracking-wider text-muted px-2.5 pt-2 pb-1 font-semibold">Review shortcuts</h4>
      <div className="flex justify-between px-2.5 py-1 text-[13px] text-ink-2">
        <span>Next / prev suggestion</span>
        <span><kbd className="bg-page border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">j</kbd>{' '}<kbd className="bg-page border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">k</kbd></span>
      </div>
      <div className="flex justify-between px-2.5 py-1 text-[13px] text-ink-2">
        <span>Accept</span>
        <kbd className="bg-page border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">a</kbd>
      </div>
      <div className="flex justify-between px-2.5 py-1 text-[13px] text-ink-2">
        <span>Reject</span>
        <kbd className="bg-page border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">x</kbd>
      </div>
      <hr className="border-hairline my-1.5" />
      <h4 className="text-[11px] uppercase tracking-wider text-muted px-2.5 pt-1 pb-1 font-semibold">Taxonomy</h4>
      <div className="px-2.5 py-1 text-[13px] text-ink-2 flex flex-wrap gap-x-3 gap-y-0.5">
        {Object.entries(TAG_META).slice(0, 6).map(([key, meta]) => (
          <span key={key}>{meta.emoji} {meta.name}</span>
        ))}
      </div>
      <div className="px-2.5 py-1 text-[13px] text-ink-2 flex flex-wrap gap-x-3 gap-y-0.5">
        {Object.entries(TAG_META).slice(6).map(([key, meta]) => (
          <span key={key}>{meta.emoji} {meta.name}</span>
        ))}
      </div>
    </div>
  );
}

// ─── Layout ───

export function Layout() {
  const auth = useAuthOptional();
  const initial = auth ? (auth.user.name || auth.user.email)[0].toUpperCase() : '?';
  const [helpOpen, setHelpOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();

  // Pending inbox count for nav badge
  const { data: inboxData } = useQuery({
    queryKey: ['inbox', 'pending_import'],
    queryFn: async () => {
      const res = await fetch('/api/inbox?status=pending_import', { credentials: 'include' });
      if (!res.ok) return { total: 0 };
      return res.json() as Promise<{ total: number }>;
    },
    staleTime: 30_000,
  });
  const pendingCount = inboxData?.total ?? 0;

  const navLinks = [
    { to: '/', label: 'Library', end: true },
    { to: '/explore', label: 'Explore' },
    { to: '/hypotheses', label: 'Hypotheses' },
    { to: '/decisions', label: 'Decisions' },
    { to: '/insights', label: 'Insights' },
  ];

  // Close dropdowns on navigation
  useEffect(() => {
    setHelpOpen(false);
    setSettingsOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex flex-col h-screen">
      <nav className="sticky top-0 z-20 flex items-center gap-1.5 px-5 h-[52px] bg-surface border-b border-hairline flex-none">
        <Link to="/" className="font-extrabold tracking-tight mr-3.5 hover:opacity-80">
          Mom<span className="text-accent">Board</span>
        </Link>
        <div className="flex gap-1">
          {navLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `relative px-[13px] py-1.5 rounded-lg font-medium text-ink-2 ${
                  isActive ? 'bg-accent-soft !text-accent font-semibold' : 'hover:bg-page'
                }`
              }
            >
              {link.label}
              {link.to === '/' && pendingCount > 0 && (
                <span className="absolute -top-0.5 right-0 bg-crit text-white text-[10px] font-bold rounded-full px-[5px] py-px leading-tight border-2 border-surface">
                  {pendingCount}
                </span>
              )}
            </NavLink>
          ))}
        </div>
        <div className="flex-1" />

        {/* Practice pill — right-aligned */}
        <NavLink
          to="/simulator"
          className={({ isActive }) =>
            `inline-flex items-center gap-1.5 px-[13px] py-1.5 border rounded-full text-[13px] font-semibold cursor-pointer ${
              isActive ? 'border-accent bg-accent-soft text-accent' : 'border-hairline text-ink-2 hover:border-accent hover:text-accent'
            }`
          }
        >
          🎯 Practice
        </NavLink>

        {/* Settings gear dropdown */}
        <div className="relative">
          <button
            className="w-8 h-8 rounded-full grid place-items-center cursor-pointer text-ink-2 border-none bg-transparent text-[15px] hover:bg-page"
            onClick={() => { setSettingsOpen(!settingsOpen); setHelpOpen(false); }}
            aria-label="Settings"
            aria-expanded={settingsOpen}
          >
            ⚙
          </button>
          {settingsOpen && <SettingsDropdown onClose={() => setSettingsOpen(false)} />}
        </div>

        {/* Help popover */}
        <div className="relative">
          <button
            className="w-8 h-8 rounded-full grid place-items-center cursor-pointer text-ink-2 border-none bg-transparent text-[15px] hover:bg-page"
            onClick={() => { setHelpOpen(!helpOpen); setSettingsOpen(false); }}
            aria-label="Help"
            aria-expanded={helpOpen}
          >
            ?
          </button>
          {helpOpen && <HelpPopover onClose={() => setHelpOpen(false)} />}
        </div>

        {/* User avatar */}
        <div className="w-7 h-7 rounded-full bg-accent text-white grid place-items-center text-xs font-semibold">
          {initial}
        </div>
      </nav>
      <Outlet />
    </div>
  );
}

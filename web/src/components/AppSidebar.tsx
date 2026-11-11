import { NavLink } from 'react-router-dom';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  /** SVG path(s) for the 24x24 stroked icon. */
  d: string;
  /** Shows a count badge (used for the Library pending-inbox count). */
  badge?: number;
}

// Content items, then a gap, then tools (Practice, Settings). Order and icons
// follow momboard-ui-redesign/Sidebar.dc.html.
const CONTENT: NavItem[] = [
  { to: '/', label: 'Library', end: true, d: 'M4 5h5v14H4zM10 5h4v14h-4zM15 6l4-1 2 13-4 1z' },
  { to: '/explore', label: 'Explore', d: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4' },
  { to: '/summaries', label: 'Summaries', d: 'M6 3h9l4 4v14H6zM9 11h7M9 15h7M9 7h4' },
  { to: '/hypotheses', label: 'Hypotheses', d: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3' },
  { to: '/decisions', label: 'Decisions', d: 'M4 4h16v16H4zM8 12l3 3 5-6' },
  { to: '/insights', label: 'Insights', d: 'M4 20V10M10 20V4M16 20v-7M22 20H2' },
];

const TOOLS: NavItem[] = [
  { to: '/settings', label: 'Settings', d: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2' },
];

function Item({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        `relative flex items-center gap-3 h-[38px] px-3 rounded-lg no-underline ${
          isActive
            ? 'bg-accent-soft text-accent-ink font-semibold'
            : 'text-ink-2 font-medium hover:bg-sub'
        }`
      }
      aria-current={undefined}
    >
      {({ isActive }) => (
        <>
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d={item.d} />
          </svg>
          <span>{item.label}</span>
          {item.badge != null && item.badge > 0 && (
            <span className="ml-auto bg-crit text-white text-[10px] font-bold rounded-pill px-1.5 leading-tight">
              {item.badge}
            </span>
          )}
          {/* NavLink sets aria-current via isActive at the DOM level below. */}
          <span className="sr-only">{isActive ? ' (current page)' : ''}</span>
        </>
      )}
    </NavLink>
  );
}

export function AppSidebar({ pendingCount = 0 }: { pendingCount?: number }) {
  const content = CONTENT.map((i) =>
    i.to === '/' ? { ...i, badge: pendingCount } : i,
  );
  return (
    <nav
      aria-label="Main"
      className="box-border h-full min-h-[600px] w-[220px] flex flex-col gap-0.5 px-3 py-4 bg-[#fbfbfc] border-r border-hairline text-sm"
    >
      {content.map((item) => (
        <Item key={item.to} item={item} />
      ))}
      <div className="mt-5" />
      {TOOLS.map((item) => (
        <Item key={item.to} item={item} />
      ))}
    </nav>
  );
}

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { Tag } from '../api';

const QUICK_COUNT = 10;
/** How long the pointer must rest on a category before its tags fly out. */
const HOVER_DELAY_MS = 150;
const FLYOUT_WIDTH = 280;
const EDGE_MARGIN = 8;

interface TagFilterBarProps {
  /** Whether a given tag key is currently an active filter. */
  isActive: (key: string) => boolean;
  /** Toggle a tag key on/off. */
  onToggle: (key: string) => void;
}

type MenuId = 'core' | 'custom';

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Inside its own category a tag does not repeat the category: "Impersonation" under Product, not
 * "Product: Impersonation". Other categories' prefixes are left alone.
 */
export function displayName(tag: Tag, category: string): string {
  const forms = Array.from(new Set([category, category.replace(/_/g, ' ')]));
  for (const form of forms) {
    const stripped = tag.name.replace(new RegExp(`^\\s*${escapeRe(form)}\\s*[:\\-–—/]\\s*`, 'i'), '').trim();
    if (stripped && stripped !== tag.name.trim()) return stripped;
  }
  return tag.name;
}

/**
 * Curated tag filter bar (T47, v0.5).
 *
 * Reads the LIVE taxonomy so custom tags are filterable. Layout (two rows, full width):
 *  - row 1: "Most used" - the 10 most-common tags (curated via sort_order),
 *  - row 2: a "Core" dropdown (flat checkable list) and a "Custom" dropdown. Custom lists its
 *    categories; resting the pointer on one (or clicking it, for touch) flies its tags out to the
 *    right. Categories are data-driven, so a new one appears with no code change.
 *
 * One dropdown is open at a time. Escape closes the innermost open level (the flyout, then the
 * menu) and returns focus to the button; clicking outside closes everything. A menu or flyout
 * that would run off the right edge of the window opens to the left instead.
 */
export function TagFilterBar({ isActive, onToggle }: TagFilterBarProps) {
  const tax = useTaxonomy();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggers = useRef<Record<MenuId, HTMLButtonElement | null>>({ core: null, custom: null });
  const [openMenu, setOpenMenu] = useState<MenuId | null>(null);
  const [openCategory, setOpenCategory] = useState<string | null>(null);

  const closeAll = useCallback(() => {
    setOpenMenu(null);
    setOpenCategory(null);
  }, []);

  useEffect(() => {
    if (!openMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (openCategory) {
        setOpenCategory(null);          // innermost level first
      } else {
        const trigger = triggers.current[openMenu];
        closeAll();
        trigger?.focus();
      }
    };
    const onOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) closeAll();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onOutside);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onOutside);
    };
  }, [openMenu, openCategory, closeAll]);

  const ordered = [...tax.tags].sort((a, b) => a.sort_order - b.sort_order);
  const quick = ordered.slice(0, QUICK_COUNT);
  const core = ordered.filter((t) => t.origin === 'core');

  // Custom categories (data-driven, alphabetical) -> their tags.
  const custom = ordered.filter((t) => t.origin !== 'core');
  const categories = Array.from(
    new Set(custom.map((t) => t.category).filter((c): c is string => !!c)),
  ).sort((a, b) => a.localeCompare(b));
  const customGroups: { label: string; tags: Tag[] }[] = categories.map((cat) => ({
    label: cat,
    tags: custom.filter((t) => t.category === cat),
  }));
  const uncategorized = custom.filter((t) => !t.category);
  if (uncategorized.length) customGroups.push({ label: 'Other', tags: uncategorized });

  const chip = (t: Tag) => (
    <button
      key={t.key}
      type="button"
      onClick={() => onToggle(t.key)}
      className={`px-2.5 py-1 rounded-full border text-[13px] cursor-pointer ${
        isActive(t.key)
          ? 'bg-accent text-white border-accent font-semibold'
          : 'bg-surface border-hairline text-ink-2'
      }`}
    >
      {t.emoji} {t.name}
    </button>
  );

  const activeCount = (tags: Tag[]) => tags.filter((t) => isActive(t.key)).length;
  const hasDropdowns = core.length > 0 || customGroups.length > 0;
  const toggleMenu = (id: MenuId) => {
    setOpenCategory(null);
    setOpenMenu((current) => (current === id ? null : id));
  };

  return (
    <div ref={rootRef} className="basis-full w-full flex flex-col gap-2" data-testid="tag-filter-bar">
      <div className="flex flex-wrap items-center gap-1.5" data-testid="tag-quick-row">
        <span className="text-xs text-muted mr-0.5">Most used</span>
        {quick.map(chip)}
      </div>
      {hasDropdowns && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="tag-dropdown-row">
          <span className="text-xs text-muted mr-0.5">More tags</span>
          {core.length > 0 && (
            <FilterDropdown
              label="Core"
              activeCount={activeCount(core)}
              open={openMenu === 'core'}
              onToggle={() => toggleMenu('core')}
              triggerRef={(el) => { triggers.current.core = el; }}
              scroll
            >
              <div className="flex flex-col gap-0.5 min-w-[200px]">
                {core.map((t) => (
                  <DropdownItem key={t.key} label={t.name} emoji={t.emoji} isActive={isActive(t.key)} onToggle={() => onToggle(t.key)} />
                ))}
              </div>
            </FilterDropdown>
          )}
          {customGroups.length > 0 && (
            <FilterDropdown
              label="Custom"
              activeCount={activeCount(custom)}
              open={openMenu === 'custom'}
              onToggle={() => toggleMenu('custom')}
              triggerRef={(el) => { triggers.current.custom = el; }}
              // No scrolling: a scroll container would clip the flyout that opens beside it.
              scroll={false}
            >
              <CategoryList
                groups={customGroups}
                isActive={isActive}
                onToggle={onToggle}
                openCategory={openCategory}
                setOpenCategory={setOpenCategory}
              />
            </FilterDropdown>
          )}
        </div>
      )}
    </div>
  );
}

function FilterDropdown({
  label,
  activeCount,
  open,
  onToggle,
  triggerRef,
  scroll,
  children,
}: {
  label: string;
  activeCount: number;
  open: boolean;
  onToggle: () => void;
  triggerRef: (el: HTMLButtonElement | null) => void;
  scroll: boolean;
  children: React.ReactNode;
}) {
  const [alignRight, setAlignRight] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Open left-aligned with the trigger; if that would run past the right edge of the window, open
  // right-aligned instead. Re-checked when the menu resizes. Width does not depend on alignment,
  // so this cannot flip-flop.
  useLayoutEffect(() => {
    if (!open) {
      setAlignRight(false);
      return;
    }
    const place = () => {
      const trigger = ref.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      setAlignRight(trigger.getBoundingClientRect().left + menu.getBoundingClientRect().width > viewportWidth - EDGE_MARGIN);
    };
    place();
    if (typeof ResizeObserver === 'undefined' || !menuRef.current) return;
    const observer = new ResizeObserver(place);
    observer.observe(menuRef.current);
    return () => observer.disconnect();
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-haspopup="menu"
        className={`px-2.5 py-1 rounded-full border text-[13px] cursor-pointer ${
          activeCount > 0 ? 'border-accent text-accent font-semibold' : 'border-hairline text-ink-2'
        }`}
      >
        {label}{activeCount > 0 ? ` (${activeCount})` : ''} ▾
      </button>
      {open && (
        <div
          role="menu"
          ref={menuRef}
          data-align={alignRight ? 'right' : 'left'}
          className={`absolute z-20 mt-1 p-2 bg-surface border border-hairline rounded-xl shadow-lg max-w-[calc(100vw-1rem)] ${
            scroll ? 'max-h-[320px] overflow-auto' : ''
          } ${alignRight ? 'right-0' : 'left-0'}`}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function DropdownItem({
  label,
  emoji,
  isActive,
  onToggle,
}: {
  label: string;
  emoji: string;
  isActive: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={isActive}
      onClick={onToggle}
      className={`flex items-center gap-2 text-left text-[13px] px-2 py-1 rounded cursor-pointer bg-transparent border-none whitespace-nowrap hover:bg-page ${
        isActive ? 'text-accent font-semibold' : 'text-ink-2'
      }`}
    >
      <span className="w-3 text-center">{isActive ? '✓' : ''}</span>
      <span>{emoji} {label}</span>
    </button>
  );
}

/** The Custom menu's categories. Each one flies its tags out to the side. */
function CategoryList({
  groups,
  isActive,
  onToggle,
  openCategory,
  setOpenCategory,
}: {
  groups: { label: string; tags: Tag[] }[];
  isActive: (key: string) => boolean;
  onToggle: (key: string) => void;
  openCategory: string | null;
  setOpenCategory: (label: string | null) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const [side, setSide] = useState<'right' | 'left'>('right');

  useEffect(() => () => clearTimeout(timer.current), []);

  const open = (label: string) => {
    // Fly out to the right unless that would run past the window edge.
    const panel = panelRef.current;
    if (panel) {
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      setSide(panel.getBoundingClientRect().right + FLYOUT_WIDTH + EDGE_MARGIN > viewportWidth ? 'left' : 'right');
    }
    setOpenCategory(label);
  };

  return (
    <div ref={panelRef} className="flex flex-col gap-0.5 min-w-[220px]" data-testid="custom-categories">
      {groups.map((group) => {
        const label = group.label.replace(/_/g, ' ');
        const selected = group.tags.filter((t) => isActive(t.key)).length;
        const isOpen = openCategory === group.label;
        return (
          <div key={group.label} className="relative">
            <button
              type="button"
              aria-expanded={isOpen}
              aria-haspopup="menu"
              onMouseEnter={() => {
                clearTimeout(timer.current);
                if (!isOpen) timer.current = setTimeout(() => open(group.label), HOVER_DELAY_MS);
              }}
              onMouseLeave={() => clearTimeout(timer.current)}
              onClick={() => {
                clearTimeout(timer.current);
                if (isOpen) setOpenCategory(null);
                else open(group.label);
              }}
              className={`flex items-center justify-between w-full text-left text-[13px] px-2 py-1.5 rounded cursor-pointer border-none hover:bg-page ${
                isOpen ? 'bg-page' : 'bg-transparent'
              }`}
            >
              <span className="capitalize">
                {label}
                {selected > 0 && <span className="text-accent font-semibold"> ({selected})</span>}
              </span>
              <span className="text-muted text-xs" aria-hidden="true">{side === 'left' && isOpen ? '◂' : '▸'}</span>
            </button>
            {isOpen && (
              <div
                role="menu"
                aria-label={label}
                data-side={side}
                className={`absolute top-0 z-30 min-w-[280px] p-2 bg-surface border border-hairline rounded-xl shadow-lg ${
                  side === 'right' ? 'left-full ml-1' : 'right-full mr-1'
                }`}
              >
                {group.tags.map((t) => (
                  <DropdownItem
                    key={t.key}
                    label={displayName(t, group.label)}
                    emoji={t.emoji}
                    isActive={isActive(t.key)}
                    onToggle={() => onToggle(t.key)}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { Tag } from '../api';

const QUICK_COUNT = 10;

interface TagFilterBarProps {
  /** Whether a given tag key is currently an active filter. */
  isActive: (key: string) => boolean;
  /** Toggle a tag key on/off. */
  onToggle: (key: string) => void;
}

/**
 * Curated tag filter bar (T47).
 *
 * Reads the LIVE taxonomy so custom tags are filterable. Layout (two rows, full width):
 *  - row 1: the 10 most-common tags (curated via sort_order),
 *  - row 2, underneath: a "Core" dropdown (flat checkable list of the core taxonomy) and
 *    a "Custom" dropdown (an accordion of custom categories — categories stay visible,
 *    clicking one expands its tags inline). Categories are data-driven, so a new one
 *    appears with no code change.
 *
 * The dropdowns live on their own left-aligned row so their menus open over the page
 * instead of from the far right of a crowded filter line, and a menu that would still
 * run off the right edge of the window flips to open leftwards.
 *
 * All selections are additive multi-select; dropdowns close on click-outside.
 */
export function TagFilterBar({ isActive, onToggle }: TagFilterBarProps) {
  const tax = useTaxonomy();

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

  return (
    <div className="basis-full w-full flex flex-col gap-2" data-testid="tag-filter-bar">
      <div className="flex flex-wrap gap-1.5" data-testid="tag-quick-row">
        {quick.map(chip)}
      </div>
      {hasDropdowns && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="tag-dropdown-row">
          <span className="text-xs text-muted mr-0.5">More tags</span>
        {core.length > 0 && (
          <FilterDropdown label="Core" activeCount={activeCount(core)}>
            <div className="flex flex-col gap-0.5 min-w-[200px]">
              {core.map((t) => (
                <DropdownItem key={t.key} tag={t} isActive={isActive(t.key)} onToggle={onToggle} />
              ))}
            </div>
          </FilterDropdown>
        )}
        {customGroups.length > 0 && (
          <FilterDropdown label="Custom" activeCount={activeCount(custom)}>
            <div className="flex flex-col gap-0.5 min-w-[220px]" data-testid="custom-categories">
              {customGroups.map((group) => (
                <CategoryAccordion
                  key={group.label}
                  group={group}
                  isActive={isActive}
                  onToggle={onToggle}
                />
              ))}
            </div>
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
  children,
}: {
  label: string;
  activeCount: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Open left-aligned with the trigger; if that would run past the right edge of the
  // window, open right-aligned instead. Re-checked when the menu resizes (the Custom
  // accordion grows as categories expand). Width does not depend on alignment, so this
  // cannot flip-flop.
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
      const overflowsRight =
        trigger.getBoundingClientRect().left + menu.getBoundingClientRect().width > viewportWidth - 8;
      setAlignRight(overflowsRight);
    };
    place();
    if (typeof ResizeObserver === 'undefined' || !menuRef.current) return;
    const observer = new ResizeObserver(place);
    observer.observe(menuRef.current);
    return () => observer.disconnect();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
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
          className={`absolute z-20 mt-1 p-2 bg-surface border border-hairline rounded-xl shadow-lg max-h-[320px] max-w-[calc(100vw-1rem)] overflow-auto ${
            alignRight ? 'right-0' : 'left-0'
          }`}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function DropdownItem({
  tag,
  isActive,
  onToggle,
}: {
  tag: Tag;
  isActive: boolean;
  onToggle: (key: string) => void;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={isActive}
      onClick={() => onToggle(tag.key)}
      className={`flex items-center gap-2 text-left text-[13px] px-2 py-1 rounded cursor-pointer bg-transparent border-none hover:bg-page ${
        isActive ? 'text-accent font-semibold' : 'text-ink-2'
      }`}
    >
      <span className="w-3 text-center">{isActive ? '✓' : ''}</span>
      <span>{tag.emoji} {tag.name}</span>
    </button>
  );
}

function CategoryAccordion({
  group,
  isActive,
  onToggle,
}: {
  group: { label: string; tags: Tag[] };
  isActive: (key: string) => boolean;
  onToggle: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const activeCount = group.tags.filter((t) => isActive(t.key)).length;

  return (
    <div className="border-b border-hairline last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center justify-between w-full text-left text-[13px] px-2 py-1.5 rounded cursor-pointer bg-transparent border-none hover:bg-page"
      >
        <span className="capitalize">
          {group.label.replace(/_/g, ' ')}
          {activeCount > 0 && <span className="text-accent font-semibold"> ({activeCount})</span>}
        </span>
        <span className="text-muted text-xs">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-0.5 pl-3 pb-1">
          {group.tags.map((t) => (
            <DropdownItem key={t.key} tag={t} isActive={isActive(t.key)} onToggle={onToggle} />
          ))}
        </div>
      )}
    </div>
  );
}

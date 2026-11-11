import { useEffect, useRef, useState } from 'react';
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
 * Reads the LIVE taxonomy so custom tags are filterable. Layout:
 *  - a quick row of the 10 most-common tags (curated via sort_order),
 *  - a "Core" dropdown: flat checkable list of the core taxonomy,
 *  - a "Custom" dropdown: an accordion of custom categories — categories stay
 *    visible, clicking one expands its tags inline (so you can always see where
 *    you can navigate). Categories are data-driven, so a new one appears here
 *    with no code change.
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

  return (
    <>
      {quick.map(chip)}
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
    </>
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
  const ref = useRef<HTMLDivElement>(null);

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
          className="absolute z-20 mt-1 p-2 bg-surface border border-hairline rounded-xl shadow-lg max-h-[320px] overflow-auto"
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

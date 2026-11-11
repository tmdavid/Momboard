import { useState } from 'react';
import { useTaxonomy } from '../hooks/useTaxonomy';

const QUICK_COUNT = 10;

interface TagFilterBarProps {
  /** Whether a given tag key is currently an active filter. */
  isActive: (key: string) => boolean;
  /** Toggle a tag key on/off. */
  onToggle: (key: string) => void;
}

/**
 * Curated tag filter bar (T47 Step 3).
 *
 * Reads the LIVE taxonomy (not the hardcoded TAG_META), so custom tags are
 * filterable. Shows a quick row of the 10 most-common tags — "most common" is
 * curated via each tag's sort_order (admins reorder in Settings) — then an
 * expandable view that lists the full taxonomy grouped Core, then each custom
 * category (alphabetical), then Other. Grouping is data-driven (useTaxonomy),
 * so a new category appears with no code change here.
 */
export function TagFilterBar({ isActive, onToggle }: TagFilterBarProps) {
  const tax = useTaxonomy();
  const [expanded, setExpanded] = useState(false);

  // Quick row: top N by sort_order (tags already arrive sort_order-ordered).
  const quick = [...tax.tags].sort((a, b) => a.sort_order - b.sort_order).slice(0, QUICK_COUNT);
  const hasMore = tax.tags.length > quick.length;

  const chip = (key: string, emoji: string, name: string) => (
    <button
      key={key}
      type="button"
      onClick={() => onToggle(key)}
      className={`px-2.5 py-1 rounded-full border text-[13px] cursor-pointer ${
        isActive(key)
          ? 'bg-accent text-white border-accent font-semibold'
          : 'bg-surface border-hairline text-ink-2'
      }`}
    >
      {emoji} {name}
    </button>
  );

  return (
    <>
      {quick.map((t) => chip(t.key, t.emoji, t.name))}
      {hasMore && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="px-2.5 py-1 rounded-full border border-dashed border-hairline text-[13px] text-muted cursor-pointer hover:border-accent"
        >
          {expanded ? 'Less ▲' : 'More ▾'}
        </button>
      )}
      {expanded && (
        <div className="basis-full flex flex-col gap-2 mt-1" data-testid="tag-filter-groups">
          {tax.groups.map((group) => (
            <div key={group.label} className="flex flex-wrap gap-1.5 items-center">
              <span className="text-[10px] uppercase tracking-wide text-muted w-full mb-0.5">
                {group.label}
              </span>
              {group.tags.map((t) => chip(t.key, t.emoji, t.name))}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

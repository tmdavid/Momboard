import { formatDate } from '../utils/format';
import { RetagNotice } from './RetagNotice';
import { useTaxonomy } from '../hooks/useTaxonomy';

export interface ActiveFilters {
  q?: string;
  tags: string[];
  companyName?: string;
  dateFrom?: string;
  dateTo?: string;
}

/**
 * Shown when the library has calls but the current filters match none of them (v0.5 U3). It must
 * not read like an empty library: it names the filters, offers to clear them, and says so when a
 * filtered tag simply has not been applied to older calls yet.
 */
export function EmptyResults({
  filters,
  onClear,
  onNew,
}: {
  filters: ActiveFilters;
  onClear: () => void;
  onNew: () => void;
}) {
  const tax = useTaxonomy();
  const items: string[] = [];
  if (filters.q) items.push(`Search: “${filters.q}”`);
  for (const key of filters.tags) items.push(`Tag: ${tax.name(key)}`);
  if (filters.companyName) items.push(`Company: ${filters.companyName}`);
  if (filters.dateFrom) items.push(`From ${formatDate(filters.dateFrom)}`);
  if (filters.dateTo) items.push(`To ${formatDate(filters.dateTo)}`);

  return (
    <div data-testid="empty-filtered" className="p-10 text-center bg-surface border border-hairline rounded-xl flex flex-col items-center gap-3">
      <p className="m-0 text-ink font-semibold">No conversations match these filters</p>
      <ul aria-label="Active filters" className="m-0 p-0 list-none flex flex-wrap justify-center gap-1.5">
        {items.map((label) => (
          <li key={label} className="text-xs px-2.5 py-1 rounded-full bg-sub text-ink-2">{label}</li>
        ))}
      </ul>
      <div className="max-w-md w-full"><RetagNotice tagKeys={filters.tags} /></div>
      <div className="flex gap-2">
        <button type="button" className="btn btn-ghost" onClick={onClear}>Clear filters</button>
        <button type="button" className="btn btn-primary" onClick={onNew}>＋ New conversation</button>
      </div>
    </div>
  );
}

/**
 * T41: Freshness dot + tooltip for hypothesis cards and evidence.
 * Reusable across hypothesis board and decision evidence rendering.
 */

interface FreshnessDotProps {
  freshness: 'fresh' | 'aging' | 'stale';
  newestEvidenceAt?: string | null;
  className?: string;
}

const COLORS = {
  fresh: 'bg-green-500',
  aging: 'bg-amber-500',
  stale: 'bg-gray-400',
} as const;

const LABELS = {
  fresh: 'Fresh evidence (<90 days)',
  aging: 'Aging evidence (90–180 days)',
  stale: 'Stale evidence (>180 days)',
} as const;

export function FreshnessDot({ freshness, newestEvidenceAt, className = '' }: FreshnessDotProps) {
  const color = COLORS[freshness] || COLORS.stale;
  const label = LABELS[freshness] || LABELS.stale;
  const dateStr = newestEvidenceAt
    ? `Last: ${new Date(newestEvidenceAt).toLocaleDateString()}`
    : 'No evidence';

  return (
    <span
      className={`relative inline-flex items-center group ${className}`}
      data-testid="freshness-dot"
      data-freshness={freshness}
    >
      <span className={`w-2.5 h-2.5 rounded-full ${color}`} aria-label={label} />
      {/* Tooltip */}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
        {label}
        <br />
        {dateStr}
      </span>
    </span>
  );
}

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { formatNumber, formatPercent } from '../utils/format';
import { totalsByTag } from '../utils/stats';

/**
 * Four headline numbers on the Library (v0.5 U12), each a link to the page behind it. They read the
 * same /api/stats the Insights page uses, so the figures always agree. If stats fail to load the
 * strip simply isn't shown: it must never get in the way of the list.
 */
export function HeadlineCards() {
  const { data: stats, isError } = useQuery({ queryKey: ['stats'], queryFn: () => api.getStats(), retry: false });
  if (isError || !stats) return null;

  const pains = totalsByTag(stats.tag_counts_by_month).pain ?? 0;
  const cards = [
    { label: 'Total conversations', value: stats.total_conversations ? formatNumber(stats.total_conversations) : '—', to: '/' },
    { label: 'Average interview score', value: stats.avg_critique_score != null ? `${formatNumber(stats.avg_critique_score, { decimals: 1 })}/10` : '—', to: '/insights' },
    { label: 'Pains captured', value: pains ? formatNumber(pains) : '—', to: '/explore?tag=pain' },
    { label: 'Compliment ratio', value: stats.avg_compliment_ratio != null ? formatPercent(stats.avg_compliment_ratio) : '—', to: '/insights' },
  ];
  return (
    <nav aria-label="Headline numbers" className="grid gap-3 mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
      {cards.map((c) => (
        <Link key={c.label} to={c.to} aria-label={`${c.label}: ${c.value}`}
          className="flex flex-col gap-0.5 p-3.5 rounded-[10px] bg-surface border border-hairline text-inherit no-underline hover:border-accent">
          <span className="text-xs font-semibold text-muted">{c.label}</span>
          <span className="text-2xl font-bold text-ink tabular-nums">{c.value}</span>
        </Link>
      ))}
    </nav>
  );
}

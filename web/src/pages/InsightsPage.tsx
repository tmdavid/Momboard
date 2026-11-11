import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { tagColor } from '../constants';
import { formatDate, formatNumber, formatPercent } from '../utils/format';
import { totalsByTag } from '../utils/stats';

/** A week bucket (YYYY-MM-DD, the Monday) as a short axis label, e.g. "9 Nov". */
function weekLabel(date: string): string {
  const full = formatDate(date.slice(0, 10));
  return full.split(' ').slice(0, 2).join(' ');
}

function daysSince(dateStr: string): number {
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24));
}

function Card({ label, sub, children }: { label: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-2.5" aria-label={label}>
      <div className="flex flex-col">
        <span className="font-semibold text-ink">{label}</span>
        {sub && <span className="text-xs text-muted">{sub}</span>}
      </div>
      {children}
    </section>
  );
}

const MIN_WEEKS = 2;

/** A weekly line with a point per week. Needs two weeks of data to say anything about a trend. */
function TrendChart({ label, sub, ariaLabel, data, unit, max }: {
  label: string; sub: string; ariaLabel: string; data: { bucket: string; value: number }[]; unit: string; max: number;
}) {
  const W = 360, H = 130, PAD_X = 18, PAD_TOP = 12, PAD_BOTTOM = 8;
  const n = data.length;
  const x = (i: number) => PAD_X + (n === 1 ? 0 : (i / (n - 1)) * (W - 2 * PAD_X));
  const y = (v: number) => PAD_TOP + (1 - Math.min(1, Math.max(0, v / max))) * (H - PAD_TOP - PAD_BOTTOM);
  return (
    <Card label={label} sub={sub}>
      {n < MIN_WEEKS ? (
        <p className="text-sm text-muted text-center py-6">Trends appear after two weeks of calls</p>
      ) : (
        <>
          <svg role="img" aria-label={ariaLabel} viewBox={`0 0 ${W} ${H}`} className="w-full h-[130px] overflow-visible">
            <line x1={PAD_X} x2={W - PAD_X} y1={H - PAD_BOTTOM} y2={H - PAD_BOTTOM} className="stroke-hairline" strokeWidth={1} />
            <polyline fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className="stroke-accent"
              points={data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ')} />
            {data.map((d, i) => (
              <circle key={i} cx={x(i)} cy={y(d.value)} r={3.5} className="fill-accent stroke-surface" strokeWidth={1.5}>
                <title>{`${d.bucket}: ${formatNumber(d.value, { decimals: unit === '%' ? 0 : 1 })}${unit}`}</title>
              </circle>
            ))}
          </svg>
          <div className="flex justify-between text-[11px] text-muted">
            {data.map((d, i) => <span key={i}>{d.bucket}</span>)}
          </div>
        </>
      )}
    </Card>
  );
}

export function InsightsPage() {
  const { data: stats, isLoading, error } = useQuery({ queryKey: ['stats'], queryFn: () => api.getStats() });
  const tax = useTaxonomy();

  // Signal volume: sum per-tag counts across all month buckets, sorted desc.
  const volume = useMemo(() => {
    const byTag = totalsByTag(stats?.tag_counts_by_month);
    return Object.entries(byTag).map(([tag, n]) => ({ tag, n })).sort((a, b) => b.n - a.n);
  }, [stats]);
  const volumeMax = Math.max(1, ...volume.map((v) => v.n));
  const painsCaptured = volume.find((v) => v.tag === 'pain')?.n ?? 0;

  const critiqueData = useMemo(() =>
    (stats?.critique_trend ?? []).map((i) => ({ bucket: i.date ? weekLabel(i.date) : '—', value: i.score })), [stats]);
  const ratioData = useMemo(() =>
    (stats?.compliment_ratio_trend ?? []).map((i) => ({ bucket: i.date ? weekLabel(i.date) : '—', value: Math.round(i.ratio * 100) })), [stats]);

  const totalConversations = stats?.total_conversations ?? 0;
  const openFollowups = stats?.open_followups ?? [];
  // Overall averages over every call (not the newest week, which is noisy and can be one call).
  const avgScore = stats?.avg_critique_score ?? null;
  const avgRatio = stats?.avg_compliment_ratio ?? null;

  if (isLoading) return <main className="p-6 flex justify-center"><div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow mt-8" /></main>;
  if (error) return <main className="p-6 text-crit">Failed to load insights.</main>;

  const hasData = volume.length > 0 || critiqueData.length > 0;
  const kpis = [
    { label: 'Conversations', value: totalConversations ? formatNumber(totalConversations) : '—', hint: 'All imported calls' },
    { label: 'Pains captured', value: painsCaptured ? formatNumber(painsCaptured) : '—', hint: 'Accepted and suggested, above the confidence floor' },
    { label: 'Avg interview score', value: avgScore != null ? `${formatNumber(avgScore, { decimals: 1 })}/10` : '—', hint: 'Mom Test critique' },
    { label: 'Compliment ratio', value: avgRatio != null ? formatPercent(avgRatio) : '—', hint: 'Lower is better' },
  ];

  return (
    <main className="p-6 flex flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <h1 className="text-2xl font-bold text-ink">Insights</h1>
        <span className="text-muted">How the corpus and your interviewing are trending</span>
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        {kpis.map((k) => (
          <div key={k.label} className="flex flex-col gap-1 p-4 rounded-[10px] bg-surface border border-hairline">
            <span className="text-xs font-semibold text-muted">{k.label}</span>
            <span className="text-[28px] leading-[34px] font-bold text-ink">{k.value}</span>
            <span className="text-xs text-muted">{k.hint}</span>
          </div>
        ))}
      </div>

      {hasData ? (
        <div className="flex flex-wrap gap-4 items-start">
          <section className="flex-[1_1_420px] min-w-0 bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-2.5" aria-label="Signal volume">
            <div className="flex flex-col"><span className="font-semibold text-ink">Signal volume by tag</span><span className="text-xs text-muted">Accepted and suggested, above the confidence floor</span></div>
            {volume.map((v) => (
              <div key={v.tag} className="grid items-center gap-2.5" style={{ gridTemplateColumns: '130px minmax(0,1fr) 52px' }}>
                <span className="trunc text-[13px]">{tax.name(v.tag)}</span>
                <div className="h-3 rounded bg-sub overflow-hidden"><span className="block h-full" style={{ width: `${(v.n / volumeMax * 100).toFixed(1)}%`, background: tagColor(v.tag) }} /></div>
                <span className="text-[13px] text-right text-ink tabular-nums">{formatNumber(v.n)}</span>
              </div>
            ))}
          </section>

          <div className="flex-[1_1_420px] min-w-0 flex flex-col gap-4">
            <TrendChart label="Interview quality trend" sub="Average critique score per week, out of 10" ariaLabel="Interview quality by week" data={critiqueData} unit="/10" max={10} />
            <TrendChart label="Compliment ratio trend" sub="Share of highlights that are compliments, per week (lower is better)" ariaLabel="Compliment ratio by week" data={ratioData} unit="%" max={Math.max(15, ...ratioData.map((d) => d.value))} />
          </div>
        </div>
      ) : (
        <div className="bg-surface border border-hairline rounded-[10px] p-12 text-center text-muted">Not enough data yet to show charts. Add some conversations to get started.</div>
      )}

      <section className="bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-1" aria-label="Open follow-ups">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="font-semibold text-ink">Open follow-ups</span>
          <span className="text-xs text-muted">Oldest first</span>
          <Link to="/" className="ml-auto text-[13px]">See all</Link>
        </div>
        {openFollowups.length === 0 ? (
          <p className="text-sm text-muted py-4 text-center">No open follow-ups.</p>
        ) : (
          [...openFollowups]
            .sort((a, b) => (a.created_at && b.created_at ? new Date(a.created_at).getTime() - new Date(b.created_at).getTime() : 0))
            .map((fu) => {
              const age = fu.created_at ? daysSince(fu.created_at) : null;
              const isOld = age != null && age > 14;
              return (
                <div key={fu.id} className="grid items-center gap-2.5 py-2 border-t border-sub" style={{ gridTemplateColumns: '20px minmax(0,1fr) 200px 70px' }}>
                  <input type="checkbox" aria-label="Mark done" className="m-0" />
                  <span className="trunc" title={fu.task || fu.quote}>{fu.task || fu.quote}</span>
                  <Link to={`/conversations/${fu.conversation_id}`} className="trunc text-[13px]">{fu.conversation_title}</Link>
                  <span className={`text-xs text-right ${isOld ? 'text-crit-text font-semibold' : 'text-muted'}`}>{age != null ? `${age} days` : '—'}</span>
                </div>
              );
            })
        )}
      </section>
    </main>
  );
}

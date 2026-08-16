import { useMemo, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts';
import { api } from '../api';
import { tagEmoji } from '../constants';

const CHART_COLORS: Record<string, string> = {
  pain: '#2a78d6',
  workaround: '#eb6834',
  money: '#1baf7a',
  commitment: '#eda100',
  compliment: '#d03b3b',
  obstacle: '#898781',
};

export function InsightsPage() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.getStats(),
  });

  // Track which series are hidden (toggled off)
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());

  const toggleSeries = useCallback((tag: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  // Transform tag_counts_by_month into chart data
  const tagVolumeData = useMemo(() => {
    if (!stats?.tag_counts_by_month) return [];
    const months = Object.keys(stats.tag_counts_by_month).sort();
    return months.map((month) => ({
      month: formatMonth(month),
      ...stats.tag_counts_by_month[month],
    }));
  }, [stats]);

  // Critique trend chart data
  const critiqueTrendData = useMemo(() => {
    if (!stats?.critique_trend) return [];
    return stats.critique_trend.map((item) => ({
      date: item.date ? formatMonth(item.date.slice(0, 7)) : '—',
      score: item.score,
    }));
  }, [stats]);

  // Compliment ratio trend
  const complimentRatioData = useMemo(() => {
    if (!stats?.compliment_ratio_trend) return [];
    return stats.compliment_ratio_trend.map((item) => ({
      date: item.date ? formatMonth(item.date.slice(0, 7)) : '—',
      ratio: Math.round(item.ratio * 100),
    }));
  }, [stats]);

  // KPIs
  const totalConversations = tagVolumeData.length;
  const openFollowups = stats?.open_followups ?? [];
  const latestScore = stats?.critique_trend?.at(-1)?.score ?? null;
  const latestRatio = stats?.compliment_ratio_trend?.at(-1)?.ratio ?? null;
  const overdueFollowups = openFollowups.filter((f) => {
    if (!f.created_at) return false;
    const days = (Date.now() - new Date(f.created_at).getTime()) / (1000 * 60 * 60 * 24);
    return days > 14;
  });

  if (isLoading) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 flex items-center justify-center text-crit">
        Failed to load insights.
      </main>
    );
  }

  const hasData = tagVolumeData.length > 0 || critiqueTrendData.length > 0;

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto p-7">
        <div className="flex items-baseline gap-3 mb-4">
          <h1 className="text-xl font-bold tracking-tight">Insights</h1>
        </div>

        {/* KPI tiles */}
        <div className="grid grid-cols-4 gap-3.5 mb-3.5">
          <KpiTile label="Conversations" value={String(totalConversations || '—')} />
          <KpiTile
            label="Open follow-ups ☆"
            value={String(openFollowups.length)}
            sub={
              overdueFollowups.length > 0 ? (
                <span className="text-crit font-semibold text-xs">{overdueFollowups.length} overdue</span>
              ) : undefined
            }
          />
          <KpiTile
            label="Avg interview score"
            value={latestScore != null ? `${latestScore}/10` : '—'}
          />
          <KpiTile
            label="Compliment ratio"
            value={latestRatio != null ? `${Math.round(latestRatio * 100)}%` : '—'}
          />
        </div>

        {/* Main chart: signal volume over time */}
        {hasData ? (
          <>
            <div className="bg-surface border border-hairline rounded-xl p-4 mb-3.5">
              <h2 className="text-[13.5px] font-semibold mb-0.5">Signal volume over time</h2>
              <p className="text-xs text-muted mb-3">Accepted highlights per month, by tag · click legend to toggle</p>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={tagVolumeData}>
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  {Object.keys(CHART_COLORS).map((tag) => (
                    <Line
                      key={tag}
                      type="monotone"
                      dataKey={tag}
                      stroke={CHART_COLORS[tag]}
                      strokeWidth={2}
                      dot={false}
                      name={`${tagEmoji(tag)} ${tag}`}
                      hide={hiddenSeries.has(tag)}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              {/* Custom interactive legend */}
              <ul className="flex flex-wrap gap-3 mt-2 list-none p-0" role="list" aria-label="Chart legend">
                {Object.entries(CHART_COLORS).map(([tag, color]) => (
                  <li key={tag} role="listitem">
                    <button
                      className="inline-flex items-center gap-1 text-xs cursor-pointer border-none bg-transparent p-0"
                      onClick={() => toggleSeries(tag)}
                      aria-pressed={!hiddenSeries.has(tag)}
                      aria-label={`Toggle ${tagEmoji(tag)} ${tag} series`}
                      style={{ opacity: hiddenSeries.has(tag) ? 0.4 : 1 }}
                    >
                      <span
                        className="inline-block w-3 h-0.5 rounded"
                        style={{ backgroundColor: color }}
                        aria-hidden="true"
                      />
                      {tagEmoji(tag)} {tag}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {/* Row of two smaller charts */}
            <div className="grid grid-cols-2 gap-3.5 mb-3.5">
              <div className="bg-surface border border-hairline rounded-xl p-4">
                <h2 className="text-[13.5px] font-semibold mb-0.5">Compliment ratio trend</h2>
                <p className="text-xs text-muted mb-3">🎈 share of all highlights — are interviews getting less fluffy?</p>
                <ResponsiveContainer width="100%" height={150}>
                  <AreaChart data={complimentRatioData}>
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} unit="%" />
                    <Tooltip />
                    <Area type="monotone" dataKey="ratio" stroke="#2a78d6" fill="#2a78d6" fillOpacity={0.1} strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              <div className="bg-surface border border-hairline rounded-xl p-4">
                <h2 className="text-[13.5px] font-semibold mb-0.5">Interview quality trend</h2>
                <p className="text-xs text-muted mb-3">Avg Mom Test critique score per month</p>
                <ResponsiveContainer width="100%" height={150}>
                  <AreaChart data={critiqueTrendData}>
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} domain={[0, 10]} />
                    <Tooltip />
                    <Area type="monotone" dataKey="score" stroke="#2a78d6" fill="#2a78d6" fillOpacity={0.1} strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        ) : (
          <div className="bg-surface border border-hairline rounded-xl p-12 text-center text-muted mb-3.5">
            Not enough data yet to show charts. Add some conversations to get started.
          </div>
        )}

        {/* Open follow-ups */}
        <div className="bg-surface border border-hairline rounded-xl p-4">
          <h2 className="text-[13.5px] font-semibold mb-0.5">Open follow-ups</h2>
          <p className="text-xs text-muted mb-3">Every unresolved ☆ across all conversations — your action list</p>

          {openFollowups.length === 0 ? (
            <p className="text-sm text-muted py-4 text-center">No open follow-ups. Great job! 🎉</p>
          ) : (
            openFollowups.map((fu) => {
              const age = fu.created_at ? daysSince(fu.created_at) : null;
              const isOld = age != null && age > 14;
              return (
                <div key={fu.id} className="flex gap-2.5 items-baseline py-2 border-b border-hairline last:border-b-0 text-[13px]">
                  <span>☆ {fu.quote}</span>
                  <Link to={`/conversations/${fu.conversation_id}`} className="text-accent whitespace-nowrap">
                    {fu.conversation_title} ↗
                  </Link>
                  <span className={`ml-auto text-xs whitespace-nowrap ${isOld ? 'text-crit font-semibold' : 'text-muted'}`}>
                    {age != null ? `${age} days` : '—'}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </main>
  );
}

function KpiTile({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="bg-surface border border-hairline rounded-xl px-4 py-3.5">
      <div className="text-xs text-ink-2 mb-1.5">{label}</div>
      <div className="text-[28px] font-semibold tracking-tight leading-none">{value}</div>
      {sub && <div className="mt-1.5">{sub}</div>}
    </div>
  );
}

function formatMonth(ym: string): string {
  const parts = ym.split('-');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return months[parseInt(parts[1], 10) - 1] || ym;
}

function daysSince(dateStr: string): number {
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24));
}

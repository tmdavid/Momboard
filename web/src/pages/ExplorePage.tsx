import { useState, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, HighlightWithContext } from '../api';
import { RetagNotice } from '../components/RetagNotice';
import { TagFilterBar } from '../components/TagFilterBar';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { tagColor } from '../constants';

const SYNTHESIS_THRESHOLD = 5;

export function ExplorePage() {
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set(['pain', 'workaround']));
  const [companyId, setCompanyId] = useState<number | undefined>();
  const [statusFilter, setStatusFilter] = useState<string>('');
  // v0.5 D4: by default show the strongest quotes above each tag's floor, at most 3 per call per
  // tag, so one long call cannot fill the first screen. This switch shows everything.
  const [showLow, setShowLow] = useState(false);

  const { data: companies } = useQuery({
    queryKey: ['companies', 'active'],
    queryFn: () => api.listActiveCompanies(),
  });

  const { data, isLoading } = useQuery({
    queryKey: ['explore-highlights', { tags: Array.from(activeTags), companyId, statusFilter, showLow }],
    queryFn: () =>
      api.listHighlights({
        tag: activeTags.size > 0 ? Array.from(activeTags) : undefined,
        company_id: companyId,
        status: statusFilter || undefined,
        sort: 'confidence',
        ...(showLow ? {} : { floor: true, per_call_cap: 3 }),
        limit: 200,
      }),
  });

  const filteredItems = useMemo(() => data?.items ?? [], [data]);
  const companiesInResults = useMemo(() => new Set(filteredItems.map((i) => i.company_name)), [filteredItems]);

  const [synthQueued, setSynthQueued] = useState(false);
  const [synthError, setSynthError] = useState<string | null>(null);

  const synthesisMutation = useMutation({
    mutationFn: () => api.createSynthesis({ tags: Array.from(activeTags), company_id: companyId }),
    onSuccess: () => { setSynthError(null); setSynthQueued(true); },
    onError: () => setSynthError('Failed to start synthesis. Please try again.'),
  });

  const toggleTag = (key: string) => {
    setActiveTags((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const hasFilter = activeTags.size > 0 || !!companyId || !!statusFilter;
  const belowThreshold = filteredItems.length < SYNTHESIS_THRESHOLD;
  // Synthesize is gated on at least one active filter (README rule).
  const synthDisabled = !hasFilter || belowThreshold || synthesisMutation.isPending;

  const clearAll = () => { setActiveTags(new Set()); setCompanyId(undefined); setStatusFilter(''); };

  return (
    <main className="p-6 flex flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <h1 className="text-2xl font-bold text-ink">Explore</h1>
        <span className="text-muted">Every tagged quote, across all conversations</span>
      </div>

      {/* Filter row. DECISION (README): Synthesize is never in the page header; it
          sits at the end of this row, enabled only when a filter is active, and its
          label carries the scope. */}
      <div className="flex flex-wrap gap-2 items-center" data-testid="filter-container">
        <TagFilterBar isActive={(key) => activeTags.has(key)} onToggle={toggleTag} />
        <select
          className="h-10 px-3 border border-hairline rounded-lg bg-surface text-ink text-sm font-semibold"
          value={companyId || ''} onChange={(e) => setCompanyId(e.target.value ? Number(e.target.value) : undefined)}
          aria-label="Filter by company">
          <option value="">All companies</option>
          {companies?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        {/* Accepted + suggested | Accepted only segmented control */}
        <div className="flex gap-0.5 p-0.5 rounded-lg bg-sub" role="tablist" aria-label="Tag status">
          <button role="tab" aria-selected={statusFilter === ''} onClick={() => setStatusFilter('')}
            className={`h-8 px-3 rounded-md border-none font-semibold cursor-pointer ${statusFilter === '' ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'}`}>Accepted + suggested</button>
          <button role="tab" aria-selected={statusFilter === 'accepted'} onClick={() => setStatusFilter('accepted')}
            className={`h-8 px-3 rounded-md border-none font-semibold cursor-pointer ${statusFilter === 'accepted' ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'}`}>Accepted only</button>
        </div>

        {hasFilter && (
          <button onClick={clearAll} data-testid="clear-all-filters" className="text-[13px] text-accent bg-transparent border-none cursor-pointer">Clear all</button>
        )}

        <label className="flex items-center gap-1.5 text-[13px] text-ink-2 cursor-pointer">
          <input type="checkbox" checked={showLow} onChange={(e) => setShowLow(e.target.checked)} />
          Show low-confidence
        </label>

        <span className="ml-auto text-[13px] text-muted">{filteredItems.length} highlights · {companiesInResults.size} companies</span>

        {synthDisabled && !synthesisMutation.isPending ? (
          <span className="flex items-center gap-2">
            <button aria-disabled="true" disabled title="Add a filter to synthesize"
              className="h-9 px-3 rounded-lg border border-hairline bg-sub text-[#9ca3af] text-[13px] font-semibold cursor-not-allowed">
              Synthesize
            </button>
            {!hasFilter ? (
              <span className="text-xs text-muted">Add a filter to synthesize</span>
            ) : belowThreshold ? (
              <span className="text-xs text-muted" aria-live="polite">
                {filteredItems.length}/{SYNTHESIS_THRESHOLD} — {SYNTHESIS_THRESHOLD - filteredItems.length} more needed (min {SYNTHESIS_THRESHOLD})
              </span>
            ) : null}
          </span>
        ) : (
          <button
            className="h-9 px-3 rounded-lg border border-accent bg-accent-soft text-accent-ink text-[13px] font-semibold cursor-pointer disabled:opacity-60"
            disabled={synthesisMutation.isPending}
            onClick={() => { setSynthError(null); setSynthQueued(false); synthesisMutation.mutate(); }}>
            {synthesisMutation.isPending ? 'Queuing…' : `Synthesize ${filteredItems.length} highlights`}
          </button>
        )}
      </div>

      {synthQueued && (
        <div className="bg-accent-soft border border-accent rounded-xl p-4" role="status" aria-label="Synthesis queued">
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <p className="text-sm font-semibold text-accent-ink">Summary queued</p>
              <p className="text-xs text-ink-2">It’s being generated in the background — find it in Summaries in a moment.</p>
            </div>
            <Link to="/summaries" className="h-9 px-3 flex items-center text-xs font-semibold bg-accent text-white rounded-lg hover:opacity-90">View summaries →</Link>
          </div>
        </div>
      )}
      {synthError && (
        <div className="bg-crit-soft border border-crit/30 rounded-xl p-4" role="alert">
          <div className="flex items-center gap-3">
            <span className="text-crit-text text-sm font-medium flex-1">{synthError}</span>
            <button className="h-8 px-3 text-xs font-semibold bg-crit-soft text-crit-text rounded-lg border border-crit/30" onClick={() => synthesisMutation.mutate()}>Retry</button>
          </div>
        </div>
      )}

      {isLoading && <div className="flex justify-center py-12"><div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" /></div>}

      {!showLow && (
        <p className="m-0 text-xs text-muted">
          Strongest first. Suggestions below each tag's confidence floor are hidden, and each call shows at most 3 per tag.
        </p>
      )}
      <RetagNotice tagKeys={Array.from(activeTags)} />

      {!isLoading && filteredItems.length === 0 && (
        <div className="text-center text-muted py-12">
          No highlights match these filters.{' '}
          {!showLow ? 'Low-confidence suggestions are hidden; tick “Show low-confidence” to see them. ' : ''}
          {activeTags.size > 1 ? 'Try removing a tag,' : activeTags.size === 1 ? 'Try a different tag,' : ''}{' '}
          {companyId ? 'widen the company filter,' : ''}{' '}
          {statusFilter ? 'or switch to Accepted + suggested.' : 'or loosen a filter.'}
        </div>
      )}

      <div className="grid gap-3 items-start" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
        {filteredItems.map((item) => <QuoteCard key={item.id} item={item} />)}
      </div>
    </main>
  );
}

function QuoteCard({ item }: { item: HighlightWithContext }) {
  const navigate = useNavigate();
  const [linking, setLinking] = useState(false);
  const tax = useTaxonomy();
  const color = tagColor(item.tag_key);
  const href = item.utterance_id
    ? `/conversations/${item.conversation_id}#utterance-${item.utterance_id}`
    : `/conversations/${item.conversation_id}`;

  const conf = item.confidence ?? null;

  return (
    <article className="bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-2.5" data-testid="quote-card"
      aria-label={`${item.tag_key} quote from ${item.company_name || 'Unknown'}: ${item.quote}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold px-2.5 py-0.5 rounded-pill capitalize" style={{ background: `${color}1a`, color }}>
          {tax.name(item.tag_key)}
        </span>
        {conf != null && (
          <div className="ml-auto flex items-center gap-1.5" title={`Confidence ${conf.toFixed(2)}`}>
            <div className="w-12 h-1 rounded bg-sub overflow-hidden"><span className="block h-full" style={{ width: `${Math.round(conf * 100)}%`, background: color }} /></div>
            <span className="text-xs text-muted">{conf.toFixed(2)}</span>
          </div>
        )}
      </div>
      <blockquote className="m-0 text-ink text-[15px] leading-[23px]">“{item.quote}”</blockquote>
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <strong className="text-ink-2 font-semibold">{item.company_name || 'Unknown'}</strong>
        <span aria-hidden="true">·</span><span>{item.contact_names[0] || '—'}</span>
        <span aria-hidden="true">·</span>
        <span>{item.conversation_happened_at ? new Date(item.conversation_happened_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—'}</span>
      </div>
      <div className="flex gap-3 pt-2 border-t border-sub text-[13px]">
        <button onClick={() => navigate(href)} className="bg-transparent border-none p-0 text-accent cursor-pointer">Open in transcript</button>
        <button onClick={() => setLinking((v) => !v)} aria-expanded={linking} className="bg-transparent border-none p-0 text-accent cursor-pointer">Link to hypothesis</button>
        <Link to={`/decisions?highlight_id=${item.id}`} className="ml-auto">Cite in decision</Link>
      </div>
      {linking && <LinkToHypothesis highlightId={item.id} onDone={() => setLinking(false)} />}
    </article>
  );
}

function LinkToHypothesis({ highlightId, onDone }: { highlightId: number; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [hypothesisId, setHypothesisId] = useState('');
  const [done, setDone] = useState(false);
  const { data } = useQuery({
    queryKey: ['hypotheses'],
    queryFn: () => api.listHypotheses(),
  });
  const link = useMutation({
    mutationFn: (stance: 'supports' | 'contradicts') =>
      api.addHypothesisLink(parseInt(hypothesisId, 10), { highlight_id: highlightId, stance, confirm: true }),
    onSuccess: () => {
      setDone(true);
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      queryClient.invalidateQueries({ queryKey: ['hypothesis'] });
      queryClient.invalidateQueries({ queryKey: ['hypothesis-history'] });
      setTimeout(onDone, 1200);
    },
  });
  const items = data ?? [];

  if (done) return <p role="status" className="text-xs text-good-text">Linked as confirmed evidence.</p>;
  if (items.length === 0) {
    return <p className="text-xs text-muted">No hypotheses yet — add one on the Hypotheses page first.</p>;
  }
  return (
    <div className="flex flex-col gap-2 pt-2 border-t border-sub" role="group" aria-label="Link to hypothesis">
      <select
        value={hypothesisId}
        onChange={(e) => setHypothesisId(e.target.value)}
        aria-label="Hypothesis"
        className="h-8 px-2 border border-hairline rounded-lg bg-surface text-sm text-ink"
      >
        <option value="">Choose a hypothesis…</option>
        {items.map((h) => (
          <option key={h.id} value={h.id}>{h.statement}</option>
        ))}
      </select>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!hypothesisId || link.isPending}
          onClick={() => link.mutate('supports')}
          className="text-xs font-semibold px-2.5 py-1 rounded bg-green-100 text-green-800 disabled:opacity-50"
        >
          Supports
        </button>
        <button
          type="button"
          disabled={!hypothesisId || link.isPending}
          onClick={() => link.mutate('contradicts')}
          className="text-xs font-semibold px-2.5 py-1 rounded bg-red-100 text-red-800 disabled:opacity-50"
        >
          Contradicts
        </button>
      </div>
      {link.isError && (
        <p role="alert" className="text-xs text-red-600">
          {(link.error as Error).message || 'Could not link this quote.'}
        </p>
      )}
    </div>
  );
}

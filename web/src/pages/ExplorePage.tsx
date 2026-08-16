import { useState, useMemo, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, HighlightWithContext, SynthesisResponse } from '../api';
import { TAG_META, tagEmoji } from '../constants';

const SYNTHESIS_THRESHOLD = 5;

export function ExplorePage() {
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set(['pain', 'workaround']));
  const [companyId, setCompanyId] = useState<number | undefined>();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [synthesisId, setSynthesisId] = useState<number | null>(null);
  const [expandedThemes, setExpandedThemes] = useState<Set<number>>(new Set());

  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: () => api.listCompanies(),
  });

  // Fetch highlights with server-side filtering via repeated tag params
  const { data, isLoading } = useQuery({
    queryKey: ['explore-highlights', { tags: Array.from(activeTags), companyId, statusFilter }],
    queryFn: () =>
      api.listHighlights({
        tag: activeTags.size > 0 ? Array.from(activeTags) : undefined,
        company_id: companyId,
        status: statusFilter || undefined,
        limit: 200,
      }),
  });

  // Items come pre-filtered from server
  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    return data.items;
  }, [data]);

  const companiesInResults = useMemo(() => new Set(filteredItems.map((i) => i.company_name)), [filteredItems]);

  // Synthesis result state (populated by polling)
  const [synthesis, setSynthesis] = useState<SynthesisResponse | null>(null);

  // Synthesis creation mutation
  const synthesisMutation = useMutation({
    mutationFn: () =>
      api.createSynthesis({
        tags: Array.from(activeTags),
        company_id: companyId,
      }),
    onSuccess: (result) => {
      setSynthesisId(result.id);
      setSynthesis(result);
      setExpandedThemes(new Set());
    },
  });

  // Robust polling with setInterval + bounded timeout
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (synthesisId == null || synthesis?.result) return;

    const poll = () => {
      api.getSynthesis(synthesisId).then((updated) => {
        if (updated.result) {
          setSynthesis(updated);
          if (pollRef.current) clearInterval(pollRef.current);
          if (timeoutRef.current) clearTimeout(timeoutRef.current);
          pollRef.current = null;
          timeoutRef.current = null;
        }
      }).catch(() => {
        // On error, stop polling
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
      });
    };

    pollRef.current = setInterval(poll, 2000);
    // Safety timeout: stop after 30s
    timeoutRef.current = setTimeout(() => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    }, 30000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      pollRef.current = null;
      timeoutRef.current = null;
    };
  }, [synthesisId, synthesis?.result]);

  const isSynthesizing = synthesisId != null && !synthesis?.result;

  const toggleTag = (key: string) => {
    setActiveTags((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleTheme = (index: number) => {
    setExpandedThemes((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  // Build a map of highlight id → highlight for evidence lookups
  const highlightsById = useMemo(() => {
    const map = new Map<number, HighlightWithContext>();
    for (const item of filteredItems) {
      map.set(item.id, item);
    }
    return map;
  }, [filteredItems]);

  const filterTags = Object.entries(TAG_META).slice(0, 6);

  const belowThreshold = filteredItems.length < SYNTHESIS_THRESHOLD;
  const needed = SYNTHESIS_THRESHOLD - filteredItems.length;

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-4">Explore highlights</h1>

        {/* Filters */}
        <div className="flex flex-wrap gap-2 items-center p-3 bg-surface border border-hairline rounded-xl mb-2">
          <span className="text-xs text-muted font-semibold">TAGS</span>
          {filterTags.map(([key, meta]) => (
            <button
              key={key}
              onClick={() => toggleTag(key)}
              className={`px-2.5 py-1 rounded-full border text-[13px] cursor-pointer ${
                activeTags.has(key)
                  ? 'bg-accent-soft border-accent text-accent font-semibold'
                  : 'bg-surface border-hairline text-ink-2'
              }`}
            >
              {meta.emoji} {meta.name}
            </button>
          ))}
          <select
            className="px-2 py-1.5 border border-hairline rounded-lg bg-page text-ink-2 text-sm"
            value={companyId || ''}
            onChange={(e) => setCompanyId(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">All companies</option>
            {companies?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            className="px-2 py-1.5 border border-hairline rounded-lg bg-page text-ink-2 text-sm"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Accepted + suggested</option>
            <option value="accepted">Accepted only</option>
          </select>
        </div>

        {/* Active bar */}
        <div className="flex items-center gap-2 text-[13px] text-muted my-2 mx-0.5">
          <span>
            {filteredItems.length} highlights · {companiesInResults.size} companies
          </span>
          <span className="flex-1" />
          <div className="flex items-center gap-2">
            {belowThreshold && (
              <span className="text-xs text-muted" aria-live="polite">
                {needed === 1 ? '1 more needed' : `need ${SYNTHESIS_THRESHOLD}`} (min {SYNTHESIS_THRESHOLD})
              </span>
            )}
            <button
              className="btn btn-primary"
              disabled={belowThreshold || synthesisMutation.isPending || isSynthesizing}
              onClick={() => synthesisMutation.mutate()}
            >
              {isSynthesizing || synthesisMutation.isPending ? (
                <span className="inline-flex items-center gap-2 text-[13px] text-muted" role="status">
                  <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" aria-hidden="true" />
                  Synthesizing…
                </span>
              ) : (
                '✨ Synthesize this view'
              )}
            </button>
          </div>
        </div>

        {/* Synthesis result */}
        {synthesis?.result && (
          <div className="bg-surface border border-hairline rounded-[14px] p-5 mb-5 synth-panel">
            <h2 className="text-[15px] font-semibold mb-1">
              Synthesis — {Array.from(activeTags).map((t) => `${tagEmoji(t)} ${t}`).join(' + ')}
            </h2>
            <div className="text-xs text-muted mb-3.5">
              {filteredItems.length} highlights across {companiesInResults.size} conversations
            </div>

            {synthesis.result.themes?.map((theme, i) => (
              <div key={i} className="border-l-[3px] border-accent px-3.5 py-2.5 bg-page rounded-r-xl mb-2.5 synth-theme">
                <b className="block mb-0.5">
                  {i + 1}. {theme.name}
                </b>
                <p className="text-[13px] text-ink-2">{theme.summary}</p>
                <button
                  className="text-xs text-accent cursor-pointer mt-1 inline-block bg-transparent border-none p-0"
                  onClick={() => toggleTheme(i)}
                  aria-expanded={expandedThemes.has(i)}
                  aria-controls={`theme-evidence-${i}`}
                >
                  {expandedThemes.has(i) ? '▾' : '▸'} {theme.evidence_highlight_ids?.length || 0} supporting quotes
                </button>
                {expandedThemes.has(i) && (
                  <div id={`theme-evidence-${i}`} className="mt-2 pl-2 border-l-2 border-hairline space-y-1.5">
                    {theme.evidence_highlight_ids?.map((hId) => {
                      const h = highlightsById.get(hId);
                      if (!h) return null;
                      return (
                        <blockquote key={hId} className="text-[13px] text-ink-2 italic before:content-['\u201c'] after:content-['\u201d']">
                          {h.quote}
                        </blockquote>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}

            {synthesis.result.contradictions?.map((c, i) => (
              <div key={i} className="border-l-[3px] border-warn px-3.5 py-2.5 bg-page rounded-r-xl mb-2.5">
                <b className="block mb-0.5">⚠ Contradiction</b>
                <p className="text-[13px] text-ink-2">{c.description}</p>
              </div>
            ))}

            {synthesis.result.validate_next && synthesis.result.validate_next.length > 0 && (
              <div className="bg-[#e6f4e6] rounded-xl px-3.5 py-2.5 text-[13px]">
                <b className="text-good-text">Validate next:</b>{' '}
                {synthesis.result.validate_next.join(' ')}
              </div>
            )}
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex justify-center py-12">
            <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
          </div>
        )}

        {/* Quote wall — hidden when synthesis result is displayed */}
        {!isLoading && filteredItems.length === 0 && !synthesis?.result && (
          <div className="text-center text-muted py-12">
            No highlights match the current filters.
          </div>
        )}

        {!synthesis?.result && (
          <div className="columns-[300px] gap-3.5">
            {filteredItems.map((item) => (
              <QuoteCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

function QuoteCard({ item }: { item: HighlightWithContext }) {
  const navigate = useNavigate();
  const href = item.utterance_id
    ? `/conversations/${item.conversation_id}#utterance-${item.utterance_id}`
    : `/conversations/${item.conversation_id}`;

  const handleActivate = () => {
    navigate(href);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleActivate();
    }
  };

  return (
    <article
      className="break-inside-avoid bg-surface border border-hairline rounded-xl p-3.5 mb-3.5 cursor-pointer hover:border-accent transition-colors"
      data-testid="quote-card"
      tabIndex={0}
      aria-label={`${item.tag_key} quote from ${item.company_name || 'Unknown'}: ${item.quote}`}
      onClick={handleActivate}
      onKeyDown={handleKeyDown}
    >
      <div className="text-xs font-semibold text-ink-2 flex items-center gap-1.5 mb-2">
        {tagEmoji(item.tag_key)} {item.tag_key}
        {item.confidence != null && <span className="text-muted font-normal ml-auto">{item.confidence.toFixed(2)}</span>}
      </div>
      <blockquote className="text-[14.5px] text-ink mb-2.5 before:content-['\u201c'] after:content-['\u201d']">
        {item.quote}
      </blockquote>
      <div className="text-xs text-muted">
        <b className="text-ink-2">{item.company_name || 'Unknown'}</b> · {item.contact_names[0] || '—'} ·{' '}
        {item.conversation_happened_at
          ? new Date(item.conversation_happened_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
          : '—'}{' '}
        <span className="text-accent" aria-label="open conversation">→ open ↗</span>
      </div>
    </article>
  );
}

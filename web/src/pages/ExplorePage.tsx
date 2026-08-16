import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, HighlightWithContext, SynthesisResponse } from '../api';
import { TAG_META, tagEmoji } from '../constants';

export function ExplorePage() {
  const navigate = useNavigate();
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set(['pain', 'workaround']));
  const [companyId, setCompanyId] = useState<number | undefined>();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [synthesis, setSynthesis] = useState<SynthesisResponse | null>(null);

  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: () => api.listCompanies(),
  });

  // We fetch highlights for the first active tag (API supports single tag filter)
  // To support multi-tag, we fetch all and filter client-side, or make multiple queries
  const { data, isLoading } = useQuery({
    queryKey: ['explore-highlights', { tags: Array.from(activeTags), companyId, statusFilter }],
    queryFn: () =>
      api.listHighlights({
        tag: activeTags.size === 1 ? Array.from(activeTags)[0] : undefined,
        company_id: companyId,
        status: statusFilter || undefined,
        limit: 200,
      }),
  });

  // Client-side filter for multi-tag
  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    if (activeTags.size <= 1) return data.items;
    return data.items.filter((item) => activeTags.has(item.tag_key));
  }, [data, activeTags]);

  const companiesInResults = useMemo(() => new Set(filteredItems.map((i) => i.company_name)), [filteredItems]);

  const synthesisMutation = useMutation({
    mutationFn: () =>
      api.createSynthesis({
        tags: Array.from(activeTags),
        company_id: companyId,
      }),
    onSuccess: (result) => {
      setSynthesis(result);
      // Poll for result
      const pollInterval = setInterval(async () => {
        const updated = await api.getSynthesis(result.id);
        if (updated.result) {
          setSynthesis(updated);
          clearInterval(pollInterval);
        }
      }, 2000);
      setTimeout(() => clearInterval(pollInterval), 30000); // timeout
    },
  });

  const toggleTag = (key: string) => {
    setActiveTags((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const filterTags = Object.entries(TAG_META).slice(0, 6);

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
          <button
            className="btn btn-primary"
            disabled={filteredItems.length < 5 || synthesisMutation.isPending}
            onClick={() => synthesisMutation.mutate()}
          >
            {synthesisMutation.isPending ? (
              <span className="inline-flex items-center gap-2 text-[13px] text-muted">
                <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
                Synthesizing…
              </span>
            ) : (
              '✨ Synthesize this view'
            )}
          </button>
        </div>

        {/* Synthesis result */}
        {synthesis?.result && (
          <div className="bg-surface border border-hairline rounded-[14px] p-5 mb-5">
            <h2 className="text-[15px] font-semibold mb-1">
              Synthesis — {Array.from(activeTags).map((t) => `${tagEmoji(t)} ${t}`).join(' + ')}
            </h2>
            <div className="text-xs text-muted mb-3.5">
              {filteredItems.length} highlights across {companiesInResults.size} conversations
            </div>

            {synthesis.result.themes?.map((theme, i) => (
              <div key={i} className="border-l-[3px] border-accent px-3.5 py-2.5 bg-page rounded-r-xl mb-2.5">
                <b className="block mb-0.5">
                  {i + 1}. {theme.name}
                </b>
                <p className="text-[13px] text-ink-2">{theme.summary}</p>
                <span className="text-xs text-accent cursor-pointer mt-1 inline-block">
                  ▸ {theme.evidence_highlight_ids?.length || 0} supporting quotes
                </span>
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

        {/* Quote wall */}
        {!isLoading && filteredItems.length === 0 && (
          <div className="text-center text-muted py-12">
            No highlights match the current filters.
          </div>
        )}

        <div className="columns-[300px] gap-3.5">
          {filteredItems.map((item) => (
            <QuoteCard key={item.id} item={item} onClick={() => navigate(`/conversations/${item.conversation_id}`)} />
          ))}
        </div>
      </div>
    </main>
  );
}

function QuoteCard({ item, onClick }: { item: HighlightWithContext; onClick: () => void }) {
  return (
    <div
      className="break-inside-avoid bg-surface border border-hairline rounded-xl p-3.5 mb-3.5 cursor-pointer hover:border-accent transition-colors"
      onClick={onClick}
      title="Open in conversation"
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
        → open ↗
      </div>
    </div>
  );
}

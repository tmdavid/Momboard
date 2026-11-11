import { useState, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, HighlightWithContext } from '../api';
import { TagFilterBar } from '../components/TagFilterBar';
import { useTaxonomy } from '../hooks/useTaxonomy';

const SYNTHESIS_THRESHOLD = 5;

export function ExplorePage() {
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set(['pain', 'workaround']));
  const [companyId, setCompanyId] = useState<number | undefined>();
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [showLensModal, setShowLensModal] = useState(false);
  const [lensResult, setLensResult] = useState<Record<string, unknown> | null>(null);

  const { data: companies } = useQuery({
    queryKey: ['companies', 'active'],
    queryFn: () => api.listActiveCompanies(),
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

  // Synthesis is fire-and-forget: POST enqueues a background job, the result
  // shows up in the Summaries tab. We only track the just-queued confirmation.
  const [synthQueued, setSynthQueued] = useState(false);
  const [synthError, setSynthError] = useState<string | null>(null);

  // Synthesis creation mutation (fire-and-forget)
  const synthesisMutation = useMutation({
    mutationFn: () =>
      api.createSynthesis({
        tags: Array.from(activeTags),
        company_id: companyId,
      }),
    onSuccess: () => {
      setSynthError(null);
      setSynthQueued(true);
    },
    onError: () => {
      setSynthError('Failed to start synthesis. Please try again.');
    },
  });

  const isSynthesizing = synthesisMutation.isPending;

  const toggleTag = (key: string) => {
    setActiveTags((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const belowThreshold = filteredItems.length < SYNTHESIS_THRESHOLD;
  const needed = SYNTHESIS_THRESHOLD - filteredItems.length;

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-4">Explore highlights</h1>

        {/* Filters */}
        <div className={`flex flex-wrap gap-2 items-center p-3 border rounded-xl mb-2 ${
          (activeTags.size > 0 || companyId || statusFilter)
            ? 'bg-accent-soft border-accent'
            : 'bg-surface border-hairline'
        }`} data-testid="filter-container">
          <span className="text-xs text-muted font-semibold">TAGS</span>
          <TagFilterBar isActive={(key) => activeTags.has(key)} onToggle={toggleTag} />
          <select
            className="px-2 py-1.5 border border-hairline rounded-lg bg-page text-ink-2 text-sm"
            value={companyId || ''}
            onChange={(e) => setCompanyId(e.target.value ? Number(e.target.value) : undefined)}
            aria-label="Filter by company"
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
            aria-label="Filter by status"
          >
            <option value="">Accepted + suggested</option>
            <option value="accepted">Accepted only</option>
          </select>
          {/* #16: Clear all when any filter is active */}
          {(activeTags.size > 0 || companyId || statusFilter) && (
            <button
              className="px-2.5 py-1 text-xs font-medium text-crit hover:underline"
              onClick={() => {
                setActiveTags(new Set());
                setCompanyId(undefined);
                setStatusFilter('');
              }}
              data-testid="clear-all-filters"
            >
              Clear all
            </button>
          )}
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
              disabled={belowThreshold || synthesisMutation.isPending}
              onClick={() => {
                setSynthError(null);
                setSynthQueued(false);
                synthesisMutation.mutate();
              }}
            >
              {isSynthesizing ? (
                <span className="inline-flex items-center gap-2 text-[13px] text-muted" role="status">
                  <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" aria-hidden="true" />
                  Queuing…
                </span>
              ) : (
                '✨ Synthesize this view'
              )}
            </button>
            <button
              className="btn"
              disabled={belowThreshold}
              onClick={() => setShowLensModal(true)}
            >
              🔍 Compare as Lens
            </button>
          </div>
        </div>

        {/* Fire-and-forget: synthesis runs in the background and appears in Summaries */}
        {synthQueued && (
          <div className="bg-accent-soft border border-accent rounded-xl p-4 mb-4" role="status" aria-label="Synthesis queued">
            <div className="flex items-center gap-3">
              <span className="text-lg" aria-hidden="true">✨</span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-accent-deep">Summary queued</p>
                <p className="text-xs text-ink-2">
                  It’s being generated in the background — find it in the Summaries tab in a moment.
                </p>
              </div>
              <Link
                to="/summaries"
                className="px-3 py-1.5 text-xs font-semibold bg-accent text-white rounded-lg hover:opacity-90"
              >
                View Summaries →
              </Link>
            </div>
          </div>
        )}

        {/* Synthesis error with retry */}
        {synthError && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4" role="alert">
            <div className="flex items-center gap-3">
              <span className="text-red-600 text-sm font-medium flex-1">{synthError}</span>
              <button
                className="px-3 py-1.5 text-xs font-semibold bg-red-100 text-red-700 rounded-lg hover:bg-red-200"
                onClick={() => {
                  setSynthError(null);
                  setSynthQueued(false);
                  synthesisMutation.mutate();
                }}
              >
                Retry
              </button>
            </div>
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
            <QuoteCard key={item.id} item={item} />
          ))}
        </div>

        {lensResult && (
          <LensResultPanel result={lensResult} onClose={() => setLensResult(null)} />
        )}
      </div>

      {showLensModal && (
        <LensModal
          filtersA={{
            ...(companyId ? { company_id: companyId } : {}),
            ...(activeTags.size > 0 ? { tag_key: Array.from(activeTags) } : {}),
            ...(statusFilter ? { status: statusFilter } : {}),
          }}
          onClose={() => setShowLensModal(false)}
          onResult={(r) => setLensResult(r)}
        />
      )}
    </main>
  );
}

function LensModal({ filtersA, onClose, onResult }: { filtersA: Record<string, unknown>; onClose: () => void; onResult: (r: Record<string, unknown>) => void }) {
  const [companyIdB, setCompanyIdB] = useState('');
  const [tagKeyB, setTagKeyB] = useState('');
  const [statusB, setStatusB] = useState('');
  const [labelA, setLabelA] = useState('Current view');
  const [labelB, setLabelB] = useState('Side B');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: companies } = useQuery({
    queryKey: ['companies', 'active'],
    queryFn: () => api.listActiveCompanies(),
  });

  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.listTags(),
  });

  const execute = async () => {
    setLoading(true);
    setError(null);
    try {
      const filtersB: Record<string, unknown> = {};
      if (companyIdB) filtersB.company_id = parseInt(companyIdB);
      if (tagKeyB) filtersB.tag_key = [tagKeyB];
      if (statusB) filtersB.status = statusB;
      const r = await fetch('/api/lenses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ a: filtersA, b: filtersB, label_a: labelA, label_b: labelB }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.detail || `Error ${r.status}`);
      }
      const data = await r.json();
      onResult(data.result);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" role="dialog" aria-label="Compare as lens">
      <div className="bg-white rounded-lg p-6 w-full max-w-md">
        <h2 className="text-lg font-bold mb-4">🔍 Compare as Lens</h2>
        <p className="text-sm text-gray-500 mb-3">Current filters become Side A. Pick Side B:</p>

        <div className="mb-3">
          <label className="text-xs font-medium text-gray-600 block mb-1">Side A label</label>
          <input type="text" value={labelA} onChange={(e) => setLabelA(e.target.value)} placeholder="Label A" className="w-full border rounded px-3 py-2" />
        </div>

        <div className="mb-3">
          <label className="text-xs font-medium text-gray-600 block mb-1">Side B company</label>
          <select value={companyIdB} onChange={(e) => setCompanyIdB(e.target.value)} className="w-full border rounded px-3 py-2" aria-label="Side B company">
            <option value="">All companies</option>
            {companies?.map((c: { id: number; name: string }) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="text-xs font-medium text-gray-600 block mb-1">Side B tag</label>
          <select value={tagKeyB} onChange={(e) => setTagKeyB(e.target.value)} className="w-full border rounded px-3 py-2" aria-label="Side B tag">
            <option value="">All tags</option>
            {tags?.map((t: { key: string; emoji: string; name: string }) => (
              <option key={t.key} value={t.key}>{t.emoji} {t.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="text-xs font-medium text-gray-600 block mb-1">Side B status</label>
          <select value={statusB} onChange={(e) => setStatusB(e.target.value)} className="w-full border rounded px-3 py-2" aria-label="Side B status">
            <option value="">Accepted + suggested</option>
            <option value="accepted">Accepted only</option>
            <option value="suggested">Suggested only</option>
          </select>
        </div>

        <div className="mb-4">
          <label className="text-xs font-medium text-gray-600 block mb-1">Side B label</label>
          <input type="text" value={labelB} onChange={(e) => setLabelB(e.target.value)} placeholder="Label B" className="w-full border rounded px-3 py-2" />
        </div>

        {error && <p className="text-red-600 text-sm mb-2">{error}</p>}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 bg-gray-200 rounded hover:bg-gray-300">Cancel</button>
          <button onClick={execute} disabled={loading || (!companyIdB && !tagKeyB)} className="px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'Comparing...' : 'Execute Lens'}
          </button>
        </div>
      </div>
    </div>
  );
}

function LensResultPanel({ result, onClose }: { result: Record<string, unknown>; onClose: () => void }) {
  const r = result as {
    themes_a?: { name: string; summary: string; evidence_highlight_ids?: number[] }[];
    themes_b?: { name: string; summary: string; evidence_highlight_ids?: number[] }[];
    themes_shared?: { name: string; summary: string; evidence_highlight_ids?: number[] }[];
    contradictions?: { name: string; summary: string; evidence_highlight_ids?: number[] }[];
    evidence_context?: Record<string, { highlight_id: number; quote: string; conversation_id: number; conversation_title: string; tag_key: string; side: string }>;
  };

  const ctx = r.evidence_context || {};

  const renderEvidence = (ids: number[] | undefined) => {
    if (!ids || ids.length === 0) return null;
    return (
      <div className="mt-1 space-y-1">
        {ids.map((hid) => {
          const ev = ctx[String(hid)];
          if (!ev) return <span key={hid} className="text-xs text-gray-400">[#{hid}]</span>;
          return (
            <div key={hid} className="text-xs bg-gray-100 rounded px-2 py-1">
              <span className="italic text-gray-600">"{ev.quote.slice(0, 80)}{ev.quote.length > 80 ? '…' : ''}"</span>
              {ev.conversation_title && (
                <Link
                  to={`/conversations/${ev.conversation_id}`}
                  className="ml-1 text-blue-600 hover:underline"
                  data-testid={`evidence-link-${hid}`}
                >
                  ↗ {ev.conversation_title}
                </Link>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="bg-surface border border-hairline rounded-[14px] p-5 mb-5" aria-label="Lens results">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[15px] font-semibold">🔍 Lens Results</h2>
        <button onClick={onClose} className="text-xs text-muted hover:text-ink">✕ Close</button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <h3 className="font-semibold text-sm mb-2" aria-label="Side A themes">Side A unique</h3>
          {(r.themes_a || []).map((t, i) => (
            <div key={i} className="text-sm mb-2 border-l-2 border-blue-400 pl-2">
              <b>{t.name}</b>: {t.summary}
              {renderEvidence(t.evidence_highlight_ids)}
            </div>
          ))}
          {!(r.themes_a?.length) && <p className="text-sm text-gray-400">None</p>}
        </div>
        <div>
          <h3 className="font-semibold text-sm mb-2" aria-label="Side B themes">Side B unique</h3>
          {(r.themes_b || []).map((t, i) => (
            <div key={i} className="text-sm mb-2 border-l-2 border-green-400 pl-2">
              <b>{t.name}</b>: {t.summary}
              {renderEvidence(t.evidence_highlight_ids)}
            </div>
          ))}
          {!(r.themes_b?.length) && <p className="text-sm text-gray-400">None</p>}
        </div>
      </div>
      {(r.themes_shared?.length ?? 0) > 0 && (
        <div className="mt-3">
          <h3 className="font-semibold text-sm mb-1" aria-label="Shared themes">Shared</h3>
          {r.themes_shared!.map((t, i) => (
            <div key={i} className="text-sm mb-1 border-l-2 border-gray-300 pl-2">
              <b>{t.name}</b>: {t.summary}
              {renderEvidence(t.evidence_highlight_ids)}
            </div>
          ))}
        </div>
      )}
      {(r.contradictions?.length ?? 0) > 0 && (
        <div className="mt-3 border-t pt-2">
          <h3 className="font-semibold text-sm mb-1 text-red-600" aria-label="Contradictions">⚡ Contradictions</h3>
          {r.contradictions!.map((t, i) => (
            <div key={i} className="text-sm mb-1 border-l-2 border-red-400 pl-2">
              <b>{t.name}</b>: {t.summary}
              {renderEvidence(t.evidence_highlight_ids)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function QuoteCard({ item }: { item: HighlightWithContext }) {
  const navigate = useNavigate();
  const tax = useTaxonomy();
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
        {tax.emoji(item.tag_key)} {tax.name(item.tag_key)}
        {item.confidence != null && <span className="text-muted font-normal ml-auto">{item.confidence.toFixed(2)}</span>}
      </div>
      <blockquote className="text-[14.5px] text-ink mb-2.5">
        “{item.quote}”
      </blockquote>
      <div className="text-xs text-muted">
        <b className="text-ink-2">{item.company_name || 'Unknown'}</b> · {item.contact_names[0] || '—'} ·{' '}
        {item.conversation_happened_at
          ? new Date(item.conversation_happened_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
          : '—'}{' '}
        <span className="text-accent" aria-label="open conversation">→ open ↗</span>
      </div>
      <div className="mt-1">
        <Link
          to={`/decisions?highlight_id=${item.id}`}
          className="text-xs text-blue-600 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          📋 Cite in decision
        </Link>
      </div>
    </article>
  );
}

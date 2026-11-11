import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, Link } from 'react-router-dom';
import { api } from '../api';

interface Decision {
  id: number;
  title: string;
  status: string;
  integrity: string;
  decided_at: string | null;
  created_at: string;
}

interface DecisionDetail extends Decision {
  rationale_md: string;
  integrity_reasons: { reason: string; source_type: string; source_id: number }[] | null;
  hypothesis_id: number | null;
  decided_by: number | null;
  superseded_by: number | null;
  evidence: {
    highlight_id: number;
    quote: string;
    tag_key: string;
    conversation_id: number;
    conversation_title: string | null;
    conversation_happened_at: string | null;
    status: string;
  }[];
}

const STATUS_PILL: Record<string, string> = {
  proposed: 'bg-[#eff4ff] text-[#1d4ed8]',
  decided: 'bg-good-soft text-good-text',
  superseded: 'bg-sub text-ink-2',
};

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-pill capitalize ${STATUS_PILL[status] || 'bg-sub text-ink-2'}`}>
      {status}
    </span>
  );
}

function IntegrityPill({ integrity }: { integrity: string }) {
  const undermined = integrity === 'undermined';
  return (
    <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-pill ${undermined ? 'bg-warn-soft text-warn-text' : 'bg-good-soft text-good-text'}`}>
      {undermined ? 'Undermined' : 'OK'}
    </span>
  );
}

const TABS = ['all', 'proposed', 'decided', 'superseded'] as const;
type Tab = typeof TABS[number];

export function DecisionsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [tab, setTab] = useState<Tab>('all');

  const preselectedHighlightId = searchParams.get('highlight_id');
  useEffect(() => {
    if (preselectedHighlightId) setShowCreate(true);
  }, [preselectedHighlightId]);

  const { data: listData, isLoading } = useQuery({
    queryKey: ['decisions'],
    queryFn: async () => {
      const r = await fetch('/api/decisions');
      if (!r.ok) throw new Error('Failed');
      return r.json() as Promise<{ items: Decision[]; total: number }>;
    },
  });

  const { data: detail } = useQuery({
    queryKey: ['decisions', selectedId],
    queryFn: async () => {
      const r = await fetch(`/api/decisions/${selectedId}`);
      if (!r.ok) throw new Error('Failed');
      return r.json() as Promise<DecisionDetail>;
    },
    enabled: !!selectedId,
  });

  const transitionMutation = useMutation({
    mutationFn: async ({ id, status, superseded_by_id }: { id: number; status: string; superseded_by_id?: number }) => {
      const r = await fetch(`/api/decisions/${id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, superseded_by_id }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Failed' }));
        throw new Error(err.detail || 'Failed');
      }
      return r.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['decisions'] }),
  });

  const items = listData?.items || [];
  const shown = tab === 'all' ? items : items.filter((d) => d.status === tab);

  const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—');

  return (
    <main className="p-6 flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-2xl font-bold text-ink">Decisions</h1>
          <span className="text-muted">What we decided, and the quotes behind it</span>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn btn-primary ml-auto">New decision</button>
      </div>

      {/* Status segmented control (preset filter) */}
      <div className="flex gap-0.5 p-0.5 rounded-lg bg-sub self-start" role="tablist" aria-label="Status">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`h-[30px] px-3 rounded-md border-none font-semibold capitalize cursor-pointer ${tab === t ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'}`}>
            {t}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-muted">Loading decisions…</p>
      ) : items.length === 0 ? (
        <p className="text-muted">No decisions yet. Create one citing highlight evidence.</p>
      ) : (
        <div className="bg-surface border border-hairline rounded-[10px] overflow-x-auto">
          <div className="min-w-[640px]">
            <div className="grid gap-4 px-4 py-2.5 border-b border-hairline text-xs font-semibold text-muted"
              style={{ gridTemplateColumns: 'minmax(0,1fr) 120px 110px 130px 90px' }}>
              <span>Decision</span><span>Status</span><span>Evidence</span><span>Integrity</span><span>Date</span>
            </div>
            {shown.map((d) => (
              <div key={d.id} role="button" tabIndex={0} aria-label={d.title}
                onClick={() => setSelectedId(d.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(d.id); } }}
                className="grid gap-4 items-center px-4 py-3 border-b border-hairline cursor-pointer last:border-b-0"
                style={{ gridTemplateColumns: 'minmax(0,1fr) 120px 110px 130px 90px', ...(selectedId === d.id ? { background: '#f1f5fe', boxShadow: 'inset 3px 0 0 #2f5bea' } : {}) }}>
                <span className="trunc font-semibold text-ink" title={d.title}>{d.title}</span>
                <span><StatusPill status={d.status} /></span>
                <span className="text-ink-2">evidence</span>
                <span><IntegrityPill integrity={d.integrity} /></span>
                <span className="text-muted">{fmtDate(d.decided_at || d.created_at)}</span>
              </div>
            ))}
            {shown.length === 0 && <p className="text-sm text-muted p-4">No {tab} decisions.</p>}
          </div>
        </div>
      )}

      {/* Inline detail for the selected row */}
      {selectedId && detail && (
        <section aria-label="Selected decision" className="bg-surface border border-hairline rounded-xl p-5 flex flex-col gap-3">
          <div className="flex flex-wrap gap-2 items-center">
            <h2 className="text-lg font-bold text-ink">{detail.title}</h2>
            <StatusPill status={detail.status} />
            <button onClick={() => setSelectedId(null)} className="ml-auto text-sm text-muted hover:text-ink bg-transparent border-none cursor-pointer">Close</button>
          </div>
          <p className="m-0">{detail.rationale_md}</p>

          {detail.integrity === 'undermined' && (
            <div className="px-3 py-2.5 rounded-lg bg-warn-soft text-[#93370d] text-[13px] flex flex-col gap-1">
              <span>
                <strong>Integrity check:</strong>{' '}
                {detail.integrity_reasons && detail.integrity_reasons.length > 0
                  ? `${detail.integrity_reasons.length} cited quote(s) changed since. Re-check whether the decision still holds.`
                  : 'A cited quote has changed since. Re-check whether the decision still holds.'}
              </span>
              {detail.integrity_reasons && detail.integrity_reasons.length > 0 && (
                <ul className="list-disc list-inside m-0">
                  {detail.integrity_reasons.map((r, i) => <li key={i}>{r.reason}</li>)}
                </ul>
              )}
            </div>
          )}

          <span className="text-xs font-semibold text-muted">Evidence receipts</span>
          <div className="flex flex-col gap-2">
            {detail.evidence.map((ev) => {
              const stale = ev.status === 'rejected';
              return (
                <div key={ev.highlight_id}
                  className="flex flex-col gap-0.5 px-3 py-2.5 rounded-lg border"
                  style={stale ? { border: '1px dashed #f79009', background: '#fffcf5', opacity: 0.85 } : { borderColor: '#e5e7eb' }}>
                  <span className="text-ink">“{ev.quote}”</span>
                  <span className="text-xs text-muted">
                    {ev.conversation_title || `Conversation ${ev.conversation_id}`}
                    {stale && ' · tag rejected in review'}
                    {' · '}
                    <Link to={`/conversations/${ev.conversation_id}`}>open</Link>
                  </span>
                </div>
              );
            })}
            {detail.evidence.length === 0 && <span className="text-sm text-muted">No evidence cited.</span>}
          </div>

          {detail.superseded_by && (
            <span className="text-sm text-muted">Superseded by decision #{detail.superseded_by}</span>
          )}

          <div className="flex gap-2">
            {detail.status === 'proposed' && (
              <button onClick={() => transitionMutation.mutate({ id: detail.id, status: 'decided' })} className="btn btn-sm btn-primary">Mark as decided</button>
            )}
            {detail.status === 'decided' && (
              <SupersedeButton currentId={detail.id} allDecisions={items}
                onSupersede={(successorId) => transitionMutation.mutate({ id: detail.id, status: 'superseded', superseded_by_id: successorId })} />
            )}
          </div>
          {transitionMutation.isError && <p className="text-crit text-sm">{(transitionMutation.error as Error).message}</p>}
        </section>
      )}

      {showCreate && (
        <CreateDecisionModal
          preselectedHighlightId={preselectedHighlightId ? parseInt(preselectedHighlightId) : undefined}
          onClose={() => {
            setShowCreate(false);
            if (preselectedHighlightId) setSearchParams({}, { replace: true });
            queryClient.invalidateQueries({ queryKey: ['decisions'] });
          }}
        />
      )}
    </main>
  );
}

function SupersedeButton({ currentId, allDecisions, onSupersede }: {
  currentId: number;
  allDecisions: Decision[];
  onSupersede: (successorId: number) => void;
}) {
  const [selecting, setSelecting] = useState(false);
  const [successorId, setSuccessorId] = useState<string>('');
  const otherDecisions = allDecisions.filter((d) => d.id !== currentId && d.status !== 'superseded');

  if (!selecting) {
    return <button onClick={() => setSelecting(true)} className="btn btn-sm btn-ghost">Supersede</button>;
  }
  return (
    <div className="flex gap-2 items-center">
      <select value={successorId} onChange={(e) => setSuccessorId(e.target.value)} className="border border-hairline rounded-lg px-2 py-1 text-sm" aria-label="Select successor decision">
        <option value="">Select successor…</option>
        {otherDecisions.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
      </select>
      <button onClick={() => { if (successorId) onSupersede(parseInt(successorId)); }} disabled={!successorId} className="btn btn-sm btn-ghost disabled:opacity-50">Confirm</button>
      <button onClick={() => setSelecting(false)} className="text-sm text-muted hover:underline bg-transparent border-none cursor-pointer">Cancel</button>
    </div>
  );
}

function CreateDecisionModal({ onClose, preselectedHighlightId }: { onClose: () => void; preselectedHighlightId?: number }) {
  const [title, setTitle] = useState('');
  const [rationale, setRationale] = useState('');
  const [selectedHighlights, setSelectedHighlights] = useState<number[]>(preselectedHighlightId ? [preselectedHighlightId] : []);
  const [searchQuery, setSearchQuery] = useState('');

  const { data: highlightsData } = useQuery({
    queryKey: ['highlights-for-decision', searchQuery],
    queryFn: () => api.listHighlights({ status: 'accepted', limit: 50 }),
  });

  const highlights = highlightsData?.items || [];
  const filteredHighlights = searchQuery
    ? highlights.filter((h) =>
        h.quote.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (h.company_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        h.tag_key.toLowerCase().includes(searchQuery.toLowerCase()))
    : highlights;

  const toggleHighlight = (id: number) =>
    setSelectedHighlights((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  const createMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch('/api/decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, rationale_md: rationale, evidence: selectedHighlights }),
      });
      if (!r.ok) { const err = await r.json(); throw new Error(err.detail || 'Failed'); }
      return r.json();
    },
    onSuccess: () => onClose(),
  });

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" role="dialog" aria-label="Create decision">
      <div className="bg-surface rounded-xl p-6 w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col border border-hairline">
        <h2 className="text-lg font-bold mb-4 text-ink">New decision</h2>
        <input type="text" placeholder="Decision title" value={title} onChange={(e) => setTitle(e.target.value)} className="w-full border border-hairline rounded-lg px-3 py-2 mb-3" />
        <textarea placeholder="Rationale (why this decision)" value={rationale} onChange={(e) => setRationale(e.target.value)} className="w-full border border-hairline rounded-lg px-3 py-2 mb-3 h-20" />
        <div className="mb-3 flex-1 min-h-0 flex flex-col">
          <label className="text-sm font-semibold mb-1">Evidence highlights ({selectedHighlights.length} selected)</label>
          <p className="text-xs text-muted mb-2">Decisions must cite evidence. Select highlights from Explore, or add evidence from conversations.</p>
          <input type="text" placeholder="Search highlights…" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full border border-hairline rounded-lg px-3 py-1.5 mb-2 text-sm" aria-label="Search evidence highlights" />
          <div className="flex-1 overflow-y-auto border border-hairline rounded-lg max-h-48">
            {filteredHighlights.map((h) => (
              <label key={h.id} className={`flex items-start gap-2 p-2 border-b border-sub last:border-0 cursor-pointer hover:bg-page ${selectedHighlights.includes(h.id) ? 'bg-accent-soft' : ''}`}>
                <input type="checkbox" checked={selectedHighlights.includes(h.id)} onChange={() => toggleHighlight(h.id)} className="mt-1" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">“{h.quote}”</p>
                  <span className="text-xs text-muted">{h.tag_key} · {h.company_name || 'Unknown'}</span>
                </div>
              </label>
            ))}
            {filteredHighlights.length === 0 && <p className="text-sm text-muted p-3">No matching highlights</p>}
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn btn-sm btn-ghost">Cancel</button>
          <button onClick={() => createMutation.mutate()} disabled={!title || !rationale || selectedHighlights.length === 0 || createMutation.isPending} className="btn btn-sm btn-primary disabled:opacity-50">
            {createMutation.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
        {createMutation.isError && <p className="text-crit text-sm mt-2">{(createMutation.error as Error).message}</p>}
      </div>
    </div>
  );
}

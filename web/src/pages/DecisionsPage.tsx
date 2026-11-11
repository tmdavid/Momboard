import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, Link } from 'react-router-dom';
import { api } from '../api';
import {
  jsonFetch, useTeamUsers, EditDecisionForm, AddQuote, LinkedHypothesisBox,
} from '../components/DecisionParts';

interface Decision {
  id: number;
  title: string;
  status: string;
  integrity: string;
  decided_at: string | null;
  created_at: string;
  owner_id?: number | null;
  area?: string | null;
  evidence_count?: number;
  hypothesis_id?: number | null;
  hypothesis_archived?: boolean;
}

interface DecisionDetail extends Decision {
  rationale_md: string;
  integrity_reasons: { reason: string; source_type: string; source_id: number }[] | null;
  hypothesis_id: number | null;
  hypothesis?: { id: number; statement: string; band: string; archived?: boolean } | null;
  decided_by: number | null;
  superseded_by: number | null;
  superseded_by_title?: string | null;
  evidence: {
    highlight_id: number | null;
    quote: string;
    tag_key: string;
    conversation_id: number;
    conversation_title: string | null;
    conversation_happened_at: string | null;
    status: string;
  }[];
}

const STATUS_PILL: Record<string, string> = {
  draft: 'bg-sub text-ink-2',
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

const TABS = ['all', 'draft', 'proposed', 'decided', 'superseded'] as const;
const SORTS = [
  { value: 'date_desc', label: 'Newest first' },
  { value: 'date_asc', label: 'Oldest first' },
  { value: 'integrity', label: 'Needs attention first' },
] as const;
type Tab = typeof TABS[number];

export function DecisionsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [tab, setTab] = useState<Tab>('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<string>('date_desc');
  const [editing, setEditing] = useState(false);
  const { nameOf } = useTeamUsers();
  useEffect(() => setEditing(false), [selectedId]);

  // Prefill from elsewhere in the app: ?highlight_id=1&highlight_id=2 and/or ?hypothesis_id=3.
  const preselectedHighlightIds = searchParams
    .getAll('highlight_id')
    .map((v) => parseInt(v, 10))
    .filter((n) => !Number.isNaN(n));
  const hypothesisIdParam = searchParams.get('hypothesis_id');
  const preselectedHypothesisId = hypothesisIdParam ? parseInt(hypothesisIdParam, 10) : undefined;
  const hasPrefill = preselectedHighlightIds.length > 0 || preselectedHypothesisId !== undefined;
  const prefillKey = `${preselectedHighlightIds.join(',')}|${preselectedHypothesisId ?? ''}`;
  useEffect(() => {
    if (prefillKey !== '|') setShowCreate(true);
  }, [prefillKey]);

  const term = search.trim();
  const { data: listData, isLoading } = useQuery({
    queryKey: ['decisions', 'list', term, sort],
    queryFn: async () => {
      const params = new URLSearchParams({ sort, limit: '200' });
      if (term) params.set('q', term);
      const r = await fetch(`/api/decisions?${params.toString()}`);
      if (!r.ok) throw new Error('Failed');
      return r.json() as Promise<{ items: Decision[]; total: number }>;
    },
    placeholderData: (prev) => prev,
  });

  const { data: detail } = useQuery({
    queryKey: ['decisions', 'detail', selectedId],
    queryFn: async () => {
      const r = await fetch(`/api/decisions/${selectedId}`);
      if (!r.ok) throw new Error('Failed');
      return r.json() as Promise<DecisionDetail>;
    },
    enabled: !!selectedId,
  });

  const removeQuote = useMutation({
    mutationFn: ({ id, highlightId }: { id: number; highlightId: number }) =>
      jsonFetch(`/api/decisions/${id}/evidence/${highlightId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['decisions'] }),
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

      <div className="flex flex-wrap items-center gap-3">
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
          aria-label="Search decisions" placeholder="Search decisions…"
          className="h-9 w-64 px-3 border border-hairline rounded-lg bg-surface text-sm" />
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort decisions"
            className="h-9 px-2 border border-hairline rounded-lg bg-surface text-sm text-ink">
            {SORTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      </div>

      {isLoading ? (
        <p className="text-muted">Loading decisions…</p>
      ) : items.length === 0 && !term ? (
        <p className="text-muted">No decisions yet. Create one citing highlight evidence.</p>
      ) : items.length === 0 ? (
        <p className="text-muted">No decisions match “{term}”.</p>
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
                <span className="min-w-0 flex flex-col">
                  <span className="trunc font-semibold text-ink" title={d.title}>{d.title}</span>
                  {(nameOf(d.owner_id) || d.area || d.hypothesis_archived) && (
                    <span className="trunc text-xs text-muted">
                      {[nameOf(d.owner_id), d.area].filter(Boolean).join(' · ')}
                      {d.hypothesis_archived && (
                        <span className="ml-1.5 text-[#93370d] font-semibold">
                          {nameOf(d.owner_id) || d.area ? '· ' : ''}Belief archived
                        </span>
                      )}
                    </span>
                  )}
                </span>
                <span><StatusPill status={d.status} /></span>
                <span className="text-ink-2">
                  {d.evidence_count == null ? '—' : `${d.evidence_count} ${d.evidence_count === 1 ? 'quote' : 'quotes'}`}
                </span>
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
            <span className="ml-auto flex gap-3">
              {!editing && (
                <button onClick={() => setEditing(true)} className="text-sm font-semibold text-accent hover:underline bg-transparent border-none cursor-pointer">Edit</button>
              )}
              <button onClick={() => { setSelectedId(null); setEditing(false); }} className="text-sm text-muted hover:text-ink bg-transparent border-none cursor-pointer">Close</button>
            </span>
          </div>
          {(nameOf(detail.owner_id) || detail.area) && !editing && (
            <span className="text-xs text-muted" data-testid="owner-area">
              {[nameOf(detail.owner_id) && `Owner: ${nameOf(detail.owner_id)}`, detail.area && `Area: ${detail.area}`].filter(Boolean).join(' · ')}
            </span>
          )}
          {editing ? (
            <EditDecisionForm
              key={detail.id}
              decision={{ id: detail.id, title: detail.title, rationale_md: detail.rationale_md, owner_id: detail.owner_id ?? null, area: detail.area ?? null }}
              onDone={() => setEditing(false)}
            />
          ) : (
            <p className="m-0">{detail.rationale_md}</p>
          )}

          {detail.hypothesis && <LinkedHypothesisBox hypothesis={detail.hypothesis} />}

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
            {detail.evidence.map((ev, idx) => {
              const stale = ev.status === 'rejected';
              const canRemove = ev.highlight_id != null && (detail.status === 'draft' || detail.evidence.length > 1);
              return (
                <div key={ev.highlight_id ?? `gone-${idx}`}
                  className="flex flex-col gap-0.5 px-3 py-2.5 rounded-lg border"
                  style={stale ? { border: '1px dashed #f79009', background: '#fffcf5', opacity: 0.85 } : { borderColor: '#e5e7eb' }}>
                  <span className="text-ink">“{ev.quote}”</span>
                  <span className="text-xs text-muted">
                    {ev.conversation_title || `Conversation ${ev.conversation_id}`}
                    {stale && ' · tag rejected in review'}
                    {' · '}
                    <Link to={`/conversations/${ev.conversation_id}`}>open</Link>
                    {canRemove && (
                      <>
                        {' · '}
                        <button type="button" aria-label={`Remove quote: ${ev.quote}`}
                          disabled={removeQuote.isPending}
                          onClick={() => removeQuote.mutate({ id: detail.id, highlightId: ev.highlight_id as number })}
                          className="bg-transparent border-none p-0 text-crit cursor-pointer hover:underline">Remove</button>
                      </>
                    )}
                  </span>
                </div>
              );
            })}
            {detail.evidence.length === 0 && <span className="text-sm text-muted">No evidence cited.</span>}
          </div>
          {removeQuote.isError && <p role="alert" className="text-crit text-sm">{(removeQuote.error as Error).message}</p>}

          {detail.status !== 'superseded' && (
            <AddQuote
              decisionId={detail.id}
              citedHighlightIds={new Set(detail.evidence.map((e) => e.highlight_id).filter((x): x is number => x != null))}
            />
          )}

          {detail.superseded_by && (
            <span className="text-sm text-muted">
              Superseded by{' '}
              <button type="button" onClick={() => setSelectedId(detail.superseded_by)}
                className="bg-transparent border-none p-0 text-accent cursor-pointer hover:underline">
                {detail.superseded_by_title || `decision #${detail.superseded_by}`}
              </button>
            </span>
          )}

          <div className="flex gap-2">
            {detail.status === 'draft' && (
              <button
                onClick={() => transitionMutation.mutate({ id: detail.id, status: 'proposed' })}
                disabled={detail.evidence.length === 0}
                title={detail.evidence.length === 0 ? 'Cite at least one quote first' : undefined}
                className="btn btn-sm btn-primary disabled:opacity-50">Propose</button>
            )}
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
          preselectedHighlightIds={preselectedHighlightIds}
          hypothesisId={Number.isNaN(preselectedHypothesisId ?? 0) ? undefined : preselectedHypothesisId}
          onClose={() => {
            setShowCreate(false);
            if (hasPrefill) setSearchParams({}, { replace: true });
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

function CreateDecisionModal({ onClose, preselectedHighlightIds = [], hypothesisId }: { onClose: () => void; preselectedHighlightIds?: number[]; hypothesisId?: number }) {
  const [title, setTitle] = useState('');
  const [rationale, setRationale] = useState('');
  const [selectedHighlights, setSelectedHighlights] = useState<number[]>(preselectedHighlightIds);
  const [ownerId, setOwnerId] = useState('');
  const [area, setArea] = useState('');
  const { users } = useTeamUsers();

  // When opened from a hypothesis, show which belief this decision is about.
  const { data: linkedHypothesis } = useQuery({
    queryKey: ['hypothesis', hypothesisId],
    queryFn: () => api.getHypothesis(hypothesisId as number),
    enabled: hypothesisId !== undefined,
  });
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
    mutationFn: async (asDraft: boolean = false) => {
      const r = await fetch('/api/decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          rationale_md: rationale,
          evidence: selectedHighlights,
          ...(hypothesisId !== undefined ? { hypothesis_id: hypothesisId } : {}),
          ...(ownerId ? { owner_id: parseInt(ownerId, 10) } : {}),
          ...(area.trim() ? { area: area.trim() } : {}),
          ...(asDraft ? { status: 'draft' } : {}),
        }),
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
        {hypothesisId !== undefined && (
          <p className="text-xs text-muted mb-3" data-testid="linked-hypothesis">
            About hypothesis: <b className="text-ink-2">{linkedHypothesis?.statement ?? `#${hypothesisId}`}</b>
          </p>
        )}
        <input type="text" placeholder="Decision title" value={title} onChange={(e) => setTitle(e.target.value)} className="w-full border border-hairline rounded-lg px-3 py-2 mb-3" />
        <textarea placeholder="Rationale (why this decision)" value={rationale} onChange={(e) => setRationale(e.target.value)} className="w-full border border-hairline rounded-lg px-3 py-2 mb-3 h-20" />
        <div className="flex gap-3 mb-3">
          <label className="flex-1 flex flex-col gap-1 text-xs font-semibold text-muted">
            Owner
            <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} className="h-9 px-2 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink">
              <option value="">No owner</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </label>
          <label className="flex-1 flex flex-col gap-1 text-xs font-semibold text-muted">
            Area
            <input value={area} onChange={(e) => setArea(e.target.value)} placeholder="e.g. Pricing" className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink" />
          </label>
        </div>
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
          <button onClick={() => createMutation.mutate(true)} disabled={!title || !rationale || createMutation.isPending} className="btn btn-sm btn-ghost disabled:opacity-50" title="Keep working on it; quotes can be added later">
            Save as draft
          </button>
          <button onClick={() => createMutation.mutate(false)} disabled={!title || !rationale || selectedHighlights.length === 0 || createMutation.isPending} className="btn btn-sm btn-primary disabled:opacity-50">
            {createMutation.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
        {createMutation.isError && <p className="text-crit text-sm mt-2">{(createMutation.error as Error).message}</p>}
      </div>
    </div>
  );
}

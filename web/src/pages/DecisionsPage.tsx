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

export function DecisionsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Support preselected highlight from query params (for "Cite in decision")
  const preselectedHighlightId = searchParams.get('highlight_id');

  // Auto-open modal when arriving with a preselected highlight
  useEffect(() => {
    if (preselectedHighlightId) {
      setShowCreate(true);
    }
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['decisions'] });
    },
  });

  if (isLoading) return <div className="p-6">Loading decisions...</div>;

  const items = listData?.items || [];

  // Detail view
  if (selectedId && detail) {
    return (
      <div className="max-w-3xl mx-auto p-6">
        <button onClick={() => setSelectedId(null)} className="text-accent hover:underline mb-4">
          ← Back to list
        </button>

        <div className="bg-surface rounded-xl border border-hairline p-6">
          <div className="flex items-center gap-2 mb-2">
            <h1 className="text-xl font-bold">{detail.title}</h1>
            {detail.integrity === 'undermined' && (
              <span className="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded-full font-medium">
                ⚠️ Undermined
              </span>
            )}
          </div>

          <div className="flex gap-2 mb-4">
            <span className={`px-2 py-0.5 text-xs rounded-full ${
              detail.status === 'decided' ? 'bg-green-100 text-green-700' :
              detail.status === 'superseded' ? 'bg-gray-100 text-gray-500' :
              'bg-yellow-100 text-yellow-700'
            }`}>
              {detail.status}
            </span>
            {detail.decided_at && (
              <span className="text-xs text-gray-500">
                Decided {new Date(detail.decided_at).toLocaleDateString()}
              </span>
            )}
          </div>

          <div className="prose prose-sm mb-4">
            <h3>Rationale</h3>
            <p>{detail.rationale_md}</p>
          </div>

          {/* Integrity reasons */}
          {detail.integrity === 'undermined' && detail.integrity_reasons && detail.integrity_reasons.length > 0 && (
            <div className="mb-4 border border-red-200 rounded-lg p-3 bg-red-50">
              <h3 className="text-sm font-semibold text-red-700 mb-1">Integrity concerns</h3>
              <ul className="list-disc list-inside text-sm text-red-600">
                {detail.integrity_reasons.map((r, i) => (
                  <li key={i}>{r.reason}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mb-4">
            <h3 className="font-semibold text-sm mb-2">Evidence ({detail.evidence.length})</h3>
            <div className="space-y-2">
              {detail.evidence.map((ev) => (
                <div key={ev.highlight_id} className="border rounded p-3 bg-gray-50">
                  <p className="text-sm italic">"{ev.quote}"</p>
                  <div className="flex gap-2 mt-1 text-xs text-gray-500">
                    <span className="font-medium">{ev.tag_key}</span>
                    {ev.conversation_title && (
                      <Link to={`/conversations/${ev.conversation_id}`} className="text-blue-600 hover:underline">
                        {ev.conversation_title}
                      </Link>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {detail.superseded_by && (
            <div className="text-sm text-gray-500 mb-4">
              Superseded by decision #{detail.superseded_by}
            </div>
          )}

          <div className="flex gap-2">
            {detail.status === 'proposed' && (
              <button
                onClick={() => transitionMutation.mutate({ id: detail.id, status: 'decided' })}
                className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700"
              >
                Mark as Decided
              </button>
            )}
            {detail.status === 'decided' && (
              <SupersedeButton
                currentId={detail.id}
                allDecisions={items}
                onSupersede={(successorId) =>
                  transitionMutation.mutate({ id: detail.id, status: 'superseded', superseded_by_id: successorId })
                }
              />
            )}
          </div>
          {transitionMutation.isError && (
            <p className="text-red-600 text-sm mt-2">{(transitionMutation.error as Error).message}</p>
          )}
        </div>
      </div>
    );
  }

  // List view
  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold tracking-tight">📋 Decisions</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="btn btn-primary"
        >
          + New Decision
        </button>
      </div>

      {items.length === 0 ? (
        <p className="text-muted">No decisions yet. Create one citing highlight evidence.</p>
      ) : (
        <div className="space-y-2">
          {items.map((d) => (
            <div
              key={d.id}
              onClick={() => setSelectedId(d.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSelectedId(d.id);
                }
              }}
              className="border border-hairline rounded-xl p-4 bg-surface hover:bg-page cursor-pointer"
              role="button"
              tabIndex={0}
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{d.title}</span>
                <span className={`px-2 py-0.5 text-xs rounded-full ${
                  d.status === 'decided' ? 'bg-green-100 text-green-700' :
                  d.status === 'superseded' ? 'bg-gray-100 text-gray-500' :
                  'bg-yellow-100 text-yellow-700'
                }`}>
                  {d.status}
                </span>
                {d.integrity === 'undermined' && (
                  <span className="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded-full">
                    ⚠️ Undermined
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Created {new Date(d.created_at).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateDecisionModal
          preselectedHighlightId={preselectedHighlightId ? parseInt(preselectedHighlightId) : undefined}
          onClose={() => {
            setShowCreate(false);
            // Clear the query param so the modal doesn't reopen
            if (preselectedHighlightId) {
              setSearchParams({}, { replace: true });
            }
            queryClient.invalidateQueries({ queryKey: ['decisions'] });
          }}
        />
      )}
    </div>
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
    return (
      <button
        onClick={() => setSelecting(true)}
        className="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700"
      >
        Supersede
      </button>
    );
  }

  return (
    <div className="flex gap-2 items-center">
      <select
        value={successorId}
        onChange={(e) => setSuccessorId(e.target.value)}
        className="border rounded px-2 py-1 text-sm"
        aria-label="Select successor decision"
      >
        <option value="">Select successor…</option>
        {otherDecisions.map((d) => (
          <option key={d.id} value={d.id}>{d.title}</option>
        ))}
      </select>
      <button
        onClick={() => { if (successorId) onSupersede(parseInt(successorId)); }}
        disabled={!successorId}
        className="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 disabled:opacity-50"
      >
        Confirm
      </button>
      <button onClick={() => setSelecting(false)} className="text-sm text-gray-500 hover:underline">
        Cancel
      </button>
    </div>
  );
}

function CreateDecisionModal({ onClose, preselectedHighlightId }: { onClose: () => void; preselectedHighlightId?: number }) {
  const [title, setTitle] = useState('');
  const [rationale, setRationale] = useState('');
  const [selectedHighlights, setSelectedHighlights] = useState<number[]>(
    preselectedHighlightId ? [preselectedHighlightId] : []
  );
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch accepted highlights for the evidence picker
  const { data: highlightsData } = useQuery({
    queryKey: ['highlights-for-decision', searchQuery],
    queryFn: () => api.listHighlights({ status: 'accepted', limit: 50 }),
  });

  const highlights = highlightsData?.items || [];
  const filteredHighlights = searchQuery
    ? highlights.filter((h) =>
        h.quote.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (h.company_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        h.tag_key.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : highlights;

  const toggleHighlight = (id: number) => {
    setSelectedHighlights((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const createMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch('/api/decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, rationale_md: rationale, evidence: selectedHighlights }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.detail || 'Failed');
      }
      return r.json();
    },
    onSuccess: () => onClose(),
  });

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" role="dialog" aria-label="Create decision">
      <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col">
        <h2 className="text-lg font-bold mb-4">New Decision</h2>
        <input
          type="text"
          placeholder="Decision title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full border rounded px-3 py-2 mb-3"
        />
        <textarea
          placeholder="Rationale (why this decision)"
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          className="w-full border rounded px-3 py-2 mb-3 h-20"
        />

        {/* Evidence picker */}
        <div className="mb-3 flex-1 min-h-0 flex flex-col">
          <label className="text-sm font-semibold mb-1">Evidence highlights ({selectedHighlights.length} selected)</label>
          <p className="text-xs text-gray-500 mb-2">
            Decisions must cite evidence. Select highlights from Explore, or add evidence from conversations.
          </p>
          <input
            type="text"
            placeholder="Search highlights..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full border rounded px-3 py-1.5 mb-2 text-sm"
            aria-label="Search evidence highlights"
          />
          <div className="flex-1 overflow-y-auto border rounded max-h-48">
            {filteredHighlights.map((h) => (
              <label
                key={h.id}
                className={`flex items-start gap-2 p-2 border-b last:border-0 cursor-pointer hover:bg-gray-50 ${
                  selectedHighlights.includes(h.id) ? 'bg-blue-50' : ''
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedHighlights.includes(h.id)}
                  onChange={() => toggleHighlight(h.id)}
                  className="mt-1"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">"{h.quote}"</p>
                  <span className="text-xs text-gray-500">{h.tag_key} · {h.company_name || 'Unknown'}</span>
                </div>
              </label>
            ))}
            {filteredHighlights.length === 0 && (
              <p className="text-sm text-gray-400 p-3">No matching highlights</p>
            )}
          </div>
        </div>

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 bg-gray-200 rounded hover:bg-gray-300">
            Cancel
          </button>
          <button
            onClick={() => createMutation.mutate()}
            disabled={!title || !rationale || selectedHighlights.length === 0 || createMutation.isPending}
            className="px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {createMutation.isPending ? 'Creating...' : 'Create'}
          </button>
        </div>
        {createMutation.isError && (
          <p className="text-red-600 text-sm mt-2">{(createMutation.error as Error).message}</p>
        )}
      </div>
    </div>
  );
}

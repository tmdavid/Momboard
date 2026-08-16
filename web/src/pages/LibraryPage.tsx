import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { api, ConversationListItem } from '../api';
import { NewConversationModal, NewConversationFormData } from '../components/NewConversationModal';
import { useConversationEvents } from '../hooks/useConversationEvents';
import { TAG_META } from '../constants';

export function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [modalOpen, setModalOpen] = useState(false);
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Track conversation IDs that need SSE monitoring (lifted from modal)
  const [trackingIds, setTrackingIds] = useState<number[]>([]);

  const activeTags = searchParams.getAll('tag');
  const companyId = searchParams.get('company_id') || undefined;
  const q = searchParams.get('q') || undefined;
  const dateFrom = searchParams.get('date_from') || undefined;
  const dateTo = searchParams.get('date_to') || undefined;
  const offset = parseInt(searchParams.get('offset') || '0', 10);
  const limit = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ['conversations', { tag: activeTags, company_id: companyId, q, date_from: dateFrom, date_to: dateTo, offset }],
    queryFn: () =>
      api.listConversations({
        tag: activeTags,
        company_id: companyId ? Number(companyId) : undefined,
        q,
        date_from: dateFrom,
        date_to: dateTo,
        offset,
        limit,
      }),
  });

  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: () => api.listCompanies(),
  });

  const handleSearch = useCallback(
    (value: string) => {
      setSearchInput(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        setSearchParams((prev) => {
          if (value) prev.set('q', value);
          else prev.delete('q');
          prev.delete('offset');
          return prev;
        });
      }, 300);
    },
    [setSearchParams],
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const toggleTag = (key: string) => {
    setSearchParams((prev) => {
      const current = prev.getAll('tag');
      if (current.includes(key)) {
        // Remove this tag
        prev.delete('tag');
        current.filter((t) => t !== key).forEach((t) => prev.append('tag', t));
      } else {
        // Add this tag
        prev.append('tag', key);
      }
      prev.delete('offset');
      return prev;
    });
  };

  const handleDateFrom = useCallback(
    (value: string) => {
      setSearchParams((prev) => {
        if (value) prev.set('date_from', value);
        else prev.delete('date_from');
        prev.delete('offset');
        return prev;
      });
    },
    [setSearchParams],
  );

  const handleDateTo = useCallback(
    (value: string) => {
      setSearchParams((prev) => {
        if (value) prev.set('date_to', value);
        else prev.delete('date_to');
        prev.delete('offset');
        return prev;
      });
    },
    [setSearchParams],
  );

  const filterTags = Object.entries(TAG_META).slice(0, 8);

  const conversations = data?.items ?? [];
  const total = data?.total ?? 0;
  const isEmpty = !isLoading && conversations.length === 0;

  // Callback for SSE completion — invalidate conversations list
  const handleSseDone = useCallback(
    (id: number) => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      setTrackingIds((prev) => prev.filter((tid) => tid !== id));
    },
    [queryClient],
  );

  // Optimistic insert mutation — lives in the parent so it survives modal close
  const optimisticInsertMutation = useMutation({
    mutationFn: (variables: NewConversationFormData) =>
      api.createConversation(variables),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ['conversations'] });
      const queryKey = ['conversations', { tag: activeTags, company_id: companyId, q, date_from: dateFrom, date_to: dateTo, offset }];
      const previous = queryClient.getQueryData(queryKey);
      const tempId = -(Date.now());
      const optimisticItem: ConversationListItem = {
        id: tempId,
        title: variables.title,
        happened_at: variables.happened_at || new Date().toISOString(),
        status: 'processing',
        interviewer: variables.interviewer || null,
        company: variables.company ? { id: 0, name: variables.company.name, domain: null, notes: null, created_at: new Date().toISOString() } : null,
        contacts: (variables.contacts || []).map((c, i) => ({ id: -(i + 1), name: c.name, role: c.role || null, email: null, company_id: null, created_at: new Date().toISOString() })),
        meta: variables.meta || null,
        created_at: new Date().toISOString(),
        tag_counts: {},
        critique_score: null,
      };
      queryClient.setQueryData(queryKey, (old: typeof data) => {
        if (!old) return { items: [optimisticItem], total: 1, limit: 50, offset: 0 };
        return { ...old, items: [optimisticItem, ...old.items], total: old.total + 1 };
      });
      // Close modal immediately on submit (optimistic)
      setModalOpen(false);
      return { previous, queryKey, tempId };
    },
    onSuccess: (result, _variables, context) => {
      // Replace temp ID with real ID in cache
      if (context) {
        queryClient.setQueryData(context.queryKey, (old: typeof data) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((item) =>
              item.id === context.tempId ? { ...item, id: result.id } : item,
            ),
          };
        });
      }
      // Start SSE tracking with the real ID
      setTrackingIds((prev) => [...prev, result.id]);
    },
    onError: (_err, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(context.queryKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto p-7">
        {/* Header */}
        <div className="flex items-center mb-4">
          <h1 className="text-xl font-bold tracking-tight">
            Conversations{' '}
            <span className="text-muted font-normal ml-2">({total})</span>
          </h1>
          <div className="flex-1" />
          <button className="btn btn-primary" onClick={() => setModalOpen(true)}>
            ＋ New conversation
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-2.5 items-center p-3 bg-surface border border-hairline rounded-xl mb-4">
          <div className="flex-1 min-w-[220px] flex items-center gap-2 px-2.5 py-1.5 border border-hairline rounded-lg bg-page">
            <span>🔎</span>
            <input
              className="border-none bg-transparent outline-none w-full text-sm text-ink"
              placeholder="Search titles & transcripts…"
              value={searchInput}
              onChange={(e) => handleSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {filterTags.map(([key, meta]) => (
              <button
                key={key}
                onClick={() => toggleTag(key)}
                className={`px-2.5 py-1 rounded-full border text-[13px] cursor-pointer ${
                  activeTags.includes(key)
                    ? 'bg-accent-soft border-accent text-accent font-semibold'
                    : 'bg-surface border-hairline text-ink-2'
                }`}
              >
                {meta.emoji} {meta.name}
              </button>
            ))}
          </div>
          <select
            className="px-2 py-1.5 border border-hairline rounded-lg bg-page text-ink-2 text-sm"
            value={companyId || ''}
            onChange={(e) => {
              setSearchParams((prev) => {
                if (e.target.value) prev.set('company_id', e.target.value);
                else prev.delete('company_id');
                prev.delete('offset');
                return prev;
              });
            }}
            aria-hidden={modalOpen ? 'true' : undefined}
          >
            <option value="">All companies</option>
            {!modalOpen && companies?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-1.5">
            <label htmlFor="filter-date-from" className="text-xs text-muted">From</label>
            <input
              id="filter-date-from"
              type="date"
              className="px-1.5 py-1 border border-hairline rounded-lg bg-page text-ink-2 text-xs"
              value={dateFrom || ''}
              onChange={(e) => handleDateFrom(e.target.value)}
            />
            <label htmlFor="filter-date-to" className="text-xs text-muted">To</label>
            <input
              id="filter-date-to"
              type="date"
              className="px-1.5 py-1 border border-hairline rounded-lg bg-page text-ink-2 text-xs"
              value={dateTo || ''}
              onChange={(e) => handleDateTo(e.target.value)}
            />
          </div>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex justify-center py-12">
            <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="p-4 bg-surface border border-crit/20 rounded-xl text-crit text-sm">
            Failed to load conversations. Please try again.
          </div>
        )}

        {/* Empty state */}
        {isEmpty && (
          <div className="p-16 text-center text-muted bg-surface border border-hairline rounded-xl">
            No conversations yet.
            <br />
            <br />
            <button className="btn btn-primary" onClick={() => setModalOpen(true)}>
              ＋ New conversation
            </button>
          </div>
        )}

        {/* Table */}
        {!isLoading && !modalOpen && conversations.length > 0 && (
          <>
            <table className="w-full border-collapse bg-surface border border-hairline rounded-xl overflow-hidden">
              <thead>
                <tr>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Date
                  </th>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Company / contact
                  </th>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Title
                  </th>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Signals
                  </th>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Score
                  </th>
                  <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {conversations.map((c) => (
                  <ConversationRow key={c.id} conversation={c} onClick={() => navigate(`/conversations/${c.id}`)} />
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            {total > limit && (
              <div className="flex items-center justify-between mt-4 text-sm text-muted">
                <span>
                  Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
                </span>
                <div className="flex gap-2">
                  <button
                    className="btn btn-ghost"
                    disabled={offset === 0}
                    onClick={() =>
                      setSearchParams((prev) => {
                        prev.set('offset', String(Math.max(0, offset - limit)));
                        return prev;
                      })
                    }
                  >
                    ← Prev
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={offset + limit >= total}
                    onClick={() =>
                      setSearchParams((prev) => {
                        prev.set('offset', String(offset + limit));
                        return prev;
                      })
                    }
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {modalOpen && (
        <NewConversationModal
          onClose={() => setModalOpen(false)}
          onCreated={() => {}}
          onSubmit={(formData) => optimisticInsertMutation.mutate(formData)}
          isSubmitting={optimisticInsertMutation.isPending}
        />
      )}

      {/* SSE trackers — lives in the parent so it survives modal close */}
      {trackingIds.map((id) => (
        <SseTracker key={id} conversationId={id} onDone={() => handleSseDone(id)} />
      ))}
    </main>
  );
}

/** Invisible SSE tracker component */
function SseTracker({ conversationId, onDone }: { conversationId: number; onDone: () => void }) {
  useConversationEvents(conversationId, onDone);
  return null;
}

function ConversationRow({ conversation: c, onClick }: { conversation: ConversationListItem; onClick: () => void }) {
  const dateStr = c.happened_at
    ? new Date(c.happened_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : '—';

  return (
    <tr className="cursor-pointer hover:bg-page border-b border-hairline last:border-b-0" onClick={onClick}>
      <td className="px-3.5 py-3 text-muted whitespace-nowrap">{dateStr}</td>
      <td className="px-3.5 py-3">
        <div className="font-semibold">{c.company?.name || '—'}</div>
        <div className="text-muted text-xs">
          {c.contacts.map((ct) => `${ct.name}${ct.role ? `: ${ct.role}` : ''}`).join(', ') || '—'}
        </div>
      </td>
      <td className="px-3.5 py-3 max-w-[290px] overflow-hidden text-ellipsis whitespace-nowrap text-ink-2">
        {c.title}
      </td>
      <td className="px-3.5 py-3">
        <div className="flex gap-1.5 flex-wrap">
          {Object.entries(c.tag_counts).map(([tag, count]) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full border border-hairline bg-page text-xs text-ink-2"
            >
              {TAG_META[tag]?.emoji || '?'} {count}
            </span>
          ))}
        </div>
      </td>
      <td className="px-3.5 py-3">
        {c.status === 'ready' && c.critique_score != null ? (
          <span
            className={`inline-grid place-items-center w-[30px] h-[22px] rounded-md text-xs font-bold ${
              c.critique_score >= 7
                ? 'bg-[#e6f4e6] text-good-text'
                : c.critique_score >= 5
                ? 'bg-[#fdf3dc] text-[#8a5b00]'
                : 'bg-[#fbe7e7] text-crit'
            }`}
          >
            {c.critique_score}
          </span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="px-3.5 py-3">
        {c.status === 'ready' ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">✓ Ready</span>
        ) : c.status === 'failed' ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-crit">✕ Failed</span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
            {c.status}
          </span>
        )}
      </td>
    </tr>
  );
}

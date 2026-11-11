import { Fragment, useState, useCallback, useRef, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { api, ConversationListItem } from '../api';
import { NewConversationModal, NewConversationFormData } from '../components/NewConversationModal';
import { useConversationEvents } from '../hooks/useConversationEvents';
import { scoreBand, tagColor } from '../constants';
import { formatDate, formatDayHeading, formatNumber, isoDay } from '../utils/format';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { HeadlineCards } from '../components/HeadlineCards';
import { ConversationPreviewPanel } from '../components/ConversationPreviewPanel';
import { EmptyResults } from '../components/EmptyResults';
import { TagFilterBar } from '../components/TagFilterBar';
import { InboxPane } from './InboxPage';

export function LibraryPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [modalOpen, setModalOpen] = useState(false);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const rowRefs = useRef<Record<number, HTMLTableRowElement | null>>({});
  const closePreview = useCallback(() => {
    setPreviewId((current) => {
      if (current != null) setTimeout(() => rowRefs.current[current]?.focus(), 0);
      return null;
    });
  }, []);
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Tab state: 'conversations' (default) or 'inbox'
  const activeTab = searchParams.get('tab') === 'inbox' ? 'inbox' : 'conversations';

  // Track conversation IDs that need SSE monitoring (lifted from modal)
  const [trackingIds, setTrackingIds] = useState<number[]>([]);

  const activeTags = searchParams.getAll('tag');
  const companyId = searchParams.get('company_id') || undefined;
  const q = searchParams.get('q') || undefined;
  const dateFrom = searchParams.get('date_from') || undefined;
  const dateTo = searchParams.get('date_to') || undefined;
  const sort = searchParams.get('sort') || 'date_desc';
  // v0.5 U11: day headers only make sense when the list is in date order.
  const grouped = sort === 'date_desc' || sort === 'date_asc';
  const offset = parseInt(searchParams.get('offset') || '0', 10);
  const limit = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ['conversations', { tag: activeTags, company_id: companyId, q, date_from: dateFrom, date_to: dateTo, sort, offset }],
    queryFn: () =>
      api.listConversations({
        tag: activeTags,
        company_id: companyId ? Number(companyId) : undefined,
        q,
        date_from: dateFrom,
        date_to: dateTo,
        sort,
        offset,
        limit,
      }),
    // UX#10: 5s polling fallback when any rows are processing
    refetchInterval: trackingIds.length > 0 ? 5000 : false,
    enabled: activeTab === 'conversations',
  });

  // #15: Only show companies with at least one conversation
  const { data: companies } = useQuery({
    queryKey: ['companies', 'active'],
    queryFn: async () => {
      const res = await fetch('/api/companies?active_only=true', { credentials: 'include' });
      if (!res.ok) return [];
      return res.json();
    },
  });

  // Inbox pending count for the badge on the Inbox subtab
  const { data: inboxData } = useQuery({
    queryKey: ['inbox', 'pending_import'],
    queryFn: async () => {
      const res = await fetch('/api/inbox?status=pending_import', { credentials: 'include' });
      if (!res.ok) return { total: 0 };
      return res.json() as Promise<{ total: number }>;
    },
    staleTime: 30_000,
  });
  const pendingCount = inboxData?.total ?? 0;

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

  const conversations = data?.items ?? [];
  const total = data?.total ?? 0;

  // One group per calendar day, in the order the server returned them. A day cut by a page edge may
  // continue on the neighbouring page, so it reports how many are *shown* rather than a false total.
  const dayGroups: { key: string; heading: string; partial: boolean; items: ConversationListItem[] }[] = [];
  for (const c of conversations) {
    const day = isoDay(c.happened_at) ?? 'none';
    const last = dayGroups[dayGroups.length - 1];
    if (last && last.key === day) last.items.push(c);
    else dayGroups.push({ key: day, heading: formatDayHeading(day === 'none' ? null : day), partial: false, items: [c] });
  }
  if (dayGroups.length > 0) {
    if (offset > 0) dayGroups[0].partial = true;
    if (offset + conversations.length < total) dayGroups[dayGroups.length - 1].partial = true;
  }
  const isEmpty = !isLoading && conversations.length === 0;

  // #16: Active filter detection + clear all
  const hasActiveFilters = activeTags.length > 0 || !!companyId || !!q || !!dateFrom || !!dateTo;
  const clearAllFilters = useCallback(() => {
    setSearchInput('');
    setSearchParams((prev) => {
      prev.delete('tag');
      prev.delete('company_id');
      prev.delete('q');
      prev.delete('date_from');
      prev.delete('date_to');
      prev.delete('offset');
      return prev;
    });
  }, [setSearchParams]);

  const setTab = useCallback(
    (tab: 'conversations' | 'inbox') => {
      setSearchParams((prev) => {
        if (tab === 'inbox') prev.set('tab', 'inbox');
        else prev.delete('tab');
        return prev;
      });
    },
    [setSearchParams],
  );

  // T-UX10: Track ALL processing rows (including already-processing ones loaded on
  // page open), not only newly-created rows. Merge server-loaded processing IDs
  // into the tracking set so their status updates without manual reload.
  const processingStatuses = new Set(['processing', 'normalizing', 'tagging', 'analyzing']);
  useEffect(() => {
    const processingIds = conversations
      .filter((c) => processingStatuses.has(c.status) && c.id > 0)
      .map((c) => c.id);
    if (processingIds.length > 0) {
      setTrackingIds((prev) => {
        const merged = new Set([...prev, ...processingIds]);
        return Array.from(merged);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Callback for SSE completion — invalidate conversations list
  const handleSseDone = useCallback(
    (id: number) => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      setTrackingIds((prev) => prev.filter((tid) => tid !== id));
    },
    [queryClient],
  );

  const handleSseStage = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['conversations'] });
  }, [queryClient]);

  // Optimistic insert mutation — lives in the parent so it survives modal close
  const optimisticInsertMutation = useMutation({
    mutationFn: (variables: NewConversationFormData) =>
      api.createConversation(variables),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ['conversations'] });
      const queryKey = ['conversations', { tag: activeTags, company_id: companyId, q, date_from: dateFrom, date_to: dateTo, sort, offset }];
      const previous = queryClient.getQueryData(queryKey);
      const tempId = -(Date.now());
      const optimisticItem: ConversationListItem = {
        id: tempId,
        title: variables.title,
        happened_at: variables.happened_at || new Date().toISOString(),
        status: 'processing',
        interviewer: variables.interviewer || null,
        company: variables.company ? { id: 0, name: variables.company.name, domain: null, notes: null, conversation_count: 0, created_at: new Date().toISOString() } : null,
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
    <main className="p-6">
      <div>
        {/* Subtabs: Conversations | Inbox */}
        <div className="flex gap-0.5 border-b border-hairline mb-4" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === 'conversations'}
            className={`relative px-3.5 py-2 font-medium border-b-2 -mb-px text-sm ${
              activeTab === 'conversations' ? 'text-ink border-accent' : 'text-muted border-transparent cursor-pointer'
            }`}
            onClick={() => setTab('conversations')}
          >
            Conversations
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'inbox'}
            className={`relative px-3.5 py-2 font-medium border-b-2 -mb-px text-sm ${
              activeTab === 'inbox' ? 'text-ink border-accent' : 'text-muted border-transparent cursor-pointer'
            }`}
            onClick={() => setTab('inbox')}
          >
            Inbox
            {pendingCount > 0 && (
              <span className="ml-1.5 bg-crit text-white text-[10.5px] font-bold rounded-full px-1.5 py-px">{formatNumber(pendingCount)}</span>
            )}
          </button>
        </div>

        {/* Inbox tab content */}
        {activeTab === 'inbox' && <InboxPane />}

        {/* Conversations tab content */}
        {activeTab === 'conversations' && (
          <>
            {/* Header: title + corpus size + one primary action */}
            <div className="flex flex-wrap items-end gap-4 mb-4">
              <div className="flex flex-col gap-0.5">
                <h1 className="text-2xl font-bold text-ink">Library</h1>
                <span className="text-muted">
                  {isLoading ? (
                    <span role="status" aria-label="Loading conversations" className="inline-block w-3 h-3 align-middle border-2 border-hairline border-t-accent rounded-full animate-spin" />
                  ) : (
                    <><span>({formatNumber(total)})</span> conversation{total === 1 ? '' : 's'}</>
                  )}
                </span>
              </div>
              <button className="btn btn-primary ml-auto" onClick={() => setModalOpen(true)}>
                New conversation
              </button>
            </div>

            <HeadlineCards />

            {/* Saved views — preset filters (not persisted). */}
            <SavedViews activeTags={activeTags} companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} sort={sort} setSearchParams={setSearchParams} />


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
            {!modalOpen && companies?.map((c: { id: number; name: string }) => (
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
          <div className="flex items-center gap-1.5">
            <label htmlFor="filter-sort" className="text-xs text-muted">Sort</label>
            <select
              id="filter-sort"
              className="px-2 py-1.5 border border-hairline rounded-lg bg-page text-ink-2 text-sm"
              value={sort}
              onChange={(e) => {
                setSearchParams((prev) => {
                  if (e.target.value && e.target.value !== 'date_desc') prev.set('sort', e.target.value);
                  else prev.delete('sort');
                  prev.delete('offset');
                  return prev;
                });
              }}
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="score_desc">Score: high → low</option>
              <option value="score_asc">Score: low → high</option>
            </select>
          </div>
          {/* #16: Clear all button */}
          {hasActiveFilters && (
            <button
              className="px-2.5 py-1 text-xs font-medium text-crit hover:underline"
              onClick={clearAllFilters}
            >
              Clear all
            </button>
          )}
          {/* Tags get their own full-width line: top-10 chips, then the Core / Custom dropdowns. */}
          <TagFilterBar isActive={(key) => activeTags.includes(key)} onToggle={toggleTag} />
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

        {/* Empty state: an empty library, or filters that match nothing (not the same thing) */}
        {isEmpty && hasActiveFilters && (
          <EmptyResults
            filters={{
              q,
              tags: activeTags,
              companyName: companies?.find((c: { id: number; name: string }) => String(c.id) === companyId)?.name ?? (companyId ? `#${companyId}` : undefined),
              dateFrom,
              dateTo,
            }}
            onClear={clearAllFilters}
            onNew={() => setModalOpen(true)}
          />
        )}
        {isEmpty && !hasActiveFilters && (
          <div data-testid="empty-library" className="p-16 text-center text-muted bg-surface border border-hairline rounded-xl">
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
                  {!grouped && (
                    <th className="text-left text-xs font-semibold text-muted uppercase tracking-wider px-3.5 py-2.5 border-b border-hairline">
                      Date
                    </th>
                  )}
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
                {(grouped ? dayGroups : [{ key: '', heading: '', partial: false, items: conversations }]).map((g) => (
                  <Fragment key={g.key || 'all'}>
                    {grouped && (
                      <tr className="bg-page">
                        <th scope="row" colSpan={5} className="text-left text-xs font-semibold text-ink-2 px-3.5 py-2 border-b border-hairline">
                          {g.heading} · {g.items.length === 1 && !g.partial ? '1 call' : g.partial ? `${formatNumber(g.items.length)} shown` : `${formatNumber(g.items.length)} calls`}
                        </th>
                      </tr>
                    )}
                    {g.items.map((c) => (
                      <ConversationRow key={c.id} conversation={c} showDate={!grouped} selected={previewId === c.id}
                        rowRef={(el) => { rowRefs.current[c.id] = el; }} onClick={() => setPreviewId(c.id)} />
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            {total > limit && (
              <div className="flex items-center justify-between mt-4 text-sm text-muted">
                <span>
                  Showing {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + limit, total))} of {formatNumber(total)}
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
        </>
        )}
      </div>

      {previewId != null && !modalOpen && <ConversationPreviewPanel id={previewId} onClose={closePreview} />}

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
        <SseTracker
          key={id}
          conversationId={id}
          onStage={handleSseStage}
          onDone={() => handleSseDone(id)}
        />
      ))}
    </main>
  );
}

type ParamSetter = ReturnType<typeof useSearchParams>[1];

/**
 * Saved views = preset filter sets (NOT persisted per user — confirmed). Each
 * view rewrites the URL filter params; "All" clears them. Active view is derived
 * from the current params so a manual filter change deselects the preset.
 */
function SavedViews({ activeTags, companyId, dateFrom, dateTo, sort, setSearchParams }: {
  activeTags: string[]; companyId?: string; dateFrom?: string; dateTo?: string; sort: string; setSearchParams: ParamSetter;
}) {
  const apply = (mut: (p: URLSearchParams) => void) => {
    setSearchParams((prev) => {
      ['tag', 'company_id', 'date_from', 'date_to', 'sort', 'score_max', 'offset'].forEach((k) => prev.delete(k));
      mut(prev);
      return prev;
    });
  };

  const views: { label: string; on: boolean; apply: () => void; title?: string }[] = [
    { label: 'All', on: activeTags.length === 0 && !companyId && !dateFrom && !dateTo, apply: () => apply(() => {}) },
    { label: 'Needs review', on: sort === 'date_asc' && !!dateFrom === false && activeTags.length === 0 && !companyId, apply: () => apply((p) => p.set('sort', 'date_asc')) },
    { label: 'Low score (≤3)', on: sort === 'score_asc', apply: () => apply((p) => p.set('sort', 'score_asc')) },
    // The customer hurts AND is already paying to cope: at least one Pain and one Workaround in the
    // same call (both above their confidence floor - the API applies it to tag filters).
    { label: 'Strong pains', on: activeTags.length === 2 && activeTags.includes('pain') && activeTags.includes('workaround'),
      title: 'Calls with at least one pain and a workaround: the customer hurts and is already paying to cope, so they want it fixed.',
      apply: () => apply((p) => { p.append('tag', 'pain'); p.append('tag', 'workaround'); }) },
    { label: 'Partnerships', on: activeTags.length === 1 && activeTags[0] === 'person', apply: () => apply((p) => p.set('tag', 'person')) },
  ];

  return (
    <div className="flex flex-wrap gap-1 p-1 rounded-lg bg-sub self-start mb-4" role="tablist" aria-label="Saved views">
      {views.map((v) => (
        <button key={v.label} role="tab" aria-selected={v.on} onClick={v.apply} title={v.title}
          className={`h-8 px-3.5 rounded-md border-none font-semibold cursor-pointer ${v.on ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'}`}>
          {v.label}
        </button>
      ))}
    </div>
  );
}

/** Invisible SSE tracker component */
function SseTracker({
  conversationId,
  onDone,
  onStage,
}: {
  conversationId: number;
  onDone: () => void;
  onStage: (stage: 'normalizing' | 'tagging' | 'analyzing') => void;
}) {
  useConversationEvents(conversationId, onDone, onStage);
  return null;
}

function ConversationRow({ conversation: c, onClick, selected, rowRef, showDate }: {
  conversation: ConversationListItem; onClick: () => void; selected: boolean; rowRef: (el: HTMLTableRowElement | null) => void; showDate: boolean;
}) {
  const dateStr = formatDate(c.happened_at);

  return (
    <tr
      ref={rowRef}
      tabIndex={0}
      aria-selected={selected}
      className={`cursor-pointer hover:bg-page border-b border-hairline last:border-b-0 ${selected ? 'bg-accent-soft' : ''}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {showDate && <td className="px-3.5 py-3 text-muted whitespace-nowrap">{dateStr}</td>}
      <td className="px-3.5 py-3">
        <div className="font-semibold">
          {c.company ? (
            // The company name opens the company page; it must not also open the preview.
            <Link to={`/companies/${c.company.id}`} onClick={(e) => e.stopPropagation()} className="text-inherit hover:underline">
              {c.company.name}
            </Link>
          ) : '—'}
        </div>
        <div className="text-muted text-xs">
          {c.contacts.map((ct) => `${ct.name}${ct.role ? `: ${ct.role}` : ''}`).join(', ') || '—'}
        </div>
      </td>
      <td className="px-3.5 py-3 max-w-[290px] overflow-hidden text-ellipsis whitespace-nowrap text-ink-2">
        {c.title}
      </td>
      <td className="px-3.5 py-3">
        <SignalChips tagCounts={c.tag_counts} />
      </td>
      <td className="px-3.5 py-3">
        {c.status === 'ready' && c.critique_score != null ? (
          <span className={`score-pill ${scoreBand(c.critique_score).cls}`}>{c.critique_score}<span className="font-normal opacity-75">/10</span></span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="px-3.5 py-3">
        {c.status === 'ready' ? (
          // Ready is the normal state — no badge (mockup). Keep an SR-only marker.
          <span className="sr-only">Ready</span>
        ) : c.status === 'failed' ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-crit-text">Failed</span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
            {c.status === 'normalizing' ? 'Normalizing…' :
             c.status === 'tagging' ? 'Tagging…' :
             c.status === 'analyzing' ? 'Analyzing…' :
             'Processing…'}
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * Signal mix (v0.4): one 8px stacked bar (segment width = count share, colour =
 * tag colour) + the top 3 tags in words + "+N more". Full breakdown in the
 * bar's aria-label/title. Replaces the old emoji chip soup.
 */
const CONTEXT_TAGS = new Set(['context', 'person']);
/** Flattery is not a signal worth leading with: never named in a row's top 3, drawn last in the bar. */
const FLUFF_TAGS = new Set(['compliment']);

function SignalChips({ tagCounts }: { tagCounts: Record<string, number> }) {
  const tax = useTaxonomy();
  const entries = Object.entries(tagCounts).filter(([, n]) => n > 0);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (total === 0) return <span className="text-muted text-xs">—</span>;

  const byCount = [...entries].sort((a, b) => b[1] - a[1]);
  // Fluff goes to the end of the bar whatever its count, so it never reads as the main signal.
  const sorted = [...byCount.filter(([t]) => !FLUFF_TAGS.has(t)), ...byCount.filter(([t]) => FLUFF_TAGS.has(t))];
  const named = sorted.filter(([t]) => !CONTEXT_TAGS.has(t) && !FLUFF_TAGS.has(t));
  const top = named.slice(0, 3);
  const shownCount = top.reduce((s, [, n]) => s + n, 0);
  const rest = total - shownCount;
  const label = 'Signal mix: ' + sorted.map(([t, n]) => `${tax.name(t)} ${formatNumber(n)}`).join(', ');

  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <div className="flex h-2 rounded overflow-hidden bg-hairline" role="img" aria-label={label} title={label}>
        {sorted.map(([t, n]) => (
          <span key={t} data-tag={t} className="block h-full" style={{ width: `${(n / total * 100).toFixed(1)}%`, background: FLUFF_TAGS.has(t) ? '#d1d5db' : tagColor(t) }} />
        ))}
      </div>
      <span className="trunc text-xs text-muted" title={label}>
        {top.map(([t, n]) => `${tax.name(t)} ${formatNumber(n)}`).join(' · ')}{top.length > 0 && rest > 0 ? '  ' : ''}{rest > 0 ? `+${formatNumber(rest)} more` : ''}
      </span>
    </div>
  );
}

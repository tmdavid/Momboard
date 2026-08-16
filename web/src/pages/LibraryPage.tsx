import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ConversationListItem } from '../api';
import { NewConversationModal } from '../components/NewConversationModal';
import { TAG_META } from '../constants';

export function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [modalOpen, setModalOpen] = useState(false);
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const activeTags = searchParams.getAll('tag');
  const companyId = searchParams.get('company_id') || undefined;
  const q = searchParams.get('q') || undefined;
  const offset = parseInt(searchParams.get('offset') || '0', 10);
  const limit = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ['conversations', { tag: activeTags[0], company_id: companyId, q, offset }],
    queryFn: () =>
      api.listConversations({
        tag: activeTags[0],
        company_id: companyId ? Number(companyId) : undefined,
        q,
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
      const current = prev.get('tag');
      if (current === key) prev.delete('tag');
      else prev.set('tag', key);
      prev.delete('offset');
      return prev;
    });
  };

  const filterTags = Object.entries(TAG_META).slice(0, 6);

  const conversations = data?.items ?? [];
  const total = data?.total ?? 0;
  const isEmpty = !isLoading && conversations.length === 0;

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
          >
            <option value="">All companies</option>
            {companies?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
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
        {!isLoading && conversations.length > 0 && (
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
          onCreated={() => {
            setModalOpen(false);
            queryClient.invalidateQueries({ queryKey: ['conversations'] });
          }}
        />
      )}
    </main>
  );
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
          {c.contacts.map((ct) => `${ct.name}${ct.role ? ` · ${ct.role}` : ''}`).join(', ') || '—'}
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

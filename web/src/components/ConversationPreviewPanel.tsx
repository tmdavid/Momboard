import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { formatDate, formatNumber } from '../utils/format';
import { scoreBand } from '../constants';

/**
 * Right-hand preview of one call, opened from a Library row (v0.5 U5). It answers "is this the
 * call I want?" without leaving the list: summary, top pains, score, follow-ups, and how many tag
 * suggestions still wait for review. Escape (or Close) dismisses it.
 */
export function ConversationPreviewPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['conversation-preview', id],
    queryFn: () => api.conversationPreview(id),
  });
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toReview = data?.suggestions_to_review ?? 0;
  return (
    <aside
      aria-label="Conversation preview"
      className="fixed right-0 top-14 bottom-0 z-30 w-[380px] max-w-full bg-surface border-l border-hairline shadow-xl overflow-y-auto p-5 flex flex-col gap-4"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-lg font-bold text-ink">{data?.title ?? 'Conversation'}</h2>
          {data && (
            <p className="m-0 text-xs text-muted">
              {data.company_name ?? 'Unknown company'} · {formatDate(data.happened_at)}
            </p>
          )}
        </div>
        <button ref={closeRef} type="button" onClick={onClose} aria-label="Close preview"
          className="text-muted hover:text-ink bg-transparent border-none cursor-pointer text-lg leading-none">×</button>
      </div>

      {isLoading && <p className="m-0 text-sm text-muted">Loading…</p>}
      {isError && <p role="alert" className="m-0 text-sm text-crit">Couldn’t load the preview. You can still open the conversation.</p>}

      {data && (
        <>
          <section className="flex flex-col gap-1">
            <h3 className="m-0 text-xs font-semibold text-muted">Summary</h3>
            {data.summary
              ? <p className="m-0 text-sm text-ink-2">{data.summary}</p>
              : <p className="m-0 text-sm text-muted">No summary yet.</p>}
          </section>

          {data.top_pains && data.top_pains.length > 0 && (
            <section className="flex flex-col gap-1">
              <h3 className="m-0 text-xs font-semibold text-muted">Top pains</h3>
              <ul className="m-0 pl-4 text-sm text-ink-2">
                {data.top_pains.map((p) => <li key={p.pain}>{p.pain}</li>)}
              </ul>
            </section>
          )}

          <div className="flex items-center gap-3">
            {data.score != null && (
              <span className={`score-pill ${scoreBand(data.score).cls}`}>
                {data.score}<span className="font-normal opacity-75">/10</span>
              </span>
            )}
            {toReview > 0 && (
              <span className="text-xs text-warn-text bg-warn-soft px-2.5 py-1 rounded-full">
                {formatNumber(toReview)} tag suggestions to review
              </span>
            )}
          </div>

          {data.followups && data.followups.length > 0 && (
            <section className="flex flex-col gap-1">
              <h3 className="m-0 text-xs font-semibold text-muted">Follow-ups</h3>
              <ul className="m-0 pl-4 text-sm text-ink-2">
                {data.followups.map((f) => <li key={f}>{f}</li>)}
              </ul>
            </section>
          )}
        </>
      )}

      <Link to={`/conversations/${id}`} className="btn btn-primary self-start">Open conversation</Link>
    </aside>
  );
}

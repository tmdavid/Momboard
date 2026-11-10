import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, SynthesisResponse } from '../api';
import { tagEmoji, tagName } from '../constants';
import { friendlyModelName } from '../utils/modelName';

type SavedFilter = 'all' | 'saved';

function scopeLabel(scope: Record<string, unknown> | null | undefined): string {
  if (!scope) return 'All highlights';
  const tags = scope.tags;
  const parts: string[] = [];
  if (Array.isArray(tags) && tags.length > 0) {
    parts.push(tags.map((t) => `${tagEmoji(String(t))} ${tagName(String(t))}`).join(' + '));
  } else if (typeof scope.tag === 'string' && scope.tag) {
    parts.push(`${tagEmoji(scope.tag)} ${tagName(scope.tag)}`);
  }
  if (scope.company_id) parts.push(`company #${scope.company_id}`);
  return parts.length > 0 ? parts.join(' · ') : 'All highlights';
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function SummariesPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<SavedFilter>('all');

  const { data, isLoading } = useQuery({
    queryKey: ['syntheses', filter],
    queryFn: () => api.listSyntheses(filter === 'saved' ? { saved: true } : {}),
    // Poll so freshly-completed background syntheses appear without a manual refresh.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const anyPending = items.some((s) => !s.result && s.status !== 'error');
      return anyPending ? 3000 : false;
    },
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  const saveMutation = useMutation({
    mutationFn: ({ id, saved }: { id: number; saved: boolean }) => api.setSynthesisSaved(id, saved),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['syntheses'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteSynthesis(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['syntheses'] });
    },
  });

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto p-7">
        <div className="flex items-center gap-3 mb-4">
          <h1 className="text-xl font-bold tracking-tight">Summaries</h1>
          <span className="flex-1" />
          <div className="flex gap-1 text-[13px]" role="tablist" aria-label="Filter summaries">
            <button
              role="tab"
              aria-selected={filter === 'all'}
              className={`px-3 py-1 rounded-lg font-medium ${filter === 'all' ? 'bg-accent-soft text-accent font-semibold' : 'text-ink-2 hover:bg-page'}`}
              onClick={() => setFilter('all')}
            >
              All
            </button>
            <button
              role="tab"
              aria-selected={filter === 'saved'}
              className={`px-3 py-1 rounded-lg font-medium ${filter === 'saved' ? 'bg-accent-soft text-accent font-semibold' : 'text-ink-2 hover:bg-page'}`}
              onClick={() => setFilter('saved')}
            >
              Saved
            </button>
          </div>
        </div>

        <p className="text-[13px] text-muted mb-4">
          Cross-conversation syntheses run in the background. Kick one off from{' '}
          <span className="font-medium text-ink-2">Explore → ✨ Synthesize this view</span>, then keep the ones worth revisiting.
        </p>

        {isLoading && (
          <div className="flex justify-center py-12">
            <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
          </div>
        )}

        {!isLoading && items.length === 0 && (
          <div className="text-center text-muted py-12" data-testid="summaries-empty">
            {filter === 'saved' ? 'No saved summaries yet.' : 'No summaries yet — start one from Explore.'}
          </div>
        )}

        <div className="space-y-4">
          {items.map((s) => (
            <SummaryCard
              key={s.id}
              synthesis={s}
              onSaveToggle={(saved) => saveMutation.mutate({ id: s.id, saved })}
              onDiscard={() => deleteMutation.mutate(s.id)}
              busy={saveMutation.isPending || deleteMutation.isPending}
            />
          ))}
        </div>
      </div>
    </main>
  );
}

function SummaryCard({
  synthesis,
  onSaveToggle,
  onDiscard,
  busy,
}: {
  synthesis: SynthesisResponse;
  onSaveToggle: (saved: boolean) => void;
  onDiscard: () => void;
  busy: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const s = synthesis;
  const isDone = !!s.result;
  const isError = s.status === 'error';

  const toggle = (i: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <div
      className="bg-surface border border-hairline rounded-[14px] p-5"
      data-testid="summary-card"
      data-synthesis-id={s.id}
    >
      <div className="flex items-start gap-3 mb-3">
        <div className="flex-1">
          <h2 className="text-[15px] font-semibold">{scopeLabel(s.input_scope)}</h2>
          <div className="text-xs text-muted mt-0.5">
            {formatDate(s.created_at)}
            {s.model ? ` · ${friendlyModelName(s.model)}` : ''}
          </div>
        </div>

        {/* Status chip */}
        {!isDone && !isError && (
          <span className="inline-flex items-center gap-1.5 text-xs text-accent bg-accent-soft rounded-full px-2.5 py-1" role="status">
            <span className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" aria-hidden="true" />
            Processing…
          </span>
        )}
        {isError && (
          <span className="text-xs text-red-600 bg-red-50 rounded-full px-2.5 py-1">Failed</span>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          {isDone && (
            <button
              className={`px-2.5 py-1 text-xs font-semibold rounded-lg border ${
                s.saved
                  ? 'bg-accent text-white border-accent'
                  : 'border-hairline text-ink-2 hover:border-accent hover:text-accent'
              }`}
              disabled={busy}
              aria-pressed={s.saved}
              onClick={() => onSaveToggle(!s.saved)}
            >
              {s.saved ? '★ Saved' : '☆ Save'}
            </button>
          )}
          <button
            className="px-2.5 py-1 text-xs font-medium rounded-lg text-crit hover:bg-red-50"
            disabled={busy}
            onClick={onDiscard}
            aria-label="Discard summary"
          >
            Discard
          </button>
        </div>
      </div>

      {isError && (
        <p className="text-[13px] text-ink-2">{s.error || 'Synthesis failed. Try running it again from Explore.'}</p>
      )}

      {isDone && s.result && (
        <div>
          {s.result.themes?.map((theme, i) => (
            <div key={i} className="border-l-[3px] border-accent px-3.5 py-2.5 bg-page rounded-r-xl mb-2.5">
              <b className="block mb-0.5">
                {i + 1}. {theme.name}
              </b>
              <p className="text-[13px] text-ink-2">{theme.summary}</p>
              {(theme.evidence_highlight_ids?.length ?? 0) > 0 && (
                <button
                  className="text-xs text-accent cursor-pointer mt-1 inline-block bg-transparent border-none p-0"
                  onClick={() => toggle(i)}
                  aria-expanded={expanded.has(i)}
                >
                  {expanded.has(i) ? '▾' : '▸'} {theme.evidence_highlight_ids.length} supporting quotes
                </button>
              )}
              {expanded.has(i) && (
                <div className="mt-2 pl-2 border-l-2 border-hairline text-xs text-muted">
                  Highlight IDs: {theme.evidence_highlight_ids.join(', ')}
                </div>
              )}
            </div>
          ))}

          {s.result.contradictions?.map((c, i) => (
            <div key={i} className="border-l-[3px] border-warn px-3.5 py-2.5 bg-page rounded-r-xl mb-2.5">
              <b className="block mb-0.5">⚠ Contradiction</b>
              <p className="text-[13px] text-ink-2">{c.description}</p>
            </div>
          ))}

          {s.result.validate_next && s.result.validate_next.length > 0 && (
            <div className="bg-[#e6f4e6] rounded-xl px-3.5 py-2.5 text-[13px]">
              <b className="text-good-text">Validate next:</b> {s.result.validate_next.join(' ')}
            </div>
          )}

          {(!s.result.themes || s.result.themes.length === 0) &&
            (!s.result.contradictions || s.result.contradictions.length === 0) && (
              <p className="text-[13px] text-muted">No themes were extracted for this view.</p>
            )}
        </div>
      )}
    </div>
  );
}

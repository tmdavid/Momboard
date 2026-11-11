import { useMemo, useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, SynthesisResponse } from '../api';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { formatDateTime } from '../utils/format';

type SavedFilter = 'all' | 'saved';

function scopeLabel(
  scope: Record<string, unknown> | null | undefined,
  emoji: (k: string) => string,
  name: (k: string) => string,
): string {
  if (!scope) return 'All highlights';
  const tags = scope.tags;
  const parts: string[] = [];
  if (Array.isArray(tags) && tags.length > 0) {
    parts.push(tags.map((t) => `${emoji(String(t))} ${name(String(t))}`).join(' + '));
  } else if (typeof scope.tag === 'string' && scope.tag) {
    parts.push(`${emoji(scope.tag)} ${name(scope.tag)}`);
  }
  if (scope.company_id) parts.push(`company #${scope.company_id}`);
  return parts.length > 0 ? parts.join(' · ') : 'All highlights';
}

function scopeTags(scope: Record<string, unknown> | null | undefined): string[] {
  if (!scope) return [];
  if (Array.isArray(scope.tags)) return scope.tags.map(String);
  if (typeof scope.tag === 'string' && scope.tag) return [scope.tag];
  return [];
}

function formatDate(iso: string): string {
  return formatDateTime(iso);
}

export function SummariesPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<SavedFilter>('all');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const tax = useTaxonomy();

  const { data, isLoading } = useQuery({
    queryKey: ['syntheses', filter],
    queryFn: () => api.listSyntheses(filter === 'saved' ? { saved: true } : {}),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const anyPending = items.some((s) => !s.result && s.status !== 'error');
      return anyPending ? 3000 : false;
    },
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  // Default-select the first item when the list loads / changes.
  useEffect(() => {
    if (items.length === 0) { setSelectedId(null); return; }
    if (selectedId == null || !items.some((s) => s.id === selectedId)) {
      setSelectedId(items[0].id);
    }
  }, [items, selectedId]);

  const selected = items.find((s) => s.id === selectedId) ?? null;

  const saveMutation = useMutation({
    mutationFn: ({ id, saved }: { id: number; saved: boolean }) => api.setSynthesisSaved(id, saved),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['syntheses'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteSynthesis(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['syntheses'] }),
  });

  return (
    <main className="p-6 flex flex-wrap gap-5 items-start">
      {/* Master list */}
      <section aria-label="All syntheses" className="flex-[1_1_280px] max-w-[340px] flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-2xl font-bold text-ink">Summaries</h1>
          <span className="text-muted">Syntheses you ran from Explore</span>
        </div>
        <div className="flex gap-0.5 p-0.5 rounded-lg bg-sub self-start" role="tablist" aria-label="Filter">
          {(['all', 'saved'] as const).map((f) => (
            <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
              className={`h-[30px] px-3 rounded-md border-none font-semibold capitalize cursor-pointer ${filter === f ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'}`}>
              {f === 'all' ? 'All' : 'Saved'}
            </button>
          ))}
        </div>

        {isLoading && <div className="flex justify-center py-8"><div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" /></div>}
        {!isLoading && items.length === 0 && (
          <div className="text-muted py-8" data-testid="summaries-empty">
            {filter === 'saved' ? 'No saved summaries yet.' : 'No summaries yet — start one from Explore.'}
          </div>
        )}

        {items.map((s) => {
          const running = !s.result && s.status !== 'error';
          const on = s.id === selectedId;
          return (
            <button key={s.id} onClick={() => setSelectedId(s.id)} data-testid="summary-card" data-synthesis-id={s.id}
              className={`text-left flex flex-col gap-1 p-3 rounded-[10px] bg-surface border cursor-pointer ${on ? 'border-accent shadow-[0_0_0_3px_#d6e0fb]' : 'border-hairline'}`}>
              <div className="flex items-center gap-2">
                <span className="trunc font-semibold text-ink">{scopeLabel(s.input_scope, tax.emoji, tax.name)}</span>
                {s.saved && <span className="ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-pill bg-accent-soft text-accent-ink">Saved</span>}
              </div>
              <span className="text-xs text-muted">
                {formatDate(s.created_at)}{s.result?.themes ? ` · ${s.result.themes.length} themes` : ''}
              </span>
              {running && (
                <div className="flex items-center gap-2"><div className="flex-1 h-1 rounded bg-sub overflow-hidden"><span className="block w-3/5 h-full bg-accent" /></div><span className="text-xs text-muted">Running</span></div>
              )}
            </button>
          );
        })}
      </section>

      {/* Detail */}
      <article className="flex-[999_1_520px] min-w-0 bg-surface border border-hairline rounded-xl flex flex-col">
        {!selected ? (
          <div className="p-6 text-muted">Select a summary to view its themes.</div>
        ) : (
          <SummaryDetail
            synthesis={selected}
            onSaveToggle={(saved) => saveMutation.mutate({ id: selected.id, saved })}
            onDiscard={() => deleteMutation.mutate(selected.id)}
            busy={saveMutation.isPending || deleteMutation.isPending}
          />
        )}
      </article>
    </main>
  );
}

function SummaryDetail({ synthesis, onSaveToggle, onDiscard, busy }: {
  synthesis: SynthesisResponse;
  onSaveToggle: (saved: boolean) => void;
  onDiscard: () => void;
  busy: boolean;
}) {
  const tax = useTaxonomy();
  const s = synthesis;
  const isDone = !!s.result;
  const isError = s.status === 'error';
  const tags = scopeTags(s.input_scope);

  return (
    <>
      <header className="p-5 border-b border-hairline flex flex-wrap gap-3 items-start">
        <div className="flex flex-col gap-1.5 min-w-0">
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((t) => (
                <span key={t} className="text-xs font-semibold px-2.5 py-0.5 rounded-pill bg-sub text-ink-2">{tax.emoji(t)} {tax.name(t)}</span>
              ))}
            </div>
          )}
          <h2 className="text-lg font-bold text-ink">{scopeLabel(s.input_scope, tax.emoji, tax.name)}</h2>
          {/* No raw model ARN here (per redesign); just date + counts. */}
          <span className="text-xs text-muted">
            {formatDate(s.created_at)}
            {s.result?.themes ? ` · ${s.result.themes.length} themes` : ''}
          </span>
        </div>
        {isDone && (
          <div className="ml-auto flex gap-2">
            <button onClick={onDiscard} disabled={busy} className="h-9 px-3.5 rounded-lg border border-hairline bg-surface text-crit-text font-semibold cursor-pointer disabled:opacity-50" aria-label="Discard summary">Discard</button>
            <button onClick={() => onSaveToggle(!s.saved)} disabled={busy} aria-pressed={s.saved} className="h-9 px-3.5 rounded-lg border-none bg-accent text-white font-semibold cursor-pointer disabled:opacity-50">{s.saved ? 'Saved' : 'Save'}</button>
          </div>
        )}
      </header>

      <div className="p-5 pt-2 flex flex-col">
        {!isDone && !isError && <p className="text-[13px] text-muted py-4">Running…</p>}
        {isError && <p className="text-[13px] text-ink-2 py-4">{s.error || 'Synthesis failed. Try running it again from Explore.'}</p>}

        {isDone && s.result && (
          <>
            {s.result.themes?.map((theme, i) => (
              <div key={i} className="grid gap-3 py-4 border-b border-sub" style={{ gridTemplateColumns: '32px minmax(0,1fr)' }}>
                <span className="w-7 h-7 rounded-lg bg-sub text-ink font-bold grid place-items-center">{i + 1}</span>
                <div className="flex flex-col gap-1.5 min-w-0">
                  <h3 className="text-[15px] font-semibold text-ink">{theme.name}</h3>
                  <p className="m-0 text-ink-2">{theme.summary}</p>
                  {(theme.evidence_highlight_ids?.length ?? 0) > 0 && (
                    <details>
                      <summary className="cursor-pointer text-[13px] text-accent font-semibold">{theme.evidence_highlight_ids.length} supporting quotes</summary>
                      <div className="mt-2 text-xs text-muted">Highlight IDs: {theme.evidence_highlight_ids.join(', ')}</div>
                    </details>
                  )}
                </div>
              </div>
            ))}

            {s.result.contradictions?.map((c, i) => (
              <div key={`c${i}`} className="py-4 border-b border-sub">
                <b className="block mb-0.5 text-warn-text">Contradiction</b>
                <p className="m-0 text-ink-2 text-[13px]">{c.description}</p>
              </div>
            ))}

            {s.result.validate_next && s.result.validate_next.length > 0 && (
              <div className="mt-4 px-4 py-3.5 rounded-[10px] bg-[#f8fafc] border border-hairline flex flex-col gap-1">
                <span className="text-xs font-semibold text-muted">Validate next</span>
                <span>{s.result.validate_next.join(' ')}</span>
              </div>
            )}

            {(!s.result.themes || s.result.themes.length === 0) && (!s.result.contradictions || s.result.contradictions.length === 0) && (
              <p className="text-[13px] text-muted py-4">No themes were extracted for this view.</p>
            )}
          </>
        )}
      </div>
    </>
  );
}

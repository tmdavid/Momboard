/**
 * Pieces of the Decisions page: teammate names, the edit form, the "add a quote"
 * picker, and the linked-hypothesis box (with the archived warning).
 */
import { useState, FormEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { BAND_LABEL, BandKey } from '../utils/bands';

export async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Request failed');
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

// ─── Teammates (owner names) ───

export function useTeamUsers() {
  const { data } = useQuery({
    queryKey: ['team-users'],
    queryFn: () => jsonFetch<{ items: { id: number; name: string }[] }>('/api/users'),
    staleTime: 5 * 60_000,
  });
  const users = data?.items ?? [];
  const nameOf = (id: number | null | undefined) =>
    id == null ? null : (users.find((u) => u.id === id)?.name ?? null);
  return { users, nameOf };
}

// ─── Edit form ───

export interface EditableDecision {
  id: number;
  title: string;
  rationale_md: string;
  owner_id: number | null;
  area: string | null;
}

export function EditDecisionForm({
  decision,
  onDone,
}: {
  decision: EditableDecision;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const { users } = useTeamUsers();
  const [title, setTitle] = useState(decision.title);
  const [rationale, setRationale] = useState(decision.rationale_md);
  const [ownerId, setOwnerId] = useState(decision.owner_id != null ? String(decision.owner_id) : '');
  const [area, setArea] = useState(decision.area ?? '');

  const save = useMutation({
    mutationFn: () =>
      jsonFetch(`/api/decisions/${decision.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: title.trim(),
          rationale_md: rationale,
          owner_id: ownerId ? parseInt(ownerId, 10) : null,
          area: area.trim() || null,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['decisions'] });
      onDone();
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim() && rationale.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} aria-label="Edit decision" className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)}
          className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink" />
      </label>
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Rationale
        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={3}
          className="px-3 py-2 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink" />
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
          Owner
          <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
            className="h-9 px-2 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink">
            <option value="">No owner</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
          Area
          <input value={area} onChange={(e) => setArea(e.target.value)} placeholder="e.g. Pricing"
            className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink" />
        </label>
      </div>
      {save.isError && <p role="alert" className="text-crit text-sm">{(save.error as Error).message}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={save.isPending || !title.trim() || !rationale.trim()}
          className="btn btn-sm btn-primary disabled:opacity-50">Save changes</button>
        <button type="button" onClick={onDone} className="btn btn-sm btn-ghost">Cancel edit</button>
      </div>
    </form>
  );
}

// ─── Add a quote to an existing decision ───

export function AddQuote({
  decisionId,
  citedHighlightIds,
}: {
  decisionId: number;
  citedHighlightIds: Set<number>;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const term = q.trim();

  const { data, isFetching } = useQuery({
    queryKey: ['decision-quote-search', term],
    queryFn: () => api.listHighlights({ q: term, status: 'accepted', limit: 8 }),
    enabled: open && term.length >= 3,
  });
  const results = (data?.items ?? []).filter((h) => !citedHighlightIds.has(h.id));

  const add = useMutation({
    mutationFn: (highlightId: number) =>
      jsonFetch(`/api/decisions/${decisionId}/evidence/${highlightId}`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['decisions'] }),
  });

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="self-start text-sm font-semibold text-accent bg-transparent border-none p-0 cursor-pointer hover:underline">
        Add a quote
      </button>
    );
  }
  return (
    <section aria-label="Add a quote" className="flex flex-col gap-2 border-t border-hairline pt-3">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-muted">Add a quote</span>
        <button type="button" onClick={() => setOpen(false)}
          className="ml-auto text-xs text-muted hover:text-ink bg-transparent border-none cursor-pointer">Close search</button>
      </div>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search quotes to cite"
        placeholder="Search what customers said…"
        className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm" />
      {add.isError && <p role="alert" className="text-crit text-xs">{(add.error as Error).message}</p>}
      {term.length >= 3 && !isFetching && results.length === 0 && (
        <p className="text-sm text-muted">No matching quotes.</p>
      )}
      <ul className="flex flex-col gap-2 m-0 p-0 list-none">
        {results.map((h) => (
          <li key={h.id} className="flex items-start gap-2 text-sm border border-hairline rounded-lg p-2">
            <div className="flex-1 min-w-0">
              <span className="italic">“{h.quote}”</span>
              <span className="block text-xs text-muted">
                {[h.company_name, h.contact_names?.[0]].filter(Boolean).join(' · ') || 'Unknown source'}
              </span>
            </div>
            <button type="button" disabled={add.isPending} aria-label={`Cite: ${h.quote}`}
              onClick={() => add.mutate(h.id)}
              className="text-xs font-semibold px-2.5 py-1 rounded bg-accent-soft text-accent">Cite</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Linked hypothesis (+ archived warning) ───

export function LinkedHypothesisBox({
  hypothesis,
}: {
  hypothesis: { id: number; statement: string; band: string; archived?: boolean };
}) {
  const band = BAND_LABEL[hypothesis.band as BandKey] ?? hypothesis.band;
  return (
    <div data-testid="linked-hypothesis-box" className="flex flex-col gap-1.5 px-3 py-2.5 rounded-lg border border-hairline bg-page">
      <span className="text-xs font-semibold text-muted">Based on hypothesis</span>
      <span className="text-ink">
        {hypothesis.statement}{' '}
        <span className="text-xs font-semibold px-2 py-0.5 rounded-pill bg-sub text-ink-2 align-middle">{band}</span>
      </span>
      {hypothesis.archived && (
        <p role="alert" className="m-0 px-2.5 py-1.5 rounded-md bg-warn-soft text-[#93370d] text-[13px]">
          <strong>This belief has been archived.</strong> Re-check whether the decision still stands, or restore
          the hypothesis.
        </p>
      )}
      <Link to="/hypotheses" className="text-xs self-start">Open Hypotheses</Link>
    </div>
  );
}

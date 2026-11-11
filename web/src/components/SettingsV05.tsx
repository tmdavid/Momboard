/**
 * v0.5 Settings pieces: "Your company", the per-tag tagging-details editor, and retag progress.
 * Kept out of SettingsPage.tsx so that file stays about layout.
 */
import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, RetagResult, Tag } from '../api';
import { formatNumber } from '../utils/format';

const splitList = (value: string): string[] =>
  value.split(',').map((v) => v.trim()).filter(Boolean);

const errorText = (e: unknown) => (e instanceof Error && e.message ? e.message : 'Something went wrong.');

// ─── Your company ───

export function CompanyProfileCard({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['company-profile'], queryFn: () => api.getCompanyProfile() });
  const [name, setName] = useState('');
  const [aliases, setAliases] = useState('');
  const [domains, setDomains] = useState('');
  const [saved, setSaved] = useState(false);
  const [filled, setFilled] = useState(false);

  // Fill the form from the server exactly once. Re-filling on every refetch would overwrite what
  // someone is typing, and the fields stay disabled until this has happened.
  useEffect(() => {
    if (!data || filled) return;
    setName(data.name);
    setAliases(data.aliases.join(', '));
    setDomains(data.email_domains.join(', '));
    setFilled(true);
  }, [data, filled]);
  const editable = canManage && filled;

  const save = useMutation({
    mutationFn: () =>
      api.saveCompanyProfile({ name: name.trim(), aliases: splitList(aliases), email_domains: splitList(domains) }),
    onSuccess: (profile) => {
      queryClient.setQueryData(['company-profile'], profile);
      setSaved(true);
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate();
  };
  const field = 'border border-hairline rounded-lg px-2.5 py-2 text-sm bg-surface disabled:bg-sub disabled:text-muted';

  return (
    <div role="region" aria-label="Your company" id="company" className="bg-surface border border-hairline rounded-xl p-5 flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="text-base font-semibold text-ink">Your company</h2>
        <span className="text-muted text-sm">
          The company that runs these conversations. Every AI prompt is told to spell it exactly, and
          people from it are treated as your team, not as customers, so their lines are never tagged as
          customer evidence.
        </span>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
          Company name
          <input value={name} disabled={!editable} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme Corp" className={`${field} font-normal text-ink`} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
          Aliases
          <input value={aliases} disabled={!editable} onChange={(e) => setAliases(e.target.value)} placeholder="Other names it goes by, separated by commas" className={`${field} font-normal text-ink`} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
          Email domains
          <input value={domains} disabled={!editable} onChange={(e) => setDomains(e.target.value)} placeholder="e.g. acme.io, sales.acme.io" className={`${field} font-normal text-ink`} />
        </label>
        {canManage && (
          <div className="flex items-center gap-3">
            <button type="submit" disabled={save.isPending} className="btn btn-sm btn-primary disabled:opacity-50">
              {save.isPending ? 'Saving…' : 'Save company'}
            </button>
            {saved && <span role="status" className="text-sm text-good-text">Saved.</span>}
          </div>
        )}
        {save.isError && <p role="alert" className="text-sm text-crit">{errorText(save.error)}</p>}
        {!canManage && <p className="text-xs text-muted">Only an admin can change this.</p>}
      </form>
    </div>
  );
}

// ─── Per-tag tagging details ───

export function TagDetailsEditor({ tag }: { tag: Tag }) {
  const queryClient = useQueryClient();
  const [floor, setFloor] = useState(String(tag.min_confidence ?? 0.5));
  const [hint, setHint] = useState(tag.negative_hint ?? '');
  const [example, setExample] = useState(tag.example ?? '');

  const parsed = Number(floor);
  const floorOk = floor.trim() !== '' && Number.isFinite(parsed) && parsed >= 0 && parsed <= 1;

  const save = useMutation({
    mutationFn: () =>
      api.updateTag(tag.key, {
        min_confidence: parsed,
        negative_hint: hint.trim() || null,
        example: example.trim() || null,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<Tag[]>(['tags'], (current = []) => current.map((t) => (t.key === updated.key ? updated : t)));
    },
  });
  const input = 'border border-hairline rounded-lg px-2.5 py-2 text-sm bg-surface font-normal text-ink';

  return (
    <div role="group" aria-label={`Tagging details for ${tag.name}`} className="flex flex-col gap-2.5 p-3 bg-page rounded-lg border border-hairline">
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted max-w-[220px]">
        Confidence floor
        <input type="number" step="0.05" value={floor} onChange={(e) => setFloor(e.target.value)} className={input} aria-invalid={!floorOk} />
        <span className={`font-normal ${floorOk ? '' : 'text-crit'}`}>
          {floorOk
            ? 'Suggestions below this stay in conversation review but are left out of Library, Explore, Insights and hypothesis matching.'
            : 'Enter a number between 0 and 1.'}
        </span>
      </label>
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Don't tag when
        <input value={hint} onChange={(e) => setHint(e.target.value)} placeholder="e.g. the rep is speaking, or it is only a greeting" className={input} maxLength={1000} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Example
        <input value={example} onChange={(e) => setExample(e.target.value)} placeholder="One quote that is a good example of this tag" className={input} maxLength={1000} />
      </label>
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => save.mutate()} disabled={!floorOk || save.isPending} className="btn btn-sm btn-primary disabled:opacity-50">
          {save.isPending ? 'Saving…' : 'Save tag details'}
        </button>
        {save.isSuccess && <span role="status" className="text-sm text-good-text">Saved.</span>}
        {save.isError && <span role="alert" className="text-sm text-crit">{errorText(save.error)}</span>}
      </div>
    </div>
  );
}

// ─── Retag progress ───

const BATCH = 100;

export function RetagProgressCard({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ['taxonomy-status'],
    queryFn: () => api.taxonomyStatus(),
    // Keep the numbers moving while a batch is being worked through.
    refetchInterval: (query) => ((query.state.data?.in_progress ?? 0) > 0 ? 10_000 : false),
  });
  const [preview, setPreview] = useState<RetagResult | null>(null);
  const [done, setDone] = useState<RetagResult | null>(null);

  const dryRun = useMutation({ mutationFn: () => api.retagBatch(BATCH, true), onSuccess: (r) => { setDone(null); setPreview(r); } });
  const queue = useMutation({
    mutationFn: () => api.retagBatch(BATCH, false),
    onSuccess: (r) => {
      setPreview(null);
      setDone(r);
      queryClient.invalidateQueries({ queryKey: ['taxonomy-status'] });
    },
  });

  if (!status) return <div role="region" aria-label="Retag progress" id="retag" className="bg-surface border border-hairline rounded-xl p-5 text-sm text-muted">Loading…</div>;

  const pct = status.total_calls ? Math.round((status.calls_on_current / status.total_calls) * 100) : 100;
  return (
    <div role="region" aria-label="Retag progress" id="retag" className="bg-surface border border-hairline rounded-xl p-5 flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="text-base font-semibold text-ink">Retag progress</h2>
        <span className="text-muted text-sm">
          Tags added or improved later only reach calls once those calls are retagged.
        </span>
      </div>
      <p className="m-0 text-ink">
        <strong>{formatNumber(status.calls_on_current)} of {formatNumber(status.total_calls)} calls</strong> are on the current taxonomy.
      </p>
      <div className="h-2 rounded-full bg-sub overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Calls on the current taxonomy">
        <span className="block h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      {status.eligible > 0 ? (
        <p className="m-0 text-sm text-ink-2">
          {formatNumber(status.eligible)} waiting
          {status.in_progress > 0 && <> · {formatNumber(status.in_progress)} being processed now</>}
          {status.seconds_per_call != null && status.estimated_minutes != null && (
            <> · measured {Math.round(status.seconds_per_call)}s per call, about {formatNumber(status.estimated_minutes)} min for the rest</>
          )}
        </p>
      ) : (
        <p className="m-0 text-sm text-good-text">Every call is on the current taxonomy.</p>
      )}
      {status.in_progress > 0 && status.eligible === 0 && (
        <p className="m-0 text-sm text-ink-2">{formatNumber(status.in_progress)} being processed now.</p>
      )}
      {status.tags.length > 0 && (
        <ul className="m-0 pl-4 text-sm text-ink-2">
          {status.tags.map((t) => (
            <li key={t.key}>{t.name} is missing from {formatNumber(t.stale_calls)} of {formatNumber(t.total_calls)} calls</li>
          ))}
        </ul>
      )}

      {canManage && status.eligible > 0 && !preview && (
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => dryRun.mutate()} disabled={dryRun.isPending} className="btn btn-sm btn-primary disabled:opacity-50">
            Retag the next {BATCH}…
          </button>
          <span className="text-xs text-muted">Start small, check the results, then continue. Newest calls first.</span>
        </div>
      )}
      {preview && (
        <div className="flex flex-col gap-2 p-3 rounded-lg bg-page border border-hairline">
          <p className="m-0 text-sm text-ink">
            This will queue {formatNumber(preview.would_queue)} calls for retagging. Each call uses LLM tokens, so this costs money.
          </p>
          {preview.protected_highlights > 0 && (
            <p className="m-0 text-xs text-muted">
              {formatNumber(preview.protected_highlights)} suggestions will be kept because a decision or a confirmed belief depends on them.
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={() => queue.mutate()} disabled={queue.isPending} className="btn btn-sm btn-primary disabled:opacity-50">Confirm and queue</button>
            <button type="button" onClick={() => setPreview(null)} className="btn btn-sm btn-ghost">Cancel</button>
          </div>
        </div>
      )}
      {done && (
        <p role="status" className="m-0 text-sm text-good-text">
          Queued {formatNumber(done.queued)} calls. {formatNumber(done.remaining)} still waiting.
        </p>
      )}
      {(dryRun.isError || queue.isError) && <p role="alert" className="m-0 text-sm text-crit">{errorText(dryRun.error ?? queue.error)}</p>}
    </div>
  );
}

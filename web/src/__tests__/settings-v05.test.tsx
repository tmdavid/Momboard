/** v0.5: Settings gets "Your company", per-tag tagging fields, and the retag rollout card. */
import { describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { SettingsPage } from '../pages/SettingsPage';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/settings']}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

const status = (admin: boolean) => ({
  llm: { backend: 'openai', model_normalizer: 'm', model_tagger: 'm', model_analyst: 'm', model_synthesizer: 'm',
    api_key_configured: true, api_key_hint: 'sk-•••', credential_ready: true, credential_label: 'sk-•••', single_model: true },
  vexa: { configured: false, detail: 'x' }, gdrive: { configured: false, detail: 'x' }, slack: { configured: false, detail: 'x' },
  digest: { slack_configured: false, schedule: 'x' }, taxonomy_count: 2, active_company_count: 1, can_manage_taxonomy: admin,
});

const tag = (over: Record<string, unknown> = {}) => ({
  key: 'pain', emoji: '⚡', name: 'Pain', description: 'A real problem', signal_strength: 'strong', sort_order: 1,
  is_active: true, origin: 'core', category: null, min_confidence: 0.5, negative_hint: null, example: null, added_in_version: 0, ...over,
});

const taxStatus = (over: Record<string, unknown> = {}) => ({
  version: 3, total_calls: 1000, calls_on_current: 312, tags: [{ key: 'impersonation', name: 'Impersonation', added_in_version: 3, total_calls: 1000, stale_calls: 688 }],
  eligible: 688, in_progress: 0, seconds_per_call: 30, estimated_minutes: 172, ...over,
});

function setup(opts: { admin?: boolean; company?: Record<string, unknown>; tags?: unknown[]; tax?: Record<string, unknown> } = {}) {
  const admin = opts.admin ?? true;
  const calls: Record<string, unknown[]> = { company: [], tag: [], retag: [] };
  server.use(
    http.get('/api/settings/status', () => HttpResponse.json(status(admin))),
    http.get('/api/settings/company', () => HttpResponse.json(opts.company ?? { name: '', aliases: [], email_domains: [], configured: false })),
    http.put('/api/settings/company', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.company.push(body);
      return HttpResponse.json({ ...body, configured: !!body.name });
    }),
    http.get('/api/tags', () => HttpResponse.json(opts.tags ?? [tag()])),
    http.patch('/api/tags/:key', async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.tag.push({ key: params.key, ...body });
      return HttpResponse.json(tag({ key: params.key, ...body }));
    }),
    http.get('/api/taxonomy/status', () => HttpResponse.json(taxStatus(opts.tax))),
    http.post('/api/taxonomy/retag', async ({ request }) => {
      const body = (await request.json()) as { limit: number; dry_run: boolean };
      calls.retag.push(body);
      return HttpResponse.json(body.dry_run
        ? { queued: 0, would_queue: 100, remaining: 688, ids: [], protected_highlights: 4, taxonomy_version: 3 }
        : { queued: 100, would_queue: 100, remaining: 588, ids: [], protected_highlights: 4, taxonomy_version: 3 });
    }),
  );
  return calls;
}

describe('Your company', () => {
  it('shows the saved profile and explains what it is used for', async () => {
    setup({ company: { name: 'Acme Corp', aliases: ['Acme', 'AcmeCo'], email_domains: ['acme.io'], configured: true } });
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /your company/i });
    await waitFor(() => expect(within(card).getByLabelText(/company name/i)).toHaveValue('Acme Corp'));
    expect(within(card).getByLabelText(/aliases/i)).toHaveValue('Acme, AcmeCo');
    expect(within(card).getByLabelText(/email domains/i)).toHaveValue('acme.io');
    expect(within(card).getByText(/spell it exactly/i)).toBeInTheDocument();
  });

  it('saves name, aliases and domains as lists, trimming blanks', async () => {
    const calls = setup();
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /your company/i });
    await waitFor(() => expect(within(card).getByLabelText(/company name/i)).toBeEnabled());
    await user.type(within(card).getByLabelText(/company name/i), 'Acme Corp');
    await user.type(within(card).getByLabelText(/aliases/i), 'Acme,  AcmeCo , ');
    await user.type(within(card).getByLabelText(/email domains/i), '@acme.io, sales.acme.io');
    await user.click(within(card).getByRole('button', { name: /save company/i }));
    await waitFor(() => expect(calls.company).toHaveLength(1));
    // The page sends what was typed, split into a clean list; the server strips '@' and lowercases
    // domains (covered by the backend tests), so it stays the single source of truth.
    expect(calls.company[0]).toEqual({ name: 'Acme Corp', aliases: ['Acme', 'AcmeCo'], email_domains: ['@acme.io', 'sales.acme.io'] });
    expect(await within(card).findByText(/saved/i)).toBeInTheDocument();
  });

  it('does not overwrite what is being typed when the saved profile arrives late', async () => {
    setup();
    server.use(
      http.get('/api/settings/company', async () => {
        await new Promise((r) => setTimeout(r, 150));
        return HttpResponse.json({ name: 'Saved Name', aliases: [], email_domains: [], configured: true });
      }),
    );
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /your company/i });
    // While loading, the field is not editable, so nothing can be lost.
    expect(within(card).getByLabelText(/company name/i)).toBeDisabled();
    await waitFor(() => expect(within(card).getByLabelText(/company name/i)).toHaveValue('Saved Name'));
    expect(within(card).getByLabelText(/company name/i)).toBeEnabled();
  });

  it('is read-only for non-admins', async () => {
    setup({ admin: false, company: { name: 'Acme Corp', aliases: [], email_domains: [], configured: true } });
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /your company/i });
    expect(within(card).getByLabelText(/company name/i)).toBeDisabled();
    expect(within(card).queryByRole('button', { name: /save company/i })).not.toBeInTheDocument();
  });

  it('shows a server validation message instead of failing silently', async () => {
    setup();
    server.use(http.put('/api/settings/company', () => HttpResponse.json({ detail: 'bad domain' }, { status: 422 })));
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /your company/i });
    await waitFor(() => expect(within(card).getByLabelText(/company name/i)).toBeEnabled());
    await user.type(within(card).getByLabelText(/company name/i), 'Acme');
    await user.type(within(card).getByLabelText(/email domains/i), 'not a domain');
    await user.click(within(card).getByRole('button', { name: /save company/i }));
    expect(await within(card).findByRole('alert')).toBeInTheDocument();
  });
});

describe('Tag tagging fields', () => {
  it('edits confidence floor, "don\'t tag when" and example for a tag', async () => {
    const calls = setup();
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    await user.click(await screen.findByRole('button', { name: /edit tagging details for pain/i }));
    const editor = await screen.findByRole('group', { name: /tagging details for pain/i });
    const floor = within(editor).getByLabelText(/confidence floor/i);
    await user.clear(floor);
    await user.type(floor, '0.7');
    await user.type(within(editor).getByLabelText(/don't tag when/i), 'the rep is speaking');
    await user.type(within(editor).getByLabelText(/example/i), 'We lose two hours every Monday');
    await user.click(within(editor).getByRole('button', { name: /save tag details/i }));
    await waitFor(() => expect(calls.tag).toHaveLength(1));
    expect(calls.tag[0]).toEqual({ key: 'pain', min_confidence: 0.7, negative_hint: 'the rep is speaking', example: 'We lose two hours every Monday' });
  });

  it('rejects a confidence floor outside 0 to 1 before sending', async () => {
    const calls = setup();
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    await user.click(await screen.findByRole('button', { name: /edit tagging details for pain/i }));
    const editor = await screen.findByRole('group', { name: /tagging details for pain/i });
    const floor = within(editor).getByLabelText(/confidence floor/i);
    await user.clear(floor);
    await user.type(floor, '1.5');
    expect(within(editor).getByRole('button', { name: /save tag details/i })).toBeDisabled();
    expect(within(editor).getByText(/between 0 and 1/i)).toBeInTheDocument();
    expect(calls.tag).toHaveLength(0);
  });

  it('is not offered to non-admins', async () => {
    setup({ admin: false });
    render(<SettingsPage />, { wrapper });
    await screen.findByText('Pain');
    expect(screen.queryByRole('button', { name: /edit tagging details/i })).not.toBeInTheDocument();
  });
});

describe('Retag rollout card', () => {
  it('shows progress, what is missing, and the measured estimate', async () => {
    setup();
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    expect(await within(card).findByText(/312 of 1,000 calls/i)).toBeInTheDocument();
    expect(within(card).getByText(/688 waiting/i)).toBeInTheDocument();
    expect(within(card).getByText(/30s per call/i)).toBeInTheDocument();
    expect(within(card).getByText(/172 min/i)).toBeInTheDocument();
    expect(within(card).getByText(/Impersonation/)).toBeInTheDocument();
  });

  it('says everything is current when nothing is waiting', async () => {
    setup({ tax: { calls_on_current: 1000, eligible: 0, tags: [], estimated_minutes: null } });
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    expect(await within(card).findByText(/every call is on the current taxonomy/i)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /retag the next/i })).not.toBeInTheDocument();
  });

  it('previews first, then queues only after an explicit confirmation', async () => {
    const calls = setup();
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    await user.click(await within(card).findByRole('button', { name: /retag the next 100/i }));
    // A dry run only: nothing is queued yet.
    expect(await within(card).findByText(/queue 100 calls/i)).toBeInTheDocument();
    expect(within(card).getByText(/4 suggestions .* kept/i)).toBeInTheDocument();
    expect(within(card).getByText(/LLM tokens/i)).toBeInTheDocument();
    expect(calls.retag).toEqual([{ limit: 100, dry_run: true }]);
    await user.click(within(card).getByRole('button', { name: /confirm and queue/i }));
    await waitFor(() => expect(calls.retag).toHaveLength(2));
    expect(calls.retag[1]).toEqual({ limit: 100, dry_run: false });
    expect(await within(card).findByText(/queued 100/i)).toBeInTheDocument();
  });

  it('can be cancelled without queuing anything', async () => {
    const calls = setup();
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    await user.click(await within(card).findByRole('button', { name: /retag the next 100/i }));
    await user.click(await within(card).findByRole('button', { name: /^cancel$/i }));
    expect(calls.retag).toEqual([{ limit: 100, dry_run: true }]);
    expect(within(card).queryByText(/queue 100 calls/i)).not.toBeInTheDocument();
  });

  it('non-admins see progress but cannot start a retag', async () => {
    setup({ admin: false });
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    expect(await within(card).findByText(/312 of 1,000 calls/i)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /retag the next/i })).not.toBeInTheDocument();
  });

  it('shows an in-progress count while a batch runs', async () => {
    setup({ tax: { in_progress: 37 } });
    render(<SettingsPage />, { wrapper });
    const card = await screen.findByRole('region', { name: /retag progress/i });
    expect(await within(card).findByText(/37 being processed/i)).toBeInTheDocument();
  });
});

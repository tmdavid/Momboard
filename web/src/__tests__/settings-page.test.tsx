import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';

function createWrapper(initialEntries = ['/settings']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

const localStatus = {
  llm: {
    backend: 'local',
    model_normalizer: 'qwen3:8b',
    model_tagger: 'qwen3:8b',
    model_analyst: 'qwen3:8b',
    model_synthesizer: 'qwen3:8b',
    api_key_configured: false,
    api_key_hint: 'not required',
    credential_ready: true,
    credential_label: 'Local model — no API key required',
    single_model: true,
  },
  vexa: { configured: false, detail: 'not configured' },
  gdrive: { configured: false, detail: 'not configured' },
  slack: { configured: false, detail: 'not configured' },
  digest: { slack_configured: false, schedule: 'not configured' },
  taxonomy_count: 1,
  active_company_count: 1,
  can_manage_taxonomy: true,
};

const tags = [
  {
    key: 'pain',
    emoji: '⚡',
    name: 'Pain / problem',
    description: 'A real problem',
    signal_strength: 'strong',
    sort_order: 1,
    is_active: true,
    origin: 'core',
    category: null,
  },
];

const companies = [
  {
    id: 10,
    name: 'Acme Corp',
    domain: 'acme.example',
    notes: null,
    conversation_count: 2,
    created_at: '2026-08-01T00:00:00Z',
  },
];

const contacts = [
  {
    id: 20,
    name: 'Jane Doe',
    role: 'Research lead',
    email: 'jane@example.test',
    company_id: 10,
    created_at: '2026-08-01T00:00:00Z',
  },
];

function installBaseHandlers() {
  server.use(
    http.get('/api/settings/status', () => HttpResponse.json(localStatus)),
    http.get('/api/tags', () => HttpResponse.json(tags)),
    http.get('/api/companies', () => HttpResponse.json(companies)),
    http.get('/api/contacts', () => HttpResponse.json(contacts)),
  );
}

describe('Settings management', () => {
  it('shows the active local model, taxonomy, and companies/contacts directory', async () => {
    installBaseHandlers();
    const { SettingsPage } = await import('../pages/SettingsPage');

    render(<SettingsPage />, { wrapper: createWrapper() });

    // Friendly provider + credential label are visible; the raw model ID is behind "show ID".
    expect(await screen.findByText('Local (Ollama)')).toBeInTheDocument();
    expect(screen.getByText('Local model — no API key required')).toBeInTheDocument();
    expect(screen.queryByText('qwen3:8b')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /show id/i }));
    expect(screen.getByText('qwen3:8b')).toBeInTheDocument();
    expect(await screen.findByText('Pain / problem')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Acme Corp' })).toBeInTheDocument();
    expect(await screen.findByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('2 conversations')).toBeInTheDocument();
  });

  it('renders the bedrock backend with per-stage models and AWS credential status', async () => {
    const bedrockStatus = {
      ...localStatus,
      llm: {
        backend: 'bedrock',
        model_normalizer: 'eu.anthropic.claude-haiku-5-5',
        model_tagger: 'eu.anthropic.claude-haiku-5-5',
        model_analyst: 'eu.anthropic.claude-sonnet-5-5',
        model_synthesizer: 'eu.anthropic.claude-haiku-5-5',
        api_key_configured: false,
        api_key_hint: 'not required',
        credential_ready: true,
        credential_label: 'AWS credentials resolved',
        single_model: false,
      },
    };
    server.use(
      http.get('/api/settings/status', () => HttpResponse.json(bedrockStatus)),
      http.get('/api/tags', () => HttpResponse.json(tags)),
      http.get('/api/companies', () => HttpResponse.json(companies)),
      http.get('/api/contacts', () => HttpResponse.json(contacts)),
    );
    const { SettingsPage } = await import('../pages/SettingsPage');

    render(<SettingsPage />, { wrapper: createWrapper() });

    // Friendly AWS provider + credential label (not OpenAI framing, not raw ARN).
    expect(await screen.findByText('AWS Bedrock')).toBeInTheDocument();
    expect(screen.getByText('AWS credentials resolved')).toBeInTheDocument();
    // Raw model IDs are hidden until "show ID" is clicked.
    expect(screen.queryByText(/eu.anthropic.claude-sonnet-5-5/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /show id/i }));
    expect(screen.getByText(/eu.anthropic.claude-sonnet-5-5/)).toBeInTheDocument();
  });

  it('lets an admin deactivate a taxonomy tag', async () => {
    installBaseHandlers();
    let patchBody: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/tags/:key', async ({ request }) => {
        patchBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ ...tags[0], is_active: false });
      }),
    );
    const { SettingsPage } = await import('../pages/SettingsPage');
    const user = userEvent.setup();

    render(<SettingsPage />, { wrapper: createWrapper() });
    await user.click(await screen.findByRole('switch', { name: 'Deactivate Pain / problem' }));

    await waitFor(() => expect(patchBody).toEqual({ is_active: false }));
  });

  it('creates directory companies and company-linked contacts', async () => {
    installBaseHandlers();
    let companyBody: Record<string, unknown> | null = null;
    let contactBody: Record<string, unknown> | null = null;
    server.use(
      http.post('/api/companies', async ({ request }) => {
        companyBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          id: 11,
          ...companyBody,
          notes: null,
          conversation_count: 0,
          created_at: '2026-08-18T00:00:00Z',
        }, { status: 201 });
      }),
      http.post('/api/contacts', async ({ request }) => {
        contactBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          id: 21,
          ...contactBody,
          created_at: '2026-08-18T00:00:00Z',
        }, { status: 201 });
      }),
    );
    const { SettingsPage } = await import('../pages/SettingsPage');
    const user = userEvent.setup();

    render(<SettingsPage />, { wrapper: createWrapper() });

    await user.type(await screen.findByLabelText('New company name'), 'New Company');
    await user.type(screen.getByLabelText('New company domain'), 'new.example');
    await user.click(screen.getByRole('button', { name: 'Add company' }));
    await waitFor(() => expect(companyBody).toEqual({ name: 'New Company', domain: 'new.example' }));

    await user.type(screen.getByLabelText('New contact name'), 'Alex Example');
    await user.type(screen.getByLabelText('New contact role'), 'Buyer');
    await user.selectOptions(screen.getByLabelText('New contact company'), '10');
    await user.click(screen.getByRole('button', { name: 'Add contact' }));
    await waitFor(() => expect(contactBody).toEqual({
      name: 'Alex Example',
      role: 'Buyer',
      email: null,
      company_id: 10,
    }));
  });

  it('reorders a taxonomy tag by swapping sort_order with its neighbor', async () => {
    const twoTags = [
      { key: 'pain', emoji: '⚡', name: 'Pain / problem', description: null, signal_strength: 'strong', sort_order: 1, is_active: true, origin: 'core', category: null },
      { key: 'money', emoji: '💰', name: 'Money', description: null, signal_strength: 'strong', sort_order: 2, is_active: true, origin: 'core', category: null },
    ];
    const patches: { key: string; body: Record<string, unknown> }[] = [];
    server.use(
      http.get('/api/settings/status', () => HttpResponse.json(localStatus)),
      http.get('/api/tags', () => HttpResponse.json(twoTags)),
      http.get('/api/companies', () => HttpResponse.json(companies)),
      http.get('/api/contacts', () => HttpResponse.json(contacts)),
      http.patch('/api/tags/:key', async ({ request, params }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patches.push({ key: params.key as string, body });
        return HttpResponse.json({ ...twoTags.find((t) => t.key === params.key), ...body });
      }),
    );
    const { SettingsPage } = await import('../pages/SettingsPage');
    const user = userEvent.setup();

    render(<SettingsPage />, { wrapper: createWrapper() });

    // Move the second tag (Money, sort_order 2) up — swaps with Pain (sort_order 1).
    await user.click(await screen.findByRole('button', { name: 'Move Money up' }));

    await waitFor(() => expect(patches.length).toBe(2));
    expect(patches).toContainEqual({ key: 'money', body: { sort_order: 1 } });
    expect(patches).toContainEqual({ key: 'pain', body: { sort_order: 2 } });
  });

  it('disables the up arrow on the first tag and the down arrow on the last', async () => {
    const twoTags = [
      { key: 'pain', emoji: '⚡', name: 'Pain / problem', description: null, signal_strength: 'strong', sort_order: 1, is_active: true, origin: 'core', category: null },
      { key: 'money', emoji: '💰', name: 'Money', description: null, signal_strength: 'strong', sort_order: 2, is_active: true, origin: 'core', category: null },
    ];
    server.use(
      http.get('/api/settings/status', () => HttpResponse.json(localStatus)),
      http.get('/api/tags', () => HttpResponse.json(twoTags)),
      http.get('/api/companies', () => HttpResponse.json(companies)),
      http.get('/api/contacts', () => HttpResponse.json(contacts)),
    );
    const { SettingsPage } = await import('../pages/SettingsPage');

    render(<SettingsPage />, { wrapper: createWrapper() });

    expect(await screen.findByRole('button', { name: 'Move Pain / problem up' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Move Money down' })).toBeDisabled();
  });
});

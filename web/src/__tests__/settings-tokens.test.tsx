/** MCP PRD: API tokens in Settings, and the Connect to Claude card. */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { SettingsPage } from '../pages/SettingsPage';

// userEvent.setup() installs its own clipboard; spy on what the page writes to it (jsdom cannot read it back).
const spyOnWrite = () => vi.spyOn(navigator.clipboard, 'writeText');
let writeSpy: ReturnType<typeof spyOnWrite> | null = null;
const watchClipboard = () => { writeSpy = spyOnWrite(); };
const lastCopied = () => String(writeSpy?.mock.calls.at(-1)?.[0]);
afterEach(() => { writeSpy?.mockRestore(); writeSpy = null; });

const SECRET = 'mb_4fK9aQ7wXz2LmN8pRt5VbYc3HdEgJu6SoA1iBkCnMq0';

type TokenRow = Record<string, unknown> & { id: number; name: string; status: string };
const token = (over: Record<string, unknown> = {}): TokenRow => ({
  id: 1, name: 'Claude Team connector', prefix: 'mb_4fK9a', scope: 'read', status: 'active',
  created_at: '2026-11-02T09:00:00Z', expires_at: '2027-02-02T09:00:00Z', last_used_at: '2026-11-10T12:00:00Z',
  revoked_at: null, owner_id: 1, owner_name: 'David', ...over,
});

const status = (mcp: Record<string, unknown> = {}) => ({
  llm: { backend: 'openai', model_normalizer: 'm', model_tagger: 'm', model_analyst: 'm', model_synthesizer: 'm', api_key_configured: true,
    api_key_hint: 'configured', credential_ready: true, credential_label: 'ok', single_model: true },
  vexa: { configured: false, detail: '' }, gdrive: { configured: false, detail: '' }, slack: { configured: false, detail: '' },
  digest: { slack_configured: false, schedule: '' }, taxonomy_count: 12, active_company_count: 1, can_manage_taxonomy: true,
  mcp: { enabled: true, url: 'https://momboard.example.com/mcp', allow_write: false, rate_limit_per_minute: 60, public_url_configured: true, ...mcp },
});

function setup(items: TokenRow[] = [token()], mcp: Record<string, unknown> = {}) {
  const calls: { created: unknown[]; revoked: number[] } = { created: [], revoked: [] };
  let rows = [...items];
  server.use(
    http.get('/api/settings/status', () => HttpResponse.json(status(mcp))),
    http.get('/api/tokens', () => HttpResponse.json({ items: rows })),
    http.post('/api/tokens', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.created.push(body);
      const created = token({ id: 99, name: body.name as string, prefix: SECRET.slice(0, 8), scope: body.scope as string,
        expires_at: body.expires_in_days ? '2027-02-09T09:00:00Z' : null, last_used_at: null });
      rows = [created, ...rows];
      return HttpResponse.json({ ...created, token: SECRET }, { status: 201 });
    }),
    http.post('/api/tokens/:id/revoke', ({ params }) => {
      const id = Number(params.id);
      calls.revoked.push(id);
      rows = rows.map((r) => (r.id === id ? { ...r, status: 'revoked', revoked_at: '2026-11-11T10:00:00Z' } : r));
      return HttpResponse.json(rows.find((r) => r.id === id));
    }),
  );
  renderWithProviders(<SettingsPage />, { route: '/settings' });
  return calls;
}

const tokensCard = async () => (await screen.findByRole('region', { name: /api tokens/i }));
const claudeCard = async () => (await screen.findByRole('region', { name: /connect to claude/i }));

describe('API tokens card', () => {
  test('is in the settings navigation and lists tokens with what a person needs to tell them apart', async () => {
    setup();
    const nav = await screen.findByRole('navigation', { name: /settings sections/i });
    expect(within(nav).getByRole('link', { name: /api tokens/i })).toHaveAttribute('href', '#tokens');
    expect(within(nav).getByRole('link', { name: /connect to claude/i })).toHaveAttribute('href', '#claude');
    const card = await tokensCard();
    const row = (await within(card).findByText('Claude Team connector')).closest('tr') as HTMLElement;
    expect(within(row).getByText('mb_4fK9a…')).toBeInTheDocument();
    expect(within(row).getByText('Read only')).toBeInTheDocument();
    expect(within(row).getByText('2 Nov 2026')).toBeInTheDocument();       // created
    expect(within(row).getByText('10 Nov 2026')).toBeInTheDocument();      // last used
    expect(within(row).getByText('2 Feb 2027')).toBeInTheDocument();       // expires
  });

  test('shows Never for unused and non-expiring tokens, and Read and write for write tokens', async () => {
    setup([token({ last_used_at: null, expires_at: null, scope: 'write' })]);
    const row = (await within(await tokensCard()).findByText('Claude Team connector')).closest('tr') as HTMLElement;
    expect(within(row).getAllByText('Never')).toHaveLength(2);
    expect(within(row).getByText('Read and write')).toBeInTheDocument();
  });

  test('an empty list says how to start', async () => {
    setup([]);
    expect(await within(await tokensCard()).findByText(/no api tokens yet/i)).toBeInTheDocument();
  });

  test('never renders a secret or a hash from the list', async () => {
    setup();
    await within(await tokensCard()).findByText('Claude Team connector');
    expect(document.body.textContent).not.toMatch(/mb_[A-Za-z0-9_-]{20,}/);
  });

  test('inactive tokens are tucked into a collapsed list', async () => {
    setup([token(), token({ id: 2, name: 'Old laptop', status: 'revoked', revoked_at: '2026-10-01T00:00:00Z' }),
      token({ id: 3, name: 'Lapsed', status: 'expired' })]);
    const card = await tokensCard();
    const details = (await within(card).findByText(/inactive \(2\)/i)).closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByText('Old laptop')).toBeInTheDocument();
    expect(within(details).getByText('Revoked')).toBeInTheDocument();
    expect(within(details).getByText('Expired')).toBeInTheDocument();
    expect(within(details).queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });

  test('admins see whose token it is when more than one person has tokens', async () => {
    setup([token(), token({ id: 2, name: 'Maria laptop', owner_id: 2, owner_name: 'Maria' })]);
    const card = await tokensCard();
    expect(await within(card).findByRole('columnheader', { name: /owner/i })).toBeInTheDocument();
    expect(within(card).getByText('Maria')).toBeInTheDocument();
  });

  test('a single person does not see an Owner column', async () => {
    setup();
    const card = await tokensCard();
    await within(card).findByText('Claude Team connector');
    expect(within(card).queryByRole('columnheader', { name: /owner/i })).not.toBeInTheDocument();
  });
});

describe('Creating a token', () => {
  async function openDialog(user: ReturnType<typeof userEvent.setup>) {
    const card = await tokensCard();
    await user.click(await within(card).findByRole('button', { name: /create token/i }));
    return screen.findByRole('dialog', { name: /create (an )?api token/i });
  }

  test('defaults are read-only and 90 days, and a name is required', async () => {
    const user = userEvent.setup();
    setup();
    const dialog = await openDialog(user);
    expect(within(dialog).getByRole('radio', { name: /read only/i })).toBeChecked();
    expect(within(dialog).getByRole('radio', { name: /read and write/i })).not.toBeChecked();
    expect(within(dialog).getByRole('combobox', { name: /expires/i })).toHaveValue('90');
    expect(within(dialog).getByRole('button', { name: /^create token$/i })).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/name/i), '   ');
    expect(within(dialog).getByRole('button', { name: /^create token$/i })).toBeDisabled();
  });

  test('offers 30, 90 and 365 days or never', async () => {
    const user = userEvent.setup();
    setup();
    const dialog = await openDialog(user);
    const options = within(within(dialog).getByRole('combobox', { name: /expires/i })).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['30 days', '90 days', '1 year', 'Never']);
  });

  test('creating sends what was chosen and shows the secret once, with a clear warning', async () => {
    const user = userEvent.setup();
    const calls = setup();
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), '  Claude Desktop  ');
    await user.selectOptions(within(dialog).getByRole('combobox', { name: /expires/i }), '30');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    await waitFor(() => expect(calls.created).toHaveLength(1));
    expect(calls.created[0]).toEqual({ name: 'Claude Desktop', scope: 'read', expires_in_days: 30 });
    expect(await within(dialog).findByDisplayValue(SECRET)).toBeInTheDocument();
    expect(within(dialog).getByText(/you won.t see this again/i)).toBeInTheDocument();
  });

  test('never sends no expiry as null, and write scope as write', async () => {
    const user = userEvent.setup();
    const calls = setup();
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), 'Script');
    await user.click(within(dialog).getByRole('radio', { name: /read and write/i }));
    await user.selectOptions(within(dialog).getByRole('combobox', { name: /expires/i }), 'never');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    await waitFor(() => expect(calls.created).toHaveLength(1));
    expect(calls.created[0]).toEqual({ name: 'Script', scope: 'write', expires_in_days: null });
  });

  test('Copy puts the secret on the clipboard and says so', async () => {
    const user = userEvent.setup();
    watchClipboard();
    setup();
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), 'Copy me');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    await within(dialog).findByDisplayValue(SECRET);
    await user.click(within(dialog).getByRole('button', { name: /copy token/i }));
    expect(lastCopied()).toBe(SECRET);
    expect(await within(dialog).findByText(/copied/i)).toBeInTheDocument();
  });

  test('closing the dialog removes the secret from the page, and the list shows only the prefix', async () => {
    const user = userEvent.setup();
    setup();
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), 'Gone soon');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    await within(dialog).findByDisplayValue(SECRET);
    await user.click(within(dialog).getByRole('button', { name: /^done$/i }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(document.querySelector(`input[value="${SECRET}"]`)).toBeNull();
    const card = await tokensCard();
    expect(await within(card).findByText('Gone soon')).toBeInTheDocument();
    expect(within(card).getAllByText('mb_4fK9a…').length).toBeGreaterThan(0);
  });

  test('Escape closes it too and the secret does not come back when it is reopened', async () => {
    const user = userEvent.setup();
    setup();
    let dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), 'Esc');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    await within(dialog).findByDisplayValue(SECRET);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    dialog = await openDialog(user);
    expect(within(dialog).queryByDisplayValue(SECRET)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/name/i)).toHaveValue('');
  });

  test('a refused creation shows the reason and keeps what was typed', async () => {
    const user = userEvent.setup();
    setup();
    server.use(http.post('/api/tokens', () => HttpResponse.json(
      { detail: 'You already have 10 active tokens. Revoke one before creating another.' }, { status: 409 })));
    const dialog = await openDialog(user);
    await user.type(within(dialog).getByLabelText(/name/i), 'Eleventh');
    await user.click(within(dialog).getByRole('button', { name: /^create token$/i }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Revoke one before creating another.');
    expect(within(dialog).getByLabelText(/name/i)).toHaveValue('Eleventh');
    expect(within(dialog).queryByText(/you won.t see this again/i)).not.toBeInTheDocument();
  });

  test('says that write access does not unlock write tools over MCP yet', async () => {
    const user = userEvent.setup();
    setup();
    const dialog = await openDialog(user);
    expect(within(dialog).getByText(/write tools.*not available/i)).toBeInTheDocument();
  });
});

describe('Revoking a token', () => {
  test('needs a confirm step, and Cancel changes nothing', async () => {
    const user = userEvent.setup();
    const calls = setup();
    const card = await tokensCard();
    const row = (await within(card).findByText('Claude Team connector')).closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: /^revoke$/i }));
    expect(within(row).getByText(/stops working immediately/i)).toBeInTheDocument();
    await user.click(within(row).getByRole('button', { name: /cancel/i }));
    expect(calls.revoked).toEqual([]);
    expect(within(row).getByRole('button', { name: /^revoke$/i })).toBeInTheDocument();
  });

  test('confirming revokes it and moves it to Inactive', async () => {
    const user = userEvent.setup();
    const calls = setup();
    const card = await tokensCard();
    const row = (await within(card).findByText('Claude Team connector')).closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: /^revoke$/i }));
    await user.click(within(row).getByRole('button', { name: /yes, revoke/i }));
    await waitFor(() => expect(calls.revoked).toEqual([1]));
    expect(await within(card).findByText(/inactive \(1\)/i)).toBeInTheDocument();
    expect(within(card).getByText(/no api tokens yet|no active tokens/i)).toBeInTheDocument();
  });

  test('a failed revoke says so and leaves the token active', async () => {
    const user = userEvent.setup();
    setup();
    server.use(http.post('/api/tokens/:id/revoke', () => new HttpResponse(null, { status: 500 })));
    const card = await tokensCard();
    const row = (await within(card).findByText('Claude Team connector')).closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: /^revoke$/i }));
    await user.click(within(row).getByRole('button', { name: /yes, revoke/i }));
    expect(await within(card).findByRole('alert')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /^revoke$|yes, revoke/i })).toBeInTheDocument();
  });
});

describe('Connect to Claude card', () => {
  test('when MCP is off it says so and how to turn it on, without a URL', async () => {
    setup([token()], { enabled: false, url: null });
    const card = await claudeCard();
    expect(within(card).getByText(/MCP_ENABLED/)).toBeInTheDocument();
    expect(within(card).queryByDisplayValue(/\/mcp$/)).not.toBeInTheDocument();
  });

  test('shows the exact URL and the header to add, each with a Copy button', async () => {
    const user = userEvent.setup();
    watchClipboard();
    setup();
    const card = await claudeCard();
    expect(within(card).getByDisplayValue('https://momboard.example.com/mcp')).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: /copy server url/i }));
    expect(lastCopied()).toBe('https://momboard.example.com/mcp');
    expect(within(card).getByText('Authorization')).toBeInTheDocument();
    expect(within(card).getByText('Bearer <your token>')).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: /copy header value/i }));
    expect(lastCopied()).toBe('Bearer <your token>');
  });

  test('gives the Team plan steps in the right order', async () => {
    setup();
    const card = await claudeCard();
    const steps = within(card).getAllByRole('listitem').map((li) => li.textContent ?? '');
    const joined = steps.join(' | ');
    expect(joined).toMatch(/Owner.*custom connector.*URL/i);
    expect(joined).toMatch(/No sign in/i);
    expect(joined.indexOf('No sign in')).toBeLessThan(joined.search(/request headers/i));
  });

  test('the Claude Desktop config has the URL filled in and a pinned bridge version', async () => {
    const user = userEvent.setup();
    watchClipboard();
    setup();
    const card = await claudeCard();
    const config = within(card).getByLabelText(/claude desktop config/i) as HTMLTextAreaElement;
    const parsed = JSON.parse(config.value);
    const server_ = parsed.mcpServers.momboard;
    expect(server_.command).toBe('npx');
    expect(server_.args[0]).toMatch(/^(-y|--yes)$/);
    expect(server_.args).toContain('https://momboard.example.com/mcp');
    expect(server_.args.some((a: string) => /^mcp-remote@\d+\.\d+\.\d+$/.test(a))).toBe(true);   // pinned, not "latest"
    expect(server_.args).not.toContain('--allow-http');
    expect(server_.env.MOMBOARD_AUTH).toBe('Bearer <your token>');
    await user.click(within(card).getByRole('button', { name: /copy config/i }));
    expect(JSON.parse(lastCopied())).toEqual(parsed);
  });

  test('a plain http address (internal host) adds the flag the bridge needs', async () => {
    setup([token()], { url: 'http://momboard.internal:8080/mcp', public_url_configured: false });
    const config = (await within(await claudeCard()).findByLabelText(/claude desktop config/i)) as HTMLTextAreaElement;
    expect(JSON.parse(config.value).mcpServers.momboard.args).toContain('--allow-http');
  });

  test('warns that quotes and transcripts leave MomBoard for Claude', async () => {
    setup();
    expect(within(await claudeCard()).getByText(/sent to claude/i)).toBeInTheDocument();
  });

  test('says when the address was taken from the browser rather than configured', async () => {
    setup([token()], { public_url_configured: false });
    expect(within(await claudeCard()).getByText(/PUBLIC_BASE_URL/)).toBeInTheDocument();
  });

  test('stays quiet about it when a public address is configured', async () => {
    setup();
    const card = await claudeCard();
    await within(card).findByDisplayValue('https://momboard.example.com/mcp');
    expect(within(card).queryByText(/PUBLIC_BASE_URL/)).not.toBeInTheDocument();
  });

  test('copes with a server that predates the mcp block', async () => {
    server.use(http.get('/api/settings/status', () => HttpResponse.json({ ...status(), mcp: undefined })),
      http.get('/api/tokens', () => HttpResponse.json({ items: [] })));
    renderWithProviders(<SettingsPage />, { route: '/settings' });
    expect(within(await claudeCard()).getByText(/MCP_ENABLED/)).toBeInTheDocument();
  });
});

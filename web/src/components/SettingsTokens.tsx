/**
 * Settings for the MCP server: API tokens, and the "Connect to Claude" card (MCP PRD).
 *
 * A token's secret exists only in the create dialog's state, once. It is never put in a list, a URL
 * or storage, and it disappears when the dialog closes.
 */
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiToken, ApiTokenCreated } from '../api';
import { formatDate } from '../utils/format';

/** The bridge Claude Desktop uses to reach a remote server. Pinned: never "latest" in a pasted config. */
export const MCP_REMOTE_VERSION = '0.15.2';

export interface McpStatus {
  enabled: boolean;
  url?: string | null;
  allow_write?: boolean;
  rate_limit_per_minute?: number;
  public_url_configured?: boolean;
}

const EXPIRY_OPTIONS = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'never', label: 'Never' },
] as const;

/** The server's `detail` message when it sent one, otherwise a plain fallback. */
function problemText(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    try {
      const detail = (JSON.parse(error.message) as { detail?: unknown }).detail;
      if (typeof detail === 'string' && detail) return detail;
      if (Array.isArray(detail)) {
        const first = detail[0] as { msg?: string } | undefined;
        if (first?.msg) return first.msg;
      }
    } catch {
      /* not JSON: use the fallback */
    }
  }
  return fallback;
}

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = useCallback(async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), 2500);
    } catch {
      setCopied(null);
    }
  }, []);
  return { copied, copy };
}

const Card = ({ id, label, children }: { id: string; label: string; children: React.ReactNode }) => (
  <section id={id} aria-label={label} className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 flex flex-col gap-3">
    {children}
  </section>
);

const accessLabel = (t: ApiToken) => (t.scope === 'write' ? 'Read and write' : 'Read only');
const dateOrNever = (value: string | null | undefined) => (value ? formatDate(value) : 'Never');

// ─── API tokens ───

export function ApiTokensCard() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: ['api-tokens'], queryFn: () => api.listApiTokens() });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  const openButton = useRef<HTMLButtonElement>(null);

  const revoke = useMutation({
    mutationFn: (id: number) => api.revokeApiToken(id),
    onSuccess: () => {
      setConfirming(null);
      void queryClient.invalidateQueries({ queryKey: ['api-tokens'] });
    },
  });

  const items = data?.items ?? [];
  const active = items.filter((t) => t.status === 'active');
  const inactive = items.filter((t) => t.status !== 'active');
  const showOwner = new Set(items.map((t) => t.owner_id)).size > 1;

  const closeDialog = () => {
    setDialogOpen(false);
    void queryClient.invalidateQueries({ queryKey: ['api-tokens'] });
    setTimeout(() => openButton.current?.focus(), 0);
  };

  return (
    <>
      <Card id="tokens" label="API tokens">
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <h2 className="text-base font-semibold text-ink">API tokens</h2>
            <span className="text-[13px] text-muted">
              Let Claude or a script read MomBoard. A token acts as you, and can never do more than you can.
            </span>
          </div>
          <button ref={openButton} type="button" className="btn btn-sm btn-primary ml-auto" onClick={() => setDialogOpen(true)}>
            Create token
          </button>
        </div>

        {isLoading && <p className="text-sm text-muted m-0">Loading…</p>}
        {isError && <p role="alert" className="text-sm text-crit m-0">Couldn’t load your tokens.</p>}
        {revoke.isError && (
          <p role="alert" className="text-sm text-crit m-0">{problemText(revoke.error, 'Couldn’t revoke that token. Try again.')}</p>
        )}

        {!isLoading && !isError && (
          active.length === 0 ? (
            <p className="text-sm text-muted m-0">
              {items.length === 0 ? 'No API tokens yet. Create one to connect Claude or a script.' : 'No active tokens.'}
            </p>
          ) : (
            <TokenTable rows={active} showOwner={showOwner} confirming={confirming} setConfirming={setConfirming}
              onRevoke={(id) => revoke.mutate(id)} revoking={revoke.isPending} />
          )
        )}

        {inactive.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-ink-2">Inactive ({inactive.length})</summary>
            <div className="mt-2">
              <TokenTable rows={inactive} showOwner={showOwner} confirming={null} setConfirming={() => undefined}
                onRevoke={() => undefined} revoking={false} inactive />
            </div>
          </details>
        )}
      </Card>
      {dialogOpen && <CreateTokenDialog onClose={closeDialog} />}
    </>
  );
}

function TokenTable({ rows, showOwner, confirming, setConfirming, onRevoke, revoking, inactive = false }: {
  rows: ApiToken[]; showOwner: boolean; confirming: number | null; setConfirming: (id: number | null) => void;
  onRevoke: (id: number) => void; revoking: boolean; inactive?: boolean;
}) {
  const th = 'text-left text-xs font-semibold text-muted px-2 py-1.5 border-b border-hairline whitespace-nowrap';
  const td = 'px-2 py-2 text-[13px] align-top';
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Token</th>
            <th className={th}>Access</th>
            <th className={th}>Created</th>
            <th className={th}>Last used</th>
            <th className={th}>{inactive ? 'Status' : 'Expires'}</th>
            {showOwner && <th className={th}>Owner</th>}
            {!inactive && <th className={th}><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className="border-b border-sub last:border-b-0">
              <td className={`${td} font-medium text-ink`}>{t.name}</td>
              <td className={`${td} font-mono text-ink-2`}>{t.prefix}…</td>
              <td className={td}>{accessLabel(t)}</td>
              <td className={`${td} whitespace-nowrap`}>{formatDate(t.created_at)}</td>
              <td className={`${td} whitespace-nowrap`}>{dateOrNever(t.last_used_at)}</td>
              <td className={`${td} whitespace-nowrap`}>
                {inactive ? (t.status === 'revoked' ? 'Revoked' : 'Expired') : dateOrNever(t.expires_at)}
              </td>
              {showOwner && <td className={td}>{t.owner_name ?? '—'}</td>}
              {!inactive && (
                <td className={`${td} text-right whitespace-nowrap`}>
                  {confirming === t.id ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="text-xs text-muted">Stops working immediately.</span>
                      <button type="button" className="btn btn-sm" disabled={revoking} onClick={() => onRevoke(t.id)}>Yes, revoke</button>
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => setConfirming(null)}>Cancel</button>
                    </span>
                  ) : (
                    <button type="button" className="btn btn-sm" aria-label="Revoke" onClick={() => setConfirming(t.id)}>Revoke</button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreateTokenDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [scope, setScope] = useState<'read' | 'write'>('read');
  const [expires, setExpires] = useState<string>('90');
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const { copied, copy } = useCopy();
  const nameInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameInput.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const create = useMutation({
    mutationFn: () =>
      api.createApiToken({ name: name.trim(), scope, expires_in_days: expires === 'never' ? null : (Number(expires) as 30 | 90 | 365) }),
    onSuccess: (token) => setCreated(token),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim() && !create.isPending) create.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-modal="true" aria-label="Create API token"
        className="w-full max-w-md rounded-2xl border border-hairline bg-surface p-5 shadow-xl flex flex-col gap-3">
        {created ? (
          <>
            <h3 className="m-0 text-lg font-bold text-ink">Token created</h3>
            <p className="m-0 text-sm font-semibold text-warn-text">You won’t see this again. Copy it now and keep it somewhere safe.</p>
            <div className="flex gap-2">
              <input readOnly aria-label="New API token" value={created.token} onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-0 font-mono text-xs px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink" />
              <button type="button" className="btn btn-sm btn-primary" aria-label="Copy token" onClick={() => void copy('token', created.token)}>
                Copy
              </button>
            </div>
            <span role="status" className="text-xs text-good-text min-h-[1em]">{copied === 'token' ? 'Copied' : ''}</span>
            <p className="m-0 text-xs text-muted">
              Anyone with this token can read {created.scope === 'write' ? '(and, where allowed, change) ' : ''}MomBoard as you until you revoke it.
            </p>
            <button type="button" className="btn btn-primary self-end" onClick={onClose}>Done</button>
          </>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <h3 className="m-0 text-lg font-bold text-ink">Create API token</h3>
            <label className="flex flex-col gap-1 text-sm text-ink-2">
              Name
              <input ref={nameInput} value={name} onChange={(e) => setName(e.target.value)} maxLength={100}
                placeholder="Claude Team connector" className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink" />
            </label>
            <fieldset className="border-none p-0 m-0 flex flex-col gap-1.5">
              <legend className="text-sm text-ink-2 mb-1">Access</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" name="scope" checked={scope === 'read'} onChange={() => setScope('read')} /> Read only
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" name="scope" checked={scope === 'write'} onChange={() => setScope('write')} /> Read and write
              </label>
              <span className="text-xs text-muted">
                Write tools are not available over MCP yet, so Read only is right for Claude. Write access only matters for scripts using the REST API.
              </span>
            </fieldset>
            <label className="flex flex-col gap-1 text-sm text-ink-2">
              Expires
              <select value={expires} onChange={(e) => setExpires(e.target.value)} className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink">
                {EXPIRY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            {create.isError && (
              <p role="alert" className="m-0 text-sm text-crit">{problemText(create.error, 'Couldn’t create the token. Try again.')}</p>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={!name.trim() || create.isPending}>Create token</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ─── Connect to Claude ───

const PLACEHOLDER_AUTH = 'Bearer <your token>';

/** The Claude Desktop config for the local bridge, with the address filled in. */
export function desktopConfig(url: string): string {
  const args = ['-y', `mcp-remote@${MCP_REMOTE_VERSION}`, url];
  if (url.startsWith('http://')) args.push('--allow-http'); // the bridge refuses plain http without it
  args.push('--header', 'Authorization:${MOMBOARD_AUTH}');
  return JSON.stringify({ mcpServers: { momboard: { command: 'npx', args, env: { MOMBOARD_AUTH: PLACEHOLDER_AUTH } } } }, null, 2);
}

export function ConnectToClaudeCard({ mcp }: { mcp?: McpStatus | null }) {
  const { copied, copy } = useCopy();
  const enabled = !!mcp?.enabled && !!mcp.url;
  const url = mcp?.url ?? '';
  const config = enabled ? desktopConfig(url) : '';
  const copyButton = (key: string, label: string, text: string) => (
    <button type="button" className="btn btn-sm" aria-label={label} onClick={() => void copy(key, text)}>
      {copied === key ? 'Copied' : 'Copy'}
    </button>
  );

  return (
    <Card id="claude" label="Connect to Claude">
      <h2 className="text-base font-semibold text-ink">Connect to Claude</h2>
      {!enabled ? (
        <p className="m-0 text-sm text-muted">
          The MCP server is switched off. To let Claude search your conversations, set <code>MCP_ENABLED=true</code> in the
          server’s environment and restart MomBoard. Then create a token above.
        </p>
      ) : (
        <>
          <p className="m-0 text-sm text-ink-2">
            Claude can search your conversations, quotes, hypotheses and decisions, and cite them with links back here.
            Each token can make up to {mcp?.rate_limit_per_minute ?? 60} tool calls a minute.
          </p>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">MCP server URL</span>
            <div className="flex gap-2">
              <input readOnly aria-label="MCP server URL" value={url} onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-0 font-mono text-xs px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink" />
              {copyButton('url', 'Copy server URL', url)}
            </div>
            {!mcp?.public_url_configured && (
              <span className="text-xs text-muted">
                This address was worked out from the request you are using. If MomBoard has another public name or sits behind a
                proxy, set <code>PUBLIC_BASE_URL</code> so the links Claude cites are right.
              </span>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">Request header to add</span>
            <div className="flex items-center gap-2 flex-wrap">
              <code className="px-2 py-1 rounded bg-page border border-hairline text-xs">Authorization</code>
              <code className="px-2 py-1 rounded bg-page border border-hairline text-xs">{PLACEHOLDER_AUTH}</code>
              {copyButton('header', 'Copy header value', PLACEHOLDER_AUTH)}
            </div>
            <span className="text-xs text-muted">Replace the placeholder with a token from above.</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">On a Claude Team plan</span>
            <ol className="m-0 pl-5 text-sm text-ink-2 flex flex-col gap-0.5">
              <li>An Owner adds a custom connector and pastes the server URL.</li>
              <li>Choose “No sign in”.</li>
              <li>Add the header above under request headers, with a token from this page.</li>
              <li>Members then switch the connector on for themselves.</li>
            </ol>
            <span className="text-xs text-muted">
              A header set this way is shared by everyone in the organisation, so every member reaches MomBoard with the same
              token. Use a read-only token. On Pro or Max, each person adds the connector with their own token.
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">Claude Desktop, on the company network or VPN</span>
            <textarea readOnly aria-label="Claude Desktop config" value={config} rows={Math.min(14, config.split('\n').length)}
              onFocus={(e) => e.currentTarget.select()}
              className="w-full font-mono text-xs px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink" />
            <div className="flex items-center gap-2">
              {copyButton('config', 'Copy config', config)}
              <span className="text-xs text-muted">
                Runs the community <code>mcp-remote</code> bridge (version pinned to {MCP_REMOTE_VERSION}) through <code>npx</code>.
              </span>
            </div>
          </div>
        </>
      )}
      <p className="m-0 text-xs text-muted border-t border-sub pt-2.5">
        Quotes and transcript text that tools return are sent to Claude. Before connecting real customer conversations, confirm
        that your agreement with Anthropic covers them.
      </p>
      <span role="status" className="sr-only">{copied ? 'Copied to the clipboard' : ''}</span>
    </Card>
  );
}

# MCP server and API tokens

MomBoard can expose its evidence to Claude (or any MCP client) at `/mcp`, so you can ask "What pains did
law firms mention last month?" and get quotes back with links to the source in MomBoard. Access uses
**API tokens** created in Settings. This page is for the person switching it on and operating it.

The server is **off by default** and **read-only**. Nothing is exposed until you set `MCP_ENABLED=true`.

## What it does

The server has 13 tools. All of them read; none changes anything.

| Tool | Use it to |
|---|---|
| `list_tags` | Learn the valid tag keys before filtering |
| `search_conversations` | Find calls by topic, company, tag (all must match), date or Mom Test score |
| `get_conversation` | Read one call's analysis: summary, top pains, commitments, critique, follow-ups |
| `get_transcript` | Read what was said, about 3,000 words a page |
| `search_highlights` | Pull tagged customer quotes across calls, strongest first |
| `list_summaries`, `get_summary` | See and read past syntheses |
| `list_hypotheses`, `get_hypothesis` | See beliefs, their grounding band and the quotes behind them |
| `list_decisions`, `get_decision` | See decisions, their cited quotes and whether that evidence still holds |
| `get_insights` | Corpus numbers: calls, pains, average score, compliment ratio, tag volumes (30d, 90d or all) |
| `check_hypothesis_evidence` | Test a belief against the calls **without saving anything** |

How results behave:

- **Same rules as the app.** Tools call the same code as the web app and REST API, so permissions and the
  per-tag confidence floor are identical. Quotes are customer speech only (our own reps' lines are left out,
  except follow-ups and commitments), and simulated practice calls never appear.
- **Cited.** Every item has a `url` that opens the call, quote, hypothesis, decision or summary in MomBoard.
- **Compact and paged.** 20 items by default, 50 at most, with a `next_cursor` when there is more. Dates are
  ISO 8601.
- **Errors say how to fix them**, e.g. `Unknown tag key 'pains'. Call list_tags for valid keys.` A server
  fault returns a short reference id and logs the detail on the server; stack traces never reach the client.
- **Time limit.** A tool call stops after 30 seconds (`check_hypothesis_evidence` uses an LLM and can be slow).

## Privacy: what leaves MomBoard

Everything a tool returns is sent to the AI service the client uses. Before connecting a real corpus, **confirm
that your agreement with Anthropic (or whichever provider you use) covers customer transcripts.**

MomBoard limits what is sent:

- Searches return quotes and summaries. Full text only comes from `get_transcript`, a page at a time.
- Every field is on an allowlist. **Contact email addresses and phone numbers are never returned**, and any
  that appear *inside* a quote or transcript are replaced with `[email removed]` / `[phone removed]`.
- Transcript text is marked as quoted speech in the output, and the server instructions tell the model it is
  data, never instructions. Treat that as a mitigation, not a guarantee: a customer line could still say
  "ignore your instructions", and the model decides what to do with it. The tools are read-only, so the worst
  outcome is a misleading answer, not a change to your data.
- Tokens are never logged and never shown after creation.

## Turn it on

Set these in the environment (see `.env.example`) and restart:

| Variable | Default | Meaning |
|---|---|---|
| `MCP_ENABLED` | `false` | Serve `/mcp` |
| `PUBLIC_BASE_URL` | empty | The address people use to reach MomBoard, e.g. `https://momboard.example.com`. Links in tool output use it. If empty, MomBoard works the address out from each request (honouring `X-Forwarded-Proto` / `X-Forwarded-Host`), which is wrong behind some proxies. |
| `MCP_RATE_LIMIT_PER_MINUTE` | `60` | Tool calls per token per minute |
| `MCP_TOOL_TIMEOUT_SECONDS` | `30` | Per-call time limit |
| `MCP_ALLOW_WRITE` | `false` | Reserved for phase 2. No write tools exist yet, so it changes nothing today. |

The database change (migration `012`) creates two tables and touches nothing else; the container applies it on
start. MomBoard must run as **one process** (as SQLite already requires): the rate limit is kept in memory.

Then in MomBoard: **Settings → API tokens → Create token**, and **Settings → Connect to Claude** for the address
and ready-to-paste setup.

## API tokens

- Format `mb_` plus 32 random bytes (46 characters). Sent as `Authorization: Bearer mb_…`. Never in a URL.
- Shown **once**, at creation. MomBoard stores only a SHA-256 hash and the first 8 characters (the prefix you
  see in the list).
- A token acts as the person who created it and never exceeds their role. A *read* token may only make safe
  (GET) requests; a *write* token is for scripts using the REST API. **No token can create or revoke tokens**,
  so a leaked token cannot mint another.
- Expiry: 30, 90 (default) or 365 days, or never. Anyone signed in can make tokens for themselves, up to **10
  active** at a time. Admins see and can revoke everyone's.
- Revoking works on the very next request. The row is kept for the audit trail.
- Any failure (unknown, revoked, expired, malformed) returns the same HTTP 401, so a response never reveals
  whether a token exists.
- The same tokens work on the REST API, so scripts can use them.

### One shared connector means one shared identity

On a Claude **Team** plan, an Owner adds a custom connector and sets request headers once for the organisation,
so **every member calls MomBoard with the same token**. That token acts as a service account, not as each
person, and anything done with it is attributed to its owner. This is why only read tools exist. Use a token
owned by a dedicated service user, read-only, with an expiry you will remember to renew. On Pro or Max, each
person can add the connector with their own token.

## Connecting a client

### Path A: Claude on the web, mobile or Cowork (remote connector)

Claude reaches a remote connector **from Anthropic's cloud, not from the user's laptop**
([Claude help](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)),
so MomBoard's `/mcp` must be reachable from the internet. Either:

- **Allowlist** [the IP ranges Anthropic publishes](https://platform.claude.com/docs/en/api/ip-addresses) so that only they can reach `/mcp` (preferred), or
- expose `/mcp` publicly behind TLS, relying on the token check and the rate limit.

In both cases: HTTPS only, route **`/mcp` alone** (the rest of MomBoard stays internal), and make sure the
reverse proxy does not buffer streamed responses. Example for nginx:

```nginx
location = /mcp {
    proxy_pass http://momboard:8080;
    proxy_http_version 1.1;
    proxy_buffering off;                       # do not hold streamed responses
    proxy_read_timeout 60s;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header Authorization $http_authorization;
}
```

The address must be exactly `/mcp`: `/mcp/` (with a trailing slash) redirects and some clients will not follow it.

Add the connector (Team: an Owner does this): paste the URL from Settings, choose **No sign in**, and add the
request header `Authorization: Bearer <your token>`.

> Claude's help page confirms that connectors can use "an API key or other fixed credential" and that everyone
> on a Team or Enterprise plan then shares it. The exact wording of the options in the connector dialog (here
> "No sign in" and "request headers") comes from our product plan, not from that page, and Anthropic changes
> the dialog from time to time. If you cannot find a field to add a header, check Claude's current help before
> assuming MomBoard is at fault.

### Path B: Claude Desktop on the company network or VPN

No firewall change. Claude Desktop runs a small bridge that forwards to `/mcp` over your VPN. Settings shows a
ready-to-paste config with the address filled in. It uses the community `mcp-remote` package, **pinned to one
version** in the config (not "latest"), so a bad release cannot reach everyone who pastes it. This path works
only where the desktop app runs and the VPN is up. Claude's help says local servers do not reach Cowork or
claude.ai, so test before relying on it there.

If MomBoard is addressed over plain `http://` (an internal host), the config adds `--allow-http`, because the
bridge refuses plain HTTP otherwise. Prefer HTTPS.

## Watching it

Every tool call writes one row to `mcp_calls`: the token's **prefix** (never the token), the tool, a summary of
the arguments (names and short values only, long text is cut, so transcripts do not land in the log), the
outcome (`ok`, `denied` or `error`), duration and result count. Rows older than 90 days are deleted (at start-up
and then at most once a day).

```sql
-- who is calling what, today
SELECT token_prefix, tool, status, COUNT(*) AS calls, MAX(created_at) AS last_call
FROM mcp_calls WHERE created_at >= date('now') GROUP BY token_prefix, tool, status ORDER BY calls DESC;
```

Listing the tools is not a call and is not logged.

## Limits

- 60 tool calls a minute per token (`MCP_RATE_LIMIT_PER_MINUTE`), then HTTP 429 with `Retry-After`. Listing the
  tools and the connection handshake do not count. A batch of calls counts each call.
- 50 items a page, about 3,000 words per transcript page, 30 seconds a call, 1 MB per request.
- `GET` and `DELETE` on `/mcp` answer 405 straight away (the server is stateless and has no event stream).

## Troubleshooting

| You see | Likely cause |
|---|---|
| HTTP 401 | No `Authorization: Bearer` header, or a token that is wrong, revoked or expired. The reply never says which. Check Settings → API tokens. |
| HTTP 405 on a `POST` to `/mcp`, or MomBoard's web page coming back from `/mcp` | MCP is switched off (`MCP_ENABLED` is not `true`), so `/mcp` is just part of the web app. |
| HTTP 405 from the real MCP server | A client used `GET`/`DELETE`, or hit `/mcp/` with a trailing slash. Use `POST` on exactly `/mcp`. |
| The proxy answers 404 or 502 | The proxy is not routing `/mcp` to MomBoard, or MomBoard is not running. |
| HTTP 429 | The per-minute limit. Wait for `Retry-After`. |
| Links in answers point at the wrong host | Set `PUBLIC_BASE_URL`. |
| "Unknown tag key …" | Call `list_tags` for the valid keys. |
| "That took longer than 30 seconds" | Narrow the request. `check_hypothesis_evidence` is the slowest tool. |

## Not built yet

- **Write tools** (`create_hypothesis`, `create_decision`). They need per-person identity (OAuth), because a
  shared connector token cannot say who a change is attributed to.
- **OAuth** for the connector.
- Per-token limits on which companies or dates a token can see: today a token sees everything its owner can.

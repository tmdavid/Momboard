# callcompass.xyz + GitHub Pages + Wiki — Setup Runbook

Everything below is copy-paste. Total time: ~15 minutes, plus DNS propagation (minutes to a few hours on GoDaddy).

---

## Step 1 — Add the site to the repo

From your local Momboard checkout, copy this pack's `docs/` folder in and push:

```bash
cp -r site-pack/docs ./docs        # contains index.html + CNAME
git add docs && git commit -m "Add landing page for callcompass.xyz (GitHub Pages)"
git push
```

The `docs/CNAME` file (contents: `callcompass.xyz`) is what tells Pages your custom domain — keep it, GitHub reads it on every deploy.

## Step 2 — Enable GitHub Pages

Repo → **Settings → Pages**:

- Source: **Deploy from a branch**
- Branch: `main`, folder: **/docs** → Save
- In **Custom domain**, type `callcompass.xyz` → Save. (It may warn "DNS check unsuccessful" until Step 3 propagates — that's expected.)
- Leave **Enforce HTTPS** unchecked for now; come back and check it after the DNS check passes (GitHub needs to issue the certificate first, usually < 1 hour after DNS resolves).

## Step 3 — GoDaddy DNS

GoDaddy → My Products → callcompass.xyz → **DNS / Manage DNS**. Delete GoDaddy's default "Parked" A record and the default `www` CNAME if present, then add:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | @ | `185.199.108.153` | 1 Hour |
| A | @ | `185.199.109.153` | 1 Hour |
| A | @ | `185.199.110.153` | 1 Hour |
| A | @ | `185.199.111.153` | 1 Hour |
| CNAME | www | `tmdavid.github.io` | 1 Hour |

(All four A records — GitHub load-balances across them. The CNAME makes `www.callcompass.xyz` redirect to the apex automatically once Pages sees it.)

## Step 4 — Verify

```bash
dig +short callcompass.xyz A        # → the four 185.199.x.153 addresses
dig +short www.callcompass.xyz      # → tmdavid.github.io + the A records
curl -sI https://callcompass.xyz | head -3   # after HTTPS enforce: HTTP/2 200
```

Then flip **Enforce HTTPS** on in the Pages settings.

> Optional but recommended: in GitHub **Settings → Pages → Verified domains** (account level: Settings → Pages), verify `callcompass.xyz` with the TXT record GitHub gives you — prevents domain takeover if you ever disable Pages.

---

## Step 5 — Wiki

GitHub wikis are git repos, but the repo only exists after the wiki is initialized once in the UI:

1. Repo → **Wiki** tab → **Create the first page** → save the placeholder Home as-is. (If there's no Wiki tab: Settings → General → Features → check **Wikis**.)
2. Then push this pack's content over it:

```bash
git clone https://github.com/tmdavid/Momboard.wiki.git
cp site-pack/wiki/*.md Momboard.wiki/
cd Momboard.wiki
git add -A && git commit -m "Wiki: home, getting started, architecture, taxonomy, task plan, local LLM, fixtures"
git push
```

Pages included: `Home`, `_Sidebar` (navigation), `Getting-Started`, `Architecture`, `Mom-Test-Taxonomy`, `Task-Plan`, `Local-LLM-Setup`, `Fixtures-and-Evals`. GitHub renders `[[Wiki Links]]` and the sidebar automatically.

---

## Afterwards (nice-to-haves)

- Add the site to the repo header: repo → About ⚙ → Website: `https://callcompass.xyz`, plus topics (`mom-test`, `customer-discovery`, `user-research`, `fastapi`, `self-hosted`).
- The landing page's scoreboard section ("★ 0 stars…") is static HTML — update the numbers weekly by editing `docs/index.html`, or later replace with a tiny fetch of the GitHub API.
- When you pick a license, update the FAQ line in `docs/index.html` (currently says "Open source on GitHub", deliberately license-neutral).

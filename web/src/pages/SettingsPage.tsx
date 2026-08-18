import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { api, Company, Contact, Tag } from '../api';

interface SettingsStatus {
  llm: {
    backend: string;
    model_normalizer: string;
    model_tagger: string;
    model_analyst: string;
    model_synthesizer: string;
    api_key_configured: boolean;
    api_key_hint: string;
  };
  vexa: { configured: boolean; detail: string };
  gdrive: { configured: boolean; detail: string };
  slack: { configured: boolean; detail: string };
  digest: { slack_configured: boolean; schedule: string };
  taxonomy_count: number;
  active_company_count: number;
  can_manage_taxonomy?: boolean;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block w-2 h-2 rounded-full mr-2 ${ok ? 'bg-good' : 'bg-hairline'}`}
    />
  );
}

function MutationError({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p className="text-xs text-crit mt-2" role="alert">{error.message}</p>;
}

function TaxonomySettings({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState('');
  const [emoji, setEmoji] = useState('');
  const [name, setName] = useState('');
  const [signalStrength, setSignalStrength] = useState('medium');

  const { data: tags = [], isLoading, error } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.listTags(),
  });

  const toggleTag = useMutation({
    mutationFn: ({ tag, active }: { tag: Tag; active: boolean }) =>
      api.updateTag(tag.key, { is_active: active }),
    onSuccess: (updated) => {
      queryClient.setQueryData<Tag[]>(['tags'], (current = []) =>
        current.map((tag) => tag.key === updated.key ? updated : tag),
      );
    },
  });

  const createTag = useMutation({
    mutationFn: () => api.createTag({
      key: key.trim(),
      emoji: emoji.trim(),
      name: name.trim(),
      description: null,
      signal_strength: signalStrength,
      sort_order: Math.max(0, ...tags.map((tag) => tag.sort_order)) + 1,
      is_active: true,
    }),
    onSuccess: (created) => {
      queryClient.setQueryData<Tag[]>(['tags'], (current = []) =>
        [...current, created].sort((a, b) => a.sort_order - b.sort_order),
      );
      setKey('');
      setEmoji('');
      setName('');
      setSignalStrength('medium');
    },
  });

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim() && emoji.trim() && name.trim()) createTag.mutate();
  };

  return (
    <section id="taxonomy" className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 mb-4">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">🏷 Taxonomy</h2>
          <p className="text-xs text-muted mt-1">Evidence tags used by review, Explore, and agents.</p>
        </div>
        {!canManage && <span className="text-xs text-muted">Admin access required to edit</span>}
      </div>

      {isLoading && <p className="text-sm text-muted">Loading taxonomy…</p>}
      {error && <p className="text-sm text-crit" role="alert">Failed to load taxonomy.</p>}
      {!isLoading && !error && (
        <div className="divide-y divide-hairline border border-hairline rounded-lg overflow-hidden">
          {tags.map((tag) => (
            <div key={tag.key} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <span className="text-lg w-6 text-center" aria-hidden="true">{tag.emoji}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium text-ink-2">{tag.name}</div>
                <div className="text-xs text-muted">
                  <code>{tag.key}</code> · {tag.signal_strength || 'unrated'}
                </div>
              </div>
              <span className={`text-xs ${tag.is_active ? 'text-good-text' : 'text-muted'}`}>
                {tag.is_active ? 'active' : 'inactive'}
              </span>
              {canManage && (
                <button
                  type="button"
                  className="px-2.5 py-1 text-xs border border-hairline rounded-md hover:border-accent disabled:opacity-50"
                  aria-label={`${tag.is_active ? 'Deactivate' : 'Activate'} ${tag.name}`}
                  disabled={toggleTag.isPending}
                  onClick={() => toggleTag.mutate({ tag, active: !tag.is_active })}
                >
                  {tag.is_active ? 'Deactivate' : 'Activate'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <MutationError error={toggleTag.error as Error | null} />

      {canManage && (
        <form onSubmit={handleCreate} className="mt-4 border-t border-hairline pt-4">
          <h3 className="text-sm font-medium mb-2">Add taxonomy tag</h3>
          <div className="grid grid-cols-[1fr_72px_1.5fr_130px_auto] gap-2">
            <input
              aria-label="New tag key"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="key"
              className="border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <input
              aria-label="New tag emoji"
              value={emoji}
              onChange={(event) => setEmoji(event.target.value)}
              placeholder="emoji"
              className="border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <input
              aria-label="New tag name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Display name"
              className="border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <select
              aria-label="New tag signal strength"
              value={signalStrength}
              onChange={(event) => setSignalStrength(event.target.value)}
              className="border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            >
              <option value="very strong">very strong</option>
              <option value="strong">strong</option>
              <option value="medium">medium</option>
              <option value="weak">weak</option>
              <option value="anti-signal">anti-signal</option>
              <option value="n/a">n/a</option>
            </select>
            <button
              type="submit"
              className="btn btn-primary whitespace-nowrap"
              disabled={!key.trim() || !emoji.trim() || !name.trim() || createTag.isPending}
            >
              Add tag
            </button>
          </div>
          <MutationError error={createTag.error as Error | null} />
        </form>
      )}
    </section>
  );
}

function DirectorySettings() {
  const queryClient = useQueryClient();
  const [companyName, setCompanyName] = useState('');
  const [companyDomain, setCompanyDomain] = useState('');
  const [contactName, setContactName] = useState('');
  const [contactRole, setContactRole] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactCompanyId, setContactCompanyId] = useState('');

  const companiesQuery = useQuery({
    queryKey: ['companies'],
    queryFn: () => api.listCompanies(),
  });
  const contactsQuery = useQuery({
    queryKey: ['contacts'],
    queryFn: () => api.listContacts(),
  });
  const companies = companiesQuery.data ?? [];
  const contacts = contactsQuery.data ?? [];

  const createCompany = useMutation({
    mutationFn: () => api.createCompany({
      name: companyName.trim(),
      domain: companyDomain.trim() || null,
    }),
    onSuccess: (created) => {
      queryClient.setQueryData<Company[]>(['companies'], (current = []) =>
        [...current, created].sort((a, b) => a.name.localeCompare(b.name)),
      );
      queryClient.invalidateQueries({ queryKey: ['settings-status'] });
      setCompanyName('');
      setCompanyDomain('');
    },
  });

  const createContact = useMutation({
    mutationFn: () => api.createContact({
      name: contactName.trim(),
      role: contactRole.trim() || null,
      email: contactEmail.trim() || null,
      company_id: contactCompanyId ? Number(contactCompanyId) : null,
    }),
    onSuccess: (created) => {
      queryClient.setQueryData<Contact[]>(['contacts'], (current = []) =>
        [...current, created].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setContactName('');
      setContactRole('');
      setContactEmail('');
      setContactCompanyId('');
    },
  });

  const companyById = new Map(companies.map((company) => [company.id, company]));

  return (
    <section id="directory" className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 mb-4">
      <h2 className="text-sm font-semibold text-ink">🏢 Companies &amp; contacts</h2>
      <p className="text-xs text-muted mt-1 mb-4">Directory entries can be reused when capturing conversations.</p>

      {(companiesQuery.error || contactsQuery.error) && (
        <p className="text-sm text-crit mb-3" role="alert">Failed to load the directory.</p>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">Companies</h3>
          <div className="border border-hairline rounded-lg divide-y divide-hairline max-h-64 overflow-auto">
            {companies.length === 0 && <p className="text-sm text-muted p-3">No companies yet.</p>}
            {companies.map((company) => {
              const count = company.conversation_count ?? 0;
              return (
                <div key={company.id} className="p-3 text-sm">
                  <div className="flex justify-between gap-2">
                    <Link to={`/companies/${company.id}`} className="font-medium text-accent hover:underline">
                      {company.name}
                    </Link>
                    <span className="text-xs text-muted">
                      {count} conversation{count === 1 ? '' : 's'}
                    </span>
                  </div>
                  {company.domain && <div className="text-xs text-muted mt-0.5">{company.domain}</div>}
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">Contacts</h3>
          <div className="border border-hairline rounded-lg divide-y divide-hairline max-h-64 overflow-auto">
            {contacts.length === 0 && <p className="text-sm text-muted p-3">No contacts yet.</p>}
            {contacts.map((contact) => (
              <div key={contact.id} className="p-3 text-sm">
                <Link to={`/contacts/${contact.id}`} className="font-medium text-accent hover:underline">
                  {contact.name}
                </Link>
                <div className="text-xs text-muted mt-0.5">
                  {[contact.role, contact.company_id ? companyById.get(contact.company_id)?.name : null]
                    .filter(Boolean).join(' · ') || 'No role or company'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 mt-4 border-t border-hairline pt-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (companyName.trim()) createCompany.mutate();
          }}
        >
          <h3 className="text-sm font-medium mb-2">Add company</h3>
          <div className="space-y-2">
            <input
              aria-label="New company name"
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
              placeholder="Company name"
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <input
              aria-label="New company domain"
              value={companyDomain}
              onChange={(event) => setCompanyDomain(event.target.value)}
              placeholder="Domain (optional)"
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!companyName.trim() || createCompany.isPending}
            >
              Add company
            </button>
          </div>
          <MutationError error={createCompany.error as Error | null} />
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (contactName.trim()) createContact.mutate();
          }}
        >
          <h3 className="text-sm font-medium mb-2">Add contact</h3>
          <div className="space-y-2">
            <input
              aria-label="New contact name"
              value={contactName}
              onChange={(event) => setContactName(event.target.value)}
              placeholder="Contact name"
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <input
              aria-label="New contact role"
              value={contactRole}
              onChange={(event) => setContactRole(event.target.value)}
              placeholder="Role (optional)"
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <input
              aria-label="New contact email"
              type="email"
              value={contactEmail}
              onChange={(event) => setContactEmail(event.target.value)}
              placeholder="Email (optional)"
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            />
            <select
              aria-label="New contact company"
              value={contactCompanyId}
              onChange={(event) => setContactCompanyId(event.target.value)}
              className="w-full border border-hairline rounded-lg px-2.5 py-2 bg-page text-sm"
            >
              <option value="">No company</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>{company.name}</option>
              ))}
            </select>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!contactName.trim() || createContact.isPending}
            >
              Add contact
            </button>
          </div>
          <MutationError error={createContact.error as Error | null} />
        </form>
      </div>
    </section>
  );
}

export function SettingsPage() {
  const location = useLocation();
  const { data: status, isLoading, error } = useQuery<SettingsStatus>({
    queryKey: ['settings-status'],
    queryFn: () => api.getSettingsStatus<SettingsStatus>(),
  });

  useEffect(() => {
    if (!status || !location.hash) return;
    const target = document.getElementById(location.hash.slice(1));
    target?.scrollIntoView({ block: 'start' });
  }, [location.hash, status]);

  if (isLoading) {
    return (
      <main className="flex-1 overflow-auto">
        <div className="max-w-[960px] mx-auto p-7 flex justify-center py-12">
          <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
        </div>
      </main>
    );
  }

  if (error || !status) {
    return (
      <main className="flex-1 overflow-auto">
        <div className="max-w-[960px] mx-auto p-7">
          <div className="p-4 bg-surface border border-crit/20 rounded-xl text-crit text-sm">
            Failed to load settings status.
          </div>
        </div>
      </main>
    );
  }

  const localBackend = status.llm.backend === 'local';
  const keyReady = localBackend || status.llm.api_key_configured;

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[960px] mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-2">Settings</h1>
        <p className="text-sm text-muted mb-6">
          Provider credentials and integrations are read-only environment configuration. Taxonomy and directory changes save immediately.
        </p>

        <section id="llm" className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">🔑 LLM &amp; API configuration</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted">Backend</span>
              <div className="font-medium">{status.llm.backend}</div>
            </div>
            <div>
              <span className="text-muted">Credential status</span>
              <div className="font-medium">
                <StatusDot ok={keyReady} />
                {localBackend
                  ? 'OpenAI key not required for the local backend'
                  : status.llm.api_key_hint}
              </div>
            </div>
            {localBackend ? (
              <div className="col-span-2">
                <span className="text-muted">Model for all stages</span>
                <div className="font-medium">{status.llm.model_tagger}</div>
              </div>
            ) : (
              <>
                <div><span className="text-muted">Normalizer model</span><div className="font-medium">{status.llm.model_normalizer}</div></div>
                <div><span className="text-muted">Tagger model</span><div className="font-medium">{status.llm.model_tagger}</div></div>
                <div><span className="text-muted">Analyst model</span><div className="font-medium">{status.llm.model_analyst}</div></div>
                <div><span className="text-muted">Synthesizer model</span><div className="font-medium">{status.llm.model_synthesizer}</div></div>
              </>
            )}
          </div>
          <p className="text-xs text-muted mt-3">
            Change <code>LLM_BACKEND</code>, provider credentials, and model variables in <code>.env</code> or deployment secrets, then restart MomBoard.
          </p>
        </section>

        <section id="sources" className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">🔌 Sources &amp; delivery</h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between items-center gap-4">
              <div><Link to="/meetings" className="font-medium text-accent hover:underline">🤖 Vexa meeting bots</Link><div className="text-xs text-muted">VEXA_BASE_URL + VEXA_API_KEY</div></div>
              <span className={status.vexa.configured ? 'text-good-text' : 'text-muted'}><StatusDot ok={status.vexa.configured} />{status.vexa.detail}</span>
            </div>
            <div className="flex justify-between items-center gap-4">
              <div><span className="font-medium">📁 Google Drive sync</span><div className="text-xs text-muted">GDRIVE_FOLDER_ID + GDRIVE_SERVICE_ACCOUNT_JSON</div></div>
              <span className={status.gdrive.configured ? 'text-good-text' : 'text-muted'}><StatusDot ok={status.gdrive.configured} />{status.gdrive.detail}</span>
            </div>
            <div className="flex justify-between items-center gap-4">
              <div><Link to="/digest" className="font-medium text-accent hover:underline">📬 Weekly digest</Link><div className="text-xs text-muted">SLACK_WEBHOOK_URL · Monday 08:00 UTC</div></div>
              <span className={status.slack.configured ? 'text-good-text' : 'text-muted'}><StatusDot ok={status.slack.configured} />{status.digest.schedule}</span>
            </div>
          </div>
        </section>

        <section className="bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">📊 Data summary</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-muted">Taxonomy tags</span><div className="font-medium">{status.taxonomy_count}</div></div>
            <div><span className="text-muted">Active companies</span><div className="font-medium">{status.active_company_count}</div></div>
          </div>
        </section>

        <TaxonomySettings canManage={status.can_manage_taxonomy === true} />
        <DirectorySettings />
      </div>
    </main>
  );
}

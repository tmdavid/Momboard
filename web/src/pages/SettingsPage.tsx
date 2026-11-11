import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { CompanyProfileCard, RetagProgressCard, TagDetailsEditor } from '../components/SettingsV05';
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
    credential_ready: boolean;
    credential_label: string;
    single_model: boolean;
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
      className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-good' : 'bg-[#d0d5dd]'}`}
    />
  );
}

function MutationError({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p className="text-xs text-crit mt-2" role="alert">{error.message}</p>;
}

/** Card wrapper matching the mockup (white, 1px line, 12px radius, 20px pad). */
function Card({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 bg-surface border border-hairline rounded-xl p-5 flex flex-col gap-3">
      {children}
    </section>
  );
}

function AiModelSettings({ status }: { status: SettingsStatus }) {
  const [showId, setShowId] = useState(false);
  const llm = status.llm;
  // Friendly provider label (no raw ARN / account id in the main UI).
  const provider = llm.backend === 'bedrock' ? 'AWS Bedrock' : llm.backend === 'local' ? 'Local (Ollama)' : 'OpenAI';
  const friendlyModel = llm.single_model ? 'Single model' : 'Per-stage models';

  return (
    <Card id="llm">
      <div className="flex flex-col">
        <h2 className="text-base font-semibold text-ink">AI model</h2>
        <span className="text-[13px] text-muted">Read-only. Change it in your environment variables, then restart.</span>
      </div>
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted">Provider</span>
          <span className="font-semibold text-ink">{provider}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted">Model</span>
          <span className="font-semibold text-ink flex items-center gap-2">
            {friendlyModel}
            <button
              type="button"
              onClick={() => setShowId((v) => !v)}
              className="text-xs font-medium text-accent bg-transparent border-none cursor-pointer p-0"
            >
              {showId ? 'hide ID' : 'show ID'}
            </button>
          </span>
          {showId && (
            <span className="text-xs text-muted font-mono break-all mt-0.5">
              {llm.single_model
                ? llm.model_tagger
                : `normalizer=${llm.model_normalizer} · tagger=${llm.model_tagger} · analyst=${llm.model_analyst} · synthesizer=${llm.model_synthesizer}`}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted">Credentials</span>
          <span className={`font-semibold flex items-center gap-1.5 ${llm.credential_ready ? 'text-good-text' : 'text-muted'}`}>
            <StatusDot ok={llm.credential_ready} />
            {llm.credential_label}
          </span>
        </div>
      </div>
    </Card>
  );
}

function SourcesSettings({ status }: { status: SettingsStatus }) {
  const rows = [
    { name: 'Meeting bots', desc: 'Send a bot to record and transcribe calls', ok: status.vexa.configured, detail: status.vexa.detail, to: '/meetings' },
    { name: 'Google Drive sync', desc: 'Import transcripts from a shared folder', ok: status.gdrive.configured, detail: status.gdrive.detail, to: null },
    { name: 'Weekly digest', desc: 'Post a summary to Slack every Monday 08:00 UTC', ok: status.slack.configured, detail: status.digest.schedule, to: '/digest' },
  ];
  return (
    <Card id="sources">
      <h2 className="text-base font-semibold text-ink">Sources and delivery</h2>
      {rows.map((r) => (
        <div key={r.name} className="flex flex-wrap items-center gap-3 py-2.5 border-t border-sub">
          <div className="flex flex-col min-w-0">
            {r.to ? (
              <Link to={r.to} className="font-semibold text-ink hover:underline">{r.name}</Link>
            ) : (
              <span className="font-semibold text-ink">{r.name}</span>
            )}
            <span className="text-xs text-muted">{r.desc}</span>
          </div>
          <span className={`ml-auto flex items-center gap-1.5 text-[13px] ${r.ok ? 'text-good-text' : 'text-muted'}`}>
            <StatusDot ok={r.ok} />
            {r.ok ? r.detail || 'Connected' : 'Not set up'}
          </span>
        </div>
      ))}
    </Card>
  );
}

function ActiveSwitch({ on, disabled, onToggle, label }: { on: boolean; disabled: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className={`inline-flex w-9 h-5 rounded-pill p-0.5 box-border border-none cursor-pointer disabled:opacity-50 ${
        on ? 'bg-accent justify-end' : 'bg-[#d0d5dd] justify-start'
      }`}
    >
      <span className="w-4 h-4 rounded-pill bg-white shadow" />
    </button>
  );
}

function TaxonomySettings({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState('');
  const [emoji, setEmoji] = useState('');
  const [name, setName] = useState('');
  const [signalStrength, setSignalStrength] = useState('medium');
  const [category, setCategory] = useState('');
  const [view, setView] = useState<'core' | 'custom'>('core');
  const [showAdd, setShowAdd] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);

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

  const reorderTag = useMutation({
    mutationFn: async ({ tag, direction }: { tag: Tag; direction: 'up' | 'down' }) => {
      const ordered = [...tags].sort((a, b) => a.sort_order - b.sort_order);
      const idx = ordered.findIndex((t) => t.key === tag.key);
      const neighborIdx = direction === 'up' ? idx - 1 : idx + 1;
      if (neighborIdx < 0 || neighborIdx >= ordered.length) return;
      const neighbor = ordered[neighborIdx];
      await api.updateTag(tag.key, { sort_order: neighbor.sort_order });
      await api.updateTag(neighbor.key, { sort_order: tag.sort_order });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tags'] }),
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
      origin: 'custom',
      category: category.trim() || null,
    }),
    onSuccess: (created) => {
      queryClient.setQueryData<Tag[]>(['tags'], (current = []) =>
        [...current, created].sort((a, b) => a.sort_order - b.sort_order),
      );
      setKey(''); setEmoji(''); setName(''); setSignalStrength('medium'); setCategory('');
      setShowAdd(false);
    },
  });

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim() && emoji.trim() && name.trim()) createTag.mutate();
  };

  const existingCategories = Array.from(
    new Set(tags.map((tag) => tag.category).filter((c): c is string => !!c)),
  ).sort((a, b) => a.localeCompare(b));

  const ordered = [...tags].sort((a, b) => a.sort_order - b.sort_order);
  const shown = ordered.filter((t) => (view === 'core' ? t.origin === 'core' : t.origin !== 'core'));
  const coreCount = ordered.filter((t) => t.origin === 'core').length;
  const customCount = ordered.length - coreCount;

  return (
    <Card id="taxonomy">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <h2 className="text-base font-semibold text-ink">Taxonomy</h2>
          <span className="text-[13px] text-muted">{coreCount} core · {customCount} custom tags. Changes save immediately.</span>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setShowAdd((v) => !v)}
            className="btn btn-sm btn-primary ml-auto"
          >
            Add tag
          </button>
        )}
        {!canManage && <span className="ml-auto text-xs text-muted">Admin access required to edit</span>}
      </div>

      {/* Core | Custom segmented control */}
      <div className="flex gap-0.5 p-0.5 rounded-lg bg-sub self-start" role="tablist" aria-label="Tag type">
        {(['core', 'custom'] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`h-[30px] px-3 rounded-md border-none font-semibold capitalize cursor-pointer ${
              view === v ? 'bg-surface text-ink shadow-sm' : 'bg-transparent text-ink-2'
            }`}
          >
            {v}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-sm text-muted">Loading taxonomy…</p>}
      {error && <p className="text-sm text-crit" role="alert">Failed to load taxonomy.</p>}
      {!isLoading && !error && (
        <div className="overflow-x-auto">
          <div className="min-w-[600px]">
            <div className="grid items-center gap-3 py-2 text-xs font-semibold text-muted border-b border-hairline"
              style={{ gridTemplateColumns: canManage ? '44px 32px minmax(0,1fr) 130px 110px 90px' : '32px minmax(0,1fr) 130px 110px 90px' }}>
              {canManage && <span />}
              <span />
              <span>Tag</span>
              <span>Category</span>
              <span>Strength</span>
              <span className="text-right">Active</span>
            </div>
            {shown.map((tag, idx) => (
              <div key={tag.key} className="border-b border-sub">
              <div className="grid items-center gap-3 py-2.5"
                style={{ gridTemplateColumns: canManage ? '44px 32px minmax(0,1fr) 130px 110px 90px' : '32px minmax(0,1fr) 130px 110px 90px' }}>
                {canManage && (
                  <div className="flex flex-col">
                    <button type="button" aria-label={`Move ${tag.name} up`} disabled={idx === 0 || reorderTag.isPending}
                      onClick={() => reorderTag.mutate({ tag, direction: 'up' })}
                      className="text-xs leading-none text-muted hover:text-accent disabled:opacity-30 bg-transparent border-none cursor-pointer px-1">▲</button>
                    <button type="button" aria-label={`Move ${tag.name} down`} disabled={idx === shown.length - 1 || reorderTag.isPending}
                      onClick={() => reorderTag.mutate({ tag, direction: 'down' })}
                      className="text-xs leading-none text-muted hover:text-accent disabled:opacity-30 bg-transparent border-none cursor-pointer px-1">▼</button>
                  </div>
                )}
                <span className="text-lg text-center" aria-hidden="true">{tag.emoji}</span>
                <div className="min-w-0 flex flex-col">
                  <span className="trunc font-semibold text-ink">{tag.name}</span>
                  {tag.description && <span className="trunc text-xs text-muted" title={tag.description}>{tag.description}</span>}
                </div>
                <span>
                  {tag.category
                    ? <span className="text-xs font-semibold px-2.5 py-0.5 rounded-pill bg-sub text-ink-2 capitalize">{tag.category}</span>
                    : <span className="text-xs text-muted">—</span>}
                </span>
                <span className="text-[13px]">{tag.signal_strength || 'n/a'}</span>
                <span className="flex justify-end">
                  {canManage
                    ? <ActiveSwitch on={tag.is_active} disabled={toggleTag.isPending}
                        onToggle={() => toggleTag.mutate({ tag, active: !tag.is_active })}
                        label={`${tag.is_active ? 'Deactivate' : 'Activate'} ${tag.name}`} />
                    : <span className={`text-xs ${tag.is_active ? 'text-good-text' : 'text-muted'}`}>{tag.is_active ? 'active' : 'inactive'}</span>}
                </span>
              </div>
              {canManage && (
                <div className="pb-2.5 pl-[44px]">
                  <button type="button" aria-expanded={editingKey === tag.key}
                    aria-label={`Edit tagging details for ${tag.name}`}
                    onClick={() => setEditingKey(editingKey === tag.key ? null : tag.key)}
                    className="text-xs font-semibold text-accent bg-transparent border-none p-0 cursor-pointer hover:underline">
                    {editingKey === tag.key ? 'Hide tagging details' : `Tagging details · floor ${(tag.min_confidence ?? 0.5).toFixed(2)}`}
                  </button>
                  {editingKey === tag.key && <div className="mt-2"><TagDetailsEditor tag={tag} /></div>}
                </div>
              )}
              </div>
            ))}
            {shown.length === 0 && <p className="text-sm text-muted py-4">No {view} tags.</p>}
          </div>
        </div>
      )}
      <MutationError error={toggleTag.error as Error | null} />

      {canManage && showAdd && (
        <form onSubmit={handleCreate} className="border-t border-hairline pt-4 flex flex-col gap-2">
          <h3 className="text-sm font-medium">Add taxonomy tag</h3>
          <div className="grid gap-2" style={{ gridTemplateColumns: '1fr 72px 1.5fr 130px 130px auto' }}>
            <input aria-label="New tag key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="key" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
            <input aria-label="New tag emoji" value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="emoji" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
            <input aria-label="New tag name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
            <select aria-label="New tag signal strength" value={signalStrength} onChange={(e) => setSignalStrength(e.target.value)} className="border border-hairline rounded-lg px-2.5 py-2 text-sm">
              <option value="very strong">very strong</option>
              <option value="strong">strong</option>
              <option value="medium">medium</option>
              <option value="weak">weak</option>
              <option value="anti-signal">anti-signal</option>
              <option value="n/a">n/a</option>
            </select>
            <input aria-label="New tag category" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="category" list="tag-category-suggestions" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
            <datalist id="tag-category-suggestions">
              {existingCategories.map((cat) => <option key={cat} value={cat} />)}
            </datalist>
            <button type="submit" className="btn btn-sm btn-primary whitespace-nowrap" disabled={!key.trim() || !emoji.trim() || !name.trim() || createTag.isPending}>Add tag</button>
          </div>
          <MutationError error={createTag.error as Error | null} />
        </form>
      )}
    </Card>
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
  const [search, setSearch] = useState('');

  const companiesQuery = useQuery({ queryKey: ['companies'], queryFn: () => api.listCompanies() });
  const contactsQuery = useQuery({ queryKey: ['contacts'], queryFn: () => api.listContacts() });
  const companies = companiesQuery.data ?? [];
  const contacts = contactsQuery.data ?? [];

  const createCompany = useMutation({
    mutationFn: () => api.createCompany({ name: companyName.trim(), domain: companyDomain.trim() || null }),
    onSuccess: (created) => {
      queryClient.setQueryData<Company[]>(['companies'], (current = []) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      queryClient.invalidateQueries({ queryKey: ['settings-status'] });
      setCompanyName(''); setCompanyDomain('');
    },
  });

  const createContact = useMutation({
    mutationFn: () => api.createContact({
      name: contactName.trim(), role: contactRole.trim() || null, email: contactEmail.trim() || null,
      company_id: contactCompanyId ? Number(contactCompanyId) : null,
    }),
    onSuccess: (created) => {
      queryClient.setQueryData<Contact[]>(['contacts'], (current = []) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setContactName(''); setContactRole(''); setContactEmail(''); setContactCompanyId('');
    },
  });

  const companyById = new Map(companies.map((c) => [c.id, c]));
  const q = search.trim().toLowerCase();
  const shownCompanies = q ? companies.filter((c) => c.name.toLowerCase().includes(q)) : companies;

  return (
    <Card id="directory">
      <div className="flex items-center gap-3">
        <h2 className="text-base font-semibold text-ink">Companies and contacts</h2>
        <span className="text-[13px] text-muted">{companies.length} companies</span>
      </div>
      {(companiesQuery.error || contactsQuery.error) && <p className="text-sm text-crit" role="alert">Failed to load the directory.</p>}

      <label className="flex items-center gap-2 h-[38px] px-3 rounded-lg border border-hairline text-muted">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
        <input aria-label="Find a company" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a company" className="flex-1 bg-transparent border-none outline-none text-ink-2 placeholder:text-muted" />
      </label>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <h3 className="text-xs font-semibold text-muted mb-2">Companies</h3>
          <div className="border border-hairline rounded-lg divide-y divide-sub max-h-64 overflow-auto">
            {shownCompanies.length === 0 && <p className="text-sm text-muted p-3">No companies.</p>}
            {shownCompanies.map((company) => {
              const count = company.conversation_count ?? 0;
              return (
                <div key={company.id} className="p-3 text-sm flex items-center gap-2">
                  <Link to={`/companies/${company.id}`} className="trunc font-semibold text-ink hover:underline">{company.name}</Link>
                  <span className="ml-auto text-xs text-muted whitespace-nowrap">{count} conversation{count === 1 ? '' : 's'}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div>
          <h3 className="text-xs font-semibold text-muted mb-2">Contacts</h3>
          <div className="border border-hairline rounded-lg divide-y divide-sub max-h-64 overflow-auto">
            {contacts.length === 0 && <p className="text-sm text-muted p-3">No contacts.</p>}
            {contacts.map((contact) => (
              <div key={contact.id} className="p-3 text-sm">
                <Link to={`/contacts/${contact.id}`} className="font-semibold text-ink hover:underline">{contact.name}</Link>
                <div className="text-xs text-muted mt-0.5">
                  {[contact.role, contact.company_id ? companyById.get(contact.company_id)?.name : null].filter(Boolean).join(' · ') || 'No role or company'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 border-t border-hairline pt-4">
        <form onSubmit={(e) => { e.preventDefault(); if (companyName.trim()) createCompany.mutate(); }} className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Add company</h3>
          <input aria-label="New company name" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Company name" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
          <input aria-label="New company domain" value={companyDomain} onChange={(e) => setCompanyDomain(e.target.value)} placeholder="Domain (optional)" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
          <button type="submit" className="btn btn-sm btn-primary self-start" disabled={!companyName.trim() || createCompany.isPending}>Add company</button>
          <MutationError error={createCompany.error as Error | null} />
        </form>
        <form onSubmit={(e) => { e.preventDefault(); if (contactName.trim()) createContact.mutate(); }} className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Add contact</h3>
          <input aria-label="New contact name" value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder="Contact name" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
          <input aria-label="New contact role" value={contactRole} onChange={(e) => setContactRole(e.target.value)} placeholder="Role (optional)" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
          <input aria-label="New contact email" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} placeholder="Email (optional)" className="border border-hairline rounded-lg px-2.5 py-2 text-sm" />
          <select aria-label="New contact company" value={contactCompanyId} onChange={(e) => setContactCompanyId(e.target.value)} className="border border-hairline rounded-lg px-2.5 py-2 text-sm">
            <option value="">No company</option>
            {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
          </select>
          <button type="submit" className="btn btn-sm btn-primary self-start" disabled={!contactName.trim() || createContact.isPending}>Add contact</button>
          <MutationError error={createContact.error as Error | null} />
        </form>
      </div>
    </Card>
  );
}

const SECTIONS = [
  { label: 'AI model', href: '#llm' },
  { label: 'Sources and delivery', href: '#sources' },
  { label: 'Your company', href: '#company' },
  { label: 'Taxonomy', href: '#taxonomy' },
  { label: 'Retag progress', href: '#retag' },
  { label: 'Companies and contacts', href: '#directory' },
];

export function SettingsPage() {
  const location = useLocation();
  const { data: status, isLoading, error } = useQuery<SettingsStatus>({
    queryKey: ['settings-status'],
    queryFn: () => api.getSettingsStatus<SettingsStatus>(),
  });

  useEffect(() => {
    if (!status || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [location.hash, status]);

  if (isLoading) {
    return (
      <main className="p-6 flex justify-center">
        <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow mt-8" />
      </main>
    );
  }
  if (error || !status) {
    return (
      <main className="p-6">
        <div className="p-4 bg-surface border border-crit/20 rounded-xl text-crit text-sm">Failed to load settings status.</div>
      </main>
    );
  }

  return (
    <main className="p-6 flex flex-wrap gap-6 items-start">
      <nav aria-label="Settings sections" className="flex-[1_1_180px] max-w-[200px] flex flex-col gap-0.5">
        <h1 className="text-2xl font-bold text-ink mb-3">Settings</h1>
        {SECTIONS.map((s, i) => (
          <a key={s.href} href={s.href}
            className={`block px-3 py-2 rounded-lg font-medium ${i === 0 ? '' : ''} text-ink-2 hover:bg-sub`}>
            {s.label}
          </a>
        ))}
      </nav>
      <div className="flex-[999_1_560px] min-w-0 flex flex-col gap-4">
        <AiModelSettings status={status} />
        <SourcesSettings status={status} />
        <CompanyProfileCard canManage={status.can_manage_taxonomy === true} />
        <TaxonomySettings canManage={status.can_manage_taxonomy === true} />
        <RetagProgressCard canManage={status.can_manage_taxonomy === true} />
        <DirectorySettings />
      </div>
    </main>
  );
}

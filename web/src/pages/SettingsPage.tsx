import { useQuery } from '@tanstack/react-query';

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
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full mr-2 ${ok ? 'bg-good' : 'bg-hairline'}`} />
  );
}

export function SettingsPage() {
  const { data: status, isLoading, error } = useQuery<SettingsStatus>({
    queryKey: ['settings-status'],
    queryFn: async () => {
      const res = await fetch('/api/settings/status', { credentials: 'include' });
      if (!res.ok) throw new Error('Failed to load settings');
      return res.json();
    },
  });

  if (isLoading) {
    return (
      <main className="flex-1 overflow-auto">
        <div className="max-w-[800px] mx-auto p-7">
          <div className="flex justify-center py-12">
            <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
          </div>
        </div>
      </main>
    );
  }

  if (error || !status) {
    return (
      <main className="flex-1 overflow-auto">
        <div className="max-w-[800px] mx-auto p-7">
          <div className="p-4 bg-surface border border-crit/20 rounded-xl text-crit text-sm">
            Failed to load settings status.
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="flex-1 overflow-auto">
      <div className="max-w-[800px] mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-6">Settings</h1>
        <p className="text-sm text-muted mb-6">
          Read-only system status. Configuration is managed via environment variables.
        </p>

        {/* LLM section */}
        <section className="bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">🔑 LLM &amp; API Configuration</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted">Backend</span>
              <div className="font-medium">{status.llm.backend}</div>
            </div>
            <div>
              <span className="text-muted">API Key</span>
              <div className="font-medium">
                <StatusDot ok={status.llm.api_key_configured} />
                {status.llm.api_key_hint}
              </div>
            </div>
            <div>
              <span className="text-muted">Normalizer model</span>
              <div className="font-medium">{status.llm.model_normalizer}</div>
            </div>
            <div>
              <span className="text-muted">Tagger model</span>
              <div className="font-medium">{status.llm.model_tagger}</div>
            </div>
            <div>
              <span className="text-muted">Analyst model</span>
              <div className="font-medium">{status.llm.model_analyst}</div>
            </div>
            <div>
              <span className="text-muted">Synthesizer model</span>
              <div className="font-medium">{status.llm.model_synthesizer}</div>
            </div>
          </div>
        </section>

        {/* Services section */}
        <section className="bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">🔌 Connected Services</h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between items-center">
              <span>🤖 Vexa Meeting Bots</span>
              <span className={status.vexa.configured ? 'text-good-text' : 'text-muted'}>
                <StatusDot ok={status.vexa.configured} />
                {status.vexa.detail}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span>📁 Google Drive</span>
              <span className={status.gdrive.configured ? 'text-good-text' : 'text-muted'}>
                <StatusDot ok={status.gdrive.configured} />
                {status.gdrive.detail}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span>💬 Slack Webhook</span>
              <span className={status.slack.configured ? 'text-good-text' : 'text-muted'}>
                <StatusDot ok={status.slack.configured} />
                {status.slack.detail}
              </span>
            </div>
          </div>
        </section>

        {/* Digest section */}
        <section className="bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">📬 Digest Schedule</h2>
          <div className="text-sm">
            <StatusDot ok={status.digest.slack_configured} />
            {status.digest.schedule}
          </div>
        </section>

        {/* Counts section */}
        <section className="bg-surface border border-hairline rounded-xl p-5 mb-4">
          <h2 className="text-sm font-semibold mb-3 text-ink">📊 Data Summary</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted">Taxonomy tags</span>
              <div className="font-medium">{status.taxonomy_count}</div>
            </div>
            <div>
              <span className="text-muted">Active companies</span>
              <div className="font-medium">{status.active_company_count}</div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { renderSafeMarkdown } from '../utils/markdown';

export function DigestPage() {
  const [previewLoading, setPreviewLoading] = useState(false);

  const { data: preview, refetch: refetchPreview } = useQuery({
    queryKey: ['digest-preview'],
    queryFn: async () => {
      const res = await fetch('/api/digest/preview', { credentials: 'include' });
      if (!res.ok) return null;
      return res.json() as Promise<{ markdown: string }>;
    },
    enabled: false,
  });

  const handlePreview = async () => {
    setPreviewLoading(true);
    await refetchPreview();
    setPreviewLoading(false);
  };

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-xl font-bold tracking-tight mb-6">Weekly Digest</h1>

      {/* Preview button */}
      <div className="mb-6">
        <button
          onClick={handlePreview}
          disabled={previewLoading}
          aria-busy={previewLoading}
          className="btn btn-primary"
          data-testid="digest-preview-btn"
        >
          {previewLoading ? 'Generating...' : 'Preview This Week'}
        </button>
      </div>

      {/* Preview content — Slack-like rendered markdown */}
      {preview?.markdown && (
        <div
          className="max-w-none p-4 bg-surface rounded-xl border border-hairline"
          data-testid="digest-preview"
        >
          <div className="flex items-center gap-2 mb-3 pb-3 border-b border-hairline">
            <div className="w-8 h-8 rounded bg-accent-soft grid place-items-center text-accent font-bold text-sm">M</div>
            <div>
              <span className="font-semibold text-sm text-ink-2">MomBoard</span>
              <span className="text-xs text-muted ml-2">Weekly Digest</span>
            </div>
          </div>
          <div
            className="prose prose-sm text-sm leading-relaxed [&_li]:ml-4 [&_li]:list-disc"
            dangerouslySetInnerHTML={{ __html: renderSafeMarkdown(preview.markdown, 'digest') }}
          />
        </div>
      )}

      {/* Settings section */}
      <section className="mt-8 border-t border-hairline pt-6">
        <h2 className="text-lg font-semibold mb-4 text-ink-2">Delivery Settings</h2>
        <p className="text-sm text-muted mb-4">
          The digest is automatically sent every Monday at 08:00 UTC to the configured Slack webhook.
        </p>
        <div className="text-sm text-ink-2">
          <p>Slack webhook: configured via <code className="bg-page px-1 rounded">SLACK_WEBHOOK_URL</code> environment variable.</p>
          <p className="mt-2">Digest includes: new commitments, overdue follow-ups, hypothesis movements, drift alerts, stale evidence, and an AI-generated insight.</p>
        </div>
      </section>
    </div>
  );
}

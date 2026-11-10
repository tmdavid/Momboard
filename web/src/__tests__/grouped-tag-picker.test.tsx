import { describe, test, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode } from 'react';
import { server } from '../test/mocks/server';
import { useTaxonomy } from '../hooks/useTaxonomy';

/**
 * T47 Step 2: useTaxonomy groups tags for the menus — "Core" first, then one
 * group per custom category (alphabetical), then "Other" for uncategorized
 * custom tags. Fully data-driven: a new category must appear with no code change.
 */
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function mockTags() {
  server.use(
    http.get('/api/tags', () =>
      HttpResponse.json([
        { key: 'pain', emoji: '⚡', name: 'Pain', description: null, signal_strength: 'strong', sort_order: 1, is_active: true, origin: 'core', category: null },
        { key: 'money', emoji: '💰', name: 'Money', description: null, signal_strength: 'strong', sort_order: 3, is_active: true, origin: 'core', category: null },
        { key: 'ch_slack', emoji: '💬', name: 'Slack', description: null, signal_strength: null, sort_order: 20, is_active: true, origin: 'custom', category: 'channel' },
        { key: 'pr_billing', emoji: '💳', name: 'Billing', description: null, signal_strength: null, sort_order: 21, is_active: true, origin: 'custom', category: 'product' },
        { key: 'ch_email', emoji: '📧', name: 'Email', description: null, signal_strength: null, sort_order: 22, is_active: true, origin: 'custom', category: 'channel' },
        { key: 'loose', emoji: '🔖', name: 'Loose', description: null, signal_strength: null, sort_order: 23, is_active: true, origin: 'custom', category: null },
      ]),
    ),
  );
}

describe('useTaxonomy grouping', () => {
  test('orders Core, then categories alphabetically, then Other', async () => {
    mockTags();
    const { result } = renderHook(() => useTaxonomy(), { wrapper });

    await waitFor(() => expect(result.current.tags.length).toBe(6));

    const labels = result.current.groups.map((g) => g.label);
    expect(labels).toEqual(['Core', 'channel', 'product', 'Other']);

    const core = result.current.groups.find((g) => g.label === 'Core')!;
    expect(core.tags.map((t) => t.key)).toEqual(['pain', 'money']);

    const channel = result.current.groups.find((g) => g.label === 'channel')!;
    expect(channel.tags.map((t) => t.key)).toEqual(['ch_slack', 'ch_email']);

    const other = result.current.groups.find((g) => g.label === 'Other')!;
    expect(other.tags.map((t) => t.key)).toEqual(['loose']);
  });

  test('custom emoji/name resolve from the live taxonomy', async () => {
    mockTags();
    const { result } = renderHook(() => useTaxonomy(), { wrapper });
    await waitFor(() => expect(result.current.tags.length).toBe(6));
    expect(result.current.emoji('ch_slack')).toBe('💬');
    expect(result.current.name('ch_slack')).toBe('Slack');
  });
});

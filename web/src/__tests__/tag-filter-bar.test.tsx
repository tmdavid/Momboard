import { describe, test, expect, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode } from 'react';
import { server } from '../test/mocks/server';
import { TagFilterBar } from '../components/TagFilterBar';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// 12 core (fills the quick row) + 3 custom across 2 categories.
function mockManyTags() {
  const core = Array.from({ length: 12 }, (_, i) => ({
    key: `core_${i}`, emoji: '🔵', name: `Core ${i}`, description: null,
    signal_strength: null, sort_order: i + 1, is_active: true, origin: 'core', category: null,
  }));
  const custom = [
    { key: 'ch_slack', emoji: '💬', name: 'Slack', description: null, signal_strength: null, sort_order: 20, is_active: true, origin: 'custom', category: 'channel' },
    { key: 'ch_email', emoji: '📧', name: 'Email', description: null, signal_strength: null, sort_order: 21, is_active: true, origin: 'custom', category: 'channel' },
    { key: 'sa_objection', emoji: '✋', name: 'Objection', description: null, signal_strength: null, sort_order: 22, is_active: true, origin: 'custom', category: 'sales' },
  ];
  server.use(http.get('/api/tags', () => HttpResponse.json([...core, ...custom])));
}

describe('TagFilterBar', () => {
  test('quick row shows the top 10; custom tags are behind the Custom dropdown', async () => {
    mockManyTags();
    render(<TagFilterBar isActive={() => false} onToggle={() => {}} />, { wrapper });

    // Quick row = first 10 by sort_order (core_0..core_9). core_10/11 and custom are not inline.
    await waitFor(() => expect(screen.getByText(/Core 0/)).toBeInTheDocument());
    expect(screen.getByText(/Core 9/)).toBeInTheDocument();
    // Custom tags are NOT visible until the Custom dropdown + its category are opened.
    expect(screen.queryByText(/Slack/)).not.toBeInTheDocument();
    // Core and Custom dropdown triggers exist.
    expect(screen.getByRole('button', { name: /^Core ▾/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Custom ▾/ })).toBeInTheDocument();
  });

  test('Custom dropdown shows categories; expanding a category reveals its tags (accordion)', async () => {
    mockManyTags();
    render(<TagFilterBar isActive={() => false} onToggle={() => {}} />, { wrapper });

    await userEvent.click(await screen.findByRole('button', { name: /^Custom ▾/ }));
    const panel = screen.getByTestId('custom-categories');

    // Categories are listed; their tags are NOT shown yet.
    expect(within(panel).getByRole('button', { name: /channel/i })).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /sales/i })).toBeInTheDocument();
    expect(within(panel).queryByText(/Slack/)).not.toBeInTheDocument();

    // Expand "channel" — its tags appear; categories stay visible (accordion).
    await userEvent.click(within(panel).getByRole('button', { name: /channel/i }));
    expect(within(panel).getByRole('menuitemcheckbox', { name: /Slack/ })).toBeInTheDocument();
    expect(within(panel).getByRole('menuitemcheckbox', { name: /Email/ })).toBeInTheDocument();
    // sales category header still visible after expanding channel.
    expect(within(panel).getByRole('button', { name: /sales/i })).toBeInTheDocument();
    // sales tags still hidden (only channel was expanded).
    expect(within(panel).queryByText(/Objection/)).not.toBeInTheDocument();
  });

  test('toggling a tag inside a category calls onToggle with its key', async () => {
    mockManyTags();
    const onToggle = vi.fn();
    render(<TagFilterBar isActive={() => false} onToggle={onToggle} />, { wrapper });

    await userEvent.click(await screen.findByRole('button', { name: /^Custom ▾/ }));
    const panel = screen.getByTestId('custom-categories');
    await userEvent.click(within(panel).getByRole('button', { name: /channel/i }));
    await userEvent.click(within(panel).getByRole('menuitemcheckbox', { name: /Slack/ }));
    expect(onToggle).toHaveBeenCalledWith('ch_slack');
  });

  test('clicking a quick-row chip calls onToggle', async () => {
    mockManyTags();
    const onToggle = vi.fn();
    render(<TagFilterBar isActive={() => false} onToggle={onToggle} />, { wrapper });

    await userEvent.click(await screen.findByRole('button', { name: /Core 0/ }));
    expect(onToggle).toHaveBeenCalledWith('core_0');
  });
});

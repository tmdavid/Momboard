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

// 12 tags: 10 core (quick row fills), + 2 custom with a category so expansion shows groups.
function mockManyTags() {
  const core = Array.from({ length: 10 }, (_, i) => ({
    key: `core_${i}`, emoji: '🔵', name: `Core ${i}`, description: null,
    signal_strength: null, sort_order: i + 1, is_active: true, origin: 'core', category: null,
  }));
  const custom = [
    { key: 'ch_slack', emoji: '💬', name: 'Slack', description: null, signal_strength: null, sort_order: 20, is_active: true, origin: 'custom', category: 'channel' },
    { key: 'loose', emoji: '🔖', name: 'Loose', description: null, signal_strength: null, sort_order: 21, is_active: true, origin: 'custom', category: null },
  ];
  server.use(http.get('/api/tags', () => HttpResponse.json([...core, ...custom])));
}

describe('TagFilterBar', () => {
  test('shows a quick row of the top 10 and hides the rest behind More', async () => {
    mockManyTags();
    render(<TagFilterBar isActive={() => false} onToggle={() => {}} />, { wrapper });

    // Quick row: the 10 core chips are visible; the custom tags are not yet.
    await waitFor(() => expect(screen.getByText(/Core 0/)).toBeInTheDocument());
    expect(screen.queryByText(/Slack/)).not.toBeInTheDocument();

    // Expand
    await userEvent.click(screen.getByRole('button', { name: /More/ }));

    const groups = screen.getByTestId('tag-filter-groups');
    expect(within(groups).getByText('Core')).toBeInTheDocument();
    expect(within(groups).getByText('channel')).toBeInTheDocument();
    expect(within(groups).getByText('Other')).toBeInTheDocument();
    expect(within(groups).getByRole('button', { name: /Slack/ })).toBeInTheDocument();
  });

  test('clicking a chip calls onToggle with the tag key', async () => {
    mockManyTags();
    const onToggle = vi.fn();
    render(<TagFilterBar isActive={() => false} onToggle={onToggle} />, { wrapper });

    const chip = await screen.findByRole('button', { name: /Core 0/ });
    await userEvent.click(chip);
    expect(onToggle).toHaveBeenCalledWith('core_0');
  });
});

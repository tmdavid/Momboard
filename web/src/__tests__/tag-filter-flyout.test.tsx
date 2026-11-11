/** v0.5 U1 + U2: "Most used" label and the Custom submenu that flies out to the right. */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { TagFilterBar } from '../components/TagFilterBar';
import { server } from '../test/mocks/server';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const mk = (key: string, name: string, over: Record<string, unknown> = {}) => ({
  key, emoji: '🔹', name, description: null, signal_strength: null, sort_order: 1, is_active: true,
  origin: 'custom', category: null, min_confidence: 0.5, negative_hint: null, example: null, added_in_version: 0, ...over,
});

function mockTags() {
  const core = Array.from({ length: 12 }, (_, i) => mk(`core_${i}`, `Core ${i}`, { origin: 'core', sort_order: i + 1 }));
  const custom = [
    // Names that repeat their own category, the way they were typed in: "Product: Impersonation".
    mk('pr_imp', 'Product: Impersonation', { category: 'product', sort_order: 20 }),
    mk('pr_bill', 'Product - Billing', { category: 'product', sort_order: 21 }),
    mk('ch_slack', 'Slack', { category: 'channel', sort_order: 22 }),
    mk('sa_obj', 'Sales: Objection', { category: 'sales', sort_order: 23 }),
    mk('x_other', 'Product: Pricing', { category: 'sales', sort_order: 24 }),   // different category: keep its prefix
  ];
  server.use(http.get('/api/tags', () => HttpResponse.json([...core, ...custom])));
}

const bar = (props: Partial<Parameters<typeof TagFilterBar>[0]> = {}) =>
  render(<TagFilterBar isActive={() => false} onToggle={() => {}} {...props} />, { wrapper });

async function openCustom(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^Custom ▾/ }));
  return screen.getByTestId('custom-categories');
}

describe('U1: Most used', () => {
  test('the chip row is labelled "Most used" so it is not mistaken for the Core dropdown', async () => {
    mockTags();
    bar();
    const row = await screen.findByTestId('tag-quick-row');
    expect(within(row).getByText(/^most used$/i)).toBeInTheDocument();
    expect(await within(row).findByRole('button', { name: /Core 0/ })).toBeInTheDocument();
  });

  test('a quick chip that is a core tag still counts in the Core (n) badge', async () => {
    mockTags();
    bar({ isActive: (k) => k === 'core_0' });
    expect(await screen.findByRole('button', { name: /^Core \(1\) ▾/ })).toBeInTheDocument();
  });
});

describe('U2: Custom flyout', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });
  const userT = () => userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });

  test('hovering a category opens its tags to the right after a short delay, not instantly', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    const product = within(panel).getByRole('button', { name: /product/i });
    await user.hover(product);
    expect(screen.queryByRole('menu', { name: /product/i })).not.toBeInTheDocument();   // not yet
    act(() => { vi.advanceTimersByTime(160); });
    const fly = await screen.findByRole('menu', { name: /product/i });
    expect(fly).toHaveAttribute('data-side', 'right');
    expect(within(fly).getAllByRole('menuitemcheckbox')).toHaveLength(2);
  });

  test('leaving a category before the delay never opens it', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    await user.hover(within(panel).getByRole('button', { name: /product/i }));
    act(() => { vi.advanceTimersByTime(60); });
    await user.unhover(within(panel).getByRole('button', { name: /product/i }));
    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.queryByRole('menu', { name: /product/i })).not.toBeInTheDocument();
  });

  test('moving from one category to another swaps the flyout', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    await user.hover(within(panel).getByRole('button', { name: /product/i }));
    act(() => { vi.advanceTimersByTime(160); });
    await screen.findByRole('menu', { name: /product/i });
    await user.hover(within(panel).getByRole('button', { name: /channel/i }));
    act(() => { vi.advanceTimersByTime(160); });
    expect(await screen.findByRole('menu', { name: /channel/i })).toBeInTheDocument();
    expect(screen.queryByRole('menu', { name: /product/i })).not.toBeInTheDocument();
  });

  test('clicking a category opens it immediately (touch has no hover)', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    await user.click(within(panel).getByRole('button', { name: /channel/i }));
    expect(screen.getByRole('menu', { name: /channel/i })).toBeInTheDocument();
    expect(within(screen.getByRole('menu', { name: /channel/i })).getByRole('menuitemcheckbox', { name: /Slack/ })).toBeInTheDocument();
  });

  test('clicking the open category again closes it', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    const channel = within(panel).getByRole('button', { name: /channel/i });
    await user.click(channel);
    await user.click(channel);
    expect(screen.queryByRole('menu', { name: /channel/i })).not.toBeInTheDocument();
  });

  test('choosing a tag in the flyout toggles it and keeps the menu open for more', async () => {
    mockTags();
    const onToggle = vi.fn();
    bar({ onToggle });
    const user = userT();
    const panel = await openCustom(user);
    await user.click(within(panel).getByRole('button', { name: /product/i }));
    await user.click(within(screen.getByRole('menu', { name: /product/i })).getByRole('menuitemcheckbox', { name: /Billing/ }));
    expect(onToggle).toHaveBeenCalledWith('pr_bill');
    expect(screen.getByRole('menu', { name: /product/i })).toBeInTheDocument();
  });

  test('inside its own category a tag drops the category prefix; other categories keep theirs', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    await user.click(within(panel).getByRole('button', { name: /product/i }));
    const fly = screen.getByRole('menu', { name: /product/i });
    // Accessible names carry the emoji ("🔹 Impersonation"); the point is the missing prefix.
    expect(within(fly).getByRole('menuitemcheckbox', { name: /🔹 Impersonation$/ })).toBeInTheDocument();   // not "Product: Impersonation"
    expect(within(fly).getByRole('menuitemcheckbox', { name: /🔹 Billing$/ })).toBeInTheDocument();         // not "Product - Billing"
    await user.click(within(panel).getByRole('button', { name: /sales/i }));
    const sales = screen.getByRole('menu', { name: /sales/i });
    expect(within(sales).getByRole('menuitemcheckbox', { name: /🔹 Objection$/ })).toBeInTheDocument();
    expect(within(sales).getByRole('menuitemcheckbox', { name: /🔹 Product: Pricing$/ })).toBeInTheDocument();   // a different category's prefix stays
  });

  test('labels stay on one line and the flyout is wide enough', async () => {
    mockTags();
    bar();
    const user = userT();
    const panel = await openCustom(user);
    await user.click(within(panel).getByRole('button', { name: /product/i }));
    const fly = screen.getByRole('menu', { name: /product/i });
    expect(fly.className).toMatch(/min-w-\[280px\]/);
    expect(fly.className).not.toMatch(/overflow-x-auto|overflow-auto/);   // no horizontal scroll
    for (const item of within(fly).getAllByRole('menuitemcheckbox')) expect(item.className).toMatch(/whitespace-nowrap/);
  });

  test('a category shows how many of its tags are selected', async () => {
    mockTags();
    bar({ isActive: (k) => k === 'pr_imp' || k === 'pr_bill' });
    const user = userT();
    await user.click(await screen.findByRole('button', { name: /^Custom \(2\) ▾/ }));
    const panel = screen.getByTestId('custom-categories');
    expect(within(panel).getByRole('button', { name: /product.*\(2\)/i })).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /channel/i }).textContent).not.toMatch(/\(\d\)/);
  });

  test('the flyout opens to the left when there is no room on the right', async () => {
    mockTags();
    Object.defineProperty(document.documentElement, 'clientWidth', { value: 700, configurable: true });
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const box = (left: number, width: number) => ({ left, right: left + width, width, top: 0, bottom: 0, height: 0, x: left, y: 0, toJSON: () => ({}) }) as DOMRect;
      if (this.getAttribute('data-testid') === 'custom-categories') return box(300, 260);   // panel right edge at 560
      if (this.getAttribute('role') === 'menu' && this.getAttribute('aria-label')) return box(0, 280);
      return box(0, 0);
    });
    try {
      bar();
      const user = userT();
      const panel = await openCustom(user);
      await user.click(within(panel).getByRole('button', { name: /product/i }));
      // 560 + 280 = 840 > 700 -> flip
      expect(screen.getByRole('menu', { name: /product/i })).toHaveAttribute('data-side', 'left');
    } finally {
      spy.mockRestore();
    }
  });
});

describe('U2: closing', () => {
  const userT = () => userEvent.setup();

  test('Escape closes the flyout first, then the whole menu, and returns focus to the button', async () => {
    mockTags();
    bar();
    const user = userT();
    const trigger = await screen.findByRole('button', { name: /^Custom ▾/ });
    await user.click(trigger);
    const panel = screen.getByTestId('custom-categories');
    await user.click(within(panel).getByRole('button', { name: /channel/i }));
    expect(screen.getByRole('menu', { name: /channel/i })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', { name: /channel/i })).not.toBeInTheDocument();   // inner level closed
    expect(screen.getByTestId('custom-categories')).toBeInTheDocument();                 // outer still open

    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('custom-categories')).not.toBeInTheDocument();           // whole menu closed
    expect(trigger).toHaveFocus();
  });

  test('Escape also closes the Core dropdown and returns focus', async () => {
    mockTags();
    bar();
    const user = userT();
    const trigger = await screen.findByRole('button', { name: /^Core ▾/ });
    await user.click(trigger);
    expect(screen.getAllByRole('menuitemcheckbox').length).toBeGreaterThan(0);
    await user.keyboard('{Escape}');
    expect(screen.queryAllByRole('menuitemcheckbox')).toHaveLength(0);
    expect(trigger).toHaveFocus();
  });

  test('clicking outside closes everything', async () => {
    mockTags();
    render(<div><button>elsewhere</button><TagFilterBar isActive={() => false} onToggle={() => {}} /></div>, { wrapper });
    const user = userT();
    await user.click(await screen.findByRole('button', { name: /^Custom ▾/ }));
    await user.click(within(screen.getByTestId('custom-categories')).getByRole('button', { name: /channel/i }));
    await user.click(screen.getByRole('button', { name: 'elsewhere' }));
    await waitFor(() => expect(screen.queryByTestId('custom-categories')).not.toBeInTheDocument());
    expect(screen.queryByRole('menu', { name: /channel/i })).not.toBeInTheDocument();
  });

  test('opening Core closes Custom (only one dropdown at a time)', async () => {
    mockTags();
    bar();
    const user = userT();
    await user.click(await screen.findByRole('button', { name: /^Custom ▾/ }));
    await user.click(screen.getByRole('button', { name: /^Core ▾/ }));
    expect(screen.queryByTestId('custom-categories')).not.toBeInTheDocument();
  });
});

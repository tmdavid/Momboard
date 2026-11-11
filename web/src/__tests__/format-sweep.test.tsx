/** v0.5 U9: one formatter for numbers and dates, used everywhere. */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, test } from 'vitest';
import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { LibraryPage } from '../pages/LibraryPage';
import { ExplorePage } from '../pages/ExplorePage';
import { formatTime } from '../utils/format';

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === '__tests__' || name === 'generated' || name === 'test' ? [] : sources(p);
    return /\.(tsx?)$/.test(name) ? [p] : [];
  });
}

describe('no page formats numbers or dates by hand', () => {
  const root = join(__dirname, '..');
  const files = sources(root).filter((f) => !f.endsWith(join('utils', 'format.ts')));

  test.each(['toLocaleDateString', 'toLocaleTimeString', 'toLocaleString', 'Intl.DateTimeFormat', 'Intl.NumberFormat'])(
    'nothing calls %s outside utils/format',
    (needle) => {
      const offenders = files.filter((f) => readFileSync(f, 'utf8').includes(needle)).map((f) => relative(root, f));
      expect(offenders).toEqual([]);
    },
  );
});

describe('formatTime', () => {
  test('is a 24-hour clock time, or a dash', () => {
    expect(formatTime(new Date(2026, 8, 14, 9, 5))).toBe('09:05');
    expect(formatTime(null)).toBe('—');
    expect(formatTime('nonsense')).toBe('—');
  });
});

describe('Library and Explore counts read with thousands separators', () => {
  test('Library headline count and the pager', async () => {
    server.use(
      http.get('/api/conversations', () => HttpResponse.json({
        items: [{ id: 1, title: 'Call', happened_at: '2026-09-14T12:30:00', status: 'ready', interviewer: 'Rep',
          company: { id: 1, name: 'Acme' }, contacts: [], meta: null, created_at: '2026-09-14T12:30:00', tag_counts: { pain: 1500 }, critique_score: 7 }],
        total: 1234, limit: 50, offset: 0,
      })),
    );
    renderWithProviders(<LibraryPage />, { route: '/' });
    expect(await screen.findByText('(1,234)')).toBeInTheDocument();
    expect(screen.getByText(/of 1,234/)).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /Mon 14 Sep/ })).toBeInTheDocument();   // a day header, never the raw ISO string
    expect(screen.queryByText(/2026-09-14T/)).not.toBeInTheDocument();
  });

  test('Explore header count', async () => {
    const items = Array.from({ length: 3 }, (_, i) => ({
      id: i + 1, conversation_id: 1, utterance_id: null, tag_key: 'pain', quote: `Quote ${i}`, char_start: null, char_end: null,
      note: null, confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'Call', conversation_happened_at: '2026-09-14T12:30:00',
      company_name: 'Acme', contact_names: [],
    }));
    server.use(http.get('/api/highlights', () => HttpResponse.json({ items, total: 1500, limit: 50, offset: 0 })));
    renderWithProviders(<ExplorePage />, { route: '/explore' });
    expect(await screen.findByText(/Quote 0/)).toBeInTheDocument();
    expect(screen.getAllByText(/14 Sep 2026/).length).toBeGreaterThan(0);
  });
});

describe('formatDayHeading', () => {
  const now = new Date(2026, 10, 10, 15, 0);                       // Tue 10 Nov 2026
  test('today and yesterday are named, with the weekday and day', async () => {
    const { formatDayHeading } = await import('../utils/format');
    expect(formatDayHeading('2026-11-10', now)).toBe('Today · Tue 10 Nov');
    expect(formatDayHeading('2026-11-09', now)).toBe('Yesterday · Mon 9 Nov');
  });
  test('other days this year read "Fri 6 Nov"; other years add the year', async () => {
    const { formatDayHeading } = await import('../utils/format');
    expect(formatDayHeading('2026-11-06', now)).toBe('Fri 6 Nov');
    expect(formatDayHeading('2025-12-31', now)).toBe('Wed 31 Dec 2025');
  });
  test('a missing day is "No date"', async () => {
    const { formatDayHeading } = await import('../utils/format');
    expect(formatDayHeading(null, now)).toBe('No date');
  });
});

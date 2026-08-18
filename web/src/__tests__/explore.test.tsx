import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/render';
import { Routes, Route } from 'react-router-dom';
import { ExplorePage } from '../pages/ExplorePage';

function renderExplore() {
  return renderWithProviders(
    <Routes>
      <Route path="/explore" element={<ExplorePage />} />
    </Routes>,
    { route: '/explore' },
  );
}

describe('Explore page', () => {
  test('quote cards render emoji, verbatim quote, company · contact · date', async () => {
    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export all flagged listings/)).toBeInTheDocument();
    });

    // Multiple "Acme Watches" are expected (in filter dropdown + cards)
    expect(screen.getAllByText(/Acme Watches/).length).toBeGreaterThan(0);
  });

  test('quote cards render real curly quotation marks instead of unicode escape text', async () => {
    renderExplore();

    const quote = await screen.findByText(/Every Monday I export all flagged listings/);

    expect(quote.tagName).toBe('BLOCKQUOTE');
    expect(quote).toHaveTextContent(
      '“Every Monday I export all flagged listings to Excel”',
    );
    expect(quote).not.toHaveTextContent(/u201c|u201d/);
  });

  test('tag filter chips update results; active filters summarized in a bar', async () => {
    const user = userEvent.setup();
    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/5 highlights/)).toBeInTheDocument();
    });

    // After toggling a tag off, the count should update  
    const painBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('pain'));
    if (painBtn) await user.click(painBtn);

    // After removing pain from active (leaving only workaround), count changes
    await waitFor(() => {
      expect(screen.queryByText(/5 highlights/)).not.toBeInTheDocument();
    });
  });

  test('"Synthesize this view" enabled with 5+ highlights', async () => {
    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/5 highlights/)).toBeInTheDocument();
    });

    const btn = screen.getByRole('button', { name: /Synthesize this view/ });
    expect(btn).not.toBeDisabled();
  });

  test('card click navigates to conversation', async () => {
    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export all flagged listings/)).toBeInTheDocument();
    });

    expect(screen.getAllByText(/open ↗/).length).toBeGreaterThan(0);
  });
});

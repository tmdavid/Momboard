import { describe, test, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import { FreshnessDot } from '../components/FreshnessDot';

describe('FreshnessDot (T41)', () => {
  test('renders green dot for fresh evidence', () => {
    renderWithProviders(
      <FreshnessDot freshness="fresh" newestEvidenceAt="2026-08-01T00:00:00Z" />
    );
    const dot = screen.getByTestId('freshness-dot');
    expect(dot).toHaveAttribute('data-freshness', 'fresh');
  });

  test('renders amber dot for aging evidence', () => {
    renderWithProviders(
      <FreshnessDot freshness="aging" newestEvidenceAt="2026-04-01T00:00:00Z" />
    );
    const dot = screen.getByTestId('freshness-dot');
    expect(dot).toHaveAttribute('data-freshness', 'aging');
  });

  test('renders gray dot for stale evidence', () => {
    renderWithProviders(
      <FreshnessDot freshness="stale" newestEvidenceAt={null} />
    );
    const dot = screen.getByTestId('freshness-dot');
    expect(dot).toHaveAttribute('data-freshness', 'stale');
  });

  test('tooltip shows newest evidence date', () => {
    renderWithProviders(
      <FreshnessDot freshness="fresh" newestEvidenceAt="2026-08-01T00:00:00Z" />
    );
    // Tooltip text is in a span (invisible by default)
    expect(screen.getByText(/Last:/)).toBeInTheDocument();
  });
});

import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { Routes, Route } from 'react-router-dom';
import { InsightsPage } from '../pages/InsightsPage';

function renderInsights() {
  return renderWithProviders(
    <Routes>
      <Route path="/insights" element={<InsightsPage />} />
    </Routes>,
    { route: '/insights' },
  );
}

describe('Insights page', () => {
  test('renders four panels: tag volume over time, compliment ratio, critique trend, open follow-ups', async () => {
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Signal volume over time')).toBeInTheDocument();
    });

    expect(screen.getByText('Compliment ratio trend')).toBeInTheDocument();
    expect(screen.getByText('Interview quality trend')).toBeInTheDocument();
    expect(screen.getByText('Open follow-ups')).toBeInTheDocument();
  });

  test('open follow-ups list links to source conversations and shows age', async () => {
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText(/Watch the Monday export/)).toBeInTheDocument();
    });

    expect(screen.getByText(/Acme Watches discovery/)).toBeInTheDocument();
    expect(screen.getAllByText(/days/).length).toBeGreaterThan(0);
  });

  test('empty/insufficient-data states render guidance copy, not broken charts', async () => {
    server.use(
      http.get('/api/stats', () => {
        return HttpResponse.json({
          tag_counts_by_month: {},
          critique_trend: [],
          compliment_ratio_trend: [],
          open_followups: [],
        });
      }),
    );

    renderInsights();

    await waitFor(() => {
      expect(screen.getByText(/Not enough data yet/)).toBeInTheDocument();
    });
  });

  test('KPI tiles show computed values', async () => {
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Open follow-ups ☆')).toBeInTheDocument();
    });

    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('8/10')).toBeInTheDocument();
    expect(screen.getByText('22%')).toBeInTheDocument();
  });
});

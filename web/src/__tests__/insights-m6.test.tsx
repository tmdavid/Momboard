/**
 * M6 Insights page — missing requirements (RED tests).
 *
 * T22: Tag-volume legend entries toggle individual series without breaking other panels.
 */
import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

describe('T22: Insights tag-volume legend series toggling', () => {
  test('clicking a legend entry hides its corresponding series line from the chart', async () => {
    // Requirement: The tag-volume chart legend entries are interactive.
    // Clicking one toggles visibility of that specific series.
    const user = userEvent.setup();
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Signal volume over time')).toBeInTheDocument();
    });

    // The legend should show tag series entries — verify initial state with pain visible
    // Recharts renders legend items as interactive elements
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0);

    // Find the legend entry for "pain" (it will have the emoji or text)
    const painLegend = screen.getByText(/⚡ pain/);
    expect(painLegend).toBeInTheDocument();

    // Before clicking, the pain series line should be rendered in the SVG
    const chartContainer = screen.getByText('Signal volume over time').closest('div');
    expect(chartContainer).toBeTruthy();

    const painLinesBefore = chartContainer!.querySelectorAll('[stroke="#2a78d6"]');
    expect(painLinesBefore.length).toBeGreaterThan(0);

    // Click pain legend to toggle it off
    await user.click(painLegend);

    // After clicking, the pain series line should be hidden/removed
    await waitFor(() => {
      const chartAfter = screen.getByText('Signal volume over time').closest('div');
      // Verify the pain line is gone or hidden
      const visiblePainLines = Array.from(
        chartAfter!.querySelectorAll('.recharts-line'),
      ).filter((el) => {
        const path = el.querySelector('path');
        return (
          path?.getAttribute('stroke') === '#2a78d6' &&
          !path.getAttribute('style')?.includes('opacity: 0')
        );
      });
      expect(visiblePainLines.length).toBe(0);
    });
  }, 10_000);

  test('toggling a legend entry off does not break the compliment ratio or critique trend panels', async () => {
    // Requirement: Toggling a series in the tag-volume legend is isolated —
    // it must not cause the other chart panels to disappear, crash, or re-render incorrectly.
    const user = userEvent.setup();
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Signal volume over time')).toBeInTheDocument();
      expect(screen.getByText('Compliment ratio trend')).toBeInTheDocument();
      expect(screen.getByText('Interview quality trend')).toBeInTheDocument();
    });

    // Click pain legend entry to toggle it off
    const painLegend = screen.getByText(/⚡ pain/);
    await user.click(painLegend);

    // Other panels should still be fully intact
    await waitFor(() => {
      expect(screen.getByText('Compliment ratio trend')).toBeInTheDocument();
      expect(screen.getByText('Interview quality trend')).toBeInTheDocument();
      expect(screen.getByText('Open follow-ups')).toBeInTheDocument();
    });

    // The charts should still have SVG content (not empty/broken)
    const complimentPanel = screen.getByText('Compliment ratio trend').closest('div');
    expect(complimentPanel!.querySelector('svg')).toBeTruthy();

    const critiquePanel = screen.getByText('Interview quality trend').closest('div');
    expect(critiquePanel!.querySelector('svg')).toBeTruthy();
  });

  test('toggling a legend entry on again re-shows the series', async () => {
    // Requirement: Legend toggle is reversible — clicking again brings the series back.
    const user = userEvent.setup();
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Signal volume over time')).toBeInTheDocument();
    });

    const painLegend = screen.getByText(/⚡ pain/);

    // Toggle off
    await user.click(painLegend);

    // Toggle back on
    await user.click(painLegend);

    // The pain series line should be visible again
    await waitFor(() => {
      const chartContainer = screen.getByText('Signal volume over time').closest('div');
      const visiblePainLines = Array.from(
        chartContainer!.querySelectorAll('.recharts-line'),
      ).filter((el) => {
        const path = el.querySelector('path');
        return (
          path?.getAttribute('stroke') === '#2a78d6' &&
          !path.getAttribute('style')?.includes('opacity: 0')
        );
      });
      expect(visiblePainLines.length).toBeGreaterThan(0);
    });
  });

  test('toggling multiple legend entries hides only those specific series', async () => {
    // Requirement: Multiple series can be toggled independently.
    const user = userEvent.setup();
    renderInsights();

    await waitFor(() => {
      expect(screen.getByText('Signal volume over time')).toBeInTheDocument();
    });

    // Toggle off both pain and workaround
    const painLegend = screen.getByText(/⚡ pain/);
    const workaroundLegend = screen.getByText(/➡️ workaround/);

    await user.click(painLegend);
    await user.click(workaroundLegend);

    // Other series (money, commitment) should still be visible
    await waitFor(() => {
      const chartContainer = screen.getByText('Signal volume over time').closest('div');
      // money uses #1baf7a
      const moneyLines = Array.from(chartContainer!.querySelectorAll('.recharts-line')).filter(
        (el) => {
          const path = el.querySelector('path');
          return path?.getAttribute('stroke') === '#1baf7a';
        },
      );
      expect(moneyLines.length).toBeGreaterThan(0);
    });
  });
});

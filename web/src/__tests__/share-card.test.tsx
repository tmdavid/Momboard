import { describe, test, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../test/render';
import { server } from '../test/mocks/server';
import { ShareCardDialog } from '../components/ShareCardDialog';

// 1x1 transparent PNG for testing
const TINY_PNG = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00,
  0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x62, 0x00, 0x00, 0x00, 0x02,
  0x00, 0x01, 0xe5, 0x27, 0xde, 0xfc, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
  0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
]);

describe('ShareCardDialog (T44)', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockClear();
    server.use(
      http.get('/api/highlights/:id/card.png', () => {
        return new HttpResponse(TINY_PNG, {
          headers: { 'Content-Type': 'image/png' },
        });
      })
    );
  });

  test('renders dialog with theme and anonymize controls', () => {
    renderWithProviders(
      <ShareCardDialog highlightId={42} quote="Test quote" onClose={onClose} />
    );

    expect(screen.getByTestId('share-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('theme-select')).toBeInTheDocument();
    expect(screen.getByTestId('anonymize-checkbox')).toBeInTheDocument();
    expect(screen.getByTestId('download-btn')).toBeInTheDocument();
    expect(screen.getByTestId('copy-btn')).toBeInTheDocument();
  });

  test('anonymize is default checked (company names are sensitive)', () => {
    renderWithProviders(
      <ShareCardDialog highlightId={42} quote="Test quote" onClose={onClose} />
    );
    expect(screen.getByTestId('anonymize-checkbox')).toBeChecked();
  });

  test('light/dark theme toggle works', async () => {
    renderWithProviders(
      <ShareCardDialog highlightId={42} quote="Test quote" onClose={onClose} />
    );

    const select = screen.getByTestId('theme-select') as HTMLSelectElement;
    await userEvent.selectOptions(select, 'dark');
    expect(select.value).toBe('dark');
  });

  test('preview loads PNG image', async () => {
    renderWithProviders(
      <ShareCardDialog highlightId={42} quote="Test quote" onClose={onClose} />
    );

    await userEvent.click(screen.getByText('Preview'));

    await waitFor(() => {
      const img = screen.getByAltText('Quote card preview') as HTMLImageElement;
      expect(img).toBeInTheDocument();
    });
  });

  test('close button calls onClose', async () => {
    renderWithProviders(
      <ShareCardDialog highlightId={42} quote="Test quote" onClose={onClose} />
    );

    await userEvent.click(screen.getByText('✕'));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

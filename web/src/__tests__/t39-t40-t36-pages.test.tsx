import { describe, it, expect } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import { SimulatorPage } from '../pages/SimulatorPage';
import { DecisionsPage } from '../pages/DecisionsPage';
import { MeetingsPage } from '../pages/MeetingsPage';

describe('SimulatorPage (T39)', () => {
  it('renders build persona button', () => {
    renderWithProviders(<SimulatorPage />);
    expect(screen.getByText('Build Persona')).toBeInTheDocument();
  });

  it('builds persona and shows start session', async () => {
    renderWithProviders(<SimulatorPage />);
    fireEvent.click(screen.getByText('Build Persona'));

    await waitFor(() => {
      expect(screen.getByText('Marta')).toBeInTheDocument();
    });
    expect(screen.getByText('Start Session')).toBeInTheDocument();
  });

  it('full flow: persona → session → turn → end', async () => {
    renderWithProviders(<SimulatorPage />);

    // Build persona
    fireEvent.click(screen.getByText('Build Persona'));
    await waitFor(() => expect(screen.getByText('Marta')).toBeInTheDocument());

    // Start session
    fireEvent.click(screen.getByText('Start Session'));
    await waitFor(() => expect(screen.getByLabelText('Message input')).toBeInTheDocument());

    // Send a turn
    const input = screen.getByLabelText('Message input');
    fireEvent.change(input, { target: { value: 'Tell me about your day' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      expect(screen.getByText('We use Excel exports every Monday.')).toBeInTheDocument();
    });

    // End session
    fireEvent.click(screen.getByText('End & Score'));
    await waitFor(() => {
      expect(screen.getByText('Session Complete')).toBeInTheDocument();
    });
  });
});

describe('DecisionsPage (T40)', () => {
  it('renders decisions list', async () => {
    renderWithProviders(<DecisionsPage />);

    await waitFor(() => {
      expect(screen.getByText('Build auto-reports')).toBeInTheDocument();
    });
    expect(screen.getByText('Prioritize Slack integration')).toBeInTheDocument();
  });

  it('shows undermined badge', async () => {
    renderWithProviders(<DecisionsPage />);

    await waitFor(() => {
      expect(screen.getByText('⚠️ Undermined')).toBeInTheDocument();
    });
  });

  it('shows decision detail on click', async () => {
    renderWithProviders(<DecisionsPage />);

    await waitFor(() => expect(screen.getByText('Build auto-reports')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Build auto-reports'));

    await waitFor(() => {
      expect(screen.getByText('Rationale')).toBeInTheDocument();
      expect(screen.getByText(/Enterprise users report manual/)).toBeInTheDocument();
    });
  });

  it('shows evidence with conversation links', async () => {
    renderWithProviders(<DecisionsPage />);

    await waitFor(() => expect(screen.getByText('Build auto-reports')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Build auto-reports'));

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export to Excel/)).toBeInTheDocument();
      expect(screen.getByText('Discovery call')).toBeInTheDocument();
    });
  });

  it('opens create dialog', async () => {
    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('+ New Decision')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ New Decision'));

    expect(screen.getByRole('dialog', { name: 'Create decision' })).toBeInTheDocument();
  });
});

describe('MeetingsPage (T36)', () => {
  it('renders meeting URL input and send button', () => {
    renderWithProviders(<MeetingsPage />);
    expect(screen.getByLabelText('Meeting URL')).toBeInTheDocument();
    expect(screen.getByText('Send Bot')).toBeInTheDocument();
  });

  it('sends bot and shows meeting info with platform/native_meeting_id', async () => {
    renderWithProviders(<MeetingsPage />);

    const input = screen.getByLabelText('Meeting URL');
    fireEvent.change(input, { target: { value: 'https://meet.google.com/abc-defg-hij' } });
    fireEvent.click(screen.getByText('Send Bot'));

    await waitFor(() => {
      expect(screen.getByText(/google_meet\/abc-defg-hij/)).toBeInTheDocument();
    });
  });

  it('shows transcript preview with completed segments', async () => {
    renderWithProviders(<MeetingsPage />);

    const input = screen.getByLabelText('Meeting URL');
    fireEvent.change(input, { target: { value: 'https://meet.google.com/abc-defg-hij' } });
    fireEvent.click(screen.getByText('Send Bot'));

    await waitFor(() => {
      expect(screen.getByText('Hello world')).toBeInTheDocument();
    });
  });

  it('has stop and import buttons', async () => {
    renderWithProviders(<MeetingsPage />);

    const input = screen.getByLabelText('Meeting URL');
    fireEvent.change(input, { target: { value: 'https://meet.google.com/abc-defg-hij' } });
    fireEvent.click(screen.getByText('Send Bot'));

    await waitFor(() => {
      expect(screen.getByText('Stop Bot')).toBeInTheDocument();
      expect(screen.getByText('Import to Inbox')).toBeInTheDocument();
    });
  });
});

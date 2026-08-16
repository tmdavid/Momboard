/**
 * RED-phase tests: T16 — New Conversation Modal.
 *
 * Acceptance criteria:
 * - Modal collects title, date, interviewer, company (combobox w/ create),
 *   contacts (multiple with roles), and meta fields (deal_stage, segment).
 * - Transcript accepts paste or .txt/.vtt file; format auto-detected label shown.
 * - Submit POSTs correctly formed body and row appears optimistically with processing status.
 * - SSE updates flip the row to ready without reload (mock EventSource).
 * - Company field is a combobox: can search existing companies or create new.
 * - Multiple contacts with roles can be added.
 */
import { describe, test, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

// Mock EventSource for SSE tests
class MockEventSource {
  url: string;
  listeners: Record<string, Function[]> = {};
  readyState = 0;
  static instances: MockEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    this.readyState = 1; // OPEN
    MockEventSource.instances.push(this);
  }
  addEventListener(event: string, cb: Function) {
    this.listeners[event] = this.listeners[event] || [];
    this.listeners[event].push(cb);
  }
  removeEventListener(event: string, cb: Function) {
    this.listeners[event] = (this.listeners[event] || []).filter(l => l !== cb);
  }
  close() {
    this.readyState = 2;
  }
  // Test helper: emit an event
  emit(event: string, data?: string) {
    (this.listeners[event] || []).forEach(cb => cb({ data }));
  }
  set onerror(_fn: Function | null) {}
  set onmessage(_fn: Function | null) {}
  set onopen(_fn: Function | null) {}
}

describe('T16 — New Conversation Modal fields', () => {
  test('modal collects title, date, interviewer, company, contacts, and meta fields', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByText('New conversation')).toBeInTheDocument();
    });

    // Verify all expected fields are present
    expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/interviewer/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/company/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/contact/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/deal stage/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/segment|plan/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/transcript/i)).toBeInTheDocument();
  });

  test('company field is a combobox with search and create-new option', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/company/i)).toBeInTheDocument();
    });

    const companyInput = screen.getByLabelText(/company/i);
    await user.type(companyInput, 'Acm');

    // Should show existing company matches
    await waitFor(() => {
      expect(screen.getByText('Acme Watches')).toBeInTheDocument();
    });

    // Should show "Create new" option
    expect(screen.getByText(/create.*"Acm"/i)).toBeInTheDocument();
  });

  test('multiple contacts with roles can be added', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/contact/i)).toBeInTheDocument();
    });

    // Add first contact
    const contactInput = screen.getByLabelText(/contact/i);
    await user.type(contactInput, 'Jane Doe');

    // Should be able to specify role
    const roleInput = screen.getByLabelText(/role/i);
    await user.type(roleInput, 'Brand Manager');

    // Add button to add more contacts
    const addContactBtn = screen.getByRole('button', { name: /add contact/i });
    await user.click(addContactBtn);

    // Second contact fields appear
    const contactInputs = screen.getAllByLabelText(/contact/i);
    expect(contactInputs.length).toBeGreaterThanOrEqual(2);

    await user.type(contactInputs[1], 'John Smith');
  });
});

describe('T16 — Transcript format detection', () => {
  test('pasting VTT content shows "detected: VTT" label', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/transcript/i)).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(/paste.*transcript/i);
    await user.type(textarea, 'WEBVTT\n\n00:00.000 --> 00:02.000\nHello world');

    expect(screen.getByText(/detected.*VTT/i)).toBeInTheDocument();
  });

  test('pasting "Name: text" content shows "detected: Name: text" label', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/transcript/i)).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(/paste.*transcript/i);
    await user.type(textarea, 'David: How are you handling this today?');

    expect(screen.getByText(/detected.*Name.*text/i)).toBeInTheDocument();
  });

  test('dropping a .txt file reads content and auto-detects format', async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByText(/drop a .txt/i)).toBeInTheDocument();
    });

    // Simulate file drop
    const dropZone = screen.getByText(/drop a .txt/i);
    const vttContent = 'WEBVTT\n\n00:00.000 --> 00:02.000\nTest utterance';
    const file = new File([vttContent], 'test.vtt', { type: 'text/vtt' });

    // Create a DataTransfer with the file
    const dataTransfer = {
      files: [file],
      items: [{ kind: 'file', type: 'text/vtt', getAsFile: () => file }],
      types: ['Files'],
    };

    fireEvent.drop(dropZone, { dataTransfer });

    await waitFor(() => {
      expect(screen.getByText(/detected.*VTT/i)).toBeInTheDocument();
    });
  });
});

describe('T16 — Submit and optimistic row insertion', () => {
  test('submit POSTs correct body with all fields and row appears optimistically', async () => {
    let capturedBody: unknown = null;

    server.use(
      http.post('/api/conversations', async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(
          { id: 99, title: 'New test convo', status: 'processing', created_at: new Date().toISOString() },
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/new conversation/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    // Fill form
    await user.type(screen.getByLabelText(/title/i), 'Discovery call with Acme');
    await user.type(screen.getByPlaceholderText(/paste.*transcript/i), 'David: Hello\nJane: Hi there');

    // Submit
    await user.click(screen.getByRole('button', { name: /create.*analyz/i }));

    // Verify POST body
    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });

    const body = capturedBody as Record<string, unknown>;
    expect(body.title).toBe('Discovery call with Acme');
    expect(body.transcript).toBe('David: Hello\nJane: Hi there');
    expect(body.transcript_format).toBe('labeled');

    // Row should appear optimistically in the library with processing status
    await waitFor(() => {
      // The library should show the new item (either from optimistic cache or refetch)
      expect(screen.getByText('processing')).toBeInTheDocument();
    });
  });

  test('optimistic row shows in library immediately before server confirms', async () => {
    // Slow down the create response
    server.use(
      http.post('/api/conversations', async () => {
        await new Promise((r) => setTimeout(r, 2000));
        return HttpResponse.json(
          { id: 99, title: 'Optimistic test', status: 'processing', created_at: new Date().toISOString() },
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/title/i), 'Optimistic test');
    await user.type(screen.getByPlaceholderText(/paste.*transcript/i), 'David: Test content');

    await user.click(screen.getByRole('button', { name: /create.*analyz/i }));

    // Should appear immediately in the library (optimistic insert)
    await waitFor(
      () => {
        expect(screen.getByText('Optimistic test')).toBeInTheDocument();
      },
      { timeout: 500 }, // Must appear quickly, not after the 2s delay
    );
  });
});

describe('T16 — SSE completion flips row status', () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = global.EventSource;
    // @ts-expect-error — mock EventSource
    global.EventSource = MockEventSource;
    MockEventSource.instances = [];
  });

  afterEach(() => {
    global.EventSource = originalEventSource;
  });

  test('SSE done event flips row from processing to ready without page reload', async () => {
    server.use(
      http.post('/api/conversations', () =>
        HttpResponse.json(
          { id: 99, title: 'SSE test convo', status: 'processing', created_at: new Date().toISOString() },
          { status: 201 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/title/i), 'SSE test convo');
    await user.type(screen.getByPlaceholderText(/paste.*transcript/i), 'David: Test');

    await user.click(screen.getByRole('button', { name: /create.*analyz/i }));

    // Wait for the EventSource to be created
    await waitFor(() => {
      expect(MockEventSource.instances.length).toBeGreaterThan(0);
    });

    // Update the conversations handler to return the ready version
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [{
            id: 99, title: 'SSE test convo',
            happened_at: '2026-08-16T10:00:00Z', status: 'ready', interviewer: 'David',
            company: null, contacts: [], meta: null,
            created_at: '2026-08-16T10:00:00Z',
            tag_counts: { pain: 2 }, critique_score: 7,
          }],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );

    // Emit SSE "done" event
    const es = MockEventSource.instances[MockEventSource.instances.length - 1];
    await act(async () => {
      es.emit('done', JSON.stringify({ status: 'ready' }));
    });

    // Row should now show "Ready" status
    await waitFor(() => {
      expect(screen.getByText(/ready/i)).toBeInTheDocument();
    });
  });

  test('SSE tracking survives modal close — row still updates after modal dismissed', async () => {
    server.use(
      http.post('/api/conversations', () =>
        HttpResponse.json(
          { id: 99, title: 'Survives modal close', status: 'processing', created_at: new Date().toISOString() },
          { status: 201 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    await user.click(screen.getByText(/new conversation/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/title/i), 'Survives modal close');
    await user.type(screen.getByPlaceholderText(/paste.*transcript/i), 'David: Test');

    await user.click(screen.getByRole('button', { name: /create.*analyz/i }));

    // Wait for EventSource
    await waitFor(() => {
      expect(MockEventSource.instances.length).toBeGreaterThan(0);
    });

    // The modal should close after creation
    await waitFor(() => {
      expect(screen.queryByText('New conversation')).not.toBeInTheDocument();
    });

    // EventSource should still be open (not closed when modal unmounts)
    const es = MockEventSource.instances[MockEventSource.instances.length - 1];
    expect(es.readyState).not.toBe(2); // 2 = CLOSED

    // Update handler
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [{
            id: 99, title: 'Survives modal close',
            happened_at: '2026-08-16T10:00:00Z', status: 'ready', interviewer: 'David',
            company: null, contacts: [], meta: null,
            created_at: '2026-08-16T10:00:00Z',
            tag_counts: { pain: 1 }, critique_score: 6,
          }],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );

    // Fire SSE done after modal is closed
    await act(async () => {
      es.emit('done', JSON.stringify({ status: 'ready' }));
    });

    // Status should flip to ready
    await waitFor(() => {
      expect(screen.getByText(/ready/i)).toBeInTheDocument();
    });
  });
});

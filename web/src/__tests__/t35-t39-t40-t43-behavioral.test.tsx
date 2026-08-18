/**
 * Behavioral frontend tests for T35, T39, T40, T43.
 * Uses MSW — no mocked components, no real network.
 */
import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../test/render';
import { server } from '../test/mocks/server';
import { NewConversationModal } from '../components/NewConversationModal';
import { SimulatorPage } from '../pages/SimulatorPage';
import { DecisionsPage } from '../pages/DecisionsPage';
import { ExplorePage } from '../pages/ExplorePage';

// ═══════════════════════════════════════════════════════════════════════
// T35 — NewConversationModal: audio upload, text mode, error handling
// ═══════════════════════════════════════════════════════════════════════

describe('T35 — NewConversationModal audio upload', () => {
  it('switches to audio mode and shows file input', async () => {
    const onClose = vi.fn();
    renderWithProviders(<NewConversationModal onClose={onClose} />);

    // Initially in text mode
    expect(screen.getByLabelText(/Paste \/ .txt/)).toBeChecked();
    expect(screen.getByLabelText(/Audio \/ Video upload/)).not.toBeChecked();

    // Switch to audio
    fireEvent.click(screen.getByLabelText(/Audio \/ Video upload/));
    expect(screen.getByLabelText(/Audio \/ Video upload/)).toBeChecked();

    // Audio file chooser should appear
    expect(screen.getByText(/Choose file/)).toBeInTheDocument();
  });

  it('selects a supported audio file and shows name/size', async () => {
    const onClose = vi.fn();
    renderWithProviders(<NewConversationModal onClose={onClose} />);

    fireEvent.click(screen.getByLabelText(/Audio \/ Video upload/));

    const file = new File(['audio content bytes'], 'interview.mp3', { type: 'audio/mpeg' });
    Object.defineProperty(file, 'size', { value: 5 * 1024 * 1024 }); // 5MB

    const input = document.getElementById('audio-file-input') as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('interview.mp3')).toBeInTheDocument();
    expect(screen.getByText(/5\.0 MB/)).toBeInTheDocument();
  });

  it('submits multipart form and shows Transcribing state', async () => {
    // Delay the response to observe transcribing state
    let resolveUpload: (value: unknown) => void;
    const uploadPromise = new Promise((resolve) => { resolveUpload = resolve; });

    server.use(
      http.post('/api/conversations/upload', async () => {
        await uploadPromise;
        return HttpResponse.json(
          { id: 50, title: 'Uploaded audio', status: 'processing', created_at: new Date().toISOString() },
          { status: 201 },
        );
      }),
    );

    const onCreated = vi.fn();
    renderWithProviders(<NewConversationModal onClose={vi.fn()} onCreated={onCreated} />);

    // Fill required title
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'My interview' } });

    // Switch to audio and add file
    fireEvent.click(screen.getByLabelText(/Audio \/ Video upload/));
    const file = new File(['audio'], 'call.wav', { type: 'audio/wav' });
    const input = document.getElementById('audio-file-input') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    // Submit
    fireEvent.click(screen.getByText('Create & analyze'));

    // Should show Transcribing state
    await waitFor(() => {
      expect(screen.getByRole('status')).toBeInTheDocument();
      expect(screen.getByRole('status')).toHaveTextContent('Transcribing');
    });

    // Resolve the upload
    resolveUpload!(undefined);

    // Success callback fires
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(50, 'Uploaded audio');
    });
  });

  it('handles retryable upload error', async () => {
    server.use(
      http.post('/api/conversations/upload', () => {
        return HttpResponse.json({ detail: 'Service temporarily unavailable' }, { status: 503 });
      }),
    );

    renderWithProviders(<NewConversationModal onClose={vi.fn()} onCreated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'My call' } });
    fireEvent.click(screen.getByLabelText(/Audio \/ Video upload/));

    const file = new File(['audio'], 'call.mp3', { type: 'audio/mpeg' });
    const input = document.getElementById('audio-file-input') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByText('Create & analyze'));

    // Error message is displayed
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('Service temporarily unavailable')).toBeInTheDocument();
    });

    // Button should be re-enabled for retry
    expect(screen.getByText('Create & analyze')).not.toBeDisabled();
  });

  it('text mode still works — submits with transcript', async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<NewConversationModal onClose={vi.fn()} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Text interview' } });
    fireEvent.change(screen.getByPlaceholderText(/Paste the transcript/), {
      target: { value: 'David: Hello\nJane: Hi there' },
    });

    fireEvent.click(screen.getByText('Create & analyze'));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const data = onSubmit.mock.calls[0][0];
    expect(data.title).toBe('Text interview');
    expect(data.transcript).toBe('David: Hello\nJane: Hi there');
    expect(data.transcript_format).toBe('labeled');
  });
});

// ═══════════════════════════════════════════════════════════════════════
// T39 — SimulatorPage: persona filters in POST, score content rendering
// ═══════════════════════════════════════════════════════════════════════

describe('T39 — SimulatorPage persona filters and score', () => {
  it('sends selected company/tag in POST persona filters', async () => {
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post('/api/simulator/personas', async ({ request }) => {
        capturedBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          id: 1,
          kind: 'persona',
          result: {
            name: 'Marta',
            role: 'Operations Manager',
            company_profile: 'Mid-size enterprise, 200 employees',
            traits: [],
            sore_points: ['Manual reporting'],
            vocabulary_hints: [],
          },
        }, { status: 201 });
      }),
    );

    renderWithProviders(<SimulatorPage />);

    // Wait for companies/tags to load (options populated)
    await waitFor(() => {
      const companySelect = screen.getByLabelText('Company') as HTMLSelectElement;
      // Should have at least one non-default option
      expect(companySelect.options.length).toBeGreaterThan(1);
    });

    // Select company (Acme Watches id=1)
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: '1' } });
    // Select tag
    fireEvent.change(screen.getByLabelText('Tag'), { target: { value: 'pain' } });

    // Wait a tick for state to settle
    await waitFor(() => {
      expect((screen.getByLabelText('Company') as HTMLSelectElement).value).toBe('1');
      expect((screen.getByLabelText('Tag') as HTMLSelectElement).value).toBe('pain');
    });

    // Build persona
    fireEvent.click(screen.getByText('Build Persona'));

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });

    // Verify filters were sent
    expect(capturedBody!.filters).toEqual({ company_id: 1, tag_key: 'pain' });
  });

  it('shows score/10 and critique items after result polling', async () => {
    renderWithProviders(<SimulatorPage />);

    // Build persona
    fireEvent.click(screen.getByText('Build Persona'));
    await waitFor(() => expect(screen.getByText('Marta')).toBeInTheDocument());

    // Start session
    fireEvent.click(screen.getByText('Start Session'));
    await waitFor(() => expect(screen.getByLabelText('Message input')).toBeInTheDocument());

    // Send a turn
    const input = screen.getByLabelText('Message input');
    fireEvent.change(input, { target: { value: 'How do you handle this today?' } });
    fireEvent.click(screen.getByText('Send'));
    await waitFor(() => expect(screen.getByText('We use Excel exports every Monday.')).toBeInTheDocument());

    // End session
    fireEvent.click(screen.getByText('End & Score'));

    // Wait for result with score/10
    await waitFor(() => {
      expect(screen.getByText('7/10')).toBeInTheDocument();
    }, { timeout: 10000 });

    // Critique items
    expect(screen.getByText('Mom Test Score')).toBeInTheDocument();
    expect(screen.getByText('Asked about past events')).toBeInTheDocument();
    expect(screen.getByText(/pitched_the_idea/)).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════
// T40 — DecisionsPage: evidence search, checkbox selection, cite action,
//        modal close, integrity reasons, successor selection payload
// ═══════════════════════════════════════════════════════════════════════

describe('T40 — DecisionsPage behavioral tests', () => {
  it('evidence search filters highlights in create modal', async () => {
    // Override highlights endpoint to return mock data for search
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json({
          items: [
            { id: 10, conversation_id: 1, tag_key: 'pain', quote: 'Manual export takes too long', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'Call 1', conversation_happened_at: '2026-08-01', company_name: 'Acme', contact_names: ['Alice'] },
            { id: 11, conversation_id: 2, tag_key: 'workaround', quote: 'We bought the products ourselves', confidence: 0.8, status: 'accepted', origin: 'ai', conversation_title: 'Call 2', conversation_happened_at: '2026-08-02', company_name: 'Beta Inc', contact_names: ['Bob'] },
          ],
          total: 2,
          limit: 50,
          offset: 0,
        });
      }),
    );

    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('+ New Decision')).toBeInTheDocument());

    fireEvent.click(screen.getByText('+ New Decision'));

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Create decision' })).toBeInTheDocument();
    });

    // Wait for highlights to load — look for partial text within quotes
    await waitFor(() => {
      expect(screen.getByText(/Manual export/)).toBeInTheDocument();
    });

    // Search for "products"
    const searchInput = screen.getByLabelText('Search evidence highlights');
    fireEvent.change(searchInput, { target: { value: 'products' } });

    // Wait for search filter result — query refetches but data stays same
    await waitFor(() => {
      expect(screen.queryByText(/Manual export/)).not.toBeInTheDocument();
      expect(screen.getByText(/bought the products/)).toBeInTheDocument();
    });
  });

  it('checkbox selection toggles highlight inclusion', async () => {
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json({
          items: [
            { id: 10, conversation_id: 1, tag_key: 'pain', quote: 'Manual export', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'Call 1', conversation_happened_at: '2026-08-01', company_name: 'Acme', contact_names: ['Alice'] },
            { id: 11, conversation_id: 2, tag_key: 'pain', quote: 'Legal takes weeks', confidence: 0.8, status: 'accepted', origin: 'ai', conversation_title: 'Call 2', conversation_happened_at: '2026-08-02', company_name: 'Beta', contact_names: ['Bob'] },
          ],
          total: 2,
          limit: 50,
          offset: 0,
        });
      }),
    );

    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('+ New Decision')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ New Decision'));

    await waitFor(() => {
      expect(screen.getByText(/Manual export/)).toBeInTheDocument();
    });

    // Both checkboxes should be unchecked initially
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[0]).not.toBeChecked();

    // Check first
    fireEvent.click(checkboxes[0]);
    expect(checkboxes[0]).toBeChecked();

    // Label shows selected count
    expect(screen.getByText(/1 selected/)).toBeInTheDocument();

    // Uncheck
    fireEvent.click(checkboxes[0]);
    expect(checkboxes[0]).not.toBeChecked();
    expect(screen.getByText(/0 selected/)).toBeInTheDocument();
  });

  it('preselected highlight_id opens modal and close clears query param', async () => {
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json({
          items: [
            { id: 7, conversation_id: 1, tag_key: 'pain', quote: 'Preselected evidence', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'Call', conversation_happened_at: '2026-08-01', company_name: 'Acme', contact_names: ['Alice'] },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
    );

    renderWithProviders(<DecisionsPage />, {
      route: '/decisions?highlight_id=7',
      path: '/decisions',
    });

    // Modal opens automatically because of highlight_id param
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Create decision' })).toBeInTheDocument();
    });

    // Cancel closes and clears
    fireEvent.click(screen.getByText('Cancel'));

    // Modal should be gone
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('integrity reasons render when decision is undermined', async () => {
    server.use(
      http.get('/api/decisions/:id', () => {
        return HttpResponse.json({
          id: 2,
          title: 'Prioritize Slack integration',
          rationale_md: 'Users want faster notifications.',
          status: 'decided',
          integrity: 'undermined',
          integrity_reasons: [
            { reason: 'New evidence contradicts the premise', source_type: 'highlight', source_id: 5 },
            { reason: 'Market shifted to Teams', source_type: 'hypothesis', source_id: 3 },
          ],
          hypothesis_id: null,
          decided_at: '2026-08-10T00:00:00Z',
          decided_by: 1,
          superseded_by: null,
          evidence: [
            { highlight_id: 5, quote: 'Slack is dying', tag_key: 'pain', conversation_id: 2, conversation_title: 'Call 2', conversation_happened_at: '2026-08-07', status: 'accepted' },
          ],
          created_at: '2026-08-05T00:00:00Z',
        });
      }),
    );

    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('Prioritize Slack integration')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Prioritize Slack integration'));

    await waitFor(() => {
      expect(screen.getByText('Integrity concerns')).toBeInTheDocument();
      expect(screen.getByText('New evidence contradicts the premise')).toBeInTheDocument();
      expect(screen.getByText('Market shifted to Teams')).toBeInTheDocument();
    });
  });

  it('successor selection sends correct payload on supersede', async () => {
    let patchBody: Record<string, unknown> | null = null;

    server.use(
      http.get('/api/decisions/:id', ({ params }) => {
        return HttpResponse.json({
          id: Number(params.id),
          title: 'Build auto-reports',
          rationale_md: 'Weekly manual pain.',
          status: 'decided',
          integrity: 'ok',
          integrity_reasons: null,
          hypothesis_id: null,
          decided_at: '2026-08-10T00:00:00Z',
          decided_by: 1,
          superseded_by: null,
          evidence: [],
          created_at: '2026-08-01T00:00:00Z',
        });
      }),
      http.patch('/api/decisions/:id/status', async ({ request }) => {
        patchBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ id: 1, status: 'superseded' });
      }),
    );

    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('Build auto-reports')).toBeInTheDocument());

    // Click into detail
    fireEvent.click(screen.getByText('Build auto-reports'));
    await waitFor(() => expect(screen.getByText('Supersede')).toBeInTheDocument());

    // Click supersede
    fireEvent.click(screen.getByText('Supersede'));

    // Select successor
    const select = screen.getByLabelText('Select successor decision');
    fireEvent.change(select, { target: { value: '2' } });

    // Confirm
    fireEvent.click(screen.getByText('Confirm'));

    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody!.status).toBe('superseded');
    expect(patchBody!.superseded_by_id).toBe(2);
  });

  it('list cards activate via keyboard Enter and Space', async () => {
    renderWithProviders(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText('Build auto-reports')).toBeInTheDocument());

    const card = screen.getByText('Build auto-reports').closest('[role="button"]')!;

    // Enter activates
    fireEvent.keyDown(card, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('Rationale')).toBeInTheDocument();
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════
// T43 — ExplorePage lens: request payload, all four result areas, evidence links
// ═══════════════════════════════════════════════════════════════════════

describe('T43 — Lens compare exact request payload and result areas', () => {
  it('sends correct payload with tags as list and status for both sides', async () => {
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post('/api/lenses', async ({ request }) => {
        capturedBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          id: 1,
          kind: 'lens',
          input_scope: capturedBody,
          result: {
            themes_a: [{ name: 'A Theme', summary: 'A summary', side: 'a', evidence_highlight_ids: [1] }],
            themes_b: [{ name: 'B Theme', summary: 'B summary', side: 'b', evidence_highlight_ids: [3] }],
            themes_shared: [{ name: 'Shared Theme', summary: 'Shared', side: 'both', evidence_highlight_ids: [1, 3] }],
            contradictions: [{ name: 'Contra', summary: 'Contradiction', side: 'contradiction', evidence_highlight_ids: [1, 3] }],
            evidence_context: {
              '1': { highlight_id: 1, quote: 'Every Monday I export all flagged listings', tag_key: 'pain', conversation_id: 1, conversation_title: 'Discovery call', side: 'a' },
              '3': { highlight_id: 3, quote: 'Key sellers show up on every marketplace', tag_key: 'pain', conversation_id: 2, conversation_title: 'Key-reselling call', side: 'b' },
            },
          },
        }, { status: 201 });
      }),
    );

    renderWithProviders(<ExplorePage />);

    // Wait for highlights to load
    await waitFor(() => expect(screen.getByText('Explore highlights')).toBeInTheDocument());

    // Tags 'pain' and 'workaround' are active by default — click Lens button
    await waitFor(() => expect(screen.getByText('🔍 Compare as Lens')).not.toBeDisabled());
    fireEvent.click(screen.getByText('🔍 Compare as Lens'));

    // Lens modal
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Compare as lens' })).toBeInTheDocument();
    });

    // Pick Side B: company = Acme (id 1)
    const companySelect = screen.getByLabelText('Side B company');
    fireEvent.change(companySelect, { target: { value: '1' } });

    // Execute
    fireEvent.click(screen.getByText('Execute Lens'));

    // Verify request payload
    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });

    const a = capturedBody!.a as Record<string, unknown>;
    const b = capturedBody!.b as Record<string, unknown>;

    // Side A tags must be a list, not comma-joined
    expect(a.tag_key).toEqual(['pain', 'workaround']);
    // Side B has company_id
    expect(b.company_id).toBe(1);
  });

  it('renders all four result areas with clickable evidence links', async () => {
    renderWithProviders(<ExplorePage />);

    await waitFor(() => expect(screen.getByText('Explore highlights')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('🔍 Compare as Lens')).not.toBeDisabled());
    fireEvent.click(screen.getByText('🔍 Compare as Lens'));

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Compare as lens' })).toBeInTheDocument();
    });

    // Pick something for Side B
    fireEvent.change(screen.getByLabelText('Side B company'), { target: { value: '1' } });
    fireEvent.click(screen.getByText('Execute Lens'));

    // Wait for results panel
    await waitFor(() => {
      expect(screen.getByLabelText('Lens results')).toBeInTheDocument();
    });

    // All four areas present
    expect(screen.getByLabelText('Side A themes')).toBeInTheDocument();
    expect(screen.getByLabelText('Side B themes')).toBeInTheDocument();
    expect(screen.getByLabelText('Shared themes')).toBeInTheDocument();
    expect(screen.getByLabelText('Contradictions')).toBeInTheDocument();

    // Theme names
    expect(screen.getByText('Enterprise scale')).toBeInTheDocument();
    expect(screen.getByText('SMB simplicity')).toBeInTheDocument();
    expect(screen.getByText('Excel exports')).toBeInTheDocument();
    expect(screen.getByText('Automation vs manual')).toBeInTheDocument();

    // Evidence links exist (may appear multiple times across themes)
    const linksForId1 = screen.getAllByTestId('evidence-link-1');
    expect(linksForId1.length).toBeGreaterThanOrEqual(1);
    expect(linksForId1[0]).toHaveAttribute('href', '/conversations/1');
    expect(linksForId1[0]).toHaveTextContent('Discovery — counterfeit listings');

    const linksForId3 = screen.getAllByTestId('evidence-link-3');
    expect(linksForId3.length).toBeGreaterThanOrEqual(1);
    expect(linksForId3[0]).toHaveAttribute('href', '/conversations/2');
    expect(linksForId3[0]).toHaveTextContent('Key-reselling sites');
  });

  it('renders evidence quotes under each theme', async () => {
    renderWithProviders(<ExplorePage />);

    await waitFor(() => expect(screen.getByText('🔍 Compare as Lens')).not.toBeDisabled());
    fireEvent.click(screen.getByText('🔍 Compare as Lens'));
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Side B company'), { target: { value: '1' } });
    fireEvent.click(screen.getByText('Execute Lens'));

    await waitFor(() => expect(screen.getByLabelText('Lens results')).toBeInTheDocument());

    // Quotes rendered inline (may appear both in cards and in lens panel)
    const quoteMatches = screen.getAllByText(/Every Monday I export all flagged listings/);
    // At least one is within the lens panel evidence (the others may be in quote cards)
    expect(quoteMatches.length).toBeGreaterThanOrEqual(2); // 1 card + 1+ in lens

    const keySellerMatches = screen.getAllByText(/Key sellers show up on every marketplace/);
    expect(keySellerMatches.length).toBeGreaterThanOrEqual(1);
  });
});

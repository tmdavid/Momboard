import { http, HttpResponse } from 'msw';

// Test fixtures
export const mockUser = {
  id: 1,
  email: 'david@example.com',
  name: 'David',
  role: 'admin',
};

export const mockTags = [
  { key: 'pain', emoji: '⚡', name: 'Pain', description: null, signal_strength: 'strong', sort_order: 1, is_active: true },
  { key: 'workaround', emoji: '➡️', name: 'Workaround', description: null, signal_strength: 'very strong', sort_order: 2, is_active: true },
  { key: 'money', emoji: '💰', name: 'Money', description: null, signal_strength: 'strong', sort_order: 3, is_active: true },
  { key: 'commitment', emoji: '🤝', name: 'Commitment', description: null, signal_strength: 'very strong', sort_order: 4, is_active: true },
  { key: 'compliment', emoji: '🎈', name: 'Compliment', description: null, signal_strength: 'anti-signal', sort_order: 5, is_active: true },
  { key: 'followup', emoji: '☆', name: 'Follow-up', description: null, signal_strength: null, sort_order: 6, is_active: true },
];

export const mockCompanies = [
  { id: 1, name: 'Acme Watches', domain: 'acme.com', notes: null, created_at: '2026-08-01T00:00:00Z' },
  { id: 2, name: 'Northwind Apparel', domain: null, notes: null, created_at: '2026-08-02T00:00:00Z' },
];

export const mockConversations = {
  items: [
    {
      id: 1,
      title: 'Discovery — counterfeit listings workflow',
      happened_at: '2026-08-12T10:00:00Z',
      status: 'ready',
      interviewer: 'David',
      company: mockCompanies[0],
      contacts: [{ id: 1, name: 'Jane Doe', role: 'Brand Manager', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' }],
      meta: { deal_stage: 'discovery', segment: 'enterprise' },
      created_at: '2026-08-12T10:00:00Z',
      tag_counts: { pain: 3, workaround: 2, money: 1, commitment: 1 },
      critique_score: 8,
    },
    {
      id: 2,
      title: 'Key-reselling sites, first call',
      happened_at: '2026-08-07T10:00:00Z',
      status: 'ready',
      interviewer: 'David',
      company: { id: 3, name: 'PixelForge Games', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
      contacts: [{ id: 2, name: 'M. Chen', role: 'IP Counsel', email: null, company_id: 3, created_at: '2026-08-01T00:00:00Z' }],
      meta: null,
      created_at: '2026-08-07T10:00:00Z',
      tag_counts: { compliment: 4, feature_request: 3 },
      critique_score: 3,
    },
    {
      id: 3,
      title: 'Processing new conversation',
      happened_at: '2026-08-15T10:00:00Z',
      status: 'processing',
      interviewer: 'David',
      company: null,
      contacts: [],
      meta: null,
      created_at: '2026-08-15T10:00:00Z',
      tag_counts: {},
      critique_score: null,
    },
  ],
  total: 3,
  limit: 50,
  offset: 0,
};

export const mockConversationDetail = {
  id: 1,
  title: 'Discovery — counterfeit listings workflow',
  happened_at: '2026-08-12T10:00:00Z',
  status: 'ready',
  source: 'upload',
  interviewer: 'David',
  company: mockCompanies[0],
  contacts: [{ id: 1, name: 'Jane Doe', role: 'Brand Manager', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' }],
  meta: { deal_stage: 'discovery', segment: 'enterprise' },
  created_at: '2026-08-12T10:00:00Z',
  utterances: [
    { id: 1, idx: 0, speaker_label: 'David', speaker_side: 'us', text: 'How do you handle infringing listings today?', start_ms: null },
    { id: 2, idx: 1, speaker_label: 'Jane', speaker_side: 'them', text: 'Every Monday I export all flagged listings to Excel and clean them up by hand before legal sees them.', start_ms: null },
    { id: 3, idx: 2, speaker_label: 'Jane', speaker_side: 'them', text: 'Two months ago a counterfeit outsold our official store for a full week before we caught it.', start_ms: null },
    { id: 4, idx: 3, speaker_label: 'Jane', speaker_side: 'them', text: 'This all sounds great — I\'d totally use something like what you\'re describing.', start_ms: null },
  ],
  highlights: [
    { id: 1, conversation_id: 1, utterance_id: 2, tag_key: 'workaround', quote: 'Every Monday I export all flagged listings to Excel and clean them up by hand', char_start: null, char_end: null, note: null, confidence: 0.95, origin: 'ai', status: 'accepted', created_at: '2026-08-12T12:00:00Z' },
    { id: 2, conversation_id: 1, utterance_id: 2, tag_key: 'pain', quote: 'Every Monday I export all flagged listings to Excel and clean them up by hand', char_start: null, char_end: null, note: null, confidence: 0.93, origin: 'ai', status: 'accepted', created_at: '2026-08-12T12:00:00Z' },
    { id: 3, conversation_id: 1, utterance_id: 3, tag_key: 'pain', quote: 'Two months ago a counterfeit outsold our official store for a full week', char_start: null, char_end: null, note: null, confidence: 0.91, origin: 'ai', status: 'suggested', created_at: '2026-08-12T12:00:00Z' },
    { id: 4, conversation_id: 1, utterance_id: 4, tag_key: 'compliment', quote: "This all sounds great — I'd totally use something like what you're describing", char_start: null, char_end: null, note: null, confidence: 0.97, origin: 'ai', status: 'suggested', created_at: '2026-08-12T12:00:00Z' },
  ],
  analyses: [
    {
      id: 1,
      conversation_id: 1,
      kind: 'conversation',
      model: 'gpt-4o',
      prompt_version: 'analyst-v1',
      input_scope: null,
      result: {
        summary: 'Brand manager spends half a Monday weekly exporting and cleaning flagged listings.',
        top_pains: [
          { pain: 'Manual Excel triage consumes half a day weekly', evidence_highlight_ids: [1], severity: 'high' },
          { pain: 'Counterfeit outsold official store undetected', evidence_highlight_ids: [3], severity: 'high' },
        ],
        commitments: [
          { what: 'Session with Tomas from legal next week', type: 'time', next_step: 'Follow up' },
        ],
        compliment_ratio: 0.25,
        mom_test_critique: {
          score: 8,
          good_questions: ['Asked about the past and dug into specifics'],
          violations: [
            { utterance_idx: 3, type: 'pitched_the_idea', better: 'Keep the product out until the workflow demo is booked.' },
          ],
        },
        suggested_followups: ['Watch the Monday export live with Tomas', 'Get takedown log volumes'],
      },
      created_at: '2026-08-12T12:01:00Z',
    },
  ],
};

export const mockNote = {
  id: 1,
  conversation_id: 1,
  body_md: '# Acme Watches — call notes\n\n- Excel ritual is the wedge',
  updated_by: 1,
  updated_at: '2026-08-12T14:00:00Z',
};

export const mockHighlightsExplore = {
  items: [
    { id: 1, conversation_id: 1, tag_key: 'pain', quote: 'Every Monday I export all flagged listings to Excel', confidence: 0.95, status: 'accepted', origin: 'ai', conversation_title: 'Discovery — counterfeit listings', conversation_happened_at: '2026-08-12T10:00:00Z', company_name: 'Acme Watches', contact_names: ['Jane Doe'] },
    { id: 2, conversation_id: 1, tag_key: 'workaround', quote: 'I export to Excel and clean them up by hand', confidence: 0.93, status: 'accepted', origin: 'ai', conversation_title: 'Discovery — counterfeit listings', conversation_happened_at: '2026-08-12T10:00:00Z', company_name: 'Acme Watches', contact_names: ['Jane Doe'] },
    { id: 3, conversation_id: 2, tag_key: 'pain', quote: 'Key sellers show up on every marketplace', confidence: 0.88, status: 'suggested', origin: 'ai', conversation_title: 'Key-reselling sites', conversation_happened_at: '2026-08-07T10:00:00Z', company_name: 'PixelForge Games', contact_names: ['M. Chen'] },
    { id: 4, conversation_id: 1, tag_key: 'money', quote: 'We set aside €40k for brand protection', confidence: 0.96, status: 'accepted', origin: 'ai', conversation_title: 'Discovery — counterfeit listings', conversation_happened_at: '2026-08-12T10:00:00Z', company_name: 'Acme Watches', contact_names: ['Jane Doe'] },
    { id: 5, conversation_id: 2, tag_key: 'pain', quote: 'Legal takes two weeks to approve a takedown', confidence: 0.90, status: 'accepted', origin: 'ai', conversation_title: 'Key-reselling sites', conversation_happened_at: '2026-08-07T10:00:00Z', company_name: 'PixelForge Games', contact_names: ['M. Chen'] },
    { id: 6, conversation_id: 1, tag_key: 'workaround', quote: 'We bought the counterfeits ourselves to document them', confidence: 0.87, status: 'accepted', origin: 'ai', conversation_title: 'Discovery — counterfeit listings', conversation_happened_at: '2026-08-12T10:00:00Z', company_name: 'Acme Watches', contact_names: ['Jane Doe'] },
  ],
  total: 6,
  limit: 100,
  offset: 0,
};

export const mockStats = {
  tag_counts_by_month: {
    '2026-06': { pain: 4, workaround: 2, money: 1 },
    '2026-07': { pain: 6, workaround: 4, money: 2, commitment: 1 },
    '2026-08': { pain: 9, workaround: 5, money: 3, commitment: 2 },
  },
  critique_trend: [
    { date: '2026-06-15T00:00:00Z', score: 6, conversation_id: 1 },
    { date: '2026-07-10T00:00:00Z', score: 7, conversation_id: 2 },
    { date: '2026-08-12T00:00:00Z', score: 8, conversation_id: 3 },
  ],
  compliment_ratio_trend: [
    { date: '2026-06-15T00:00:00Z', ratio: 0.35, conversation_id: 1 },
    { date: '2026-07-10T00:00:00Z', ratio: 0.28, conversation_id: 2 },
    { date: '2026-08-12T00:00:00Z', ratio: 0.22, conversation_id: 3 },
  ],
  open_followups: [
    { id: 10, quote: 'Watch the Monday export live with Tomas', conversation_id: 1, conversation_title: 'Acme Watches discovery', happened_at: '2026-08-12T10:00:00Z', created_at: '2026-08-12T12:00:00Z' },
    { id: 11, quote: 'Send ROI one-pager for procurement', conversation_id: 2, conversation_title: 'Northwind Apparel', happened_at: '2026-07-25T10:00:00Z', created_at: '2026-07-25T12:00:00Z' },
  ],
};

export const handlers = [
  // Auth
  http.get('/api/me', () => {
    return HttpResponse.json(mockUser);
  }),

  http.post('/auth/login', async ({ request }) => {
    const body = await request.json() as { email: string; password: string };
    if (body.email === 'david@example.com' && body.password === 'password123') {
      return HttpResponse.json(mockUser);
    }
    return new HttpResponse(null, { status: 401 });
  }),

  http.post('/auth/logout', () => {
    return HttpResponse.json({ ok: true });
  }),

  // Conversations
  http.get('/api/conversations', ({ request }) => {
    const url = new URL(request.url);
    const q = url.searchParams.get('q');
    const tag = url.searchParams.get('tag');
    let items = [...mockConversations.items];

    if (q) {
      items = items.filter((c) => c.title.toLowerCase().includes(q.toLowerCase()));
    }
    if (tag) {
      items = items.filter((c) => (c.tag_counts as Record<string, number>)[tag] > 0);
    }

    return HttpResponse.json({ items, total: items.length, limit: 50, offset: 0 });
  }),

  http.get('/api/conversations/:id', ({ params }) => {
    if (params.id === '1') {
      return HttpResponse.json(mockConversationDetail);
    }
    return new HttpResponse(null, { status: 404 });
  }),

  http.post('/api/conversations', async ({ request }) => {
    const body = await request.json() as { title: string };
    return HttpResponse.json(
      { id: 99, title: body.title, status: 'processing', created_at: new Date().toISOString() },
      { status: 201 },
    );
  }),

  // Highlights
  http.patch('/api/highlights/:id', async ({ request, params }) => {
    const body = await request.json() as { status?: string; tag_key?: string };
    const base = mockConversationDetail.highlights.find((h) => h.id === Number(params.id));
    return HttpResponse.json({ ...base, ...body });
  }),

  http.post('/api/conversations/:id/highlights', async ({ request }) => {
    const body = await request.json() as { tag_key: string; quote: string; utterance_id?: number };
    return HttpResponse.json(
      { id: 100, conversation_id: 1, utterance_id: body.utterance_id || null, tag_key: body.tag_key, quote: body.quote, char_start: null, char_end: null, note: null, confidence: 1.0, origin: 'human', status: 'accepted', created_at: new Date().toISOString() },
      { status: 201 },
    );
  }),

  // Notes
  http.get('/api/conversations/:id/note', () => {
    return HttpResponse.json(mockNote);
  }),

  http.put('/api/conversations/:id/note', async ({ request }) => {
    const body = await request.json() as { body_md: string; updated_at: string };
    return HttpResponse.json({ ...mockNote, body_md: body.body_md, updated_at: new Date().toISOString() });
  }),

  // Explore
  http.get('/api/highlights', () => {
    return HttpResponse.json(mockHighlightsExplore);
  }),

  http.get('/api/stats', () => {
    return HttpResponse.json(mockStats);
  }),

  // Syntheses
  http.post('/api/syntheses', () => {
    return HttpResponse.json(
      { id: 1, kind: 'synthesis', input_scope: {}, result: null, model: null, prompt_version: null, created_at: new Date().toISOString() },
      { status: 201 },
    );
  }),

  http.get('/api/syntheses/:id', () => {
    return HttpResponse.json({
      id: 1,
      kind: 'synthesis',
      input_scope: {},
      result: {
        themes: [{ name: 'Manual triage is universal', summary: 'All companies report weekly manual exports.', evidence_highlight_ids: [1, 2], strength: 'strong' }],
        contradictions: [{ description: '2 companies file directly, 3 require legal approval', evidence_highlight_ids: [3] }],
        validate_next: ['Ask next interviewees about their takedown workflow end-to-end.'],
      },
      model: 'gpt-4o',
      prompt_version: 'synthesizer-v1',
      created_at: new Date().toISOString(),
    });
  }),

  // Admin
  http.get('/api/tags', () => {
    return HttpResponse.json(mockTags);
  }),

  http.get('/api/companies', () => {
    return HttpResponse.json(mockCompanies);
  }),
];

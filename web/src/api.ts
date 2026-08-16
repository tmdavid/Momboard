/**
 * Typed API client for MomBoard backend.
 * Grounded in the FastAPI OpenAPI contract (app/api/schemas.py).
 */

// ─── Types matching backend Pydantic schemas ───

export interface User {
  id: number;
  email: string;
  name: string | null;
  role: string;
}

export interface Company {
  id: number;
  name: string;
  domain: string | null;
  notes: string | null;
  created_at: string;
}

export interface Contact {
  id: number;
  name: string;
  role: string | null;
  email: string | null;
  company_id: number | null;
  created_at: string;
}

export interface Tag {
  key: string;
  emoji: string;
  name: string;
  description: string | null;
  signal_strength: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface Utterance {
  id: number;
  idx: number;
  speaker_label: string;
  speaker_side: string;
  text: string;
  start_ms: number | null;
}

export interface Highlight {
  id: number;
  conversation_id: number;
  utterance_id: number | null;
  tag_key: string;
  quote: string;
  char_start: number | null;
  char_end: number | null;
  note: string | null;
  confidence: number | null;
  origin: string;
  status: string;
  created_at: string;
}

export interface Analysis {
  id: number;
  conversation_id: number | null;
  kind: string;
  model: string | null;
  prompt_version: string | null;
  input_scope: Record<string, unknown> | null;
  result: AnalysisResult | null;
  created_at: string;
}

export interface AnalysisResult {
  summary?: string;
  top_pains?: Array<{ pain: string; evidence_highlight_ids: number[]; severity: string }>;
  commitments?: Array<{ what: string; type: string; next_step: string }>;
  compliment_ratio?: number;
  mom_test_critique?: {
    score: number;
    good_questions: string[];
    violations: Array<{ utterance_idx: number; type: string; better: string }>;
  };
  suggested_followups?: string[];
  open_questions?: string[];
  // Synthesis fields
  themes?: Array<{ name: string; summary: string; evidence_highlight_ids: number[]; strength: string }>;
  contradictions?: Array<{ description: string; evidence_highlight_ids: number[] }>;
  validate_next?: string[];
}

export interface ConversationListItem {
  id: number;
  title: string;
  happened_at: string | null;
  status: string;
  interviewer: string | null;
  company: Company | null;
  contacts: Contact[];
  meta: Record<string, unknown> | null;
  created_at: string;
  tag_counts: Record<string, number>;
  critique_score: number | null;
}

export interface ConversationDetail {
  id: number;
  title: string;
  happened_at: string | null;
  status: string;
  source: string;
  interviewer: string | null;
  company: Company | null;
  contacts: Contact[];
  meta: Record<string, unknown> | null;
  created_at: string;
  utterances: Utterance[];
  highlights: Highlight[];
  analyses: Analysis[];
}

export interface ConversationListResponse {
  items: ConversationListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface HighlightWithContext {
  id: number;
  conversation_id: number;
  tag_key: string;
  quote: string;
  confidence: number | null;
  status: string;
  origin: string;
  conversation_title: string;
  conversation_happened_at: string | null;
  company_name: string | null;
  contact_names: string[];
}

export interface HighlightsListResponse {
  items: HighlightWithContext[];
  total: number;
  limit: number;
  offset: number;
}

export interface Note {
  id: number;
  conversation_id: number;
  body_md: string;
  updated_by: number | null;
  updated_at: string;
}

export interface StatsResponse {
  tag_counts_by_month: Record<string, Record<string, number>>;
  critique_trend: Array<{ date: string; score: number; conversation_id: number }>;
  compliment_ratio_trend: Array<{ date: string; ratio: number; conversation_id: number }>;
  open_followups: Array<{
    id: number;
    quote: string;
    conversation_id: number;
    conversation_title: string;
    happened_at: string | null;
    created_at: string | null;
  }>;
}

export interface SynthesisResponse {
  id: number;
  kind: string;
  input_scope: Record<string, unknown> | null;
  result: AnalysisResult | null;
  model: string | null;
  prompt_version: string | null;
  created_at: string;
}

// ─── API Error ───

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

// ─── Fetch helper ───

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new ApiError(res.status, text || `HTTP ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ─── Auth ───

export const api = {
  login(email: string, password: string) {
    return apiFetch<User>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  logout() {
    return apiFetch<{ ok: boolean }>('/auth/logout', { method: 'POST' });
  },

  me() {
    return apiFetch<User>('/api/me');
  },

  // ─── Conversations ───

  listConversations(params: {
    limit?: number;
    offset?: number;
    company_id?: number;
    status?: string;
    tag?: string;
    q?: string;
    date_from?: string;
    date_to?: string;
  } = {}) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        searchParams.set(key, String(value));
      }
    }
    const qs = searchParams.toString();
    return apiFetch<ConversationListResponse>(`/api/conversations${qs ? `?${qs}` : ''}`);
  },

  getConversation(id: number) {
    return apiFetch<ConversationDetail>(`/api/conversations/${id}`);
  },

  createConversation(body: {
    title: string;
    happened_at?: string;
    interviewer?: string;
    company?: { name: string; domain?: string };
    contacts?: Array<{ name: string; role?: string }>;
    transcript: string;
    transcript_format?: string;
    meta?: Record<string, unknown>;
  }) {
    return apiFetch<{ id: number; title: string; status: string; created_at: string }>(
      '/api/conversations',
      { method: 'POST', body: JSON.stringify(body) },
    );
  },

  deleteConversation(id: number) {
    return apiFetch<void>(`/api/conversations/${id}`, { method: 'DELETE' });
  },

  reprocessConversation(id: number) {
    return apiFetch<{ id: number; status: string }>(`/api/conversations/${id}/reprocess`, {
      method: 'POST',
    });
  },

  // ─── Highlights ───

  createHighlight(conversationId: number, body: {
    utterance_id?: number;
    tag_key: string;
    quote: string;
    note?: string;
  }) {
    return apiFetch<Highlight>(`/api/conversations/${conversationId}/highlights`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  updateHighlight(id: number, body: { status?: string; tag_key?: string; quote?: string; note?: string }) {
    return apiFetch<Highlight>(`/api/highlights/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },

  // ─── Notes ───

  getNote(conversationId: number) {
    return apiFetch<Note>(`/api/conversations/${conversationId}/note`);
  },

  putNote(conversationId: number, body: { body_md: string; updated_at: string }) {
    return apiFetch<Note>(`/api/conversations/${conversationId}/note`, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },

  // ─── Explore ───

  listHighlights(params: {
    tag?: string;
    company_id?: number;
    status?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
  } = {}) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        searchParams.set(key, String(value));
      }
    }
    const qs = searchParams.toString();
    return apiFetch<HighlightsListResponse>(`/api/highlights${qs ? `?${qs}` : ''}`);
  },

  getStats() {
    return apiFetch<StatsResponse>('/api/stats');
  },

  // ─── Syntheses ───

  createSynthesis(filters: Record<string, unknown>) {
    return apiFetch<SynthesisResponse>('/api/syntheses', {
      method: 'POST',
      body: JSON.stringify({ filters }),
    });
  },

  getSynthesis(id: number) {
    return apiFetch<SynthesisResponse>(`/api/syntheses/${id}`);
  },

  // ─── Admin ───

  listTags() {
    return apiFetch<Tag[]>('/api/tags');
  },

  listCompanies() {
    return apiFetch<Company[]>('/api/companies');
  },
};

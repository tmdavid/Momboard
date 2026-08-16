/**
 * Typed API client for MomBoard backend.
 * Types sourced from OpenAPI-generated schema (T14).
 */

import type { components } from './generated/openapi';

// ─── Generated schema types ───

type Schemas = components['schemas'];

export type User = Schemas['UserResponse'];
export type Company = Schemas['CompanyResponse'];
export type Contact = Schemas['ContactResponse'];
export type Tag = Schemas['TagResponse'];
export type Utterance = Schemas['UtteranceResponse'];
export type Highlight = Schemas['HighlightResponse'];

/**
 * ConversationListItem with arrays guaranteed non-optional.
 * The backend always includes these fields (pydantic Field(default_factory=list)),
 * but OpenAPI marks them optional because of the default value.
 */
export interface ConversationListItem extends Omit<Schemas['ConversationListItem'], 'contacts' | 'tag_counts' | 'meta'> {
  contacts: Contact[];
  tag_counts: Record<string, number>;
  meta: Record<string, unknown> | null;
}

/**
 * ConversationDetail with arrays guaranteed non-optional.
 */
export interface ConversationDetail extends Omit<Schemas['ConversationDetail'], 'contacts' | 'utterances' | 'highlights' | 'analyses' | 'meta'> {
  contacts: Contact[];
  utterances: Utterance[];
  highlights: Highlight[];
  analyses: Analysis[];
  meta: Record<string, unknown> | null;
}

export interface ConversationListResponse {
  items: ConversationListItem[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * HighlightWithContext with contact_names guaranteed non-optional.
 */
export interface HighlightWithContext extends Omit<Schemas['HighlightWithContext'], 'contact_names'> {
  contact_names: string[];
}

export interface HighlightsListResponse {
  items: HighlightWithContext[];
  total: number;
  limit: number;
  offset: number;
}

export type Note = Schemas['NoteResponse'];

/**
 * SynthesisResponse with narrowed result type.
 * Backend uses dict[str, Any] for the JSON result field.
 */
export interface SynthesisResponse extends Omit<Schemas['SynthesisResponse'], 'result'> {
  result: AnalysisResult | null;
}

// ─── Domain result types (no backend schema equivalent) ───

/**
 * Structured analysis result, hand-maintained because the backend stores this
 * as an opaque JSON dict (dict[str, Any]) in the Pydantic model.
 */
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

/**
 * Extended Analysis type that narrows the `result` field to AnalysisResult.
 * The generated schema has result as Record<string, never> | null due to
 * dict[str, Any] in the Pydantic model.
 */
export interface Analysis extends Omit<Schemas['AnalysisResponse'], 'result'> {
  result: AnalysisResult | null;
}

/**
 * StatsResponse with narrowed inner types.
 * Backend uses dict[str, Any] for nested structures.
 */
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

// ─── Hypothesis types (T28) ───

export interface HypothesisRollup {
  supports: { confirmed: number; suggested: number };
  contradicts: { confirmed: number; suggested: number };
  companies_supporting: number;
  companies_contradicting: number;
  last_evidence_at: string | null;
}

export interface HypothesisListItem {
  id: number;
  statement: string;
  segment: string | null;
  status: string;
  created_by: number | null;
  created_at: string;
  decided_at: string | null;
  rollup: HypothesisRollup;
  verdict_hint: string | null;
}

export interface HypothesisEvidenceLink {
  link_id: number;
  highlight_id: number;
  quote: string;
  conversation_id: number;
  conversation_title: string;
  utterance_id: number;
  company_name: string;
  contact_name: string;
  confidence: number;
  origin: string;
  status: string;
  rationale: string;
}

export interface HypothesisDetail extends HypothesisListItem {
  evidence: {
    supports: HypothesisEvidenceLink[];
    contradicts: HypothesisEvidenceLink[];
  };
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
    tag?: string | string[];
    q?: string;
    date_from?: string;
    date_to?: string;
  } = {}) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      if (key === 'tag' && Array.isArray(value)) {
        // Support repeated tag params: ?tag=pain&tag=money
        for (const t of value) {
          if (t) searchParams.append('tag', t);
        }
      } else if (Array.isArray(value)) {
        for (const v of value) {
          if (v) searchParams.append(key, String(v));
        }
      } else {
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
    return apiFetch<Schemas['ConversationCreateResponse']>(
      '/api/conversations',
      { method: 'POST', body: JSON.stringify(body) },
    );
  },

  deleteConversation(id: number) {
    return apiFetch<void>(`/api/conversations/${id}`, { method: 'DELETE' });
  },

  reprocessConversation(id: number) {
    return apiFetch<Schemas['ConversationStatusResponse']>(`/api/conversations/${id}/reprocess`, {
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
    tag?: string | string[];
    company_id?: number;
    status?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
  } = {}) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      if (key === 'tag' && Array.isArray(value)) {
        // Support repeated tag params: ?tag=pain&tag=workaround
        for (const t of value) {
          if (t) searchParams.append('tag', t);
        }
      } else if (Array.isArray(value)) {
        for (const v of value) {
          if (v) searchParams.append(key, String(v));
        }
      } else {
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

  // ─── Hypotheses ───

  listHypotheses() {
    return apiFetch<HypothesisListItem[]>('/api/hypotheses');
  },

  getHypothesis(id: number) {
    return apiFetch<HypothesisDetail>(`/api/hypotheses/${id}`);
  },

  createHypothesis(body: { statement: string; segment?: string }) {
    return apiFetch<HypothesisListItem>('/api/hypotheses', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  updateHypothesis(id: number, body: { status?: string; statement?: string; segment?: string }) {
    return apiFetch<HypothesisListItem>(`/api/hypotheses/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },

  patchHypothesisLink(linkId: number, body: { status: 'confirmed' | 'rejected' }) {
    return apiFetch<HypothesisEvidenceLink>(`/api/hypothesis-links/${linkId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
};

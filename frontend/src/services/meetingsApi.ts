/**
 * Cliente de Meeting Intelligence.
 *
 * A transcrição tem chamada própria e nunca vem em listagem — o backend
 * também não a envia, mas o cliente reforça a intenção: quem quer o conteúdo
 * pede explicitamente.
 */

import api from './api.ts';

export type ResolutionStatus = 'matched' | 'ambiguous' | 'unmatched' | 'manual';
export type SuggestionStatus = 'pending' | 'accepted' | 'rejected' | 'applied' | 'failed';

export interface MeetingParticipant {
  id: number;
  name: string | null;
  email: string | null;
  type: string;
  role: string | null;
  attendance_status: string | null;
}

export interface ResolutionCandidate {
  lead_id: number | null;
  contact_id: number | null;
  customer_id: number | null;
  label: string | null;
  matched_on: string;
  detail: string | null;
}

export interface Meeting {
  id: number;
  title: string | null;
  provider: string;
  source: string;
  status: string;
  scheduled_start_at: string | null;
  scheduled_end_at: string | null;
  duration_seconds: number | null;
  meeting_url: string | null;
  transcript_status: string;
  analysis_status: string;
  resolution_status: ResolutionStatus;
  resolution_candidates: ResolutionCandidate[];
  lead_id: number | null;
  contact_id: number | null;
  customer_id: number | null;
  participants: MeetingParticipant[];
  summary: string | null;
  next_steps: string[];
}

export interface MeetingAnalysis {
  id: number;
  meeting_id: number;
  analysis_version: number;
  model: string | null;
  created_at: string | null;
  summary: string | null;
  meeting_purpose: string | null;
  customer_context: string | null;
  main_problem: string | null;
  budget_context: string | null;
  budget_amount: number | null;
  budget_confidence: string | null;
  urgency: string | null;
  timeline: string | null;
  sentiment: string | null;
  suggested_probability: number | null;
  probability_reason: string | null;
  suggested_next_step_date: string | null;
  pain_points: string[];
  needs: string[];
  desired_outcomes: string[];
  decision_makers: string[];
  influencers: string[];
  competitors: string[];
  objections: string[];
  questions: string[];
  unanswered_questions: string[];
  products_discussed: string[];
  offers_discussed: string[];
  prices_mentioned: string[];
  commitments_company: string[];
  commitments_customer: string[];
  next_steps: string[];
  risks: string[];
  positive_signals: string[];
  negative_signals: string[];
  evidence_snippets: string[];
}

export interface MeetingDetail extends Meeting {
  analysis: MeetingAnalysis | null;
}

export interface TranscriptSegment {
  speaker: string | null;
  speaker_external_id: string | null;
  text: string;
  start_time: number | null;
  end_time: number | null;
}

export interface MeetingTranscript {
  id: number;
  meeting_id: number;
  provider: string;
  language: string | null;
  text: string;
  segments: TranscriptSegment[];
  speaker_map: Record<string, { participant_id: number | null; name: string | null; type: string }>;
  word_count: number | null;
  imported_at: string | null;
}

export interface SalesMemory {
  lead_id: number;
  available: boolean;
  reason?: string;
  last_rebuilt_at?: string | null;
  current_summary?: string | null;
  business_context?: string | null;
  business_problem?: string | null;
  decision_process?: string | null;
  budget_context?: string | null;
  timeline?: string | null;
  next_best_action?: string | null;
  confidence?: string | null;
  desired_outcomes?: string[];
  stakeholders?: string[];
  objections?: string[];
  competitors?: string[];
  commitments_company?: string[];
  commitments_customer?: string[];
  risks?: string[];
  buying_signals?: string[];
  negative_signals?: string[];
  open_questions?: string[];
  source_refs?: Record<string, unknown>[];
}

export interface CrmSuggestion {
  id: number;
  meeting_id: number | null;
  field: string;
  suggestion_type: string;
  current_value: string | null;
  suggested_value: string | null;
  reason: string | null;
  confidence: string | null;
  status: SuggestionStatus;
  source_refs: Record<string, unknown>[];
  created_at: string | null;
  applied_at: string | null;
}

export interface ProviderStatus {
  provider: string;
  label: string;
  can_discover_meetings: boolean;
  can_import_transcripts: boolean;
  supports_realtime: boolean;
  is_operational: boolean;
  unavailable_reason: string | null;
  missing_scopes: string[];
}

export interface MeetingCapabilities {
  calendar_connected: boolean;
  meet_access: boolean;
  event_subscription_active: boolean;
  transcript_access: boolean;
  /** `null` = não foi possível determinar. Nunca exibir como sim ou não. */
  auto_transcription_available: boolean | null;
  subscription_status: string;
  subscription_expires_at: string | null;
  last_event_received_at: string | null;
  oauth_configured: boolean;
  pubsub_configured: boolean;
  missing_scopes: string[];
  needs_reconsent: boolean;
  blockers: string[];
  is_operational: boolean;
  transcription_guidance: string[];
}

export interface FollowUpDraft {
  meeting_id: number;
  lead_id: number | null;
  subject: string | null;
  message: string | null;
  key_points: string[];
  suggested_channel: string;
  status: string;
}

export const meetingsApi = {
  async list(params: {
    leadId?: number;
    resolutionStatus?: ResolutionStatus;
    page?: number;
    pageSize?: number;
  } = {}): Promise<{ items: Meeting[]; total: number; page: number; page_size: number }> {
    const response = await api.get('/meetings', {
      params: {
        lead_id: params.leadId,
        resolution_status: params.resolutionStatus,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
      },
    });
    return response.data;
  },

  async get(meetingId: number): Promise<MeetingDetail> {
    const response = await api.get<MeetingDetail>(`/meetings/${meetingId}`);
    return response.data;
  },

  async getTranscript(meetingId: number): Promise<MeetingTranscript> {
    const response = await api.get<MeetingTranscript>(`/meetings/${meetingId}/transcript`);
    return response.data;
  },

  async providers(): Promise<ProviderStatus[]> {
    const response = await api.get<{ items: ProviderStatus[] }>('/meetings/providers');
    return response.data.items;
  },

  async capabilities(): Promise<MeetingCapabilities> {
    const response = await api.get<MeetingCapabilities>('/meetings/capabilities');
    return response.data;
  },

  async createSubscription(): Promise<{ status: string; expires_at: string | null }> {
    const response = await api.post('/meetings/subscription');
    return response.data;
  },

  async sync(): Promise<void> {
    await api.post('/meetings/sync');
  },

  async associate(
    meetingId: number,
    payload: { lead_id?: number; contact_id?: number; customer_id?: number },
  ): Promise<Meeting> {
    const response = await api.post<Meeting>(`/meetings/${meetingId}/associate`, payload);
    return response.data;
  },

  async reprocess(meetingId: number): Promise<void> {
    await api.post(`/meetings/${meetingId}/reprocess`);
  },

  async followUp(meetingId: number): Promise<FollowUpDraft> {
    const response = await api.post<FollowUpDraft>(`/meetings/${meetingId}/follow-up`);
    return response.data;
  },

  async salesMemory(leadId: number): Promise<SalesMemory> {
    const response = await api.get<SalesMemory>(`/meetings/leads/${leadId}/sales-memory`);
    return response.data;
  },

  async suggestions(leadId: number): Promise<CrmSuggestion[]> {
    const response = await api.get<{ items: CrmSuggestion[] }>(
      `/meetings/leads/${leadId}/suggestions`,
    );
    return response.data.items;
  },

  async acceptSuggestion(suggestionId: number): Promise<void> {
    await api.post(`/meetings/suggestions/${suggestionId}/accept`);
  },

  async rejectSuggestion(suggestionId: number): Promise<void> {
    await api.post(`/meetings/suggestions/${suggestionId}/reject`);
  },
};

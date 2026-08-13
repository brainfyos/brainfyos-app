/**
 * Cliente do Brain.
 *
 * `company_id` nunca vai na requisição — o backend usa o workspace da sessão.
 * Enviá-lo daqui só criaria a ilusão de que o frontend escolhe o escopo.
 */

import api from './api.ts';

export type BrainScope = 'business' | 'sales' | 'customer' | 'financial' | 'marketing';

/* ---------------------------------------------------------------- */
/* Readiness e fontes                                                */
/* ---------------------------------------------------------------- */

export interface ReadinessCheck {
  key: string;
  label: string;
  weight: number;
  done: boolean;
  detail: string;
  action_route: string | null;
}

export interface BrainReadiness {
  percent: number;
  earned_weight: number;
  total_weight: number;
  checks: ReadinessCheck[];
  missing: ReadinessCheck[];
  last_updated_at: string | null;
}

export interface BrainSource {
  key: string;
  label: string;
  source_type: string;
  record_count: number | null;
  last_updated_at: string | null;
  connected: boolean;
}

export interface BrainOverview {
  company_id: number;
  readiness: BrainReadiness;
  sources: BrainSource[];
}

/* ---------------------------------------------------------------- */
/* Entidades                                                         */
/* ---------------------------------------------------------------- */

export interface BrainProfile {
  id: number | null;
  business_model: string | null;
  market: string | null;
  positioning: string | null;
  value_proposition: string | null;
  revenue_model: string | null;
  sales_motion: string | null;
  additional_context: string | null;
  competitive_advantages: string[];
  main_channels: string[];
  strategic_priorities: string[];
  constraints: string[];
  updated_at: string | null;
}

export interface BrainIcp {
  id: number;
  name: string;
  description: string | null;
  customer_type: string | null;
  industry: string | null;
  company_size: string | null;
  location: string | null;
  revenue_range: string | null;
  average_ticket: number | null;
  decision_makers: string[];
  pain_points: string[];
  desired_outcomes: string[];
  buying_triggers: string[];
  objections: string[];
  qualification_criteria: string[];
  disqualification_criteria: string[];
  priority: number;
  is_active: boolean;
  updated_at: string | null;
}

export interface BrainOffer {
  id: number;
  name: string;
  description: string | null;
  promise: string | null;
  mechanism: string | null;
  pricing_strategy: string | null;
  main_objections: string[];
  proof_points: string[];
  target_icp_id: number | null;
  target_icp_name: string | null;
  related_plan_id: number | null;
  related_plan_name: string | null;
  average_ticket: number | null;
  margin_estimate: number | null;
  sales_cycle_days: number | null;
  is_primary: boolean;
  is_active: boolean;
  updated_at: string | null;
}

export interface BrainGoal {
  id: number;
  name: string;
  description: string | null;
  metric_key: string | null;
  unit: string | null;
  baseline_value: number | null;
  target_value: number | null;
  period_start: string | null;
  period_end: string | null;
  priority: number;
  status: string;
  updated_at: string | null;
}

export interface LinkablePlan {
  id: number;
  name: string;
  price: number | null;
  billing_interval: string;
}

export type BrainProfileInput = Partial<Omit<BrainProfile, 'id' | 'updated_at'>>;
export type BrainIcpInput = Partial<Omit<BrainIcp, 'id' | 'updated_at'>>;
export type BrainOfferInput = Partial<
  Omit<BrainOffer, 'id' | 'updated_at' | 'target_icp_name' | 'related_plan_name'>
>;
export type BrainGoalInput = Partial<Omit<BrainGoal, 'id' | 'updated_at'>>;

/* ---------------------------------------------------------------- */

export const brainApi = {
  async getOverview(): Promise<BrainOverview> {
    const response = await api.get<BrainOverview>('/brain/overview');
    return response.data;
  },

  async getSources(): Promise<BrainSource[]> {
    const response = await api.get<{ sources: BrainSource[] }>('/brain/sources');
    return response.data.sources;
  },

  async getProfile(): Promise<BrainProfile> {
    const response = await api.get<BrainProfile>('/brain/profile');
    return response.data;
  },

  async saveProfile(payload: BrainProfileInput): Promise<BrainProfile> {
    const response = await api.put<BrainProfile>('/brain/profile', payload);
    return response.data;
  },

  async listIcps(): Promise<BrainIcp[]> {
    const response = await api.get<{ items: BrainIcp[] }>('/brain/icps');
    return response.data.items;
  },

  async createIcp(payload: BrainIcpInput): Promise<BrainIcp> {
    const response = await api.post<BrainIcp>('/brain/icps', payload);
    return response.data;
  },

  async updateIcp(id: number, payload: BrainIcpInput): Promise<BrainIcp> {
    const response = await api.put<BrainIcp>(`/brain/icps/${id}`, payload);
    return response.data;
  },

  async archiveIcp(id: number): Promise<BrainIcp> {
    const response = await api.post<BrainIcp>(`/brain/icps/${id}/archive`);
    return response.data;
  },

  async listOffers(): Promise<BrainOffer[]> {
    const response = await api.get<{ items: BrainOffer[] }>('/brain/offers');
    return response.data.items;
  },

  async createOffer(payload: BrainOfferInput): Promise<BrainOffer> {
    const response = await api.post<BrainOffer>('/brain/offers', payload);
    return response.data;
  },

  async updateOffer(id: number, payload: BrainOfferInput): Promise<BrainOffer> {
    const response = await api.put<BrainOffer>(`/brain/offers/${id}`, payload);
    return response.data;
  },

  async archiveOffer(id: number): Promise<BrainOffer> {
    const response = await api.post<BrainOffer>(`/brain/offers/${id}/archive`);
    return response.data;
  },

  async listPlans(): Promise<LinkablePlan[]> {
    const response = await api.get<{ items: LinkablePlan[] }>('/brain/plans');
    return response.data.items;
  },

  async listGoals(): Promise<BrainGoal[]> {
    const response = await api.get<{ items: BrainGoal[] }>('/brain/goals');
    return response.data.items;
  },

  async createGoal(payload: BrainGoalInput): Promise<BrainGoal> {
    const response = await api.post<BrainGoal>('/brain/goals', payload);
    return response.data;
  },

  async updateGoal(id: number, payload: BrainGoalInput): Promise<BrainGoal> {
    const response = await api.put<BrainGoal>(`/brain/goals/${id}`, payload);
    return response.data;
  },

  async archiveGoal(id: number): Promise<BrainGoal> {
    const response = await api.post<BrainGoal>(`/brain/goals/${id}/archive`);
    return response.data;
  },
};

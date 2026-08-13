/**
 * Cliente do onboarding do workspace.
 *
 * O `company_id` nunca vai na requisição: o backend usa o workspace da sessão.
 */

import api from './api.ts';

export type OnboardingStatus = 'todo' | 'in_progress' | 'done' | 'blocked' | 'skipped';

export interface OnboardingBlocker {
  key: string;
  title: string;
}

export interface OnboardingItem {
  key: string;
  title: string;
  description: string | null;
  estimated_minutes: number | null;
  action_label: string | null;
  action_route: string | null;
  is_required: boolean;
  status: OnboardingStatus;
  /** true quando o sistema confere a conclusão sozinho, sem marcação manual. */
  is_automatic: boolean;
  blocked_by: OnboardingBlocker[];
}

export interface OnboardingSection {
  key: string;
  title: string;
  description: string | null;
  items: OnboardingItem[];
  completed: number;
  total: number;
}

export interface OnboardingState {
  template: { key: string; name: string; description: string | null } | null;
  sections: OnboardingSection[];
  progress: { total: number; completed: number; percent: number };
  is_complete: boolean;
  next_item: OnboardingItem | null;
}

export const onboardingApi = {
  async getState(): Promise<OnboardingState> {
    const response = await api.get<OnboardingState>('/onboarding/state');
    return response.data;
  },

  async setItemStatus(itemKey: string, status: OnboardingStatus): Promise<OnboardingState> {
    const response = await api.put<OnboardingState>(`/onboarding/items/${itemKey}`, { status });
    return response.data;
  },

  async getAnswers(): Promise<Record<string, unknown>> {
    const response = await api.get<{ answers: Record<string, unknown> }>('/onboarding/answers');
    return response.data.answers;
  },

  async saveAnswers(answers: Record<string, unknown>, itemKey?: string): Promise<Record<string, unknown>> {
    const response = await api.put<{ answers: Record<string, unknown> }>('/onboarding/answers', {
      answers,
      item_key: itemKey,
    });
    return response.data.answers;
  },
};

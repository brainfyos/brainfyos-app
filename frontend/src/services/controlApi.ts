/**
 * Cliente do BrainfyOS Control.
 *
 * Reutiliza a instância axios do app (cookies de sessão, refresh automático,
 * base URL). O `company_id` do localStorage nunca é enviado: o Control opera
 * acima de workspace e o backend decide o que a conta pode ver.
 */

import api from './api.ts';

export type PeriodDays = 7 | 30 | 90;

export interface ControlSession {
  is_platform_owner: boolean;
  platform_role: string | null;
}

export interface AiTotals {
  events: number;
  failed_events: number;
  success_rate_percent: number | null;
  input_tokens: number;
  output_tokens: number;
  cached_tokens?: number;
  reasoning_tokens?: number;
  total_tokens: number;
  cost_brl: number;
  cost_usd?: number;
  revenue_brl: number | null;
  gross_profit_brl: number | null;
  margin_percent?: number | null;
  internal_credits?: number;
  companies?: number;
}

export interface AccountTotals {
  total: number;
  active: number;
  inactive: number;
  blocked: number;
  created_in_period: number;
  consuming_ai_in_period: number;
}

export interface TopCompany {
  company_id: number;
  company_name: string;
  events: number;
  failed_events: number;
  total_tokens: number;
  cost_brl: number;
}

export type AlertSeverity = 'critical' | 'warning' | 'info';

export interface ControlAlert {
  company_id: number;
  company_name: string;
  severity: AlertSeverity;
  kind: string;
  title: string;
  detail: string;
}

export interface ControlOverview {
  period_days: number;
  period_start: string;
  accounts: AccountTotals;
  ai: AiTotals;
  top_companies: TopCompany[];
  alerts: ControlAlert[];
}

export interface ControlAccount {
  company_id: number;
  company_name: string;
  status: string;
  created_at: string | null;
  user_count: number;
  last_activity_at: string | null;
  ai_events: number;
  ai_errors: number;
  total_tokens: number;
  cost_brl: number;
  integration_count: number;
  whatsapp_connected: boolean;
  nps_responses: number;
  nps_score: number | null;
  health_score: number | null;
}

export interface ControlAccountsPage {
  page: number;
  page_size: number;
  total: number;
  period_days: number;
  items: ControlAccount[];
}

export interface ControlAccountDetail {
  company_id: number;
  company_name: string;
  legal_name: string;
  document: string | null;
  status: string;
  business_type: string | null;
  created_at: string | null;
  period_days: number;
  volumes: {
    active_users: number;
    contacts: number;
    leads: number;
    messages_in_period: number;
    last_activity_at: string | null;
  };
  ai: AiTotals;
  wallet: {
    balance_credits: number;
    total_granted_credits: number;
    total_used_credits: number;
    status: string;
  } | null;
  satisfaction: {
    responses: number;
    promoters: number;
    passives: number;
    detractors: number;
    average_score: number | null;
    nps_score: number | null;
  } | null;
  health_score: number | null;
}

export interface UsagePoint {
  date: string;
  events: number;
  failed_events: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_brl: number;
}

export interface UsageBucket {
  label: string;
  events: number;
  failed_events: number;
  total_tokens: number;
  cost_brl: number;
}

export interface UsageEvent {
  id: number;
  company_id: number;
  company_name: string;
  provider: string;
  operation: string;
  model: string | null;
  status: string;
  agent: string | null;
  total_tokens: number;
  cost_brl: number;
  error_message: string | null;
  created_at: string | null;
}

export interface ControlAiUsage {
  period_days: number;
  company_id: number | null;
  summary: AiTotals;
  timeseries: UsagePoint[];
  by_company: TopCompany[];
  by_agent: UsageBucket[];
  by_model: UsageBucket[];
  by_provider: UsageBucket[];
  recent_events: UsageEvent[];
}

export interface ControlAccountAiUsage extends Omit<ControlAiUsage, 'by_company'> {}

export interface IntegrationHealth {
  company_id: number;
  company_name: string;
  provider: string;
  status: string;
  health_status: 'healthy' | 'attention' | 'down';
  connected_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  failures_in_period: number;
  last_error: string | null;
}

export interface ControlIntegrations {
  period_days: number;
  total: number;
  healthy: number;
  attention: number;
  down: number;
  items: IntegrationHealth[];
}

export interface ControlAlerts {
  period_days: number;
  total: number;
  critical: number;
  warning: number;
  info: number;
  items: ControlAlert[];
}

export const controlApi = {
  async getSession(): Promise<ControlSession> {
    const response = await api.get<ControlSession>('/control/me');
    return response.data;
  },

  async getOverview(days: number): Promise<ControlOverview> {
    const response = await api.get<ControlOverview>('/control/overview', { params: { days } });
    return response.data;
  },

  async listAccounts(params: {
    days: number;
    page?: number;
    pageSize?: number;
    search?: string;
    status?: string;
    sortBy?: string;
    sortDir?: 'asc' | 'desc';
  }): Promise<ControlAccountsPage> {
    const response = await api.get<ControlAccountsPage>('/control/accounts', {
      params: {
        days: params.days,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 25,
        search: params.search || undefined,
        status: params.status || undefined,
        sort_by: params.sortBy ?? 'cost',
        sort_dir: params.sortDir ?? 'desc',
      },
    });
    return response.data;
  },

  async getAccount(companyId: number, days: number): Promise<ControlAccountDetail> {
    const response = await api.get<ControlAccountDetail>(`/control/accounts/${companyId}`, {
      params: { days },
    });
    return response.data;
  },

  async getAccountAiUsage(companyId: number, days: number): Promise<ControlAccountAiUsage> {
    const response = await api.get<ControlAccountAiUsage>(`/control/accounts/${companyId}/ai-usage`, {
      params: { days },
    });
    return response.data;
  },

  async getAiUsage(days: number, companyId?: number, onlyFailed = false): Promise<ControlAiUsage> {
    const response = await api.get<ControlAiUsage>('/control/ai-usage', {
      params: { days, company_id: companyId || undefined, only_failed: onlyFailed },
    });
    return response.data;
  },

  async getIntegrations(days: number): Promise<ControlIntegrations> {
    const response = await api.get<ControlIntegrations>('/control/integrations', { params: { days } });
    return response.data;
  },

  async getAlerts(days: number): Promise<ControlAlerts> {
    const response = await api.get<ControlAlerts>('/control/alerts', { params: { days } });
    return response.data;
  },
};

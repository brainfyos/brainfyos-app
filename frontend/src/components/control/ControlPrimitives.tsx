/**
 * Primitivas visuais do BrainfyOS Control.
 *
 * Ficam juntas de propósito: são pequenas, sempre usadas em conjunto e
 * compartilham o mesmo contrato de tokens (`control.css`). Nenhuma delas
 * declara cor — tudo vem de `var(--ctl-*)`.
 */

import React from 'react';
import { AlertTriangle, Inbox, type LucideIcon } from 'lucide-react';

/* ------------------------------------------------------------------ */
/* Formatação                                                          */
/* ------------------------------------------------------------------ */

const numberFormatter = new Intl.NumberFormat('pt-BR');
const currencyFormatter = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  maximumFractionDigits: 2,
});
const compactFormatter = new Intl.NumberFormat('pt-BR', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

export const formatNumber = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : numberFormatter.format(value);

export const formatCompact = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : compactFormatter.format(value);

export const formatCurrency = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : currencyFormatter.format(value);

export const formatPercent = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `${value.toFixed(1).replace('.', ',')}%`;

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
};

export const formatDateTime = (value: string | null | undefined): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

/** "há 3 dias" comunica abandono melhor que uma data absoluta. */
export const formatRelative = (value: string | null | undefined): string => {
  if (!value) return 'Nunca';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  const diffMs = Date.now() - parsed.getTime();
  const diffDays = Math.floor(diffMs / 86_400_000);
  if (diffDays <= 0) {
    const diffHours = Math.floor(diffMs / 3_600_000);
    if (diffHours <= 0) return 'Agora há pouco';
    return `há ${diffHours}h`;
  }
  if (diffDays === 1) return 'ontem';
  if (diffDays < 30) return `há ${diffDays} dias`;
  return formatDate(value);
};

/* ------------------------------------------------------------------ */
/* Métrica                                                             */
/* ------------------------------------------------------------------ */

export type MetricTone = 'neutral' | 'positive' | 'warning' | 'danger';

interface MetricCardProps {
  label: string;
  /** `null` significa "essa informação ainda não existe no banco". */
  value: string | null;
  hint?: string;
  tone?: MetricTone;
  /** Texto exibido no lugar do valor quando ele é nulo. */
  emptyLabel?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  hint,
  tone = 'neutral',
  emptyLabel = 'Sem dados',
}) => (
  <div className="ctl-metric">
    <span className="ctl-metric-label">{label}</span>
    <span className={`ctl-metric-value${value === null ? ' is-empty' : ''}`}>
      {value === null ? emptyLabel : value}
    </span>
    {hint && <span className={`ctl-metric-hint${tone === 'neutral' ? '' : ` is-${tone}`}`}>{hint}</span>}
  </div>
);

export const MetricGrid: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="ctl-metric-grid">{children}</div>
);

/* ------------------------------------------------------------------ */
/* Painel                                                              */
/* ------------------------------------------------------------------ */

interface PanelProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  /** Remove o padding do corpo — use para tabelas coladas na borda. */
  flush?: boolean;
  children: React.ReactNode;
}

export const Panel: React.FC<PanelProps> = ({ title, description, actions, flush, children }) => (
  <section className="ctl-panel">
    <header className="ctl-panel-header">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {actions && <div className="ctl-panel-actions">{actions}</div>}
    </header>
    <div className={flush ? 'ctl-panel-body-flush' : 'ctl-panel-body'}>{children}</div>
  </section>
);

/* ------------------------------------------------------------------ */
/* Status                                                              */
/* ------------------------------------------------------------------ */

export type PillTone = 'positive' | 'warning' | 'danger' | 'accent' | 'neutral';

export const StatusPill: React.FC<{ tone: PillTone; children: React.ReactNode }> = ({ tone, children }) => (
  <span className={`ctl-pill is-${tone}`}>{children}</span>
);

const ACCOUNT_STATUS: Record<string, { tone: PillTone; label: string }> = {
  active: { tone: 'positive', label: 'Ativa' },
  inactive: { tone: 'neutral', label: 'Inativa' },
  blocked: { tone: 'danger', label: 'Suspensa' },
};

export const AccountStatusPill: React.FC<{ status: string }> = ({ status }) => {
  const meta = ACCOUNT_STATUS[status] || { tone: 'neutral' as PillTone, label: status };
  return <StatusPill tone={meta.tone}>{meta.label}</StatusPill>;
};

const HEALTH_STATUS: Record<string, { tone: PillTone; label: string }> = {
  healthy: { tone: 'positive', label: 'Saudável' },
  attention: { tone: 'warning', label: 'Atenção' },
  down: { tone: 'danger', label: 'Fora do ar' },
};

export const HealthPill: React.FC<{ status: string }> = ({ status }) => {
  const meta = HEALTH_STATUS[status] || { tone: 'neutral' as PillTone, label: status };
  return <StatusPill tone={meta.tone}>{meta.label}</StatusPill>;
};

const SEVERITY: Record<string, { tone: PillTone; label: string }> = {
  critical: { tone: 'danger', label: 'Crítico' },
  warning: { tone: 'warning', label: 'Atenção' },
  info: { tone: 'neutral', label: 'Informativo' },
};

export const SeverityPill: React.FC<{ severity: string }> = ({ severity }) => {
  const meta = SEVERITY[severity] || { tone: 'neutral' as PillTone, label: severity };
  return <StatusPill tone={meta.tone}>{meta.label}</StatusPill>;
};

/* ------------------------------------------------------------------ */
/* Estados vazios e de carga                                           */
/* ------------------------------------------------------------------ */

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon: Icon = Inbox }) => (
  <div className="ctl-empty">
    <Icon aria-hidden />
    <strong>{title}</strong>
    {description && <p>{description}</p>}
  </div>
);

export const ErrorState: React.FC<{ message: string }> = ({ message }) => (
  <div className="ctl-error" role="alert">
    <AlertTriangle size={16} aria-hidden />
    <span>{message}</span>
  </div>
);

export const SkeletonRows: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div
    aria-hidden
    style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ctl-space-3)', padding: 'var(--ctl-space-4)' }}
  >
    {Array.from({ length: rows }).map((_, index) => (
      <div key={index} className="ctl-skeleton" style={{ width: `${100 - index * 6}%` }} />
    ))}
  </div>
);

/* ------------------------------------------------------------------ */
/* Seletor de período                                                  */
/* ------------------------------------------------------------------ */

export const PERIOD_OPTIONS = [
  { value: 7, label: '7 dias' },
  { value: 30, label: '30 dias' },
  { value: 90, label: '90 dias' },
] as const;

export const PeriodPicker: React.FC<{ value: number; onChange: (days: number) => void }> = ({
  value,
  onChange,
}) => (
  <div className="ctl-segmented" role="group" aria-label="Período">
    {PERIOD_OPTIONS.map((option) => (
      <button
        key={option.value}
        type="button"
        aria-pressed={value === option.value}
        onClick={() => onChange(option.value)}
      >
        {option.label}
      </button>
    ))}
  </div>
);

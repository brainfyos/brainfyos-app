/**
 * Painel de consumo de IA da plataforma inteira.
 *
 * Todas as agregações vêm prontas do backend. O frontend não soma evento
 * nenhum — carregar `ai_usage_events` bruto para calcular aqui seria a forma
 * mais rápida de tornar esta tela inutilizável conforme a base cresce.
 */

import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { useControlPage } from '../../components/control/ControlLayout.tsx';
import {
  EmptyState,
  ErrorState,
  MetricCard,
  MetricGrid,
  Panel,
  SkeletonRows,
  formatCompact,
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatPercent,
} from '../../components/control/ControlPrimitives.tsx';
import UsageChart, { type UsageMetric } from '../../components/control/UsageChart.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { controlApi, type ControlAiUsage, type UsageBucket } from '../../services/controlApi.ts';

const METRIC_OPTIONS: { value: UsageMetric; label: string }[] = [
  { value: 'cost_brl', label: 'Custo' },
  { value: 'total_tokens', label: 'Tokens' },
  { value: 'events', label: 'Eventos' },
];

const ControlAIUsagePage: React.FC = () => {
  const { periodDays } = useControlPage('Consumo de IA');
  const [metric, setMetric] = useState<UsageMetric>('cost_brl');
  const [onlyFailed, setOnlyFailed] = useState(false);

  const loader = useCallback(
    () => controlApi.getAiUsage(periodDays, undefined, onlyFailed),
    [periodDays, onlyFailed],
  );
  const { data, isLoading, error, reload } = useAsyncData<ControlAiUsage>(loader, [periodDays, onlyFailed]);

  if (error) {
    return (
      <>
        <ErrorState message={error} />
        <button type="button" className="ctl-button" onClick={reload} style={{ alignSelf: 'flex-start' }}>
          Tentar novamente
        </button>
      </>
    );
  }

  if (isLoading || !data) {
    return (
      <Panel title="Carregando consumo" flush>
        <SkeletonRows rows={7} />
      </Panel>
    );
  }

  const { summary } = data;

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <h1>Consumo de IA</h1>
          <p>
            {formatNumber(summary.companies || 0)} empresas geraram eventos nos últimos {periodDays} dias.
          </p>
        </div>
      </div>

      <MetricGrid>
        <MetricCard label="Eventos" value={formatNumber(summary.events)} hint={`${formatNumber(summary.failed_events)} com erro`} tone={summary.failed_events > 0 ? 'warning' : 'neutral'} />
        <MetricCard
          label="Taxa de sucesso"
          value={summary.success_rate_percent === null ? null : formatPercent(summary.success_rate_percent)}
          emptyLabel="Sem eventos"
          tone={summary.success_rate_percent !== null && summary.success_rate_percent < 95 ? 'warning' : 'positive'}
        />
        <MetricCard label="Tokens totais" value={formatCompact(summary.total_tokens)} />
        <MetricCard label="Tokens de entrada" value={formatCompact(summary.input_tokens)} />
        <MetricCard label="Tokens de saída" value={formatCompact(summary.output_tokens)} />
        <MetricCard label="Custo estimado" value={formatCurrency(summary.cost_brl)} hint={summary.cost_usd ? `US$ ${summary.cost_usd.toFixed(2)}` : undefined} />
        {summary.revenue_brl !== null && (
          <MetricCard label="Receita de IA" value={formatCurrency(summary.revenue_brl)} tone="positive" />
        )}
        {summary.gross_profit_brl !== null && (
          <MetricCard
            label="Lucro bruto"
            value={formatCurrency(summary.gross_profit_brl)}
            hint={summary.margin_percent !== null && summary.margin_percent !== undefined ? `margem ${formatPercent(summary.margin_percent)}` : undefined}
            tone="positive"
          />
        )}
      </MetricGrid>

      <Panel
        title="Evolução"
        description={`Últimos ${periodDays} dias`}
        actions={
          <div className="ctl-segmented" role="group" aria-label="Métrica do gráfico">
            {METRIC_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={metric === option.value}
                onClick={() => setMetric(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      >
        <UsageChart data={data.timeseries} metric={metric} height={260} />
      </Panel>

      <Panel title="Por empresa" flush>
        {data.by_company.length === 0 ? (
          <EmptyState title="Nenhum consumo no período" />
        ) : (
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Empresa</th>
                  <th className="ctl-cell-num">Eventos</th>
                  <th className="ctl-cell-num">Erros</th>
                  <th className="ctl-cell-num">Tokens</th>
                  <th className="ctl-cell-num">Custo</th>
                </tr>
              </thead>
              <tbody>
                {data.by_company.map((company) => (
                  <tr key={company.company_id}>
                    <td className="ctl-cell-primary">
                      <Link to={`/control/accounts/${company.company_id}`}>{company.company_name}</Link>
                    </td>
                    <td className="ctl-cell-num">{formatNumber(company.events)}</td>
                    <td className="ctl-cell-num" style={company.failed_events > 0 ? { color: 'var(--ctl-warning)' } : undefined}>
                      {company.failed_events > 0 ? formatNumber(company.failed_events) : '—'}
                    </td>
                    <td className="ctl-cell-num">{formatCompact(company.total_tokens)}</td>
                    <td className="ctl-cell-num">{formatCurrency(company.cost_brl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="ctl-grid-2">
        <BucketTable title="Por agente" heading="Agente" buckets={data.by_agent} />
        <BucketTable title="Por modelo" heading="Modelo" buckets={data.by_model} />
      </div>

      <BucketTable title="Por provedor" heading="Provedor" buckets={data.by_provider} />

      <Panel
        title="Eventos recentes"
        flush
        actions={
          <button
            type="button"
            className="ctl-button"
            aria-pressed={onlyFailed}
            onClick={() => setOnlyFailed((current) => !current)}
          >
            {onlyFailed ? 'Mostrar todos' : 'Só com erro'}
          </button>
        }
      >
        {data.recent_events.length === 0 ? (
          <EmptyState title={onlyFailed ? 'Nenhum evento com erro' : 'Nenhum evento no período'} />
        ) : (
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Empresa</th>
                  <th>Agente</th>
                  <th>Provedor</th>
                  <th>Modelo</th>
                  <th>Status</th>
                  <th className="ctl-cell-num">Tokens</th>
                  <th className="ctl-cell-num">Custo</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_events.map((event) => (
                  <tr key={event.id}>
                    <td className="ctl-cell-muted">{formatDateTime(event.created_at)}</td>
                    <td className="ctl-cell-primary">
                      <Link to={`/control/accounts/${event.company_id}`}>{event.company_name}</Link>
                    </td>
                    <td className="ctl-cell-muted">{event.agent || '—'}</td>
                    <td className="ctl-cell-muted">{event.provider}</td>
                    <td className="ctl-cell-muted">{event.model || '—'}</td>
                    <td style={event.status === 'failed' ? { color: 'var(--ctl-danger)' } : undefined}>
                      {event.status === 'failed' && event.error_message ? (
                        <span title={event.error_message}>{event.status}</span>
                      ) : (
                        event.status
                      )}
                    </td>
                    <td className="ctl-cell-num">{formatNumber(event.total_tokens)}</td>
                    <td className="ctl-cell-num">{formatCurrency(event.cost_brl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
};

const BucketTable: React.FC<{ title: string; heading: string; buckets: UsageBucket[] }> = ({
  title,
  heading,
  buckets,
}) => (
  <Panel title={title} flush>
    {buckets.length === 0 ? (
      <EmptyState title="Sem consumo no período" />
    ) : (
      <div className="ctl-table-scroll">
        <table className="ctl-table">
          <thead>
            <tr>
              <th>{heading}</th>
              <th className="ctl-cell-num">Eventos</th>
              <th className="ctl-cell-num">Erros</th>
              <th className="ctl-cell-num">Tokens</th>
              <th className="ctl-cell-num">Custo</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label}>
                <td className="ctl-cell-primary">{bucket.label}</td>
                <td className="ctl-cell-num">{formatNumber(bucket.events)}</td>
                <td className="ctl-cell-num">{bucket.failed_events > 0 ? formatNumber(bucket.failed_events) : '—'}</td>
                <td className="ctl-cell-num">{formatCompact(bucket.total_tokens)}</td>
                <td className="ctl-cell-num">{formatCurrency(bucket.cost_brl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </Panel>
);

export default ControlAIUsagePage;

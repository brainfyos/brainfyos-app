/**
 * Ficha de uma empresa.
 *
 * Só existem as abas com dado real hoje: Visão geral, IA e Satisfação (esta
 * última apenas quando há respostas de NPS). Integrações, Atividade,
 * Resultados e Logs aparecem como estrutura vazia declarando o que falta —
 * uma aba honesta sobre a ausência é mais útil que uma cheia de número
 * inventado.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Construction } from 'lucide-react';
import { useControlPage } from '../../components/control/ControlLayout.tsx';
import {
  AccountStatusPill,
  EmptyState,
  ErrorState,
  MetricCard,
  MetricGrid,
  Panel,
  SkeletonRows,
  formatCompact,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
} from '../../components/control/ControlPrimitives.tsx';
import UsageChart from '../../components/control/UsageChart.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import {
  controlApi,
  type ControlAccountAiUsage,
  type ControlAccountDetail,
} from '../../services/controlApi.ts';

type TabKey = 'overview' | 'ai' | 'integrations' | 'activity' | 'satisfaction' | 'results' | 'logs';

interface TabDefinition {
  key: TabKey;
  label: string;
  /** Abas sem fonte de dados hoje mostram o que ainda precisa ser configurado. */
  pending?: string;
}

const TABS: TabDefinition[] = [
  { key: 'overview', label: 'Visão geral' },
  { key: 'ai', label: 'IA' },
  { key: 'satisfaction', label: 'Satisfação' },
  {
    key: 'integrations',
    label: 'Integrações',
    pending: 'A saúde das conexões desta empresa vai aparecer aqui quando a camada de normalização por conta for ligada. Por enquanto, o painel geral em Integrações já mostra o estado de todos os provedores.',
  },
  {
    key: 'activity',
    label: 'Atividade',
    pending: 'A linha do tempo de eventos da conta ainda não é registrada. O último sinal de atividade aparece na Visão geral.',
  },
  {
    key: 'results',
    label: 'Resultados',
    pending: 'Receita, conversão e ROI por conta dependem do Brain, que será construído na próxima fase.',
  },
  {
    key: 'logs',
    label: 'Logs',
    pending: 'O histórico de ações administrativas já é gravado em platform_audit_log. A visualização por conta ainda não foi construída.',
  },
];

const ControlAccountDetailPage: React.FC = () => {
  const { companyId: companyIdParam } = useParams<{ companyId: string }>();
  const companyId = Number(companyIdParam);
  const { periodDays, setTitle } = useControlPage('Conta');
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

  const detailLoader = useCallback(
    () => controlApi.getAccount(companyId, periodDays),
    [companyId, periodDays],
  );
  const detail = useAsyncData<ControlAccountDetail>(detailLoader, [companyId, periodDays]);

  // O consumo detalhado só é buscado quando a aba de IA abre — são seis
  // agregações e nenhuma delas serve à Visão geral.
  const usageLoader = useCallback(
    () =>
      activeTab === 'ai'
        ? controlApi.getAccountAiUsage(companyId, periodDays)
        : Promise.resolve(null as unknown as ControlAccountAiUsage),
    [activeTab, companyId, periodDays],
  );
  const usage = useAsyncData<ControlAccountAiUsage>(usageLoader, [activeTab, companyId, periodDays]);

  React.useEffect(() => {
    if (detail.data) setTitle(detail.data.company_name);
  }, [detail.data, setTitle]);

  const visibleTabs = useMemo(
    () => TABS.filter((tab) => tab.key !== 'satisfaction' || Boolean(detail.data?.satisfaction)),
    [detail.data],
  );

  if (!Number.isFinite(companyId) || companyId <= 0) {
    return <ErrorState message="Identificador de empresa inválido." />;
  }

  if (detail.error) {
    return (
      <>
        <ErrorState message={detail.error} />
        <Link className="ctl-button" to="/control/accounts" style={{ alignSelf: 'flex-start' }}>
          <ArrowLeft aria-hidden /> Voltar para contas
        </Link>
      </>
    );
  }

  if (detail.isLoading || !detail.data) {
    return (
      <Panel title="Carregando conta" flush>
        <SkeletonRows rows={6} />
      </Panel>
    );
  }

  const account = detail.data;
  const pendingTab = TABS.find((tab) => tab.key === activeTab)?.pending;

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <Link className="ctl-button" to="/control/accounts" style={{ marginBottom: 'var(--ctl-space-3)' }}>
            <ArrowLeft aria-hidden /> Contas
          </Link>
          <h1>{account.company_name}</h1>
          <p>
            {account.legal_name}
            {account.document ? ` · ${account.document}` : ''} · criada em {formatDate(account.created_at)}
          </p>
        </div>
        <div className="ctl-row" style={{ marginLeft: 'auto' }}>
          <AccountStatusPill status={account.status} />
        </div>
      </div>

      <div className="ctl-tabs" role="tablist" aria-label="Seções da conta">
        {visibleTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            className="ctl-tab"
            aria-selected={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <>
          <MetricGrid>
            <MetricCard label="Usuários ativos" value={formatNumber(account.volumes.active_users)} />
            <MetricCard label="Contatos" value={formatNumber(account.volumes.contacts)} />
            <MetricCard label="Leads" value={formatNumber(account.volumes.leads)} />
            <MetricCard
              label="Mensagens no período"
              value={formatNumber(account.volumes.messages_in_period)}
              hint={`última ${formatRelative(account.volumes.last_activity_at)}`}
            />
            <MetricCard label="Eventos de IA" value={formatNumber(account.ai.events)} hint={`${formatNumber(account.ai.failed_events)} com erro`} tone={account.ai.failed_events > 0 ? 'warning' : 'neutral'} />
            <MetricCard label="Custo de IA" value={formatCurrency(account.ai.cost_brl)} />
            <MetricCard
              label="Health score"
              value={account.health_score === null ? null : formatNumber(account.health_score)}
              emptyLabel="Indisponível"
              hint="Depende de dados ainda não coletados"
            />
          </MetricGrid>

          {account.wallet && (
            <Panel title="Créditos internos de IA" description={`Carteira ${account.wallet.status}`}>
              <dl className="ctl-definition">
                <dt>Saldo</dt>
                <dd>{formatNumber(account.wallet.balance_credits)}</dd>
                <dt>Concedidos</dt>
                <dd>{formatNumber(account.wallet.total_granted_credits)}</dd>
                <dt>Consumidos</dt>
                <dd>{formatNumber(account.wallet.total_used_credits)}</dd>
              </dl>
            </Panel>
          )}
        </>
      )}

      {activeTab === 'ai' && (
        usage.error ? (
          <ErrorState message={usage.error} />
        ) : usage.isLoading || !usage.data ? (
          <Panel title="Carregando consumo" flush>
            <SkeletonRows rows={5} />
          </Panel>
        ) : (
          <>
            <MetricGrid>
              <MetricCard label="Tokens" value={formatCompact(usage.data.summary.total_tokens)} hint={`${formatCompact(usage.data.summary.input_tokens)} entrada · ${formatCompact(usage.data.summary.output_tokens)} saída`} />
              <MetricCard label="Custo estimado" value={formatCurrency(usage.data.summary.cost_brl)} />
              <MetricCard
                label="Taxa de sucesso"
                value={usage.data.summary.success_rate_percent === null ? null : formatPercent(usage.data.summary.success_rate_percent)}
                emptyLabel="Sem eventos"
              />
              {usage.data.summary.revenue_brl !== null && (
                <MetricCard label="Receita" value={formatCurrency(usage.data.summary.revenue_brl)} tone="positive" />
              )}
            </MetricGrid>

            <Panel title="Evolução do custo" description={`Últimos ${periodDays} dias`}>
              <UsageChart data={usage.data.timeseries} metric="cost_brl" />
            </Panel>

            <div className="ctl-grid-2">
              <BucketPanel title="Por agente" buckets={usage.data.by_agent} />
              <BucketPanel title="Por modelo" buckets={usage.data.by_model} />
            </div>

            <Panel title="Eventos recentes" flush>
              {usage.data.recent_events.length === 0 ? (
                <EmptyState title="Nenhum evento no período" />
              ) : (
                <div className="ctl-table-scroll">
                  <table className="ctl-table">
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Agente</th>
                        <th>Modelo</th>
                        <th>Status</th>
                        <th className="ctl-cell-num">Tokens</th>
                        <th className="ctl-cell-num">Custo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.data.recent_events.map((event) => (
                        <tr key={event.id}>
                          <td className="ctl-cell-muted">{formatDateTime(event.created_at)}</td>
                          <td className="ctl-cell-primary">{event.agent || '—'}</td>
                          <td className="ctl-cell-muted">{event.model || '—'}</td>
                          <td style={event.status === 'failed' ? { color: 'var(--ctl-danger)' } : undefined}>
                            {event.status}
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
        )
      )}

      {activeTab === 'satisfaction' && account.satisfaction && (
        <>
          <MetricGrid>
            <MetricCard
              label="NPS"
              value={account.satisfaction.nps_score === null ? null : formatPercent(account.satisfaction.nps_score)}
              emptyLabel="Amostra pequena"
              hint={`${formatNumber(account.satisfaction.responses)} respostas`}
            />
            <MetricCard
              label="Nota média"
              value={account.satisfaction.average_score === null ? null : account.satisfaction.average_score.toFixed(1).replace('.', ',')}
            />
            <MetricCard label="Promotores" value={formatNumber(account.satisfaction.promoters)} tone="positive" />
            <MetricCard label="Neutros" value={formatNumber(account.satisfaction.passives)} />
            <MetricCard label="Detratores" value={formatNumber(account.satisfaction.detractors)} tone="danger" />
          </MetricGrid>
          <Panel title="Sobre esta métrica">
            <p style={{ margin: 0, color: 'var(--ctl-text-secondary)', fontSize: 'var(--ctl-text-sm)' }}>
              Calculado a partir das respostas de NPS já coletadas pela plataforma
              (<code>nps_responses</code>). O índice só é exibido a partir de cinco respostas no período —
              abaixo disso ele oscila demais para significar alguma coisa.
            </p>
          </Panel>
        </>
      )}

      {pendingTab && (
        <Panel title={TABS.find((tab) => tab.key === activeTab)?.label || ''}>
          <EmptyState icon={Construction} title="Ainda não configurado" description={pendingTab} />
        </Panel>
      )}
    </>
  );
};

const BucketPanel: React.FC<{ title: string; buckets: { label: string; total_tokens: number; cost_brl: number; events: number }[] }> = ({
  title,
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
              <th>{title.replace('Por ', '')}</th>
              <th className="ctl-cell-num">Eventos</th>
              <th className="ctl-cell-num">Tokens</th>
              <th className="ctl-cell-num">Custo</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label}>
                <td className="ctl-cell-primary">{bucket.label}</td>
                <td className="ctl-cell-num">{formatNumber(bucket.events)}</td>
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

export default ControlAccountDetailPage;

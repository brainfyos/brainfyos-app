/**
 * Primeira tela do proprietário.
 *
 * A ordem responde às perguntas na sequência em que elas são feitas: quantas
 * contas existem, quanto de IA está sendo consumido, quanto isso custa, quem
 * consome mais e o que precisa de atenção.
 *
 * Cards de receita e margem só aparecem quando `revenue_brl` existe nos
 * eventos. Sem dado de receita gravado, mostrá-los zerados sugeriria prejuízo
 * onde há apenas ausência de medição.
 */

import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import { useControlPage } from '../../components/control/ControlLayout.tsx';
import {
  EmptyState,
  ErrorState,
  MetricCard,
  MetricGrid,
  Panel,
  SeverityPill,
  SkeletonRows,
  formatCompact,
  formatCurrency,
  formatNumber,
  formatPercent,
} from '../../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { controlApi, type ControlOverview } from '../../services/controlApi.ts';

const ControlDashboardPage: React.FC = () => {
  const { periodDays, setAlertCount } = useControlPage('Visão geral');

  const loader = useCallback(() => controlApi.getOverview(periodDays), [periodDays]);
  const { data, isLoading, error, reload } = useAsyncData<ControlOverview>(loader, [periodDays]);

  React.useEffect(() => {
    if (data) setAlertCount(data.alerts.length || null);
  }, [data, setAlertCount]);

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
      <Panel title="Carregando" flush>
        <SkeletonRows rows={6} />
      </Panel>
    );
  }

  const { accounts, ai, top_companies: topCompanies, alerts } = data;

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <h1>Operação da plataforma</h1>
          <p>
            Consolidado de todas as contas nos últimos {periodDays} dias.
          </p>
        </div>
      </div>

      <MetricGrid>
        <MetricCard label="Contas" value={formatNumber(accounts.total)} hint={`${accounts.created_in_period} novas no período`} />
        <MetricCard
          label="Ativas"
          value={formatNumber(accounts.active)}
          hint={`${accounts.consuming_ai_in_period} consumindo IA`}
          tone="positive"
        />
        <MetricCard
          label="Inativas"
          value={formatNumber(accounts.inactive)}
          hint={accounts.blocked > 0 ? `${accounts.blocked} suspensas` : undefined}
          tone={accounts.blocked > 0 ? 'warning' : 'neutral'}
        />
        <MetricCard label="Eventos de IA" value={formatNumber(ai.events)} hint={`${formatNumber(ai.failed_events)} com erro`} tone={ai.failed_events > 0 ? 'warning' : 'neutral'} />
        <MetricCard
          label="Taxa de sucesso"
          value={ai.success_rate_percent === null ? null : formatPercent(ai.success_rate_percent)}
          emptyLabel="Sem eventos"
          tone={ai.success_rate_percent !== null && ai.success_rate_percent < 95 ? 'warning' : 'positive'}
        />
        <MetricCard label="Tokens" value={formatCompact(ai.total_tokens)} hint={`${formatCompact(ai.input_tokens)} entrada · ${formatCompact(ai.output_tokens)} saída`} />
        <MetricCard label="Custo estimado" value={formatCurrency(ai.cost_brl)} hint="Somatório dos eventos" />
        {ai.revenue_brl !== null && (
          <MetricCard label="Receita de IA" value={formatCurrency(ai.revenue_brl)} tone="positive" />
        )}
        {ai.gross_profit_brl !== null && (
          <MetricCard
            label="Lucro bruto de IA"
            value={formatCurrency(ai.gross_profit_brl)}
            hint={ai.margin_percent !== null && ai.margin_percent !== undefined ? `margem ${formatPercent(ai.margin_percent)}` : undefined}
            tone="positive"
          />
        )}
      </MetricGrid>

      <div className="ctl-grid-2">
        <Panel
          title="Maiores consumidores"
          description="Por custo estimado no período"
          flush
          actions={<Link className="ctl-button" to="/control/ai">Ver detalhe</Link>}
        >
          {topCompanies.length === 0 ? (
            <EmptyState
              title="Nenhum consumo registrado"
              description="Nenhuma conta gerou eventos de IA neste período."
            />
          ) : (
            <div className="ctl-table-scroll">
              <table className="ctl-table">
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th className="ctl-cell-num">Tokens</th>
                    <th className="ctl-cell-num">Custo</th>
                    <th className="ctl-cell-num">Erros</th>
                  </tr>
                </thead>
                <tbody>
                  {topCompanies.map((company) => (
                    <tr key={company.company_id}>
                      <td className="ctl-cell-primary">
                        <Link to={`/control/accounts/${company.company_id}`}>{company.company_name}</Link>
                      </td>
                      <td className="ctl-cell-num">{formatCompact(company.total_tokens)}</td>
                      <td className="ctl-cell-num">{formatCurrency(company.cost_brl)}</td>
                      <td className="ctl-cell-num">{company.failed_events > 0 ? formatNumber(company.failed_events) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel
          title="Precisam de atenção"
          description="Derivado de erros, inatividade e conexões"
          flush
          actions={<Link className="ctl-button" to="/control/alerts">Ver todos</Link>}
        >
          {alerts.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title="Nada pendente"
              description="Nenhuma conta disparou alerta neste período."
            />
          ) : (
            <div className="ctl-table-scroll">
              <table className="ctl-table">
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th>Alerta</th>
                    <th>Severidade</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((alert) => (
                    <tr key={`${alert.company_id}-${alert.kind}`}>
                      <td className="ctl-cell-primary">
                        <Link to={`/control/accounts/${alert.company_id}`}>{alert.company_name}</Link>
                      </td>
                      <td className="ctl-cell-muted">{alert.title}</td>
                      <td><SeverityPill severity={alert.severity} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
};

export default ControlDashboardPage;

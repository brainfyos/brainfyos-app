/**
 * Alertas operacionais.
 *
 * Cada linha vem de uma regra verificável no backend (taxa de erro de IA,
 * inatividade, WhatsApp habilitado sem sessão). Não existe score sintético
 * aqui — se o alerta apareceu, dá para apontar a consulta que o produziu.
 */

import React, { useCallback, useMemo, useState } from 'react';
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
  formatNumber,
} from '../../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { controlApi, type ControlAlerts } from '../../services/controlApi.ts';

const ControlAlertsPage: React.FC = () => {
  const { periodDays, setAlertCount } = useControlPage('Alertas');
  const [severityFilter, setSeverityFilter] = useState('');

  const loader = useCallback(() => controlApi.getAlerts(periodDays), [periodDays]);
  const { data, isLoading, error, reload } = useAsyncData<ControlAlerts>(loader, [periodDays]);

  React.useEffect(() => {
    if (data) setAlertCount(data.total || null);
  }, [data, setAlertCount]);

  const items = useMemo(
    () => (data ? data.items.filter((item) => !severityFilter || item.severity === severityFilter) : []),
    [data, severityFilter],
  );

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
      <Panel title="Carregando alertas" flush>
        <SkeletonRows rows={5} />
      </Panel>
    );
  }

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <h1>Alertas</h1>
          <p>Contas com sinal de problema nos últimos {periodDays} dias.</p>
        </div>
      </div>

      <MetricGrid>
        <MetricCard label="Total" value={formatNumber(data.total)} />
        <MetricCard label="Críticos" value={formatNumber(data.critical)} tone={data.critical > 0 ? 'danger' : 'neutral'} />
        <MetricCard label="Atenção" value={formatNumber(data.warning)} tone={data.warning > 0 ? 'warning' : 'neutral'} />
        <MetricCard label="Informativos" value={formatNumber(data.info)} />
      </MetricGrid>

      <Panel
        title="Ocorrências"
        flush
        actions={
          <select
            className="ctl-input"
            aria-label="Filtrar por severidade"
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value)}
          >
            <option value="">Todas as severidades</option>
            <option value="critical">Críticas</option>
            <option value="warning">Atenção</option>
            <option value="info">Informativas</option>
          </select>
        }
      >
        {items.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title={data.total === 0 ? 'Nenhum alerta aberto' : 'Nenhum alerta nesta severidade'}
            description={
              data.total === 0
                ? 'Todas as contas estão dentro dos limites de erro e atividade.'
                : 'Ajuste o filtro para ver as demais ocorrências.'
            }
          />
        ) : (
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Severidade</th>
                  <th>Empresa</th>
                  <th>Alerta</th>
                  <th>Detalhe</th>
                </tr>
              </thead>
              <tbody>
                {items.map((alert) => (
                  <tr key={`${alert.company_id}-${alert.kind}`}>
                    <td><SeverityPill severity={alert.severity} /></td>
                    <td className="ctl-cell-primary">
                      <Link to={`/control/accounts/${alert.company_id}`}>{alert.company_name}</Link>
                    </td>
                    <td>{alert.title}</td>
                    <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>{alert.detail}</td>
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

export default ControlAlertsPage;

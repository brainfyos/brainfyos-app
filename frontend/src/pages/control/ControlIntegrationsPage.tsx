/**
 * Saúde das conexões de todas as contas.
 *
 * A resposta do backend nunca traz token, senha ou refresh token — a
 * normalização em `control_metrics_service.get_integrations_health` seleciona
 * apenas presença e estado.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { PlugZap } from 'lucide-react';
import { useControlPage } from '../../components/control/ControlLayout.tsx';
import {
  EmptyState,
  ErrorState,
  HealthPill,
  MetricCard,
  MetricGrid,
  Panel,
  SkeletonRows,
  formatNumber,
  formatRelative,
} from '../../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { controlApi, type ControlIntegrations } from '../../services/controlApi.ts';

const PROVIDER_LABEL: Record<string, string> = {
  whatsapp_waha: 'WhatsApp (WAHA)',
  calendar_google: 'Google Agenda',
  calendar_clinicorp: 'Clinicorp',
  telegram: 'Telegram',
};

const providerLabel = (provider: string): string => PROVIDER_LABEL[provider] || provider;

const ControlIntegrationsPage: React.FC = () => {
  const { periodDays } = useControlPage('Integrações');
  const [healthFilter, setHealthFilter] = useState<string>('');

  const loader = useCallback(() => controlApi.getIntegrations(periodDays), [periodDays]);
  const { data, isLoading, error, reload } = useAsyncData<ControlIntegrations>(loader, [periodDays]);

  const items = useMemo(
    () => (data ? data.items.filter((item) => !healthFilter || item.health_status === healthFilter) : []),
    [data, healthFilter],
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
      <Panel title="Carregando integrações" flush>
        <SkeletonRows rows={6} />
      </Panel>
    );
  }

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <h1>Integrações</h1>
          <p>Estado das conexões de cada conta. Nenhuma credencial é exposta nesta tela.</p>
        </div>
      </div>

      <MetricGrid>
        <MetricCard label="Conexões" value={formatNumber(data.total)} />
        <MetricCard label="Saudáveis" value={formatNumber(data.healthy)} tone="positive" />
        <MetricCard label="Com atenção" value={formatNumber(data.attention)} tone="warning" />
        <MetricCard label="Fora do ar" value={formatNumber(data.down)} tone="danger" />
      </MetricGrid>

      <Panel
        title="Conexões"
        flush
        actions={
          <select
            className="ctl-input"
            aria-label="Filtrar por saúde"
            value={healthFilter}
            onChange={(event) => setHealthFilter(event.target.value)}
          >
            <option value="">Todas</option>
            <option value="healthy">Saudáveis</option>
            <option value="attention">Com atenção</option>
            <option value="down">Fora do ar</option>
          </select>
        }
      >
        {items.length === 0 ? (
          <EmptyState
            icon={PlugZap}
            title="Nenhuma conexão"
            description={
              data.total === 0
                ? 'Nenhuma empresa configurou canal ou integração até agora.'
                : 'Nenhuma conexão corresponde ao filtro selecionado.'
            }
          />
        ) : (
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Empresa</th>
                  <th>Provedor</th>
                  <th>Saúde</th>
                  <th>Status</th>
                  <th>Último sucesso</th>
                  <th>Última falha</th>
                  <th className="ctl-cell-num">Falhas</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={`${item.company_id}-${item.provider}`}>
                    <td className="ctl-cell-primary">
                      <Link to={`/control/accounts/${item.company_id}`}>{item.company_name}</Link>
                    </td>
                    <td className="ctl-cell-muted">{providerLabel(item.provider)}</td>
                    <td><HealthPill status={item.health_status} /></td>
                    <td className="ctl-cell-muted" title={item.last_error || undefined}>{item.status}</td>
                    <td className="ctl-cell-muted">{formatRelative(item.last_success_at)}</td>
                    <td className="ctl-cell-muted">{item.last_failure_at ? formatRelative(item.last_failure_at) : '—'}</td>
                    <td className="ctl-cell-num">{item.failures_in_period > 0 ? formatNumber(item.failures_in_period) : '—'}</td>
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

export default ControlIntegrationsPage;

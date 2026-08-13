/**
 * Lista de contas.
 *
 * Busca, filtro e ordenação vão para a URL: um recorte que o operador montou
 * precisa sobreviver a um reload e ser colável para outra pessoa.
 *
 * Ordenação e paginação são resolvidas no backend. Ordenar no cliente só
 * ordenaria a página corrente, o que produz um ranking errado.
 */

import React, { useCallback, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Search } from 'lucide-react';
import { useControlPage } from '../../components/control/ControlLayout.tsx';
import {
  AccountStatusPill,
  EmptyState,
  ErrorState,
  Panel,
  SkeletonRows,
  formatCompact,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  formatRelative,
} from '../../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { controlApi, type ControlAccountsPage as AccountsPage } from '../../services/controlApi.ts';

const PAGE_SIZE = 25;

interface Column {
  key: string;
  label: string;
  sortKey?: string;
  numeric?: boolean;
}

const COLUMNS: Column[] = [
  { key: 'name', label: 'Empresa', sortKey: 'name' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Criada em', sortKey: 'created_at' },
  { key: 'users', label: 'Usuários', sortKey: 'users', numeric: true },
  { key: 'last_activity', label: 'Última atividade', sortKey: 'last_activity' },
  { key: 'tokens', label: 'Tokens', sortKey: 'tokens', numeric: true },
  { key: 'cost', label: 'Custo IA', sortKey: 'cost', numeric: true },
  { key: 'events', label: 'Eventos', sortKey: 'events', numeric: true },
  { key: 'errors', label: 'Erros', sortKey: 'errors', numeric: true },
  { key: 'integrations', label: 'Conexões', numeric: true },
  { key: 'nps', label: 'NPS', numeric: true },
];

const ControlAccountsPage: React.FC = () => {
  const { periodDays } = useControlPage('Contas');
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const search = searchParams.get('q') || '';
  const status = searchParams.get('status') || '';
  const sortBy = searchParams.get('sort') || 'cost';
  const sortDir = (searchParams.get('dir') === 'asc' ? 'asc' : 'desc') as 'asc' | 'desc';
  const page = Math.max(1, Number(searchParams.get('page')) || 1);

  const updateParams = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === null || value === '') next.delete(key);
        else next.set(key, value);
      });
      // Qualquer mudança de recorte invalida a página atual.
      if (!('page' in changes)) next.delete('page');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const loader = useCallback(
    () =>
      controlApi.listAccounts({
        days: periodDays,
        page,
        pageSize: PAGE_SIZE,
        search,
        status,
        sortBy,
        sortDir,
      }),
    [periodDays, page, search, status, sortBy, sortDir],
  );

  const { data, isLoading, error, reload } = useAsyncData<AccountsPage>(loader, [
    periodDays,
    page,
    search,
    status,
    sortBy,
    sortDir,
  ]);

  const totalPages = useMemo(
    () => (data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1),
    [data],
  );

  const handleSort = (column: Column) => {
    if (!column.sortKey) return;
    const nextDir = sortBy === column.sortKey && sortDir === 'desc' ? 'asc' : 'desc';
    updateParams({ sort: column.sortKey, dir: nextDir });
  };

  return (
    <>
      <div className="ctl-page-head">
        <div>
          <h1>Contas</h1>
          <p>Todas as empresas da plataforma, com o consumo dos últimos {periodDays} dias.</p>
        </div>
      </div>

      <Panel
        title={data ? `${formatNumber(data.total)} contas` : 'Contas'}
        flush
        actions={
          <>
            <label className="ctl-row" style={{ gap: 'var(--ctl-space-2)' }}>
              <Search size={14} aria-hidden style={{ color: 'var(--ctl-text-muted)' }} />
              <span className="sr-only" style={{ position: 'absolute', left: -9999 }}>Buscar empresa</span>
              <input
                className="ctl-input"
                type="search"
                placeholder="Buscar por nome ou CNPJ"
                defaultValue={search}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    updateParams({ q: (event.target as HTMLInputElement).value });
                  }
                }}
              />
            </label>
            <select
              className="ctl-input"
              aria-label="Filtrar por status"
              value={status}
              onChange={(event) => updateParams({ status: event.target.value })}
            >
              <option value="">Todos os status</option>
              <option value="active">Ativas</option>
              <option value="inactive">Inativas</option>
              <option value="blocked">Suspensas</option>
            </select>
          </>
        }
      >
        {error ? (
          <div style={{ padding: 'var(--ctl-space-4)' }}>
            <ErrorState message={error} />
            <button type="button" className="ctl-button" onClick={reload} style={{ marginTop: 'var(--ctl-space-3)' }}>
              Tentar novamente
            </button>
          </div>
        ) : isLoading || !data ? (
          <SkeletonRows rows={8} />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="Nenhuma conta encontrada"
            description={search || status ? 'Ajuste a busca ou o filtro de status.' : 'Ainda não há empresas cadastradas.'}
          />
        ) : (
          <>
            <div className="ctl-table-scroll">
              <table className="ctl-table">
                <thead>
                  <tr>
                    {COLUMNS.map((column) => {
                      const isSorted = column.sortKey === sortBy;
                      return (
                        <th
                          key={column.key}
                          className={[
                            column.numeric ? 'ctl-cell-num' : '',
                            column.sortKey ? 'is-sortable' : '',
                            isSorted ? 'is-sorted' : '',
                          ].filter(Boolean).join(' ')}
                          aria-sort={isSorted ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}
                          onClick={() => handleSort(column)}
                        >
                          {column.label}
                          {isSorted ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((account) => (
                    <tr
                      key={account.company_id}
                      className="is-clickable"
                      onClick={() => navigate(`/control/accounts/${account.company_id}`)}
                    >
                      <td className="ctl-cell-primary">
                        <Link
                          to={`/control/accounts/${account.company_id}`}
                          onClick={(event) => event.stopPropagation()}
                        >
                          {account.company_name}
                        </Link>
                      </td>
                      <td><AccountStatusPill status={account.status} /></td>
                      <td className="ctl-cell-muted">{formatDate(account.created_at)}</td>
                      <td className="ctl-cell-num">{formatNumber(account.user_count)}</td>
                      <td className="ctl-cell-muted">{formatRelative(account.last_activity_at)}</td>
                      <td className="ctl-cell-num">{formatCompact(account.total_tokens)}</td>
                      <td className="ctl-cell-num">{formatCurrency(account.cost_brl)}</td>
                      <td className="ctl-cell-num">{formatNumber(account.ai_events)}</td>
                      <td className="ctl-cell-num" style={account.ai_errors > 0 ? { color: 'var(--ctl-warning)' } : undefined}>
                        {account.ai_errors > 0 ? formatNumber(account.ai_errors) : '—'}
                      </td>
                      <td className="ctl-cell-num">{formatNumber(account.integration_count)}</td>
                      <td className="ctl-cell-num">
                        {account.nps_score === null ? '—' : formatPercent(account.nps_score)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="ctl-pagination">
              <span>
                Página {data.page} de {totalPages}
              </span>
              <span className="ctl-pagination-spacer" />
              <button
                type="button"
                className="ctl-button"
                disabled={page <= 1}
                onClick={() => updateParams({ page: String(page - 1) })}
              >
                Anterior
              </button>
              <button
                type="button"
                className="ctl-button"
                disabled={page >= totalPages}
                onClick={() => updateParams({ page: String(page + 1) })}
              >
                Próxima
              </button>
            </div>
          </>
        )}
      </Panel>
    </>
  );
};

export default ControlAccountsPage;

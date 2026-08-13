/**
 * BrainPage — o centro estratégico da operação.
 *
 * Herda o visual enterprise escuro da Fase 1 (`styles/control.css`) em vez de
 * criar uma paleta nova: o Brain e o Control são as duas superfícies de
 * comando do sistema e devem falar a mesma língua visual.
 *
 * A aba ativa vive na URL (`?tab=icp`). O readiness aponta direto para a aba
 * que resolve cada pendência, e um link precisa continuar funcionando quando
 * colado em outro lugar.
 */

import React, { useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ErrorState, SkeletonRows, Panel } from '../../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { brainApi, type BrainOverview } from '../../services/brainApi.ts';
import BrainOverviewTab from './BrainOverviewTab.tsx';
import BrainStrategyTab from './BrainStrategyTab.tsx';
import BrainIcpTab from './BrainIcpTab.tsx';
import BrainOffersTab from './BrainOffersTab.tsx';
import BrainGoalsTab from './BrainGoalsTab.tsx';
import BrainDataTab from './BrainDataTab.tsx';
import styles from './Brain.module.css';
import '../../styles/control.css';

type TabKey = 'overview' | 'strategy' | 'icp' | 'offers' | 'goals' | 'data';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Visão Geral' },
  { key: 'strategy', label: 'Estratégia' },
  { key: 'icp', label: 'ICP' },
  { key: 'offers', label: 'Ofertas' },
  { key: 'goals', label: 'Objetivos' },
  { key: 'data', label: 'Dados' },
];

const isTabKey = (value: string | null): value is TabKey =>
  TABS.some((tab) => tab.key === value);

const BrainPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const activeTab: TabKey = isTabKey(rawTab) ? rawTab : 'overview';

  const loader = useCallback(() => brainApi.getOverview(), []);
  const { data, isLoading, error, reload } = useAsyncData<BrainOverview>(loader, []);

  useEffect(() => {
    document.title = 'Brain — BrainfyOS';
  }, []);

  const selectTab = (tab: TabKey) => {
    const next = new URLSearchParams(searchParams);
    if (tab === 'overview') next.delete('tab');
    else next.set('tab', tab);
    setSearchParams(next, { replace: true });
  };

  const readiness = data?.readiness;
  const sources = data?.sources || [];

  const availableSources = useMemo(
    () => sources.filter((source) => source.connected).length,
    [sources],
  );

  const lastUpdatedLabel = useMemo(() => {
    if (!readiness?.last_updated_at) return 'Nunca editado';
    return new Date(readiness.last_updated_at).toLocaleString('pt-BR', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }, [readiness]);

  return (
    <div className={`ctl-scope ${styles.page}`}>
      <div className={styles.inner}>
        <header className={styles.header}>
          <div className={styles.headerText}>
            <h1 className={styles.title}>Brain</h1>
            <p className={styles.subtitle}>
              O contexto central que orienta os agentes e decisões da sua operação.
            </p>

            <div className={styles.headerMeta}>
              <div className={styles.metaItem}>
                <span className={styles.metaLabel}>Última atualização</span>
                <span className={styles.metaValue}>{lastUpdatedLabel}</span>
              </div>
              <div className={styles.metaItem}>
                <span className={styles.metaLabel}>Fontes disponíveis</span>
                <span className={styles.metaValue}>
                  {availableSources} de {sources.length}
                </span>
              </div>
              <div className={styles.metaItem}>
                <span className={styles.metaLabel}>Precisa de atenção</span>
                <span className={styles.metaValue}>
                  {readiness ? `${readiness.missing.length} item(ns)` : '—'}
                </span>
              </div>
            </div>
          </div>

          <div
            className={styles.ring}
            style={{ ['--progress' as string]: readiness?.percent ?? 0 }}
            role="img"
            aria-label={`Brain Readiness em ${readiness?.percent ?? 0}%`}
          >
            <div className={styles.ringInner}>
              <span className={styles.ringValue}>{readiness ? `${readiness.percent}%` : '—'}</span>
              <span className={styles.ringLabel}>Readiness</span>
            </div>
          </div>
        </header>

        <div className="ctl-tabs" role="tablist" aria-label="Seções do Brain">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              className="ctl-tab"
              aria-selected={activeTab === tab.key}
              onClick={() => selectTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {error && <ErrorState message={error} />}

        {isLoading && !data && (
          <Panel title="Carregando Brain" flush>
            <SkeletonRows rows={6} />
          </Panel>
        )}

        {data && activeTab === 'overview' && <BrainOverviewTab overview={data} />}
        {activeTab === 'strategy' && <BrainStrategyTab onSaved={reload} />}
        {activeTab === 'icp' && <BrainIcpTab onChanged={reload} />}
        {activeTab === 'offers' && <BrainOffersTab onChanged={reload} />}
        {activeTab === 'goals' && <BrainGoalsTab onChanged={reload} />}
        {activeTab === 'data' && <BrainDataTab sources={sources} />}
      </div>
    </div>
  );
};

export default BrainPage;

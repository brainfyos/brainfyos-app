/**
 * Visão geral do Brain.
 *
 * Cada card é uma verificação do readiness — mesma fonte, mesmo peso, mesmo
 * texto. Não há número calculado no frontend: se um card mostra "1.248
 * contatos", esse valor veio de `COUNT(*)` em `contacts`.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Circle } from 'lucide-react';
import { Panel, StatusPill } from '../../components/control/ControlPrimitives.tsx';
import type { BrainOverview } from '../../services/brainApi.ts';
import styles from './Brain.module.css';

interface Props {
  overview: BrainOverview;
}

const BrainOverviewTab: React.FC<Props> = ({ overview }) => {
  const { readiness } = overview;

  return (
    <>
      <div className={styles.statusGrid}>
        {readiness.checks.map((check) => (
          <article
            key={check.key}
            className={`${styles.statusCard} ${check.done ? styles.statusCardDone : ''}`}
          >
            <span className={styles.statusHead}>
              {check.done ? (
                <CheckCircle2 className={styles.statusIconDone} aria-hidden />
              ) : (
                <Circle className={styles.statusIconPending} aria-hidden />
              )}
              {check.label}
            </span>
            <span className={styles.statusValue}>{check.done ? 'Pronto' : 'Pendente'}</span>
            <span className={styles.statusDetail}>{check.detail}</span>
            {!check.done && check.action_route && (
              <Link className={styles.statusLink} to={check.action_route}>
                Resolver →
              </Link>
            )}
          </article>
        ))}
      </div>

      {readiness.missing.length > 0 && (
        <Panel
          title="Precisa de atenção"
          description={`${readiness.missing.length} item(ns) faltando para o Brain ficar completo`}
          flush
        >
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Situação</th>
                  <th className="ctl-cell-num">Impacto</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {readiness.missing.map((check) => (
                  <tr key={check.key}>
                    <td className="ctl-cell-primary">{check.label}</td>
                    <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>
                      {check.detail}
                    </td>
                    <td className="ctl-cell-num">
                      {/* O peso é o quanto aquele item soma no readiness —
                          torna o número explicável em vez de opaco. */}
                      +{check.weight} pts
                    </td>
                    <td>
                      {check.action_route && (
                        <Link className="ctl-button" to={check.action_route}>
                          Resolver
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {readiness.missing.length === 0 && (
        <Panel title="Brain completo">
          <p className={styles.sectionNote}>
            Todas as verificações passaram. Os agentes têm estratégia, cliente ideal, oferta e
            objetivos para trabalhar, além das fontes operacionais conectadas.
          </p>
        </Panel>
      )}

      <Panel title="Como o readiness é calculado">
        <p className={styles.sectionNote}>
          É uma soma determinística: cada verificação vale um peso fixo e o percentual é a razão
          entre o peso conquistado ({readiness.earned_weight}) e o total ({readiness.total_weight}).
          Nenhuma IA participa do cálculo — a mesma base sempre produz o mesmo número, e cada ponto
          é rastreável até a verificação que o gerou.
        </p>
        <div style={{ marginTop: 'var(--ctl-space-3)', display: 'flex', gap: 'var(--ctl-space-2)', flexWrap: 'wrap' }}>
          {readiness.checks.map((check) => (
            <StatusPill key={check.key} tone={check.done ? 'positive' : 'neutral'}>
              {check.label} · {check.weight}
            </StatusPill>
          ))}
        </div>
      </Panel>
    </>
  );
};

export default BrainOverviewTab;

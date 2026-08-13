/**
 * Tela "Começar" — o primeiro destino de um workspace novo.
 *
 * O conteúdo vem inteiro do backend (`/api/onboarding/state`). Este componente
 * não conhece nenhuma tarefa: adicionar uma etapa é um seed, não um deploy.
 *
 * Tarefas marcadas como automáticas são conferidas no banco a cada carga, então
 * não há botão de "concluir" nelas — marcar à mão o que o sistema já sabe medir
 * produziria um checklist que mente.
 */

import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Circle, Clock, Lock } from 'lucide-react';
import { useAsyncData } from '../hooks/useAsyncData.ts';
import { branding } from '../config/branding.ts';
import {
  onboardingApi,
  type OnboardingItem,
  type OnboardingState,
  type OnboardingStatus,
} from '../services/onboardingApi.ts';
import styles from './GettingStarted.module.css';

const STATUS_META: Record<OnboardingStatus, { label: string; badge: string; icon: string }> = {
  done: { label: 'Concluído', badge: styles.badgeDone, icon: styles.cardIconDone },
  in_progress: { label: 'Em andamento', badge: styles.badgeProgress, icon: styles.cardIconProgress },
  blocked: { label: 'Bloqueado', badge: styles.badgeBlocked, icon: styles.cardIconBlocked },
  todo: { label: 'A fazer', badge: styles.badgeTodo, icon: styles.cardIconTodo },
  skipped: { label: 'Ignorado', badge: styles.badgeBlocked, icon: styles.cardIconBlocked },
};

const StatusIcon: React.FC<{ status: OnboardingStatus; className: string }> = ({ status, className }) => {
  if (status === 'done') return <CheckCircle2 className={className} aria-hidden />;
  if (status === 'blocked') return <Lock className={className} aria-hidden />;
  if (status === 'in_progress') return <Clock className={className} aria-hidden />;
  return <Circle className={className} aria-hidden />;
};

const GettingStarted: React.FC = () => {
  const loader = useCallback(() => onboardingApi.getState(), []);
  const { data, isLoading, error, reload } = useAsyncData<OnboardingState>(loader, []);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const updateStatus = async (item: OnboardingItem, status: OnboardingStatus) => {
    setPendingKey(item.key);
    setActionError(null);
    try {
      await onboardingApi.setItemStatus(item.key, status);
      reload();
    } catch {
      setActionError('Não foi possível atualizar esta etapa. Tente novamente.');
    } finally {
      setPendingKey(null);
    }
  };

  if (error) {
    return (
      <div className={styles.page}>
        <div className={styles.errorBox} role="alert">{error}</div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className={styles.page}>
        <div className={styles.stateBox}>Carregando seu roteiro…</div>
      </div>
    );
  }

  if (!data.template) {
    return (
      <div className={styles.page}>
        <div className={styles.stateBox}>
          Nenhum roteiro de onboarding está configurado para este workspace.
        </div>
      </div>
    );
  }

  const { progress } = data;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerText}>
          <h1 className={styles.title}>Bem-vindo à {branding.appName}</h1>
          <p className={styles.lede}>
            Vamos preparar o sistema operacional da sua empresa. Antes dos agentes começarem a
            trabalhar, precisamos entender seu negócio e conectar as principais fontes de dados.
          </p>
        </div>

        <div
          className={styles.progressRing}
          style={{ ['--progress' as string]: progress.percent }}
          role="img"
          aria-label={`${progress.completed} de ${progress.total} etapas concluídas`}
        >
          <div className={styles.progressInner}>
            <span className={styles.progressValue}>{progress.percent}%</span>
            <span className={styles.progressLabel}>
              {progress.completed}/{progress.total}
            </span>
          </div>
        </div>
      </header>

      {actionError && <div className={styles.errorBox} role="alert">{actionError}</div>}

      {data.sections.map((section) => (
        <section className={styles.section} key={section.key}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>{section.title}</h2>
            <span className={styles.sectionCount}>
              {section.completed}/{section.total}
            </span>
          </div>
          {section.description && <p className={styles.sectionDescription}>{section.description}</p>}

          <div className={styles.cards}>
            {section.items.map((item) => {
              const meta = STATUS_META[item.status];
              const isBlocked = item.status === 'blocked';
              const isDone = item.status === 'done';

              return (
                <article
                  key={item.key}
                  className={[
                    styles.card,
                    isBlocked ? styles.cardBlocked : '',
                    isDone ? styles.cardDone : '',
                  ].filter(Boolean).join(' ')}
                >
                  <div className={styles.cardTop}>
                    <StatusIcon status={item.status} className={`${styles.cardIcon} ${meta.icon}`} />
                    <h3 className={styles.cardTitle}>{item.title}</h3>
                  </div>

                  {item.description && <p className={styles.cardDescription}>{item.description}</p>}

                  {isBlocked && item.blocked_by.length > 0 && (
                    <p className={styles.blockedNote}>
                      Disponível depois de: {item.blocked_by.map((blocker) => blocker.title).join(', ')}.
                    </p>
                  )}

                  <div className={styles.cardMeta}>
                    <span className={`${styles.badge} ${meta.badge}`}>{meta.label}</span>
                    {!item.is_required && <span className={`${styles.badge} ${styles.badgeOptional}`}>Opcional</span>}
                    {item.estimated_minutes ? <span>~{item.estimated_minutes} min</span> : null}
                  </div>

                  <div className={styles.cardActions}>
                    {item.action_route && !isBlocked && (
                      <Link className={styles.primaryAction} to={item.action_route}>
                        {item.action_label || 'Abrir'}
                        <ArrowRight size={14} aria-hidden />
                      </Link>
                    )}

                    {/* Etapas automáticas não têm botão de concluir: o estado
                        vem do banco e marcar à mão seria uma mentira. */}
                    {item.is_automatic ? (
                      !isDone && <span className={styles.autoNote}>Concluída automaticamente ao configurar</span>
                    ) : (
                      !isBlocked && (
                        <button
                          type="button"
                          className={styles.ghostAction}
                          disabled={pendingKey === item.key}
                          onClick={() => updateStatus(item, isDone ? 'todo' : 'done')}
                        >
                          {isDone ? 'Reabrir' : 'Marcar como concluído'}
                        </button>
                      )
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
};

export default GettingStarted;

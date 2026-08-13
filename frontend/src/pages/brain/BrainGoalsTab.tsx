/**
 * Objetivos — o que os agentes vão usar para priorizar.
 *
 * O progresso mostrado é aritmética simples entre baseline e alvo. Não há
 * medição automática ainda: `metric_key` existe para quando houver um catálogo
 * de métricas calculadas, e até lá o valor atual não é inventado.
 */

import React, { useCallback, useState } from 'react';
import { Plus, Save, X } from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  Panel,
  SkeletonRows,
  StatusPill,
  formatDate,
} from '../../components/control/ControlPrimitives.tsx';
import { FieldGroup, SelectField, TextField } from '../../components/brain/BrainFields.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { brainApi, type BrainGoal, type BrainGoalInput } from '../../services/brainApi.ts';
import styles from './Brain.module.css';

const STATUS_OPTIONS = [
  { value: 'active', label: 'Ativo' },
  { value: 'achieved', label: 'Alcançado' },
  { value: 'missed', label: 'Não alcançado' },
];

const STATUS_TONE: Record<string, 'positive' | 'warning' | 'danger' | 'neutral'> = {
  active: 'accent' as never,
  achieved: 'positive',
  missed: 'danger',
  archived: 'neutral',
};

interface DraftState {
  id: number | null;
  name: string;
  description: string;
  metric_key: string;
  unit: string;
  baseline_value: string;
  target_value: string;
  period_start: string;
  period_end: string;
  priority: string;
  status: string;
}

const emptyDraft = (): DraftState => ({
  id: null,
  name: '',
  description: '',
  metric_key: '',
  unit: '',
  baseline_value: '',
  target_value: '',
  period_start: '',
  period_end: '',
  priority: '1',
  status: 'active',
});

const draftFrom = (goal: BrainGoal): DraftState => ({
  id: goal.id,
  name: goal.name,
  description: goal.description || '',
  metric_key: goal.metric_key || '',
  unit: goal.unit || '',
  baseline_value: goal.baseline_value === null ? '' : String(goal.baseline_value),
  target_value: goal.target_value === null ? '' : String(goal.target_value),
  period_start: goal.period_start || '',
  period_end: goal.period_end || '',
  priority: String(goal.priority),
  status: goal.status,
});

const toPayload = (draft: DraftState): BrainGoalInput => ({
  name: draft.name.trim(),
  description: draft.description.trim() || null,
  metric_key: draft.metric_key.trim() || null,
  unit: draft.unit.trim() || null,
  baseline_value: draft.baseline_value ? Number(draft.baseline_value) : null,
  target_value: draft.target_value ? Number(draft.target_value) : null,
  period_start: draft.period_start || null,
  period_end: draft.period_end || null,
  priority: Number(draft.priority) || 1,
  status: draft.status,
});

const formatValue = (value: number | null, unit: string | null): string => {
  if (value === null) return '—';
  const formatted = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(value);
  return unit ? `${formatted} ${unit}` : formatted;
};

interface Props {
  onChanged: () => void;
}

const BrainGoalsTab: React.FC<Props> = ({ onChanged }) => {
  const loader = useCallback(() => brainApi.listGoals(), []);
  const { data, isLoading, error, reload } = useAsyncData<BrainGoal[]>(loader, []);

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const set = <K extends keyof DraftState>(key: K) => (value: DraftState[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const handleSave = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      setSaveError('Dê um nome ao objetivo.');
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      if (draft.id === null) {
        await brainApi.createGoal(toPayload(draft));
      } else {
        await brainApi.updateGoal(draft.id, toPayload(draft));
      }
      setDraft(null);
      reload();
      onChanged();
    } catch {
      setSaveError('Não foi possível salvar o objetivo. Tente novamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleArchive = async (goal: BrainGoal) => {
    await brainApi.archiveGoal(goal.id);
    reload();
    onChanged();
  };

  if (error) return <ErrorState message={error} />;

  const goals = data || [];

  return (
    <>
      <Panel
        title="Objetivos"
        description="Metas que orientam a priorização dos agentes"
        actions={
          !draft && (
            <button type="button" className={styles.primaryButton} onClick={() => setDraft(emptyDraft())}>
              <Plus aria-hidden /> Novo objetivo
            </button>
          )
        }
        flush={!isLoading && goals.length > 0}
      >
        {isLoading ? (
          <SkeletonRows rows={3} />
        ) : goals.length === 0 ? (
          <EmptyState
            title="Nenhum objetivo definido"
            description="Ex.: aumentar receita mensal para R$ 500.000, reduzir CAC em 20%, encurtar o tempo de atendimento."
          />
        ) : (
          <div className="ctl-table-scroll">
            <table className="ctl-table">
              <thead>
                <tr>
                  <th>Objetivo</th>
                  <th>Métrica</th>
                  <th className="ctl-cell-num">Baseline</th>
                  <th className="ctl-cell-num">Meta</th>
                  <th>Período</th>
                  <th className="ctl-cell-num">Prioridade</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {goals.map((goal) => (
                  <tr key={goal.id}>
                    <td className="ctl-cell-primary">
                      {goal.name}
                      {goal.description && (
                        <div className="ctl-cell-muted" style={{ whiteSpace: 'normal', fontSize: 'var(--ctl-text-xs)' }}>
                          {goal.description}
                        </div>
                      )}
                    </td>
                    <td className="ctl-cell-muted">{goal.metric_key || '—'}</td>
                    <td className="ctl-cell-num">{formatValue(goal.baseline_value, goal.unit)}</td>
                    <td className="ctl-cell-num">{formatValue(goal.target_value, goal.unit)}</td>
                    <td className="ctl-cell-muted">
                      {goal.period_start || goal.period_end
                        ? `${formatDate(goal.period_start)} → ${formatDate(goal.period_end)}`
                        : '—'}
                    </td>
                    <td className="ctl-cell-num">{goal.priority}</td>
                    <td>
                      <StatusPill tone={STATUS_TONE[goal.status] || 'neutral'}>
                        {STATUS_OPTIONS.find((option) => option.value === goal.status)?.label || goal.status}
                      </StatusPill>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 'var(--ctl-space-2)' }}>
                        <button type="button" className="ctl-button" onClick={() => setDraft(draftFrom(goal))}>
                          Editar
                        </button>
                        <button type="button" className={styles.dangerLink} onClick={() => handleArchive(goal)}>
                          Arquivar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {draft && (
        <Panel
          title={draft.id === null ? 'Novo objetivo' : `Editando: ${draft.name || 'objetivo'}`}
          actions={
            <button type="button" className="ctl-button" onClick={() => setDraft(null)}>
              <X aria-hidden /> Cancelar
            </button>
          }
        >
          <FieldGroup>
            <TextField
              label="Nome"
              value={draft.name}
              onChange={set('name')}
              placeholder="Ex.: Aumentar receita mensal para R$ 500.000"
            />
            <TextField
              label="Chave da métrica"
              value={draft.metric_key}
              onChange={set('metric_key')}
              placeholder="mrr, cac, conversao_reuniao_venda…"
              hint="Identificador livre por enquanto. Vai ligar a métricas calculadas no futuro."
            />
            <TextField label="Descrição" value={draft.description} onChange={set('description')} multiline wide />
            <TextField label="Valor atual (baseline)" value={draft.baseline_value} onChange={set('baseline_value')} type="number" />
            <TextField label="Valor alvo" value={draft.target_value} onChange={set('target_value')} type="number" />
            <TextField label="Unidade" value={draft.unit} onChange={set('unit')} placeholder="R$, %, dias…" />
            <TextField label="Início do período" value={draft.period_start} onChange={set('period_start')} type="date" />
            <TextField label="Fim do período" value={draft.period_end} onChange={set('period_end')} type="date" />
            <TextField label="Prioridade" value={draft.priority} onChange={set('priority')} type="number" />
            <SelectField label="Status" value={draft.status} onChange={set('status')} options={STATUS_OPTIONS} />
          </FieldGroup>

          {saveError && <div style={{ marginTop: 'var(--ctl-space-3)' }}><ErrorState message={saveError} /></div>}

          <div className={styles.formActions}>
            <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={isSaving}>
              <Save aria-hidden />
              {isSaving ? 'Salvando…' : 'Salvar objetivo'}
            </button>
          </div>
        </Panel>
      )}
    </>
  );
};

export default BrainGoalsTab;

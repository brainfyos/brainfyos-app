/**
 * ICP — para quem a empresa vende.
 *
 * Lista em cards com edição inline num painel. Prioridade 1 é o ICP principal;
 * os demais são secundários em ordem. Arquivamento é lógico: um ICP referenciado
 * por uma oferta não pode simplesmente sumir.
 */

import React, { useCallback, useState } from 'react';
import { Plus, Save, X } from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  Panel,
  SkeletonRows,
  StatusPill,
  formatCurrency,
} from '../../components/control/ControlPrimitives.tsx';
import { FieldGroup, ListField, SelectField, TextField } from '../../components/brain/BrainFields.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { brainApi, type BrainIcp, type BrainIcpInput } from '../../services/brainApi.ts';
import styles from './Brain.module.css';

const CUSTOMER_TYPES = [
  { value: '', label: 'Não definido' },
  { value: 'b2b', label: 'B2B — vende para empresas' },
  { value: 'b2c', label: 'B2C — vende para pessoas' },
  { value: 'b2b2c', label: 'B2B2C — vende através de parceiros' },
];

interface DraftState {
  id: number | null;
  name: string;
  description: string;
  customer_type: string;
  industry: string;
  company_size: string;
  location: string;
  revenue_range: string;
  average_ticket: string;
  priority: string;
  pain_points: string[];
  desired_outcomes: string[];
  buying_triggers: string[];
  objections: string[];
  decision_makers: string[];
  qualification_criteria: string[];
  disqualification_criteria: string[];
}

const emptyDraft = (): DraftState => ({
  id: null,
  name: '',
  description: '',
  customer_type: '',
  industry: '',
  company_size: '',
  location: '',
  revenue_range: '',
  average_ticket: '',
  priority: '1',
  pain_points: [],
  desired_outcomes: [],
  buying_triggers: [],
  objections: [],
  decision_makers: [],
  qualification_criteria: [],
  disqualification_criteria: [],
});

const draftFrom = (icp: BrainIcp): DraftState => ({
  id: icp.id,
  name: icp.name,
  description: icp.description || '',
  customer_type: icp.customer_type || '',
  industry: icp.industry || '',
  company_size: icp.company_size || '',
  location: icp.location || '',
  revenue_range: icp.revenue_range || '',
  average_ticket: icp.average_ticket === null ? '' : String(icp.average_ticket),
  priority: String(icp.priority),
  pain_points: icp.pain_points,
  desired_outcomes: icp.desired_outcomes,
  buying_triggers: icp.buying_triggers,
  objections: icp.objections,
  decision_makers: icp.decision_makers,
  qualification_criteria: icp.qualification_criteria,
  disqualification_criteria: icp.disqualification_criteria,
});

const toPayload = (draft: DraftState): BrainIcpInput => ({
  name: draft.name.trim(),
  description: draft.description.trim() || null,
  customer_type: draft.customer_type || null,
  industry: draft.industry.trim() || null,
  company_size: draft.company_size.trim() || null,
  location: draft.location.trim() || null,
  revenue_range: draft.revenue_range.trim() || null,
  average_ticket: draft.average_ticket ? Number(draft.average_ticket) : null,
  priority: Number(draft.priority) || 1,
  pain_points: draft.pain_points,
  desired_outcomes: draft.desired_outcomes,
  buying_triggers: draft.buying_triggers,
  objections: draft.objections,
  decision_makers: draft.decision_makers,
  qualification_criteria: draft.qualification_criteria,
  disqualification_criteria: draft.disqualification_criteria,
});

interface Props {
  onChanged: () => void;
}

const BrainIcpTab: React.FC<Props> = ({ onChanged }) => {
  const loader = useCallback(() => brainApi.listIcps(), []);
  const { data, isLoading, error, reload } = useAsyncData<BrainIcp[]>(loader, []);

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const set = <K extends keyof DraftState>(key: K) => (value: DraftState[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const handleSave = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      setSaveError('Dê um nome ao ICP.');
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      if (draft.id === null) {
        await brainApi.createIcp(toPayload(draft));
      } else {
        await brainApi.updateIcp(draft.id, toPayload(draft));
      }
      setDraft(null);
      reload();
      onChanged();
    } catch {
      setSaveError('Não foi possível salvar o ICP. Tente novamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleArchive = async (icp: BrainIcp) => {
    await brainApi.archiveIcp(icp.id);
    reload();
    onChanged();
  };

  if (error) return <ErrorState message={error} />;

  return (
    <>
      <Panel
        title="Clientes ideais"
        description="Prioridade 1 é o ICP principal"
        actions={
          !draft && (
            <button type="button" className={styles.primaryButton} onClick={() => setDraft(emptyDraft())}>
              <Plus aria-hidden /> Novo ICP
            </button>
          )
        }
        flush={!isLoading && (data || []).length > 0}
      >
        {isLoading ? (
          <SkeletonRows rows={3} />
        ) : (data || []).length === 0 ? (
          <EmptyState
            title="Nenhum ICP definido"
            description="Sem cliente ideal, um agente trata todo lead do mesmo jeito — e qualifica mal."
          />
        ) : (
          <div className={styles.cardGrid} style={{ padding: 'var(--ctl-space-4)' }}>
            {(data || []).map((icp) => (
              <article
                key={icp.id}
                className={`${styles.entityCard} ${icp.priority === 1 ? styles.entityCardPrimary : ''}`}
              >
                <div className={styles.entityHead}>
                  <h3 className={styles.entityName}>{icp.name}</h3>
                  <div className={styles.entityActions}>
                    {icp.priority === 1 && <StatusPill tone="accent">Principal</StatusPill>}
                  </div>
                </div>

                {icp.description && <p className={styles.entityDescription}>{icp.description}</p>}

                <div className={styles.entityFacts}>
                  {icp.industry && (
                    <span className={styles.entityFact}>
                      <strong>{icp.industry}</strong>
                      segmento
                    </span>
                  )}
                  {icp.average_ticket !== null && (
                    <span className={styles.entityFact}>
                      <strong>{formatCurrency(icp.average_ticket)}</strong>
                      ticket médio
                    </span>
                  )}
                  {icp.customer_type && (
                    <span className={styles.entityFact}>
                      <strong>{icp.customer_type.toUpperCase()}</strong>
                      tipo
                    </span>
                  )}
                </div>

                {icp.pain_points.length > 0 && (
                  <div>
                    <span className={styles.label}>Principais dores</span>
                    <div className={styles.chips} style={{ marginTop: 'var(--ctl-space-2)' }}>
                      {icp.pain_points.slice(0, 4).map((pain) => (
                        <span key={pain} className={styles.chip}>{pain}</span>
                      ))}
                    </div>
                  </div>
                )}

                <div className={styles.entityFooter}>
                  <StatusPill tone={icp.is_active ? 'positive' : 'neutral'}>
                    {icp.is_active ? 'Ativo' : 'Arquivado'}
                  </StatusPill>
                  <button type="button" className="ctl-button" onClick={() => setDraft(draftFrom(icp))}>
                    Editar
                  </button>
                  <button type="button" className={styles.dangerLink} onClick={() => handleArchive(icp)}>
                    Arquivar
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>

      {draft && (
        <Panel
          title={draft.id === null ? 'Novo ICP' : `Editando: ${draft.name || 'ICP'}`}
          actions={
            <button type="button" className="ctl-button" onClick={() => setDraft(null)}>
              <X aria-hidden /> Cancelar
            </button>
          }
        >
          <FieldGroup>
            <TextField label="Nome" value={draft.name} onChange={set('name')} placeholder="Ex.: Clínicas de médio porte" />
            <SelectField label="Tipo de cliente" value={draft.customer_type} onChange={set('customer_type')} options={CUSTOMER_TYPES} />
            <TextField label="Descrição" value={draft.description} onChange={set('description')} multiline wide />
            <TextField label="Segmento" value={draft.industry} onChange={set('industry')} />
            <TextField label="Porte" value={draft.company_size} onChange={set('company_size')} placeholder="Ex.: 10 a 50 funcionários" />
            <TextField label="Localização" value={draft.location} onChange={set('location')} />
            <TextField label="Faixa de faturamento" value={draft.revenue_range} onChange={set('revenue_range')} />
            <TextField label="Ticket médio (R$)" value={draft.average_ticket} onChange={set('average_ticket')} type="number" />
            <TextField
              label="Prioridade"
              value={draft.priority}
              onChange={set('priority')}
              type="number"
              hint="1 é o ICP principal."
            />
            <ListField label="Dores" values={draft.pain_points} onChange={set('pain_points')} />
            <ListField label="Resultados desejados" values={draft.desired_outcomes} onChange={set('desired_outcomes')} />
            <ListField label="Gatilhos de compra" values={draft.buying_triggers} onChange={set('buying_triggers')} />
            <ListField label="Objeções" values={draft.objections} onChange={set('objections')} />
            <ListField label="Decisores" values={draft.decision_makers} onChange={set('decision_makers')} />
            <ListField
              label="Critérios de qualificação"
              values={draft.qualification_criteria}
              onChange={set('qualification_criteria')}
            />
            <ListField
              label="Critérios de desqualificação"
              values={draft.disqualification_criteria}
              onChange={set('disqualification_criteria')}
              hint="O que faz um lead não valer a pena. Evita que o agente insista onde não deve."
            />
          </FieldGroup>

          {saveError && <div style={{ marginTop: 'var(--ctl-space-3)' }}><ErrorState message={saveError} /></div>}

          <div className={styles.formActions}>
            <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={isSaving}>
              <Save aria-hidden />
              {isSaving ? 'Salvando…' : 'Salvar ICP'}
            </button>
          </div>
        </Panel>
      )}
    </>
  );
};

export default BrainIcpTab;

/**
 * Ofertas — como o que a empresa vende chega ao mercado.
 *
 * Oferta não é Plano. O plano é a estrutura comercial (preço, cobrança) e
 * continua dono desses números; a oferta descreve promessa, mecanismo e prova.
 * Quando há plano associado, o ticket exibido vem dele — não duplicamos o
 * valor financeiro aqui.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Plus, Save, Star, X } from 'lucide-react';
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
import {
  brainApi,
  type BrainIcp,
  type BrainOffer,
  type BrainOfferInput,
  type LinkablePlan,
} from '../../services/brainApi.ts';
import styles from './Brain.module.css';

interface OfferData {
  offers: BrainOffer[];
  icps: BrainIcp[];
  plans: LinkablePlan[];
}

interface DraftState {
  id: number | null;
  name: string;
  description: string;
  promise: string;
  mechanism: string;
  pricing_strategy: string;
  target_icp_id: string;
  related_plan_id: string;
  average_ticket: string;
  margin_estimate: string;
  sales_cycle_days: string;
  main_objections: string[];
  proof_points: string[];
  is_primary: boolean;
}

const emptyDraft = (): DraftState => ({
  id: null,
  name: '',
  description: '',
  promise: '',
  mechanism: '',
  pricing_strategy: '',
  target_icp_id: '',
  related_plan_id: '',
  average_ticket: '',
  margin_estimate: '',
  sales_cycle_days: '',
  main_objections: [],
  proof_points: [],
  is_primary: false,
});

const draftFrom = (offer: BrainOffer): DraftState => ({
  id: offer.id,
  name: offer.name,
  description: offer.description || '',
  promise: offer.promise || '',
  mechanism: offer.mechanism || '',
  pricing_strategy: offer.pricing_strategy || '',
  target_icp_id: offer.target_icp_id ? String(offer.target_icp_id) : '',
  related_plan_id: offer.related_plan_id ? String(offer.related_plan_id) : '',
  average_ticket: offer.average_ticket === null ? '' : String(offer.average_ticket),
  margin_estimate: offer.margin_estimate === null ? '' : String(offer.margin_estimate),
  sales_cycle_days: offer.sales_cycle_days === null ? '' : String(offer.sales_cycle_days),
  main_objections: offer.main_objections,
  proof_points: offer.proof_points,
  is_primary: offer.is_primary,
});

const toPayload = (draft: DraftState): BrainOfferInput => ({
  name: draft.name.trim(),
  description: draft.description.trim() || null,
  promise: draft.promise.trim() || null,
  mechanism: draft.mechanism.trim() || null,
  pricing_strategy: draft.pricing_strategy.trim() || null,
  target_icp_id: draft.target_icp_id ? Number(draft.target_icp_id) : null,
  related_plan_id: draft.related_plan_id ? Number(draft.related_plan_id) : null,
  // Ticket próprio só quando não há plano: com plano, plans.price é a verdade.
  average_ticket: draft.related_plan_id || !draft.average_ticket ? null : Number(draft.average_ticket),
  margin_estimate: draft.margin_estimate ? Number(draft.margin_estimate) : null,
  sales_cycle_days: draft.sales_cycle_days ? Number(draft.sales_cycle_days) : null,
  main_objections: draft.main_objections,
  proof_points: draft.proof_points,
  is_primary: draft.is_primary,
});

interface Props {
  onChanged: () => void;
}

const BrainOffersTab: React.FC<Props> = ({ onChanged }) => {
  const loader = useCallback(async (): Promise<OfferData> => {
    const [offers, icps, plans] = await Promise.all([
      brainApi.listOffers(),
      brainApi.listIcps(),
      brainApi.listPlans(),
    ]);
    return { offers, icps, plans };
  }, []);
  const { data, isLoading, error, reload } = useAsyncData<OfferData>(loader, []);

  const [draft, setDraft] = useState<DraftState | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const set = <K extends keyof DraftState>(key: K) => (value: DraftState[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const icpOptions = useMemo(
    () => [
      { value: '', label: 'Nenhum ICP associado' },
      ...(data?.icps || []).map((icp) => ({ value: String(icp.id), label: icp.name })),
    ],
    [data],
  );

  const planOptions = useMemo(
    () => [
      { value: '', label: 'Nenhum plano associado' },
      ...(data?.plans || []).map((plan) => ({
        value: String(plan.id),
        label: `${plan.name}${plan.price !== null ? ` — ${formatCurrency(plan.price)}` : ''}`,
      })),
    ],
    [data],
  );

  const handleSave = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      setSaveError('Dê um nome à oferta.');
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      if (draft.id === null) {
        await brainApi.createOffer(toPayload(draft));
      } else {
        await brainApi.updateOffer(draft.id, toPayload(draft));
      }
      setDraft(null);
      reload();
      onChanged();
    } catch {
      setSaveError('Não foi possível salvar a oferta. Tente novamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const handlePromote = async (offer: BrainOffer) => {
    await brainApi.updateOffer(offer.id, { is_primary: true });
    reload();
    onChanged();
  };

  const handleArchive = async (offer: BrainOffer) => {
    await brainApi.archiveOffer(offer.id);
    reload();
    onChanged();
  };

  if (error) return <ErrorState message={error} />;

  const offers = data?.offers || [];

  return (
    <>
      <Panel
        title="Ofertas"
        description="Uma oferta principal por vez; as demais ficam ativas como alternativas"
        actions={
          !draft && (
            <button type="button" className={styles.primaryButton} onClick={() => setDraft(emptyDraft())}>
              <Plus aria-hidden /> Nova oferta
            </button>
          )
        }
        flush={!isLoading && offers.length > 0}
      >
        {isLoading ? (
          <SkeletonRows rows={3} />
        ) : offers.length === 0 ? (
          <EmptyState
            title="Nenhuma oferta cadastrada"
            description="A oferta é o que o agente precisa saber para vender: a promessa, como ela é cumprida e com que prova."
          />
        ) : (
          <div className={styles.cardGrid} style={{ padding: 'var(--ctl-space-4)' }}>
            {offers.map((offer) => (
              <article
                key={offer.id}
                className={`${styles.entityCard} ${offer.is_primary ? styles.entityCardPrimary : ''}`}
              >
                <div className={styles.entityHead}>
                  <h3 className={styles.entityName}>{offer.name}</h3>
                  <div className={styles.entityActions}>
                    {offer.is_primary && <StatusPill tone="accent">Principal</StatusPill>}
                  </div>
                </div>

                {offer.promise && <p className={styles.entityDescription}>{offer.promise}</p>}

                <div className={styles.entityFacts}>
                  {offer.related_plan_name ? (
                    <span className={styles.entityFact}>
                      <strong>{offer.related_plan_name}</strong>
                      plano associado
                    </span>
                  ) : offer.average_ticket !== null ? (
                    <span className={styles.entityFact}>
                      <strong>{formatCurrency(offer.average_ticket)}</strong>
                      ticket estimado
                    </span>
                  ) : null}
                  {offer.target_icp_name && (
                    <span className={styles.entityFact}>
                      <strong>{offer.target_icp_name}</strong>
                      ICP alvo
                    </span>
                  )}
                  {offer.sales_cycle_days !== null && (
                    <span className={styles.entityFact}>
                      <strong>{offer.sales_cycle_days} dias</strong>
                      ciclo de venda
                    </span>
                  )}
                </div>

                <div className={styles.entityFooter}>
                  {!offer.is_primary && (
                    <button type="button" className="ctl-button" onClick={() => handlePromote(offer)}>
                      <Star aria-hidden /> Tornar principal
                    </button>
                  )}
                  <button type="button" className="ctl-button" onClick={() => setDraft(draftFrom(offer))}>
                    Editar
                  </button>
                  <button type="button" className={styles.dangerLink} onClick={() => handleArchive(offer)}>
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
          title={draft.id === null ? 'Nova oferta' : `Editando: ${draft.name || 'oferta'}`}
          actions={
            <button type="button" className="ctl-button" onClick={() => setDraft(null)}>
              <X aria-hidden /> Cancelar
            </button>
          }
        >
          <FieldGroup>
            <TextField label="Nome" value={draft.name} onChange={set('name')} />
            <SelectField label="ICP alvo" value={draft.target_icp_id} onChange={set('target_icp_id')} options={icpOptions} />
            <TextField label="Descrição" value={draft.description} onChange={set('description')} multiline wide />
            <TextField
              label="Promessa"
              value={draft.promise}
              onChange={set('promise')}
              multiline
              placeholder="O resultado que o cliente compra"
            />
            <TextField
              label="Mecanismo"
              value={draft.mechanism}
              onChange={set('mechanism')}
              multiline
              placeholder="Como a promessa é cumprida na prática"
            />
            <SelectField
              label="Plano associado"
              value={draft.related_plan_id}
              onChange={set('related_plan_id')}
              options={planOptions}
              hint="Com plano associado, o preço vem dele — nada é duplicado aqui."
            />
            {!draft.related_plan_id && (
              <TextField
                label="Ticket estimado (R$)"
                value={draft.average_ticket}
                onChange={set('average_ticket')}
                type="number"
                hint="Só usado enquanto não houver plano associado."
              />
            )}
            <TextField label="Margem estimada (%)" value={draft.margin_estimate} onChange={set('margin_estimate')} type="number" />
            <TextField label="Ciclo de venda (dias)" value={draft.sales_cycle_days} onChange={set('sales_cycle_days')} type="number" />
            <TextField label="Estratégia de preço" value={draft.pricing_strategy} onChange={set('pricing_strategy')} multiline wide />
            <ListField label="Principais objeções" values={draft.main_objections} onChange={set('main_objections')} />
            <ListField
              label="Provas"
              values={draft.proof_points}
              onChange={set('proof_points')}
              hint="Casos, números e garantias que o agente pode citar."
            />
          </FieldGroup>

          <label
            className={styles.field}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 'var(--ctl-space-2)', marginTop: 'var(--ctl-space-3)' }}
          >
            <input
              type="checkbox"
              checked={draft.is_primary}
              onChange={(event) => set('is_primary')(event.target.checked)}
            />
            <span className={styles.hint}>
              Oferta principal — substitui a atual, se houver
            </span>
          </label>

          {saveError && <div style={{ marginTop: 'var(--ctl-space-3)' }}><ErrorState message={saveError} /></div>}

          <div className={styles.formActions}>
            <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={isSaving}>
              <Save aria-hidden />
              {isSaving ? 'Salvando…' : 'Salvar oferta'}
            </button>
          </div>
        </Panel>
      )}
    </>
  );
};

export default BrainOffersTab;

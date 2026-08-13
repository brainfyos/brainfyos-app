/**
 * Estratégia — o perfil que orienta todo agente.
 *
 * Agrupado por contexto (identidade, mercado, execução) em vez de uma coluna
 * única com onze campos: um formulário longo e indiferenciado faz a pessoa
 * preencher no automático, e é justamente aqui que a resposta pensada importa.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { ErrorState, Panel, SkeletonRows } from '../../components/control/ControlPrimitives.tsx';
import { FieldGroup, ListField, TextField } from '../../components/brain/BrainFields.tsx';
import { useAsyncData } from '../../hooks/useAsyncData.ts';
import { brainApi, type BrainProfile } from '../../services/brainApi.ts';
import styles from './Brain.module.css';

const EMPTY: BrainProfile = {
  id: null,
  business_model: null,
  market: null,
  positioning: null,
  value_proposition: null,
  revenue_model: null,
  sales_motion: null,
  additional_context: null,
  competitive_advantages: [],
  main_channels: [],
  strategic_priorities: [],
  constraints: [],
  updated_at: null,
};

interface Props {
  onSaved: () => void;
}

const BrainStrategyTab: React.FC<Props> = ({ onSaved }) => {
  const loader = useCallback(() => brainApi.getProfile(), []);
  const { data, isLoading, error } = useAsyncData<BrainProfile>(loader, []);

  const [form, setForm] = useState<BrainProfile>(EMPTY);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    if (data) setForm({ ...EMPTY, ...data });
  }, [data]);

  const setText = (key: keyof BrainProfile) => (value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const setList = (key: keyof BrainProfile) => (values: string[]) =>
    setForm((current) => ({ ...current, [key]: values }));

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      const saved = await brainApi.saveProfile({
        business_model: form.business_model,
        market: form.market,
        positioning: form.positioning,
        value_proposition: form.value_proposition,
        revenue_model: form.revenue_model,
        sales_motion: form.sales_motion,
        additional_context: form.additional_context,
        competitive_advantages: form.competitive_advantages,
        main_channels: form.main_channels,
        strategic_priorities: form.strategic_priorities,
        constraints: form.constraints,
      });
      setForm({ ...EMPTY, ...saved });
      setSavedAt(new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }));
      onSaved();
    } catch {
      setSaveError('Não foi possível salvar a estratégia. Tente novamente.');
    } finally {
      setIsSaving(false);
    }
  };

  if (error) return <ErrorState message={error} />;
  if (isLoading) {
    return (
      <Panel title="Carregando estratégia" flush>
        <SkeletonRows rows={5} />
      </Panel>
    );
  }

  return (
    <>
      <Panel
        title="Identidade"
        description="O que a empresa é e por que alguém escolheria ela"
      >
        <FieldGroup>
          <TextField
            label="Modelo de negócio"
            value={form.business_model || ''}
            onChange={setText('business_model')}
            multiline
            placeholder="Como a empresa entrega valor e cobra por isso"
            hint="Conta para o readiness."
          />
          <TextField
            label="Posicionamento"
            value={form.positioning || ''}
            onChange={setText('positioning')}
            multiline
            placeholder="Que lugar a empresa ocupa na cabeça do cliente"
            hint="Conta para o readiness."
          />
          <TextField
            label="Proposta de valor"
            value={form.value_proposition || ''}
            onChange={setText('value_proposition')}
            multiline
            wide
            placeholder="A promessa central, na linguagem do cliente"
            hint="Conta para o readiness."
          />
        </FieldGroup>
      </Panel>

      <Panel title="Mercado" description="Onde a empresa compete e com que vantagens">
        <FieldGroup>
          <TextField
            label="Mercado"
            value={form.market || ''}
            onChange={setText('market')}
            multiline
            placeholder="Segmento, região e recorte de atuação"
          />
          <ListField
            label="Diferenciais competitivos"
            values={form.competitive_advantages}
            onChange={setList('competitive_advantages')}
            placeholder="Um diferencial por vez"
          />
          <ListField
            label="Canais principais"
            values={form.main_channels}
            onChange={setList('main_channels')}
            placeholder="WhatsApp, indicação, tráfego pago…"
          />
        </FieldGroup>
      </Panel>

      <Panel title="Execução" description="Como a receita acontece e o que limita o crescimento">
        <FieldGroup>
          <TextField
            label="Modelo de receita"
            value={form.revenue_model || ''}
            onChange={setText('revenue_model')}
            multiline
            placeholder="Recorrência, venda única, ticket por procedimento…"
          />
          <TextField
            label="Movimento de vendas"
            value={form.sales_motion || ''}
            onChange={setText('sales_motion')}
            multiline
            placeholder="Inbound, outbound, autoatendimento, vendas consultivas…"
          />
          <ListField
            label="Prioridades estratégicas"
            values={form.strategic_priorities}
            onChange={setList('strategic_priorities')}
            placeholder="O que precisa acontecer neste ciclo"
          />
          <ListField
            label="Restrições"
            values={form.constraints}
            onChange={setList('constraints')}
            placeholder="Capacidade, regulação, orçamento…"
            hint="Os agentes usam isso para não prometer o que a operação não entrega."
          />
          <TextField
            label="Contexto adicional"
            value={form.additional_context || ''}
            onChange={setText('additional_context')}
            multiline
            wide
            placeholder="Qualquer coisa relevante que não coube acima"
          />
        </FieldGroup>

        {saveError && <div style={{ marginTop: 'var(--ctl-space-3)' }}><ErrorState message={saveError} /></div>}

        <div className={styles.formActions}>
          <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={isSaving}>
            <Save aria-hidden />
            {isSaving ? 'Salvando…' : 'Salvar estratégia'}
          </button>
          {savedAt && <span className={styles.savedNote}>Salvo às {savedAt}</span>}
        </div>
      </Panel>
    </>
  );
};

export default BrainStrategyTab;

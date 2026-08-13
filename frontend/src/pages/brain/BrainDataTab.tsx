/**
 * Dados — o que o Brain já enxerga.
 *
 * Não existe data warehouse novo. Esta tela lista as fontes canônicas que já
 * estão no sistema, com a contagem real de cada uma. Serve para o cliente ver
 * o que os agentes podem usar hoje, e o que ainda está vazio.
 */

import React from 'react';
import { Database } from 'lucide-react';
import {
  EmptyState,
  Panel,
  StatusPill,
  formatNumber,
  formatRelative,
} from '../../components/control/ControlPrimitives.tsx';
import type { BrainSource } from '../../services/brainApi.ts';
import styles from './Brain.module.css';

const SOURCE_DESCRIPTION: Record<string, string> = {
  crm_contacts: 'Quem já falou com a empresa em qualquer canal',
  crm_leads: 'Oportunidades no funil, com etapa e valor',
  conversations: 'Histórico de mensagens usado como contexto de atendimento',
  contracts: 'Contratos fechados, valores e situação',
  invoices: 'Faturas emitidas e o que está em aberto',
  payments: 'Pagamentos recebidos',
  nps: 'Respostas de satisfação já coletadas',
  ai_usage: 'Consumo de IA por agente, modelo e custo',
  whatsapp: 'Canal de atendimento conectado via WAHA',
};

interface Props {
  sources: BrainSource[];
}

const BrainDataTab: React.FC<Props> = ({ sources }) => {
  if (sources.length === 0) {
    return (
      <Panel title="Fontes de dados">
        <EmptyState icon={Database} title="Nenhuma fonte disponível" />
      </Panel>
    );
  }

  const connected = sources.filter((source) => source.connected).length;

  return (
    <>
      <Panel
        title="Fontes canônicas"
        description={`${connected} de ${sources.length} com dados`}
        flush
      >
        <div className="ctl-table-scroll">
          <table className="ctl-table">
            <thead>
              <tr>
                <th>Fonte</th>
                <th>O que o Brain lê</th>
                <th className="ctl-cell-num">Registros</th>
                <th>Atualização</th>
                <th>Situação</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.key}>
                  <td className="ctl-cell-primary">{source.label}</td>
                  <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>
                    {SOURCE_DESCRIPTION[source.key] || '—'}
                  </td>
                  <td className="ctl-cell-num">
                    {/* Integração não tem contagem: exibir 0 sugeriria base
                        vazia em vez de canal desconectado. */}
                    {source.record_count === null ? '—' : formatNumber(source.record_count)}
                  </td>
                  <td className="ctl-cell-muted">
                    {source.last_updated_at ? formatRelative(source.last_updated_at) : '—'}
                  </td>
                  <td>
                    <StatusPill tone={source.connected ? 'positive' : 'neutral'}>
                      {source.connected ? 'Disponível' : 'Sem dados'}
                    </StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Sobre estas fontes">
        <p className={styles.sectionNote}>
          Nenhum destes dados é copiado para o Brain. CRM, conversas, contratos, faturas,
          pagamentos e NPS continuam sendo as fontes de verdade e são lidos onde vivem — o Brain
          apenas organiza tudo em contexto na hora em que um agente pergunta. Quando um contrato
          muda, a próxima resposta já reflete a mudança, porque não existe cópia para envelhecer.
        </p>
      </Panel>
    </>
  );
};

export default BrainDataTab;

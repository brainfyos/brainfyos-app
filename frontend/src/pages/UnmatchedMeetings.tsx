/**
 * Reuniões que o sistema não conseguiu associar sozinho.
 *
 * Existe porque o resolvedor é conservador de propósito: associar ao lead
 * errado contamina a inteligência e ninguém percebe. Uma reunião nesta lista
 * é resolvida em segundos, e depois o processamento segue.
 *
 * Visual enterprise escuro da Fase 1 — os tokens vêm de `control.css`.
 */

import React, { useCallback, useState } from 'react';
import { CheckCircle2, Link2, RefreshCw } from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  Panel,
  SkeletonRows,
  StatusPill,
  formatDateTime,
} from '../components/control/ControlPrimitives.tsx';
import { useAsyncData } from '../hooks/useAsyncData.ts';
import {
  meetingsApi,
  type Meeting,
  type ProviderStatus,
  type ResolutionCandidate,
} from '../services/meetingsApi.ts';
import '../styles/control.css';

interface PageData {
  unmatched: Meeting[];
  ambiguous: Meeting[];
  providers: ProviderStatus[];
}

const UnmatchedMeetings: React.FC = () => {
  const loader = useCallback(async (): Promise<PageData> => {
    const [unmatchedPage, ambiguousPage, providers] = await Promise.all([
      meetingsApi.list({ resolutionStatus: 'unmatched', pageSize: 50 }),
      meetingsApi.list({ resolutionStatus: 'ambiguous', pageSize: 50 }),
      meetingsApi.providers(),
    ]);
    return { unmatched: unmatchedPage.items, ambiguous: ambiguousPage.items, providers };
  }, []);

  const { data, isLoading, error, reload } = useAsyncData<PageData>(loader, []);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const associate = async (meeting: Meeting, candidate: ResolutionCandidate) => {
    setPendingId(meeting.id);
    setActionError(null);
    try {
      await meetingsApi.associate(meeting.id, {
        lead_id: candidate.lead_id ?? undefined,
        contact_id: candidate.contact_id ?? undefined,
        customer_id: candidate.customer_id ?? undefined,
      });
      reload();
    } catch {
      setActionError('Não foi possível associar esta reunião.');
    } finally {
      setPendingId(null);
    }
  };

  const sync = async () => {
    await meetingsApi.sync();
    reload();
  };

  if (error) return <div className="ctl-scope" style={{ padding: 24 }}><ErrorState message={error} /></div>;

  return (
    <div className="ctl-scope" style={{ minHeight: '100vh' }}>
      <div className="ctl-content" style={{ maxWidth: 1080 }}>
        <div className="ctl-page-head">
          <div>
            <h1>Reuniões não associadas</h1>
            <p>
              O BrainfyOS não associa uma reunião quando não tem certeza. Confirme aqui a quem
              cada uma pertence e o processamento continua sozinho.
            </p>
          </div>
          <button type="button" className="ctl-button" onClick={sync} style={{ marginLeft: 'auto' }}>
            <RefreshCw aria-hidden /> Sincronizar agora
          </button>
        </div>

        {actionError && <ErrorState message={actionError} />}

        <Panel title="Provedores" description="O que está disponível hoje nesta empresa" flush>
          {isLoading || !data ? (
            <SkeletonRows rows={2} />
          ) : (
            <div className="ctl-table-scroll">
              <table className="ctl-table">
                <thead>
                  <tr>
                    <th>Provedor</th>
                    <th>Descobre reuniões</th>
                    <th>Importa transcrição</th>
                    <th>Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {data.providers.map((provider) => (
                    <tr key={provider.provider}>
                      <td className="ctl-cell-primary">{provider.label}</td>
                      <td>
                        <StatusPill tone={provider.can_discover_meetings ? 'positive' : 'neutral'}>
                          {provider.can_discover_meetings ? 'Sim' : 'Não'}
                        </StatusPill>
                      </td>
                      <td>
                        <StatusPill tone={provider.can_import_transcripts ? 'positive' : 'warning'}>
                          {provider.can_import_transcripts ? 'Sim' : 'Requer permissão'}
                        </StatusPill>
                      </td>
                      {/* Nunca dizemos "conectado" quando a capacidade
                          necessária não está disponível. */}
                      <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>
                        {provider.unavailable_reason || 'Operacional'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {isLoading || !data ? (
          <Panel title="Carregando" flush>
            <SkeletonRows rows={4} />
          </Panel>
        ) : (
          <>
            <MeetingGroup
              title="Ambíguas"
              description="Mais de um destino plausível — escolha qual"
              meetings={data.ambiguous}
              pendingId={pendingId}
              onAssociate={associate}
              emptyText="Nenhuma reunião ambígua."
            />
            <MeetingGroup
              title="Sem associação"
              description="Nenhum participante bateu com lead ou cliente conhecido"
              meetings={data.unmatched}
              pendingId={pendingId}
              onAssociate={associate}
              emptyText="Nenhuma reunião pendente de associação."
            />
          </>
        )}
      </div>
    </div>
  );
};

interface GroupProps {
  title: string;
  description: string;
  meetings: Meeting[];
  pendingId: number | null;
  emptyText: string;
  onAssociate: (meeting: Meeting, candidate: ResolutionCandidate) => void;
}

const MeetingGroup: React.FC<GroupProps> = ({
  title,
  description,
  meetings,
  pendingId,
  emptyText,
  onAssociate,
}) => (
  <Panel title={title} description={description} flush>
    {meetings.length === 0 ? (
      <EmptyState icon={CheckCircle2} title={emptyText} />
    ) : (
      <div className="ctl-table-scroll">
        <table className="ctl-table">
          <thead>
            <tr>
              <th>Reunião</th>
              <th>Quando</th>
              <th>Participantes</th>
              <th>Transcrição</th>
              <th>Associar a</th>
            </tr>
          </thead>
          <tbody>
            {meetings.map((meeting) => (
              <tr key={meeting.id}>
                <td className="ctl-cell-primary">{meeting.title || 'Reunião sem título'}</td>
                <td className="ctl-cell-muted">{formatDateTime(meeting.scheduled_start_at)}</td>
                <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>
                  {meeting.participants
                    .map((participant) => participant.name || participant.email)
                    .filter(Boolean)
                    .join(', ') || '—'}
                </td>
                <td>
                  <StatusPill tone={meeting.transcript_status === 'imported' ? 'positive' : 'neutral'}>
                    {meeting.transcript_status === 'imported' ? 'Disponível' : 'Pendente'}
                  </StatusPill>
                </td>
                <td>
                  {meeting.resolution_candidates.length === 0 ? (
                    <span className="ctl-cell-muted">Nenhum candidato encontrado</span>
                  ) : (
                    <div style={{ display: 'flex', gap: 'var(--ctl-space-2)', flexWrap: 'wrap' }}>
                      {meeting.resolution_candidates.map((candidate, index) => (
                        <button
                          key={`${candidate.lead_id}-${candidate.contact_id}-${index}`}
                          type="button"
                          className="ctl-button"
                          disabled={pendingId === meeting.id}
                          onClick={() => onAssociate(meeting, candidate)}
                          title={candidate.detail || undefined}
                        >
                          <Link2 aria-hidden />
                          {candidate.label || `Lead ${candidate.lead_id ?? '—'}`}
                        </button>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </Panel>
);

export default UnmatchedMeetings;

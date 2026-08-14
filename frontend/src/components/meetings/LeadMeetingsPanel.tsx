/**
 * Reuniões e inteligência dentro do card do lead.
 *
 * Vive no detalhe da oportunidade que já existe — não é um segundo CRM. Usa
 * os tokens do visual enterprise escuro estabelecido na Fase 1; nenhuma
 * identidade nova, nenhuma dependência nova.
 *
 * A transcrição só é buscada quando a pessoa abre a reunião e pede: em lista
 * ela nem é enviada pelo backend.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Brain, Calendar, Check, ChevronDown, FileText, Sparkles, X } from 'lucide-react';
import {
  meetingsApi,
  type CrmSuggestion,
  type MeetingDetail,
  type Meeting,
  type MeetingTranscript,
  type SalesMemory,
} from '../../services/meetingsApi.ts';
import styles from './LeadMeetingsPanel.module.css';

interface Props {
  leadId: number;
}

const STATUS_LABEL: Record<string, string> = {
  scheduled: 'Agendada',
  in_progress: 'Em andamento',
  completed: 'Concluída',
  canceled: 'Cancelada',
  unknown: 'Indefinida',
};

const TRANSCRIPT_LABEL: Record<string, string> = {
  pending: 'Aguardando transcrição',
  unavailable: 'Transcrição indisponível',
  importing: 'Importando',
  imported: 'Transcrita',
  failed: 'Falha na transcrição',
};

const ANALYSIS_LABEL: Record<string, string> = {
  pending: 'Sem análise',
  queued: 'Na fila',
  running: 'Analisando',
  completed: 'Analisada',
  failed: 'Falha na análise',
  skipped: 'Sem conteúdo',
};

const SUGGESTION_LABEL: Record<string, string> = {
  move_stage: 'Mover etapa',
  update_deal_value: 'Atualizar valor',
  create_task: 'Criar tarefa',
  add_note: 'Adicionar nota',
  add_tag: 'Adicionar tag',
  register_objection: 'Registrar objeção',
  register_next_step: 'Registrar próximo passo',
};

const formatDate = (value: string | null | undefined): string => {
  if (!value) return 'Sem data';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? 'Sem data'
    : parsed.toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

const formatDuration = (seconds: number | null): string =>
  seconds ? `${Math.round(seconds / 60)} min` : '—';

const List: React.FC<{ title: string; items?: string[] }> = ({ title, items }) => {
  if (!items || items.length === 0) return null;
  return (
    <div className={styles.block}>
      <span className={styles.blockTitle}>{title}</span>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
};

const Line: React.FC<{ title: string; value?: string | null }> = ({ title, value }) =>
  value ? (
    <div className={styles.block}>
      <span className={styles.blockTitle}>{title}</span>
      <p className={styles.text}>{value}</p>
    </div>
  ) : null;

const LeadMeetingsPanel: React.FC<Props> = ({ leadId }) => {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [memory, setMemory] = useState<SalesMemory | null>(null);
  const [suggestions, setSuggestions] = useState<CrmSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [openMeeting, setOpenMeeting] = useState<MeetingDetail | null>(null);
  const [transcript, setTranscript] = useState<MeetingTranscript | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [meetingPage, salesMemory, crmSuggestions] = await Promise.all([
        meetingsApi.list({ leadId }),
        meetingsApi.salesMemory(leadId),
        meetingsApi.suggestions(leadId),
      ]);
      setMeetings(meetingPage.items);
      setMemory(salesMemory);
      setSuggestions(crmSuggestions);
    } catch {
      setError('Não foi possível carregar as reuniões desta oportunidade.');
    } finally {
      setIsLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleMeeting = async (meeting: Meeting) => {
    if (openMeeting?.id === meeting.id) {
      setOpenMeeting(null);
      setTranscript(null);
      return;
    }
    setTranscript(null);
    const detail = await meetingsApi.get(meeting.id);
    setOpenMeeting(detail);
  };

  const loadTranscript = async (meetingId: number) => {
    const loaded = await meetingsApi.getTranscript(meetingId);
    setTranscript(loaded);
  };

  const review = async (suggestion: CrmSuggestion, accept: boolean) => {
    setPendingId(suggestion.id);
    try {
      if (accept) await meetingsApi.acceptSuggestion(suggestion.id);
      else await meetingsApi.rejectSuggestion(suggestion.id);
      await load();
    } catch {
      setError('Não foi possível registrar a decisão. Tente novamente.');
    } finally {
      setPendingId(null);
    }
  };

  const pending = suggestions.filter((item) => item.status === 'pending');

  if (isLoading) return <div className={styles.state}>Carregando reuniões…</div>;

  return (
    <div className={styles.panel}>
      {error && <div className={styles.error}>{error}</div>}

      {pending.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <Sparkles className={styles.sectionIcon} aria-hidden />
            Sugestões pendentes
          </h3>
          {/* A IA propõe; a alteração no CRM só acontece depois do aceite. */}
          <div className={styles.suggestions}>
            {pending.map((suggestion) => (
              <article key={suggestion.id} className={styles.suggestion}>
                <div className={styles.suggestionHead}>
                  <span className={styles.badge}>
                    {SUGGESTION_LABEL[suggestion.suggestion_type] || suggestion.suggestion_type}
                  </span>
                  {suggestion.confidence && (
                    <span className={styles.confidence}>confiança {suggestion.confidence}</span>
                  )}
                </div>
                {suggestion.current_value && (
                  <p className={styles.diff}>
                    <span className={styles.diffOld}>{suggestion.current_value}</span>
                    {' → '}
                    <span className={styles.diffNew}>{suggestion.suggested_value}</span>
                  </p>
                )}
                {!suggestion.current_value && (
                  <p className={styles.text}>{suggestion.suggested_value}</p>
                )}
                {suggestion.reason && <p className={styles.reason}>{suggestion.reason}</p>}
                <div className={styles.suggestionActions}>
                  <button
                    type="button"
                    className={styles.acceptButton}
                    disabled={pendingId === suggestion.id}
                    onClick={() => review(suggestion, true)}
                  >
                    <Check aria-hidden /> Aceitar
                  </button>
                  <button
                    type="button"
                    className={styles.rejectButton}
                    disabled={pendingId === suggestion.id}
                    onClick={() => review(suggestion, false)}
                  >
                    <X aria-hidden /> Recusar
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>
          <Brain className={styles.sectionIcon} aria-hidden />
          Inteligência da oportunidade
        </h3>
        {!memory?.available ? (
          <p className={styles.empty}>
            {memory?.reason || 'Nenhuma reunião analisada ainda.'}
          </p>
        ) : (
          <div className={styles.memory}>
            <Line title="Resumo" value={memory.current_summary} />
            <Line title="Problema principal" value={memory.business_problem} />
            <Line title="Processo de decisão" value={memory.decision_process} />
            <Line title="Orçamento" value={memory.budget_context} />
            <Line title="Prazo" value={memory.timeline} />
            <List title="Objetivos" items={memory.desired_outcomes} />
            <List title="Stakeholders" items={memory.stakeholders} />
            <List title="Objeções" items={memory.objections} />
            <List title="Concorrentes" items={memory.competitors} />
            <List title="Sinais de compra" items={memory.buying_signals} />
            <List title="Riscos" items={memory.risks} />
            <List title="Perguntas abertas" items={memory.open_questions} />
            {memory.next_best_action && (
              <div className={styles.nextAction}>
                <span className={styles.blockTitle}>Próxima melhor ação</span>
                <p className={styles.text}>{memory.next_best_action}</p>
              </div>
            )}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>
          <Calendar className={styles.sectionIcon} aria-hidden />
          Reuniões
        </h3>
        {meetings.length === 0 ? (
          <p className={styles.empty}>
            Nenhuma reunião associada. Assim que a agenda conectada trouxer um encontro com
            este contato, ele aparece aqui automaticamente.
          </p>
        ) : (
          <div className={styles.meetings}>
            {meetings.map((meeting) => {
              const isOpen = openMeeting?.id === meeting.id;
              return (
                <article key={meeting.id} className={styles.meeting}>
                  <button
                    type="button"
                    className={styles.meetingHead}
                    onClick={() => toggleMeeting(meeting)}
                    aria-expanded={isOpen}
                  >
                    <div className={styles.meetingTitle}>
                      <strong>{meeting.title || 'Reunião sem título'}</strong>
                      <span className={styles.meetingMeta}>
                        {formatDate(meeting.scheduled_start_at)} · {formatDuration(meeting.duration_seconds)}
                        {' · '}
                        {meeting.provider === 'google_meet' ? 'Google Meet' : meeting.provider}
                      </span>
                    </div>
                    <div className={styles.meetingBadges}>
                      <span className={styles.badge}>{STATUS_LABEL[meeting.status] || meeting.status}</span>
                      <span className={styles.badgeMuted}>
                        {TRANSCRIPT_LABEL[meeting.transcript_status] || meeting.transcript_status}
                      </span>
                      <span className={styles.badgeMuted}>
                        {ANALYSIS_LABEL[meeting.analysis_status] || meeting.analysis_status}
                      </span>
                      <ChevronDown className={isOpen ? styles.chevronOpen : styles.chevron} aria-hidden />
                    </div>
                  </button>

                  {isOpen && openMeeting && (
                    <div className={styles.meetingBody}>
                      {openMeeting.participants.length > 0 && (
                        <div className={styles.block}>
                          <span className={styles.blockTitle}>Participantes</span>
                          <div className={styles.chips}>
                            {openMeeting.participants.map((participant) => (
                              <span key={participant.id} className={styles.chip}>
                                {participant.name || participant.email || 'participante'}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {openMeeting.analysis ? (
                        <>
                          <Line title="Resumo" value={openMeeting.analysis.summary} />
                          <Line title="Problema principal" value={openMeeting.analysis.main_problem} />
                          <List title="Dores" items={openMeeting.analysis.pain_points} />
                          <List title="Necessidades" items={openMeeting.analysis.needs} />
                          <List title="Objetivos" items={openMeeting.analysis.desired_outcomes} />
                          <List title="Objeções" items={openMeeting.analysis.objections} />
                          <List title="Concorrentes" items={openMeeting.analysis.competitors} />
                          <List title="Compromissos da empresa" items={openMeeting.analysis.commitments_company} />
                          <List title="Compromissos do cliente" items={openMeeting.analysis.commitments_customer} />
                          <List title="Riscos" items={openMeeting.analysis.risks} />
                          <List title="Próximos passos" items={openMeeting.analysis.next_steps} />
                        </>
                      ) : (
                        <p className={styles.empty}>Esta reunião ainda não foi analisada.</p>
                      )}

                      {openMeeting.transcript_status === 'imported' && (
                        <div className={styles.block}>
                          {transcript ? (
                            <>
                              <span className={styles.blockTitle}>Transcrição</span>
                              <div className={styles.transcript}>
                                {transcript.segments.length > 0
                                  ? transcript.segments.map((segment, index) => (
                                      <p key={index} className={styles.segment}>
                                        {segment.speaker && (
                                          <span className={styles.speaker}>
                                            {transcript.speaker_map[segment.speaker]?.name || segment.speaker}
                                          </span>
                                        )}
                                        {segment.text}
                                      </p>
                                    ))
                                  : <p className={styles.segment}>{transcript.text}</p>}
                              </div>
                            </>
                          ) : (
                            <button
                              type="button"
                              className={styles.ghostButton}
                              onClick={() => loadTranscript(openMeeting.id)}
                            >
                              <FileText aria-hidden /> Ver transcrição
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
};

export default LeadMeetingsPanel;

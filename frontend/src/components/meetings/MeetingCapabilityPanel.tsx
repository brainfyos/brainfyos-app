/**
 * Status da Meeting Intelligence, camada por camada.
 *
 * Existe porque "OAuth funcionou" não significa "transcrição automática
 * funciona". São quatro coisas independentes e cada uma pode faltar sozinha —
 * mostrá-las como uma só faria a tela declarar operacional o que não está.
 *
 * `auto_transcription_available === null` não é "não": é "não foi possível
 * determinar". A distinção importa porque o Google não expõe a política de
 * transcrição do Workspace por API.
 */

import React, { useState } from 'react';
import { AlertTriangle, Link2, RefreshCw } from 'lucide-react';
import { Panel, StatusPill, formatRelative } from '../control/ControlPrimitives.tsx';
import type { MeetingCapabilities } from '../../services/meetingsApi.ts';
import { meetingsApi } from '../../services/meetingsApi.ts';

type Tone = 'positive' | 'warning' | 'danger' | 'neutral';

interface Layer {
  label: string;
  tone: Tone;
  value: string;
  detail?: string;
}

const buildLayers = (capabilities: MeetingCapabilities): Layer[] => {
  const layers: Layer[] = [];

  layers.push(
    capabilities.calendar_connected
      ? { label: 'Google Calendar', tone: 'positive', value: 'Conectado' }
      : {
          label: 'Google Calendar',
          tone: 'neutral',
          value: 'Não conectado',
          detail: capabilities.oauth_configured
            ? 'Conecte a conta Google desta empresa.'
            : 'OAuth do Google ainda não configurado no servidor.',
        },
  );

  if (capabilities.calendar_connected) {
    layers.push(
      capabilities.meet_access
        ? { label: 'Google Meet', tone: 'positive', value: 'Conectado' }
        : {
            label: 'Google Meet',
            tone: 'warning',
            value: 'Requer autorização adicional',
            detail: 'Reconecte o Google para permitir a leitura das transcrições.',
          },
    );
  }

  if (capabilities.meet_access) {
    const subscriptionTone: Tone = capabilities.event_subscription_active
      ? 'positive'
      : capabilities.subscription_status === 'degraded'
        ? 'warning'
        : 'neutral';

    layers.push({
      label: 'Meeting Intelligence',
      tone: subscriptionTone,
      value: capabilities.event_subscription_active ? 'Ativa' : 'Inativa',
      detail: capabilities.event_subscription_active
        ? capabilities.last_event_received_at
          ? `Último evento ${formatRelative(capabilities.last_event_received_at)}`
          : 'Aguardando o primeiro evento.'
        : 'Enquanto isso, a sincronização periódica funciona como reserva.',
    });

    layers.push(
      capabilities.auto_transcription_available === true
        ? { label: 'Transcrição automática', tone: 'positive', value: 'Ativa' }
        : capabilities.auto_transcription_available === false
          ? {
              label: 'Transcrição automática',
              tone: 'warning',
              value: 'Não disponível',
              detail: 'Reuniões encerraram sem gerar transcrição.',
            }
          : {
              // "Não sei" é resposta honesta; inventar sucesso não é.
              label: 'Transcrição automática',
              tone: 'neutral',
              value: 'Não foi possível determinar',
              detail: 'Depende da edição do Workspace e da configuração de cada reunião.',
            },
    );
  }

  return layers;
};

interface Props {
  capabilities: MeetingCapabilities;
  onChanged: () => void;
}

const MeetingCapabilityPanel: React.FC<Props> = ({ capabilities, onChanged }) => {
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activate = async () => {
    setIsWorking(true);
    setError(null);
    try {
      await meetingsApi.createSubscription();
      onChanged();
    } catch {
      setError('Não foi possível ativar a assinatura de eventos.');
    } finally {
      setIsWorking(false);
    }
  };

  const layers = buildLayers(capabilities);
  const canActivate =
    capabilities.meet_access &&
    capabilities.pubsub_configured &&
    !capabilities.event_subscription_active;

  return (
    <Panel
      title="Meeting Intelligence"
      description="Cada camada precisa estar disponível para o fluxo ser automático"
      actions={
        canActivate ? (
          <button type="button" className="ctl-button" disabled={isWorking} onClick={activate}>
            <RefreshCw aria-hidden /> {isWorking ? 'Ativando…' : 'Ativar eventos'}
          </button>
        ) : capabilities.needs_reconsent ? (
          <a className="ctl-button" href="/integrations">
            <Link2 aria-hidden /> Reconectar Google
          </a>
        ) : null
      }
      flush
    >
      <div className="ctl-table-scroll">
        <table className="ctl-table">
          <thead>
            <tr>
              <th>Camada</th>
              <th>Situação</th>
              <th>Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {layers.map((layer) => (
              <tr key={layer.label}>
                <td className="ctl-cell-primary">{layer.label}</td>
                <td><StatusPill tone={layer.tone}>{layer.value}</StatusPill></td>
                <td className="ctl-cell-muted" style={{ whiteSpace: 'normal' }}>
                  {layer.detail || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(capabilities.blockers.length > 0 || error) && (
        <div style={{ padding: 'var(--ctl-space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--ctl-space-2)' }}>
          {error && <span style={{ color: 'var(--ctl-danger)', fontSize: 'var(--ctl-text-sm)' }}>{error}</span>}
          {capabilities.blockers.map((blocker) => (
            <span
              key={blocker}
              style={{
                display: 'flex', gap: 'var(--ctl-space-2)', alignItems: 'flex-start',
                fontSize: 'var(--ctl-text-sm)', color: 'var(--ctl-text-secondary)',
              }}
            >
              <AlertTriangle size={14} aria-hidden style={{ color: 'var(--ctl-warning)', flexShrink: 0, marginTop: 2 }} />
              {blocker}
            </span>
          ))}
        </div>
      )}

      {capabilities.auto_transcription_available !== true && capabilities.meet_access && (
        <div style={{ padding: '0 var(--ctl-space-4) var(--ctl-space-4)' }}>
          <span className="ctl-metric-label">O que precisa estar habilitado no Google</span>
          <ul style={{ margin: 'var(--ctl-space-2) 0 0', paddingLeft: '1.1rem', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {capabilities.transcription_guidance.map((item) => (
              <li key={item} style={{ fontSize: 'var(--ctl-text-sm)', color: 'var(--ctl-text-muted)', lineHeight: 1.55 }}>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
};

export default MeetingCapabilityPanel;

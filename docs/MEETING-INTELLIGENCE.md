# Meeting Intelligence

Transforma reuniões comerciais em dados estruturados da operação: descoberta automática pela agenda, importação de transcrição, análise, memória comercial e sugestões de CRM.

## O fluxo

```
evento na agenda conectada
  ↓  sync a cada 15 min (meetings.sync_all_companies)
Meeting criada/atualizada  ── idempotente por (company, provider, calendar_event_id)
  ↓  MeetingEntityResolver
matched · ambiguous · unmatched
  ↓  quando a conferência encerra
transcrição importada  ── idempotente por external_transcript_id
  ↓  meetings.analyze_meeting
MeetingAnalysis (versionada, schema validado)
  ↓
SalesMemory reconstruída  +  CrmUpdateSuggestion (status pending)
  ↓
BrainContextService passa a enxergar a reunião
```

Nada disso exige ação humana, **exceto** quando o resolvedor não tem certeza — e aí a reunião espera em `/meetings/unmatched`.

## Estado atual dos provedores

| Provedor | Descobre | Transcreve | Situação |
|---|---|---|---|
| Google Meet | sim, com agenda conectada | requer scope adicional | **Não ativável hoje** — ver abaixo |
| Upload manual | não (é manual) | sim | Operacional |
| Microsoft Teams | — | — | Sem infraestrutura de auth |

### O que falta para o Google Meet funcionar

Três coisas, nesta ordem:

**1. Configurar o OAuth do Google.** `GOOGLE_OAUTH_CLIENT_ID` e `GOOGLE_OAUTH_CLIENT_SECRET` estão vazios em produção. Sem eles nenhuma empresa consegue conectar a agenda.

**2. Adicionar o scope da Meet API.** A lista atual em `routes/integrations/google_calendar_service.GOOGLE_OAUTH_SCOPES` só cobre Calendar. A leitura de transcrições exige:

```
https://www.googleapis.com/auth/meetings.space.readonly
```

Já autorizado antes? Não importa — scope novo exige reconsentimento do usuário.

**3. Habilitar transcrição no Google Workspace.** Limites do próprio Google, que nenhuma implementação contorna:

- A transcrição precisa estar **ligada na reunião** (organizador ativa, ou política do Workspace).
- Só existe **depois** que a conferência encerra. Não há stream.
- Requer edição elegível do Workspace.
- `conferenceRecords` são retidos por **30 dias**.

Enquanto (1) e (2) não acontecem, `GET /api/meetings/providers` reporta a limitação e a UI mostra "Requer permissão" — nunca "conectado".

### Por que sincronização agendada e não webhook

O Google Calendar oferece `watch` (push), mas ele avisa sobre mudança de **evento**, não sobre transcrição pronta. O sinal que precisamos observar não tem push.

Como o artefato aparece poucos minutos após o fim da reunião e não muda depois, um ciclo de 15 minutos captura tudo. Mais frequente seria gastar cota para receber a mesma resposta vazia — e menos frequente atrasaria a análise sem ganho.

### Microsoft Teams

O contrato `MeetingProvider` já é o que o Teams vai implementar. Não existe um `MicrosoftTeamsProvider` porque não existe autenticação Microsoft no projeto: sem OAuth da Microsoft Identity Platform, sem token, sem refresh, o arquivo seria só um lugar que levanta "não configurado".

Para ativar: registrar app no Entra ID, implementar o fluxo OAuth, armazenar token com refresh, e usar a Graph API (`/me/onlineMeetings/{id}/transcripts`) com os scopes `OnlineMeetings.Read` e `OnlineMeetingTranscript.Read.All`.

## Tempo real

Não implementado, e não por omissão: nenhum provedor entrega transcrição durante a reunião pelas integrações disponíveis. O caminho seria um bot que entra na chamada — explicitamente fora de escopo.

A arquitetura suporta: `MeetingTranscript.segments` já guarda entradas com tempo, `Meeting.status` tem `in_progress`, e o provedor decide quando há conteúdo. Um provedor com streaming entraria sem tocar no domínio.

## Fronteiras que o código garante

**A IA nunca fecha negócio.** `SUGGESTION_TYPES` não tem `won`/`lost`, e o CHECK em `crm_update_suggestions` recusa qualquer outro valor. Duas barreiras porque uma sozinha é a que alguém remove sem perceber.

**Análise não é CRM.** `analyze_meeting` só grava em `meeting_analyses`. Alterar o CRM exige `accept_suggestion`, que exige uma pessoa.

**Na dúvida, não associa.** Dois leads plausíveis viram `ambiguous` com os dois candidatos guardados. Associar ao lead errado contamina a memória e ninguém audita uma associação que parece razoável.

**Transcrição não vai para prompt.** O contexto do Brain leva resumo estruturado; `has_transcript` diz que o detalhe existe. Uma hora de conversa transcrita gasta o orçamento de token e afoga o sinal.

## Custo por reunião

Todo consumo passa por `services/meetings/llm.py` e é registrado em `ai_usage_events` com `operation` em `meeting_analysis`, `sales_memory`, `follow_up_generation` ou `transcription`, e `meeting_id` no `usage_metadata`.

```sql
SELECT usage_metadata->>'meeting_id' AS reuniao,
       operation, model, total_tokens, estimated_cost_brl
FROM ai_usage_events
WHERE company_id = :company_id
  AND operation IN ('meeting_analysis','sales_memory','follow_up_generation','transcription');
```

A migration `0007` ampliou `chk_ai_usage_operation` por superconjunto: nenhum evento histórico foi invalidado.

## Operação

```bash
# Fila dedicada (já no unit do worker)
-Q ...,meetings_queue

# Forçar sincronização de uma empresa
sudo -u brainfyos /usr/local/bin/brainfyos-run .venv/bin/python -c \
  "from backend.worker.tasks_meetings import sync_company_meetings; sync_company_meetings.delay(1)"
```

Tarefas: `meetings.sync_all_companies` (beat, 15 min), `sync_company_meetings`, `import_transcript`, `analyze_meeting`, `rebuild_sales_memory`, `generate_crm_suggestions`.

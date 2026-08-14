# Configurar o Google para a Meeting Intelligence

Passo a passo do que **você** precisa fazer no Google Cloud Console e no Google Workspace. O código já está pronto e ativa sozinho quando estes valores existirem.

Nenhum segredo entra no repositório. Tudo vira variável de ambiente em `/etc/brainfyos/backend.env`.

---

## 1. Projeto e APIs

No [Google Cloud Console](https://console.cloud.google.com/), crie (ou escolha) um projeto e habilite **quatro** APIs:

| API | Para quê |
|---|---|
| **Google Calendar API** | Descobrir eventos com Meet |
| **Google Meet API** | Ler `conferenceRecords`, `participants` e `transcripts` |
| **Google Workspace Events API** | Assinar `transcript.fileGenerated` |
| **Cloud Pub/Sub API** | Transporte dos eventos |

`APIs e serviços` → `Biblioteca` → busque cada uma → `Ativar`.

---

## 2. Tela de consentimento OAuth

`APIs e serviços` → `Tela de permissão OAuth`.

- **Tipo**: Interno se todos os usuários forem do seu Workspace; Externo caso contrário.
- **Nome do app**: BrainfyOS
- **E-mail de suporte** e **e-mail do desenvolvedor**: seus
- **Domínio autorizado**: `brainfyos.com.br`
- **Link da política de privacidade**: `https://app.brainfyos.com.br/privacy-policy`
- **Link dos termos**: `https://app.brainfyos.com.br/terms`

Adicione estes **4 escopos**:

```
https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.app.created
https://www.googleapis.com/auth/calendar.events.owned
https://www.googleapis.com/auth/meetings.space.readonly
```

O último é o que libera a transcrição. Os três primeiros já eram usados — mantenha-os, ou a integração de agenda quebra.

> **Externo + escopo do Meet** exige verificação do Google (leva dias). Se for só para você e sua equipe, escolha **Interno** e pule a verificação.

---

## 3. Credencial OAuth

`APIs e serviços` → `Credenciais` → `Criar credenciais` → `ID do cliente OAuth`.

- **Tipo**: Aplicativo da Web
- **Nome**: BrainfyOS Backend
- **URIs de redirecionamento autorizados** — exatamente isto:

```
https://app.brainfyos.com.br/api/integrations/calendar/google/oauth/callback
```

Guarde o **Client ID** e o **Client Secret**.

---

## 4. Pub/Sub

### 4.1 Tópico

`Pub/Sub` → `Tópicos` → `Criar tópico`. ID: `brainfyos-meet-events`.

O nome completo fica `projects/SEU_PROJETO/topics/brainfyos-meet-events` — anote.

### 4.2 Permissão para o Google Workspace publicar

Ainda no tópico → aba `Permissões` → `Adicionar principal`:

- **Principal**: `meet-api-event-push@system.gserviceaccount.com`
- **Papel**: `Pub/Sub Publisher`

Sem isso o Workspace Events recusa criar a assinatura.

### 4.3 Service account para a entrega

`IAM e administrador` → `Contas de serviço` → `Criar`:

- **Nome**: `brainfyos-pubsub-push`
- **Papel**: nenhum necessário

Anote o e-mail gerado (`brainfyos-pubsub-push@SEU_PROJETO.iam.gserviceaccount.com`).

### 4.4 Assinatura push

`Pub/Sub` → `Assinaturas` → `Criar assinatura`:

- **ID**: `brainfyos-meet-push`
- **Tópico**: `brainfyos-meet-events`
- **Tipo de entrega**: **Push**
- **URL do endpoint**: `https://app.brainfyos.com.br/webhook/meet-events/google/pubsub`
- **Ativar autenticação**: sim
- **Conta de serviço**: a de 4.3
- **Público (audience)**: `https://app.brainfyos.com.br`
- **Prazo de confirmação**: 60 segundos

A autenticação é obrigatória. O endpoint valida o JWT OIDC e recusa qualquer entrega que não venha dessa service account.

---

## 5. Variáveis no servidor

```bash
/usr/local/bin/brainfyos-setenv GOOGLE_OAUTH_CLIENT_ID='...apps.googleusercontent.com'
/usr/local/bin/brainfyos-setenv GOOGLE_OAUTH_CLIENT_SECRET='GOCSPX-...'
/usr/local/bin/brainfyos-setenv GOOGLE_MEET_PUBSUB_TOPIC='projects/SEU_PROJETO/topics/brainfyos-meet-events'
/usr/local/bin/brainfyos-setenv GOOGLE_MEET_PUBSUB_SERVICE_ACCOUNT='brainfyos-pubsub-push@SEU_PROJETO.iam.gserviceaccount.com'
/usr/local/bin/brainfyos-setenv GOOGLE_MEET_PUBSUB_AUDIENCE='https://app.brainfyos.com.br'

systemctl restart brainfyos-api brainfyos-worker brainfyos-beat
```

`GOOGLE_OAUTH_REDIRECT_URI` é opcional — sem ela o backend deriva de `PUBLIC_BASE_URL`.

| Variável | Obrigatória | O que quebra sem ela |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | sim | Ninguém conecta o Google |
| `GOOGLE_OAUTH_CLIENT_SECRET` | sim | Idem |
| `GOOGLE_MEET_PUBSUB_TOPIC` | sim | Assinatura não é criada; só o fallback roda |
| `GOOGLE_MEET_PUBSUB_SERVICE_ACCOUNT` | sim | Endpoint recusa toda entrega (503) |
| `GOOGLE_MEET_PUBSUB_AUDIENCE` | recomendada | Validação do token fica mais fraca |

---

## 6. Transcrição no Workspace

O código não cria transcrição — ele importa a que o Google gerou. Sem isso não há nada para importar.

- **Edição elegível**: Business Standard ou superior.
- **Ativar por política**: Admin Console → `Apps` → `Google Workspace` → `Google Meet` → `Configurações de vídeo do Meet` → **Transcrições** → permitir.
- **Ativar na reunião**: o organizador liga em `Atividades` → `Transcrições` → `Iniciar transcrição`.

A transcrição só fica disponível **depois** que a reunião encerra. Não existe durante a chamada.

---

## 7. Teste de aceite

Depois de configurado, na ordem:

1. Acesse `Conexões` → `Integrações` → conectar Google. Autorize **os 4 escopos**.
2. Confirme em `Reuniões`: `Google Meet — Conectado`, `Meeting Intelligence — Ativo`.
3. Crie um evento no Google Calendar com **Google Meet**, para daqui a alguns minutos, convidando o e-mail de um lead de teste que exista no CRM.
4. Aguarde até 15 min (ou clique em `Sincronizar agora`). A reunião aparece.
5. Se não associou sozinha, associe em `Reuniões não associadas`.
6. Entre na reunião. **Ative a transcrição** (`Atividades` → `Transcrições`).
7. Fale por 1–2 minutos algo comercial: um problema, um orçamento, um próximo passo.
8. Encerre a reunião para todos.
9. Aguarde de 2 a 10 minutos — o Google gera o arquivo e dispara `fileGenerated`.
10. Abra o card do lead → aba **Reuniões**.

Deve aparecer, **sem nenhum clique seu**: transcrição importada, participantes, falas por locutor, resumo, dores, objeções, próximos passos, Sales Memory preenchida e sugestões de CRM pendentes.

### Se não aparecer

```bash
# O evento chegou?
journalctl -u brainfyos-api --since '20 min ago' | grep 'Evento do Meet'

# O worker processou?
journalctl -u brainfyos-worker --since '20 min ago' | grep -i meet

# Estado da assinatura
GET /api/meetings/capabilities
```

Ordem provável das causas: transcrição não foi ativada na reunião → escopo do Meet não autorizado → assinatura não criada → Pub/Sub sem permissão de publisher.

---

## O que ainda não foi validado

Tudo que depende de credencial real do Google: criação de assinatura, entrega de evento, leitura de `conferenceRecords` e importação de transcrição de verdade. O código está implementado e coberto por testes com duplo determinístico, mas **nunca falou com o Google**.

A validação real acontece no teste de aceite acima.

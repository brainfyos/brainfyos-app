# Deploy BrainfyOS — produção

Documento da instalação real. Para o modelo genérico, veja [public/06-deploy.md](public/06-deploy.md).

## Servidor

| Item | Valor |
|---|---|
| Provedor | Hostinger VPS (KVM) |
| Host | `srv1884392.hstgr.cloud` |
| IP | `179.198.113.87` |
| SO | Ubuntu 24.04.4 LTS |
| Recursos | 2 vCPU, 7,8 GB RAM, 96 GB disco |
| Domínio | `app.brainfyos.com.br` |

## Componentes instalados

| Componente | Versão |
|---|---|
| PostgreSQL | 16.14 |
| Redis | 7.0.15 |
| Nginx | 1.24.0 |
| Node.js | 20.20.2 (npm 10.8.2) |
| Python | 3.12.3 |
| Certbot | 2.9.0 |
| ffmpeg | 6.1.1 (áudio do WhatsApp via pydub) |

## Layout no disco

```text
/srv/brainfyos/app                  # repositório (usuário brainfyos)
/srv/brainfyos/app/.venv            # virtualenv Python
/srv/brainfyos/app/frontend/build   # estáticos servidos pelo Nginx
/srv/brainfyos/shared/              # media, chatmemory, logs, logos, account-profiles
/etc/brainfyos/backend.env          # segredos (root:brainfyos, 640)
/etc/brainfyos/.dbpass              # senha do Postgres (root, 600)
/usr/local/bin/brainfyos-run        # executa comandos com o env de produção carregado
```

O diretório `/etc/brainfyos` é `root:brainfyos 750` — o grupo precisa de permissão de travessia para os serviços lerem o `EnvironmentFile`.

## Banco de dados

- Banco: `brainfyos`
- Role: `brainfyos_app` (owner)
- Conexão: `127.0.0.1:5432`, senha via `PGPASSWORD` (a `DATABASE_URL` não carrega credencial)
- Migrations: `alembic` na versão `0001` (93 tabelas)

## Serviços systemd

| Serviço | Função |
|---|---|
| `brainfyos-api` | Uvicorn/FastAPI em `127.0.0.1:8002`, 1 worker |
| `brainfyos-worker` | Celery, concurrency 2, 14 filas |
| `brainfyos-beat` | Celery Beat, schedule em `/srv/brainfyos/shared/celerybeat-schedule` |

```bash
systemctl status brainfyos-api brainfyos-worker brainfyos-beat --no-pager
journalctl -u brainfyos-api -n 100 --no-pager
```

Só aumente `--workers` da API depois de validar pool de banco, memória, Redis Pub/Sub e WebSockets entre processos. Nunca rode dois Celery Beat no mesmo ambiente.

## Nginx e TLS

- Virtual host: `/etc/nginx/sites-available/brainfyos`
- Headers de segurança: `/etc/nginx/snippets/brainfyos-security.conf` (HSTS, nosniff, DENY, Referrer-Policy, Permissions-Policy)
- Certificado Let's Encrypt para `app.brainfyos.com.br`, renovação automática pelo `certbot.timer`
- HTTP redireciona para HTTPS (301)

Roteamento: `/ws` e `^/(api|auth|webhook|media-sources|health|media|agents-sdk)` vão para o backend; `oauth-home`, `privacy-policy` e `terms` são estáticos sem extensão; o resto cai no SPA (`/index.html`).

### WebSocket

O template de Nginx do projeto original só coloca os headers de upgrade no bloco `/ws`, mas **o Chat Ao Vivo abre a conexão em `/api/chat-optimized/ws/unified`**, que cai no bloco `/api`. Sem os headers ali, o Starlette recebe uma requisição HTTP comum numa rota WebSocket e responde `404` — o frontend fica em "Reconectando..." para sempre.

A correção usa um `map` no contexto http, em `/etc/nginx/conf.d/websocket_upgrade.conf`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

E os dois blocos de proxy repassam:

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $connection_upgrade;
```

O `close` para requisições sem `Upgrade` mantém o tráfego HTTP normal inalterado.

Para testar o handshake é preciso um cliente WebSocket real — `curl` não completa o handshake e devolve `404` mesmo quando a configuração está correta. Com sessão autenticada, a resposta esperada é `101` seguida de `{"type":"connection_established"}`.

## Firewall

`ufw` ativo, liberando apenas 22, 80 e 443. PostgreSQL e Redis escutam somente em `127.0.0.1`.

## Health checks

Não existe `/health` puro. As rotas reais exigem o header `X-Monitoring-Token`:

```bash
MON=$(grep '^MONITORING_TOKEN=' /etc/brainfyos/backend.env | cut -d= -f2)
curl -H "X-Monitoring-Token: $MON" https://app.brainfyos.com.br/health/db-connections
curl -H "X-Monitoring-Token: $MON" https://app.brainfyos.com.br/health/memory
```

Sem o token, a resposta é `403`. Não registre o valor do token em logs.

## Atualizar a aplicação

Use `/usr/local/bin/brainfyos-deploy` (veja abaixo) ou execute manualmente:

```bash
sudo -u brainfyos git -C /srv/brainfyos/app fetch origin
sudo -u brainfyos git -C /srv/brainfyos/app reset --hard origin/main
sudo -u brainfyos /srv/brainfyos/app/.venv/bin/pip install -q -r /srv/brainfyos/app/backend/requirements.txt
sudo -u brainfyos /usr/local/bin/brainfyos-run /srv/brainfyos/app/.venv/bin/alembic \
  -c /srv/brainfyos/app/backend/alembic.ini upgrade head
sudo -u brainfyos npm --prefix /srv/brainfyos/app/frontend ci
sudo -u brainfyos npm --prefix /srv/brainfyos/app/frontend run build
systemctl restart brainfyos-api brainfyos-worker brainfyos-beat
```

Antes de atualizar: faça backup verificável do PostgreSQL e das mídias, leia as novas migrations e rode `alembic upgrade head` uma única vez. Nunca use `git reset --hard` sobre alterações locais não versionadas, nem restaure dump sobre produção como procedimento comum.

## Administração

Criar administrador ou empresa adicional:

```bash
cd /srv/brainfyos/app
sudo -u brainfyos ADMIN_PASSWORD='...' /usr/local/bin/brainfyos-run \
  /srv/brainfyos/app/.venv/bin/python -m backend.scripts.bootstrap_admin \
  --email <email> --company-name "<empresa>" --document <11-ou-14-digitos> \
  --password-env ADMIN_PASSWORD
```

A senha precisa ter no mínimo 12 caracteres.

## WhatsApp (WAHA)

WAHA Core roda em Docker, com `--network host` para que o container alcance o backend em `127.0.0.1:8002` e o backend alcance o WAHA em `127.0.0.1:3000`. Como não há NAT do Docker, as regras do `ufw` continuam valendo e a porta 3000 não fica exposta.

```bash
docker ps --filter name=waha
docker logs waha --tail 50
```

| Item | Valor |
|---|---|
| Imagem | `devlikeapro/waha:latest` (Core 2026.7.2) |
| Engine | `WEBJS` |
| Sessões | `/srv/brainfyos/waha/sessions` |
| Mídia | `/srv/brainfyos/waha/media` |
| API key | `/etc/brainfyos/.wahakey` (600) |
| Dashboard | usuário `brainfyos`, senha em `/etc/brainfyos/.wahadash` |

**GOWS não funciona nesta edição.** É recurso do WAHA Plus; a Core aceita o parâmetro e cai silenciosamente para WEBJS. O `.env.production.example` do projeto original vinha com `WAHA_DEFAULT_ENGINE=GOWS`, o que era enganoso — aqui está fixado em `WEBJS`.

WEBJS usa Chromium: cerca de 450 MB de RAM ocioso, mais por sessão conectada.

Fluxo de conexão pela aplicação:

1. `POST /webhook/whatsapp/connect-waha` — cria a sessão e grava `waha_session_name` em `companies`
2. `POST /webhook/whatsapp/waha/start-session` — inicia
3. `GET /webhook/whatsapp/qrcode` — devolve o QR em PNG base64
4. `GET /webhook/whatsapp/status` — acompanha até `WORKING`

Webhooks do WAHA voltam para `http://127.0.0.1:8002/webhook/waha/callback`.

## E-mail (Resend)

| Variável | Valor |
|---|---|
| `SMTP_HOST` | `smtp.resend.com` |
| `SMTP_PORT` | `587` (STARTTLS) |
| `SMTP_USERNAME` | `resend` |
| `SMTP_PASSWORD` | API key `re_...` |
| `SMTP_FROM_EMAIL` | `noreply@mail.brainfyos.com.br` |

O domínio verificado na Resend é o subdomínio **`mail.brainfyos.com.br`**, não o raiz. O remetente precisa pertencer a ele — enviar de `@brainfyos.com.br` é recusado. Os registros DKIM, SPF e MX estão na zona da Cloudflare.

## Cloudflare

O domínio é proxiado pela Cloudflare, então o certificado que o visitante vê é o dela, não o Let's Encrypt da origem. Pontos de atenção:

- O modo SSL/TLS precisa ser **Full (strict)**. Em "Flexible" a Cloudflare fala HTTP com a origem, o nginx responde 301 e vira loop.
- A renovação do Let's Encrypt usa HTTP-01 através da Cloudflare. Se falhar, migre para validação DNS-01 com a API da Cloudflare.
- O IP real do cliente chega em `X-Forwarded-For`; `TRUST_PROXY_HEADERS=true` já está ligado.

## Pendências de configuração

| Variável | Impacto enquanto vazia |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Sem integração com Google Agenda |

Depois de editar o arquivo: `systemctl restart brainfyos-api brainfyos-worker brainfyos-beat`.

Use `/usr/local/bin/brainfyos-setenv CHAVE=valor` para alterar variáveis sem editar o arquivo à mão — ele preserva permissões e é idempotente.

## Backup recomendado

Ainda não configurado. O mínimo seria um dump diário do PostgreSQL mais cópia de `/srv/brainfyos/shared` e `/etc/brainfyos/backend.env` para fora do servidor.

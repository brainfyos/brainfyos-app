# Disciplina de testes e ambientes

Regra permanente a partir da Fase 3.1.

## O incidente que originou esta regra

Na validação da Fase 3 rodei um teste E2E contra o Postgres de produção dentro de uma transação, esperando reverter no fim. Os serviços fazem `commit()` internos — o rollback externo não desfez nada. Ficaram duas empresas fictícias, duas reuniões, oito sugestões de CRM no banco real. Precisei identificar e apagar linha por linha.

A lição não é "tomar mais cuidado com rollback". É que **transação externa não contém código que commita por conta própria**, e qualquer teste que dependa disso está errado por construção.

## Regras

**Nunca criar dados arbitrários em produção.** Nem empresa temporária, nem lead de teste improvisado, nem "só para verificar".

**Nunca assumir que rollback externo desfaz commits internos.** Se o código sob teste chama `commit()`, a transação de fora não protege nada.

**Produção recebe apenas:**
- migrations controladas, com backup antes;
- smoke tests de **leitura** (`GET`, contagens, health checks);
- ações explicitamente autorizadas sobre uma conta de teste permanente, criada de propósito e conhecida.

Qualquer coisa além disso é staging.

## Ambientes

| Ambiente | Uso | Banco |
|---|---|---|
| Local | Desenvolvimento e suíte de testes | SQLite em memória, descartado a cada teste |
| Staging | Integração, E2E, validação de provedor externo | Postgres próprio, dados descartáveis |
| Produção | Operação real | Postgres real |

**Staging ainda não existe.** Enquanto não existir, E2E que escreve não roda em lugar nenhum além do local — e é assim que a Fase 3.1 foi validada.

### Criar o staging

Mesma VPS, isolado por banco, usuário e porta. Custo próximo de zero:

```bash
# 1. Banco separado
sudo -u postgres createdb brainfyos_staging
sudo -u postgres createuser brainfyos_staging --pwprompt

# 2. Ambiente separado
install -d -m 750 -o root -g brainfyos /etc/brainfyos-staging
cp /etc/brainfyos/backend.env /etc/brainfyos-staging/backend.env
# ajustar: DATABASE_URL, porta (8003), PUBLIC_BASE_URL, e
# **remover** SMTP_PASSWORD e a chave do WAHA — staging não envia
# mensagem para cliente real de ninguém.

# 3. Serviços paralelos
#    brainfyos-staging-api.service, -worker, -beat
#    apontando para /etc/brainfyos-staging/backend.env

# 4. Subdomínio
#    staging.brainfyos.com.br → 127.0.0.1:8003
```

Cuidados que importam mais que o resto:

- **Sem WAHA de produção.** Um staging com a sessão real do WhatsApp manda mensagem para cliente de verdade.
- **Sem SMTP real.** Ou sem senha, ou apontando para um capturador.
- **Projeto Google separado** para o OAuth e o Pub/Sub, com redirect e tópico próprios.
- **Dados sintéticos.** Restaurar dump de produção em staging copia dado pessoal de cliente para um ambiente com menos proteção.

## Como validar sem staging

A Fase 3.1 foi validada assim, e continua valendo enquanto o staging não existir:

- **Suíte local** com SQLite em memória — isolamento, idempotência, escopo por empresa.
- **Duplo determinístico** nas fronteiras externas (Google, IA). Substituído só onde o assunto é *o que o sistema faz com a resposta*; nunca onde o assunto é escopo entre empresas.
- **Produção:** apenas migration com backup e smoke de leitura.

## Backup — pendência aberta

Continua sem rotina automática e sem destino externo. `pg_dump` em `/root` protege contra migration ruim e contra mais nada: some junto com a VPS.

O script com retenção está pronto em [DEPLOY-BRAINFYOS.md](DEPLOY-BRAINFYOS.md). Falta a decisão sobre destino externo (S3/B2/R2, rsync, ou snapshot da Hostinger) e as credenciais correspondentes. Sem elas não dá para configurar, e configurar só o local daria falsa sensação de proteção.

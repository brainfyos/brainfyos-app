"""Meeting Intelligence: reunioes, transcricoes, analise, memoria e sugestoes

Seis tabelas novas e uma ampliacao de CHECK.

Nada de calendar event e copiado: ``meetings.calendar_event_id`` guarda o id
externo do evento e o Google continua sendo dono do evento. O que fica aqui e
o que o sistema produz a partir dele.

Separacao deliberada entre transcricao, analise e CRM:

* ``meeting_transcripts`` guarda a fonte importada, imutavel na pratica.
* ``meeting_analyses`` guarda o que a IA entendeu -- derivado, versionado,
  reprocessavel sem perder a fonte.
* ``crm_update_suggestions`` guarda o que a IA *propoe* mudar. Nenhuma analise
  escreve no CRM sozinha.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb(name: str, default: str = "[]") -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=default)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # meetings
    # ------------------------------------------------------------------
    op.create_table(
        'meetings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.BigInteger(), nullable=True),
        sa.Column('customer_id', sa.BigInteger(), nullable=True),
        sa.Column('pipeline_id', sa.Integer(), nullable=True),
        sa.Column('pipeline_stage_id', sa.Integer(), nullable=True),
        # Id do evento no provedor de agenda. O evento em si continua no
        # Google -- aqui fica apenas a referencia.
        sa.Column('calendar_event_id', sa.String(length=255), nullable=True),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('external_meeting_id', sa.String(length=255), nullable=True),
        sa.Column('external_conference_id', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('meeting_type', sa.String(length=40), nullable=True),
        sa.Column('source', sa.String(length=40), nullable=False, server_default='calendar'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='scheduled'),
        sa.Column('scheduled_start_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('scheduled_end_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('ended_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('meeting_url', sa.Text(), nullable=True),
        sa.Column('transcript_status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('analysis_status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('sync_status', sa.String(length=20), nullable=False, server_default='pending'),
        # Resultado do MeetingEntityResolver. 'ambiguous' e 'unmatched' sao
        # estados de primeira classe: a reuniao existe e espera resolucao
        # humana em vez de ser associada com baixa confianca.
        sa.Column('resolution_status', sa.String(length=20), nullable=False, server_default='unmatched'),
        _jsonb('resolution_candidates'),
        sa.Column('last_synced_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['pipeline_stage_id'], ['pipeline_stages.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "status IN ('scheduled', 'in_progress', 'completed', 'canceled', 'unknown')",
            name='chk_meeting_status',
        ),
        sa.CheckConstraint(
            "transcript_status IN ('pending', 'unavailable', 'importing', 'imported', 'failed')",
            name='chk_meeting_transcript_status',
        ),
        sa.CheckConstraint(
            "analysis_status IN ('pending', 'queued', 'running', 'completed', 'failed', 'skipped')",
            name='chk_meeting_analysis_status',
        ),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'synced', 'failed')",
            name='chk_meeting_sync_status',
        ),
        sa.CheckConstraint(
            "resolution_status IN ('matched', 'ambiguous', 'unmatched', 'manual')",
            name='chk_meeting_resolution_status',
        ),
    )
    op.create_index('idx_meetings_company', 'meetings', ['company_id'])
    op.create_index('idx_meetings_company_lead', 'meetings', ['company_id', 'lead_id'])
    op.create_index('idx_meetings_company_start', 'meetings', ['company_id', 'scheduled_start_at'])
    op.create_index('idx_meetings_resolution', 'meetings', ['company_id', 'resolution_status'])
    # Idempotencia da ingestao: um evento externo vira exatamente uma reuniao
    # por empresa. Indice parcial porque upload manual nao tem evento.
    op.execute(
        'CREATE UNIQUE INDEX uq_meetings_company_calendar_event '
        'ON meetings (company_id, provider, calendar_event_id) '
        'WHERE calendar_event_id IS NOT NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_meetings_company_external '
        'ON meetings (company_id, provider, external_meeting_id) '
        'WHERE external_meeting_id IS NOT NULL'
    )

    # ------------------------------------------------------------------
    # meeting_participants
    # ------------------------------------------------------------------
    op.create_table(
        'meeting_participants',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('meeting_id', sa.BigInteger(), nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('contact_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('external_participant_id', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('participant_type', sa.String(length=20), nullable=False, server_default='unknown'),
        sa.Column('role', sa.String(length=40), nullable=True),
        sa.Column('attendance_status', sa.String(length=20), nullable=True),
        sa.Column('joined_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('left_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "participant_type IN ('internal', 'external', 'unknown')",
            name='chk_meeting_participant_type',
        ),
    )
    op.create_index('idx_meeting_participants_meeting', 'meeting_participants', ['meeting_id'])
    op.create_index('idx_meeting_participants_company', 'meeting_participants', ['company_id'])
    op.execute(
        'CREATE UNIQUE INDEX uq_meeting_participant_external '
        'ON meeting_participants (meeting_id, external_participant_id) '
        'WHERE external_participant_id IS NOT NULL'
    )

    # ------------------------------------------------------------------
    # meeting_transcripts -- a fonte importada, nunca sobrescrita por analise
    # ------------------------------------------------------------------
    op.create_table(
        'meeting_transcripts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('meeting_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('external_transcript_id', sa.String(length=255), nullable=True),
        sa.Column('language', sa.String(length=20), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        # Estrutura varia por provider (Google entrega entries com speaker e
        # timestamps; upload manual pode nao ter nada disso). JSONB porque a
        # forma e genuinamente do provedor.
        _jsonb('segments'),
        _jsonb('speaker_map', default='{}'),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='imported'),
        _jsonb('provider_metadata', default='{}'),
        sa.Column('source_available_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('imported_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "status IN ('imported', 'partial', 'failed')",
            name='chk_meeting_transcript_row_status',
        ),
    )
    op.create_index('idx_meeting_transcripts_meeting', 'meeting_transcripts', ['meeting_id'])
    op.create_index('idx_meeting_transcripts_company', 'meeting_transcripts', ['company_id'])
    # Retry de importacao nao duplica transcricao.
    op.execute(
        'CREATE UNIQUE INDEX uq_meeting_transcript_external '
        'ON meeting_transcripts (company_id, provider, external_transcript_id) '
        'WHERE external_transcript_id IS NOT NULL'
    )

    # ------------------------------------------------------------------
    # meeting_analyses -- derivado, versionado
    # ------------------------------------------------------------------
    op.create_table(
        'meeting_analyses',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('meeting_id', sa.BigInteger(), nullable=False),
        sa.Column('transcript_id', sa.BigInteger(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('meeting_purpose', sa.Text(), nullable=True),
        sa.Column('customer_context', sa.Text(), nullable=True),
        sa.Column('main_problem', sa.Text(), nullable=True),
        sa.Column('budget_context', sa.Text(), nullable=True),
        sa.Column('budget_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('budget_confidence', sa.String(length=10), nullable=True),
        sa.Column('urgency', sa.String(length=10), nullable=True),
        sa.Column('timeline', sa.Text(), nullable=True),
        sa.Column('sentiment', sa.String(length=10), nullable=True),
        sa.Column('suggested_probability', sa.Integer(), nullable=True),
        sa.Column('probability_reason', sa.Text(), nullable=True),
        sa.Column('suggested_next_step_date', sa.Date(), nullable=True),
        _jsonb('pain_points'),
        _jsonb('needs'),
        _jsonb('desired_outcomes'),
        _jsonb('decision_makers'),
        _jsonb('influencers'),
        _jsonb('competitors'),
        _jsonb('objections'),
        _jsonb('questions'),
        _jsonb('unanswered_questions'),
        _jsonb('products_discussed'),
        _jsonb('offers_discussed'),
        _jsonb('prices_mentioned'),
        _jsonb('commitments_company'),
        _jsonb('commitments_customer'),
        _jsonb('next_steps'),
        _jsonb('risks'),
        _jsonb('positive_signals'),
        _jsonb('negative_signals'),
        _jsonb('evidence_snippets'),
        # Proveniencia do que a IA produziu -- sem isto nao da para saber se
        # uma analise antiga veio de um prompt que ja mudou.
        sa.Column('provider', sa.String(length=40), nullable=True),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('prompt_version', sa.String(length=20), nullable=True),
        sa.Column('analysis_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transcript_id'], ['meeting_transcripts.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "budget_confidence IS NULL OR budget_confidence IN ('low', 'medium', 'high')",
            name='chk_meeting_analysis_budget_confidence',
        ),
        sa.CheckConstraint(
            "urgency IS NULL OR urgency IN ('low', 'medium', 'high')",
            name='chk_meeting_analysis_urgency',
        ),
        sa.CheckConstraint(
            "sentiment IS NULL OR sentiment IN ('positive', 'neutral', 'negative', 'mixed')",
            name='chk_meeting_analysis_sentiment',
        ),
        sa.CheckConstraint(
            'suggested_probability IS NULL OR (suggested_probability >= 0 AND suggested_probability <= 100)',
            name='chk_meeting_analysis_probability',
        ),
    )
    op.create_index('idx_meeting_analyses_meeting', 'meeting_analyses', ['meeting_id'])
    op.create_index('idx_meeting_analyses_company', 'meeting_analyses', ['company_id'])
    # Reprocessar cria uma versao nova; retry da mesma versao nao duplica.
    op.create_index(
        'uq_meeting_analysis_version',
        'meeting_analyses',
        ['meeting_id', 'analysis_version'],
        unique=True,
    )

    # ------------------------------------------------------------------
    # sales_memories -- sintese reconstruivel, uma por lead
    # ------------------------------------------------------------------
    op.create_table(
        'sales_memories',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('current_summary', sa.Text(), nullable=True),
        sa.Column('business_context', sa.Text(), nullable=True),
        sa.Column('business_problem', sa.Text(), nullable=True),
        sa.Column('decision_process', sa.Text(), nullable=True),
        sa.Column('budget_context', sa.Text(), nullable=True),
        sa.Column('timeline', sa.Text(), nullable=True),
        sa.Column('next_best_action', sa.Text(), nullable=True),
        sa.Column('confidence', sa.String(length=10), nullable=True),
        _jsonb('desired_outcomes'),
        _jsonb('stakeholders'),
        _jsonb('objections'),
        _jsonb('competitors'),
        _jsonb('commitments_company'),
        _jsonb('commitments_customer'),
        _jsonb('risks'),
        _jsonb('buying_signals'),
        _jsonb('negative_signals'),
        _jsonb('open_questions'),
        # Lineage: de onde cada pedaco veio. Sem isto a memoria vira afirmacao
        # sem prova, que e exatamente o que queremos evitar.
        _jsonb('source_refs'),
        sa.Column('last_rebuilt_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('provider', sa.String(length=40), nullable=True),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('company_id', 'lead_id', name='uq_sales_memory_company_lead'),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name='chk_sales_memory_confidence',
        ),
    )
    op.create_index('idx_sales_memories_company', 'sales_memories', ['company_id'])

    # ------------------------------------------------------------------
    # crm_update_suggestions -- a IA propoe; a pessoa decide
    # ------------------------------------------------------------------
    op.create_table(
        'crm_update_suggestions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('meeting_id', sa.BigInteger(), nullable=True),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('field', sa.String(length=60), nullable=False),
        sa.Column('suggestion_type', sa.String(length=40), nullable=False),
        sa.Column('current_value', sa.Text(), nullable=True),
        sa.Column('suggested_value', sa.Text(), nullable=True),
        _jsonb('payload', default='{}'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('confidence', sa.String(length=10), nullable=True),
        _jsonb('source_refs'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        # Chave estavel do conteudo da sugestao. E o que impede retry de
        # analise de gerar a mesma sugestao duas vezes.
        sa.Column('dedupe_key', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_client_id', sa.Integer(), nullable=True),
        sa.Column('applied_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('apply_error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'applied', 'failed')",
            name='chk_crm_suggestion_status',
        ),
        # A lista e fechada de proposito. 'won'/'lost' nao estao aqui: a IA
        # nao decide fechamento de negocio nesta fase, e o banco recusa.
        sa.CheckConstraint(
            "suggestion_type IN ('move_stage', 'update_deal_value', 'create_task', "
            "'add_note', 'add_tag', 'register_objection', 'register_next_step')",
            name='chk_crm_suggestion_type',
        ),
        sa.UniqueConstraint('company_id', 'lead_id', 'dedupe_key', name='uq_crm_suggestion_dedupe'),
    )
    op.create_index('idx_crm_suggestions_company_status', 'crm_update_suggestions', ['company_id', 'status'])
    op.create_index('idx_crm_suggestions_lead', 'crm_update_suggestions', ['lead_id'])
    op.create_index('idx_crm_suggestions_meeting', 'crm_update_suggestions', ['meeting_id'])

    # ------------------------------------------------------------------
    # Ampliar operacoes do ledger de IA
    # ------------------------------------------------------------------
    # Substituicao por superconjunto: todo evento antigo ('llm_response',
    # 'tts') continua valido. Nenhuma linha e reescrita.
    op.drop_constraint('chk_ai_usage_operation', 'ai_usage_events', type_='check')
    op.create_check_constraint(
        'chk_ai_usage_operation',
        'ai_usage_events',
        "operation IN ('llm_response', 'tts', 'transcription', 'meeting_analysis', "
        "'sales_memory', 'follow_up_generation')",
    )


def downgrade() -> None:
    op.drop_constraint('chk_ai_usage_operation', 'ai_usage_events', type_='check')
    op.create_check_constraint(
        'chk_ai_usage_operation',
        'ai_usage_events',
        "operation IN ('llm_response', 'tts')",
    )
    op.drop_table('crm_update_suggestions')
    op.drop_table('sales_memories')
    op.drop_table('meeting_analyses')
    op.drop_table('meeting_transcripts')
    op.drop_table('meeting_participants')
    op.drop_table('meetings')

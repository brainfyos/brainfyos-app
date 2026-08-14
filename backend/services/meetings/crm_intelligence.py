"""CRM Intelligence — a IA propõe, a pessoa decide.

Duas fronteiras que este módulo existe para manter:

**Nada é aplicado sem aceite.** ``generate_suggestions`` só grava linhas em
``crm_update_suggestions`` com status ``pending``. Só ``apply_suggestion``
toca no CRM, e ela exige que alguém tenha aceitado antes.

**Fechamento de negócio está fora.** A IA não marca ganho nem perdido, não
mexe em preço, contrato ou cobrança. A lista de tipos permitidos é fechada no
código *e* no CHECK do banco — duas barreiras, porque uma sozinha é a que
alguém remove sem perceber.

As sugestões só usam campos que existem de verdade no CRM deste projeto:
``leads.deal_value``, ``leads.current_stage_id``, ``ContactTask``,
``ContactNote`` e tags. Não há ``probability`` nem ``expected_close_date`` no
modelo, então nada é sugerido para eles.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import Client, Contact, ContactNote, ContactTask, Lead, PipelineStage, User
from backend.models.meeting_models import (
    CrmUpdateSuggestion,
    Meeting,
    MeetingAnalysis,
    SUGGESTION_ACCEPTED,
    SUGGESTION_APPLIED,
    SUGGESTION_FAILED,
    SUGGESTION_PENDING,
    SUGGESTION_REJECTED,
)

logger = logging.getLogger(__name__)

# Prazo padrão de uma tarefa de follow-up quando a análise não sugeriu data.
DEFAULT_TASK_DAYS = 2


class CrmSuggestionError(RuntimeError):
    pass


class CrmSuggestionScopeError(PermissionError):
    """Sugestão inexistente ou de outra empresa."""


def _dedupe_key(suggestion_type: str, value: str) -> str:
    """Chave estável do conteúdo.

    É o que garante que reprocessar uma análise não gere a mesma sugestão de
    novo: o hash do par (tipo, valor) já existe no índice único.
    """
    digest = hashlib.sha256(f"{suggestion_type}:{value}".encode("utf-8")).hexdigest()
    return f"{suggestion_type}:{digest[:32]}"


def generate_suggestions(
    db: Session,
    company_id: int,
    meeting_id: int,
) -> List[CrmUpdateSuggestion]:
    """Deriva sugestões da análise. Não altera nada no CRM."""
    company_id = int(company_id)

    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == int(meeting_id), Meeting.company_id == company_id)
        .first()
    )
    if meeting is None:
        raise CrmSuggestionError("Reunião não encontrada")
    if not meeting.lead_id:
        # Sem lead não há card onde a sugestão faria sentido. Reuniões não
        # associadas esperam resolução humana primeiro.
        return []

    analysis = (
        db.query(MeetingAnalysis)
        .filter(
            MeetingAnalysis.meeting_id == meeting.id,
            MeetingAnalysis.company_id == company_id,
        )
        .order_by(MeetingAnalysis.analysis_version.desc())
        .first()
    )
    if analysis is None:
        return []

    lead = (
        db.query(Lead)
        .filter(Lead.id == meeting.lead_id, Lead.company_id == company_id)
        .first()
    )
    if lead is None:
        return []

    source_refs = [
        {"source_type": "meeting", "meeting_id": meeting.id},
        {"source_type": "analysis", "analysis_id": analysis.id},
    ]

    drafts: List[Dict[str, Any]] = []

    if analysis.summary:
        drafts.append(
            {
                "field": "note",
                "suggestion_type": "add_note",
                "suggested_value": _note_body(meeting, analysis),
                "reason": "Registro da reunião no histórico do contato",
                "confidence": "high",
            }
        )

    if analysis.budget_amount is not None and analysis.budget_confidence in {"medium", "high"}:
        current = lead.deal_value
        if current is None or Decimal(str(current)) != Decimal(str(analysis.budget_amount)):
            drafts.append(
                {
                    "field": "deal_value",
                    "suggestion_type": "update_deal_value",
                    "current_value": str(current) if current is not None else None,
                    "suggested_value": str(analysis.budget_amount),
                    "reason": analysis.budget_context or "Valor citado na reunião",
                    "confidence": analysis.budget_confidence,
                }
            )

    for next_step in (analysis.next_steps or [])[:1]:
        drafts.append(
            {
                "field": "task",
                "suggestion_type": "create_task",
                "suggested_value": next_step,
                "payload": {
                    "title": next_step[:255],
                    "scheduled_for": _task_due_date(analysis).isoformat(),
                },
                "reason": "Próximo passo combinado na reunião",
                "confidence": "medium",
            }
        )

    for objection in (analysis.objections or [])[:3]:
        drafts.append(
            {
                "field": "objection",
                "suggestion_type": "register_objection",
                "suggested_value": objection,
                "reason": "Objeção levantada pelo cliente",
                "confidence": "medium",
            }
        )

    created: List[CrmUpdateSuggestion] = []
    for draft in drafts:
        suggestion = _persist(db, company_id, meeting, lead, draft, source_refs)
        if suggestion is not None:
            created.append(suggestion)
    return created


def _persist(
    db: Session,
    company_id: int,
    meeting: Meeting,
    lead: Lead,
    draft: Dict[str, Any],
    source_refs: List[Dict[str, Any]],
) -> Optional[CrmUpdateSuggestion]:
    dedupe = _dedupe_key(draft["suggestion_type"], str(draft.get("suggested_value") or ""))

    existing = (
        db.query(CrmUpdateSuggestion)
        .filter(
            CrmUpdateSuggestion.company_id == company_id,
            CrmUpdateSuggestion.lead_id == lead.id,
            CrmUpdateSuggestion.dedupe_key == dedupe,
        )
        .first()
    )
    if existing is not None:
        return None

    suggestion = CrmUpdateSuggestion(
        company_id=company_id,
        meeting_id=meeting.id,
        lead_id=lead.id,
        field=draft["field"],
        suggestion_type=draft["suggestion_type"],
        current_value=draft.get("current_value"),
        suggested_value=draft.get("suggested_value"),
        payload=draft.get("payload") or {},
        reason=draft.get("reason"),
        confidence=draft.get("confidence"),
        source_refs=source_refs,
        status=SUGGESTION_PENDING,
        dedupe_key=dedupe,
    )
    db.add(suggestion)

    try:
        db.commit()
    except IntegrityError:
        # Retry concorrente: o índice único já barrou a duplicata.
        db.rollback()
        return None
    return suggestion


def _note_body(meeting: Meeting, analysis: MeetingAnalysis) -> str:
    lines = [f"Reunião: {meeting.title or 'sem título'}"]
    if meeting.scheduled_start_at:
        lines.append(f"Data: {meeting.scheduled_start_at.strftime('%d/%m/%Y %H:%M')}")
    lines.append("")
    lines.append(analysis.summary or "")
    if analysis.next_steps:
        lines.append("")
        lines.append("Próximos passos:")
        lines.extend(f"- {step}" for step in analysis.next_steps)
    return "\n".join(lines).strip()


def _task_due_date(analysis: MeetingAnalysis) -> datetime:
    if analysis.suggested_next_step_date:
        return datetime.combine(
            analysis.suggested_next_step_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    return datetime.now(timezone.utc) + timedelta(days=DEFAULT_TASK_DAYS)


# ---------------------------------------------------------------------------
# Revisão e aplicação
# ---------------------------------------------------------------------------

def get_suggestion(db: Session, company_id: int, suggestion_id: int) -> CrmUpdateSuggestion:
    suggestion = (
        db.query(CrmUpdateSuggestion)
        .filter(
            CrmUpdateSuggestion.id == int(suggestion_id),
            CrmUpdateSuggestion.company_id == int(company_id),
        )
        .first()
    )
    if suggestion is None:
        raise CrmSuggestionScopeError("Sugestão não encontrada")
    return suggestion


def reject_suggestion(
    db: Session,
    company_id: int,
    suggestion_id: int,
    actor: Union[Client, User, None] = None,
) -> CrmUpdateSuggestion:
    suggestion = get_suggestion(db, company_id, suggestion_id)
    suggestion.status = SUGGESTION_REJECTED
    _stamp_review(suggestion, actor)
    db.commit()
    return suggestion


def accept_suggestion(
    db: Session,
    company_id: int,
    suggestion_id: int,
    actor: Union[Client, User, None] = None,
    *,
    apply_now: bool = True,
) -> CrmUpdateSuggestion:
    """Aceita e, por padrão, aplica.

    Aceitar sem aplicar existe para o caso de a aplicação falhar: o aceite
    fica registrado e a sugestão pode ser reaplicada sem virar uma segunda
    decisão humana.
    """
    suggestion = get_suggestion(db, company_id, suggestion_id)

    if suggestion.status == SUGGESTION_APPLIED:
        # Aplicar de novo duplicaria nota ou tarefa.
        return suggestion

    suggestion.status = SUGGESTION_ACCEPTED
    _stamp_review(suggestion, actor)
    db.commit()

    if apply_now:
        return apply_suggestion(db, company_id, suggestion_id, actor)
    return suggestion


def apply_suggestion(
    db: Session,
    company_id: int,
    suggestion_id: int,
    actor: Union[Client, User, None] = None,
) -> CrmUpdateSuggestion:
    """Escreve no CRM. Só roda depois de aceite explícito."""
    suggestion = get_suggestion(db, company_id, suggestion_id)

    if suggestion.status == SUGGESTION_APPLIED:
        return suggestion
    if suggestion.status != SUGGESTION_ACCEPTED:
        raise CrmSuggestionError("A sugestão precisa ser aceita antes de ser aplicada")

    lead = (
        db.query(Lead)
        .filter(Lead.id == suggestion.lead_id, Lead.company_id == suggestion.company_id)
        .first()
    )
    if lead is None:
        raise CrmSuggestionScopeError("Lead não encontrado nesta empresa")

    try:
        _apply_by_type(db, suggestion, lead, actor)
    except CrmSuggestionError:
        raise
    except Exception as exc:
        db.rollback()
        suggestion.status = SUGGESTION_FAILED
        suggestion.apply_error = exc.__class__.__name__
        db.commit()
        logger.warning(
            "Falha ao aplicar sugestão: suggestion_id=%s error_type=%s",
            suggestion_id,
            exc.__class__.__name__,
        )
        raise CrmSuggestionError("Não foi possível aplicar a sugestão") from None

    suggestion.status = SUGGESTION_APPLIED
    suggestion.applied_at = datetime.now(timezone.utc)
    suggestion.apply_error = None
    db.commit()
    return suggestion


def _apply_by_type(
    db: Session,
    suggestion: CrmUpdateSuggestion,
    lead: Lead,
    actor: Union[Client, User, None],
) -> None:
    kind = suggestion.suggestion_type

    if kind == "update_deal_value":
        lead.deal_value = Decimal(str(suggestion.suggested_value))
        return

    if kind == "move_stage":
        stage_id = (suggestion.payload or {}).get("stage_id")
        stage = (
            db.query(PipelineStage)
            .join(PipelineStage.pipeline)
            .filter(PipelineStage.id == int(stage_id))
            .first()
            if stage_id
            else None
        )
        # Etapa precisa ser do pipeline de uma empresa que é esta. Sem a
        # checagem, um stage_id de outro workspace moveria o lead para lá.
        if stage is None or stage.pipeline.company_id != suggestion.company_id:
            raise CrmSuggestionScopeError("Etapa não encontrada nesta empresa")
        lead.current_stage_id = stage.id
        lead.pipeline_id = stage.pipeline_id
        return

    if kind in {"add_note", "register_objection", "register_next_step"}:
        contact = _contact_for(db, suggestion, lead)
        db.add(
            ContactNote(
                contact_id=contact.id,
                company_id=suggestion.company_id,
                created_by=actor.id if isinstance(actor, User) else None,
                content=suggestion.suggested_value or "",
                note_metadata={
                    "source": "meeting_intelligence",
                    "suggestion_id": suggestion.id,
                    "meeting_id": suggestion.meeting_id,
                    "kind": kind,
                },
            )
        )
        return

    if kind == "create_task":
        contact = _contact_for(db, suggestion, lead)
        payload = suggestion.payload or {}
        scheduled_for = payload.get("scheduled_for")
        db.add(
            ContactTask(
                contact_id=contact.id,
                company_id=suggestion.company_id,
                created_by=actor.id if isinstance(actor, User) else None,
                task_type="custom",
                title=(payload.get("title") or suggestion.suggested_value or "Follow-up")[:255],
                description=suggestion.reason,
                scheduled_for=(
                    datetime.fromisoformat(scheduled_for)
                    if scheduled_for
                    else datetime.now(timezone.utc) + timedelta(days=DEFAULT_TASK_DAYS)
                ),
                status="pending",
                priority="medium",
                task_metadata={
                    "source": "meeting_intelligence",
                    "suggestion_id": suggestion.id,
                    "meeting_id": suggestion.meeting_id,
                },
            )
        )
        return

    if kind == "add_tag":
        _apply_tag(db, suggestion, lead)
        return

    raise CrmSuggestionError(f"Tipo de sugestão não suportado: {kind}")


def _contact_for(db: Session, suggestion: CrmUpdateSuggestion, lead: Lead) -> Contact:
    """Contato do lead. Notas e tarefas são chaveadas por contato no projeto."""
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.id == suggestion.meeting_id,
            Meeting.company_id == suggestion.company_id,
        )
        .first()
        if suggestion.meeting_id
        else None
    )
    if meeting is not None and meeting.contact_id:
        contact = (
            db.query(Contact)
            .filter(Contact.id == meeting.contact_id, Contact.company_id == suggestion.company_id)
            .first()
        )
        if contact is not None:
            return contact

    if lead.phone:
        contact = (
            db.query(Contact)
            .filter(Contact.company_id == suggestion.company_id, Contact.phone == lead.phone)
            .first()
        )
        if contact is not None:
            return contact

    raise CrmSuggestionError("Nenhum contato vinculado a esta oportunidade")


def _apply_tag(db: Session, suggestion: CrmUpdateSuggestion, lead: Lead) -> None:
    from backend.models import ContactTag, Tag

    contact = _contact_for(db, suggestion, lead)
    name = (suggestion.suggested_value or "").strip()
    if not name:
        raise CrmSuggestionError("Tag sem nome")

    tag = (
        db.query(Tag)
        .filter(Tag.company_id == suggestion.company_id, Tag.name == name)
        .first()
    )
    if tag is None:
        tag = Tag(company_id=suggestion.company_id, name=name, color="#3B82F6")
        db.add(tag)
        db.flush()

    already = (
        db.query(ContactTag)
        .filter(ContactTag.contact_id == contact.id, ContactTag.tag_id == tag.id)
        .first()
    )
    if already is None:
        db.add(ContactTag(contact_id=contact.id, tag_id=tag.id))


def _stamp_review(suggestion: CrmUpdateSuggestion, actor: Union[Client, User, None]) -> None:
    suggestion.reviewed_at = datetime.now(timezone.utc)
    suggestion.reviewed_by_user_id = actor.id if isinstance(actor, User) else None
    suggestion.reviewed_by_client_id = actor.id if isinstance(actor, Client) else None

"""API de Meeting Intelligence.

Escopo, sem exceção: ``company_id`` vem de ``get_current_user``. Nenhuma rota
aceita company_id do cliente, e todo id de entidade na URL é resolvido por
id **e** company — id externo nunca vale como autorização.

Proteção de dados: a transcrição completa tem endpoint próprio e não viaja em
listagem nem em detalhe. Quem quer o conteúdo pede explicitamente.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, Lead, User
from backend.models.meeting_models import (
    CrmUpdateSuggestion,
    Meeting,
    MeetingAnalysis,
    MeetingTranscript,
    SalesMemory,
)
from backend.services.meetings.crm_intelligence import (
    CrmSuggestionError,
    CrmSuggestionScopeError,
    accept_suggestion,
    reject_suggestion,
)
from backend.services.meetings.ingestion import MeetingIngestionService, MeetingScopeError
from backend.services.meetings.providers import available_providers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])

MAX_PAGE_SIZE = 50


def _company_id(user: Union[Client, User]) -> int:
    company_id = getattr(user, "company_id", None)
    if company_id is None:
        raise HTTPException(status_code=400, detail="Conta sem workspace ativo")
    return int(company_id)


class AssociatePayload(BaseModel):
    lead_id: Optional[int] = Field(default=None, ge=1)
    contact_id: Optional[int] = Field(default=None, ge=1)
    customer_id: Optional[int] = Field(default=None, ge=1)


def _meeting_dict(meeting: Meeting, analysis: Optional[MeetingAnalysis] = None) -> Dict[str, Any]:
    return {
        "id": meeting.id,
        "title": meeting.title,
        "provider": meeting.provider,
        "source": meeting.source,
        "status": meeting.status,
        "scheduled_start_at": _iso(meeting.scheduled_start_at),
        "scheduled_end_at": _iso(meeting.scheduled_end_at),
        "duration_seconds": meeting.duration_seconds,
        "meeting_url": meeting.meeting_url,
        "transcript_status": meeting.transcript_status,
        "analysis_status": meeting.analysis_status,
        "resolution_status": meeting.resolution_status,
        "resolution_candidates": meeting.resolution_candidates or [],
        "lead_id": meeting.lead_id,
        "contact_id": meeting.contact_id,
        "customer_id": meeting.customer_id,
        "participants": [
            {
                "id": participant.id,
                "name": participant.name,
                "email": participant.email,
                "type": participant.participant_type,
                "role": participant.role,
                "attendance_status": participant.attendance_status,
            }
            for participant in meeting.participants
        ],
        # Resumo entra; transcrição não. Listagem com transcrição estoura
        # payload e vaza conteúdo sensível onde ninguém pediu.
        "summary": getattr(analysis, "summary", None),
        "next_steps": list(getattr(analysis, "next_steps", None) or []),
    }


def _analysis_dict(analysis: MeetingAnalysis) -> Dict[str, Any]:
    scalar = (
        "summary", "meeting_purpose", "customer_context", "main_problem",
        "budget_context", "timeline", "sentiment", "urgency",
        "budget_confidence", "probability_reason",
    )
    lists = (
        "pain_points", "needs", "desired_outcomes", "decision_makers", "influencers",
        "competitors", "objections", "questions", "unanswered_questions",
        "products_discussed", "offers_discussed", "prices_mentioned",
        "commitments_company", "commitments_customer", "next_steps", "risks",
        "positive_signals", "negative_signals", "evidence_snippets",
    )
    return {
        "id": analysis.id,
        "meeting_id": analysis.meeting_id,
        "analysis_version": analysis.analysis_version,
        "model": analysis.model,
        "prompt_version": analysis.prompt_version,
        "created_at": _iso(analysis.created_at),
        "budget_amount": float(analysis.budget_amount) if analysis.budget_amount is not None else None,
        "suggested_probability": analysis.suggested_probability,
        "suggested_next_step_date": (
            analysis.suggested_next_step_date.isoformat()
            if analysis.suggested_next_step_date
            else None
        ),
        **{field: getattr(analysis, field) for field in scalar},
        **{field: list(getattr(analysis, field) or []) for field in lists},
    }


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _latest_analysis(db: Session, company_id: int, meeting_id: int) -> Optional[MeetingAnalysis]:
    return (
        db.query(MeetingAnalysis)
        .filter(
            MeetingAnalysis.meeting_id == meeting_id,
            MeetingAnalysis.company_id == company_id,
        )
        .order_by(MeetingAnalysis.analysis_version.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Listagem e detalhe
# ---------------------------------------------------------------------------

@router.get("")
def list_meetings(
    lead_id: Optional[int] = Query(None, ge=1),
    resolution_status: Optional[str] = Query(None, pattern="^(matched|ambiguous|unmatched|manual)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    query = db.query(Meeting).filter(Meeting.company_id == company_id)

    if lead_id is not None:
        query = query.filter(Meeting.lead_id == lead_id)
    if resolution_status:
        query = query.filter(Meeting.resolution_status == resolution_status)

    total = query.count()
    meetings = (
        query.order_by(Meeting.scheduled_start_at.desc().nullslast(), Meeting.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Uma consulta para todos os resumos, em vez de um SELECT por reunião.
    analyses = (
        db.query(MeetingAnalysis)
        .filter(
            MeetingAnalysis.company_id == company_id,
            MeetingAnalysis.meeting_id.in_([meeting.id for meeting in meetings] or [0]),
        )
        .order_by(MeetingAnalysis.analysis_version.asc())
        .all()
    )
    latest = {analysis.meeting_id: analysis for analysis in analyses}

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_meeting_dict(meeting, latest.get(meeting.id)) for meeting in meetings],
    }


@router.get("/providers")
def list_provider_status(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Estado real de cada provedor.

    Se a agenda está conectada mas a permissão de transcrição não foi
    concedida, isso aparece aqui — a tela não deve dizer "conectado" quando a
    funcionalidade necessária não está disponível.
    """
    company_id = _company_id(user)
    items = []
    for provider in available_providers():
        capabilities = provider.capabilities(db, company_id)
        items.append(
            {
                "provider": capabilities.provider,
                "label": capabilities.label,
                "can_discover_meetings": capabilities.can_discover_meetings,
                "can_import_transcripts": capabilities.can_import_transcripts,
                "supports_realtime": capabilities.supports_realtime,
                "is_operational": capabilities.is_operational,
                "unavailable_reason": capabilities.unavailable_reason,
                "missing_scopes": capabilities.missing_scopes,
            }
        )
    return {"items": items}


@router.get("/{meeting_id}")
def get_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        meeting = MeetingIngestionService(db).get_meeting(company_id, meeting_id)
    except MeetingScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    analysis = _latest_analysis(db, company_id, meeting.id)
    payload = _meeting_dict(meeting, analysis)
    payload["analysis"] = _analysis_dict(analysis) if analysis else None
    return payload


@router.get("/{meeting_id}/transcript")
def get_transcript(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Transcrição completa. Endpoint separado, pedido explicitamente."""
    company_id = _company_id(user)
    try:
        MeetingIngestionService(db).get_meeting(company_id, meeting_id)
    except MeetingScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    transcript = (
        db.query(MeetingTranscript)
        .filter(
            MeetingTranscript.meeting_id == meeting_id,
            MeetingTranscript.company_id == company_id,
        )
        .order_by(MeetingTranscript.id.desc())
        .first()
    )
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcrição não disponível")

    return {
        "id": transcript.id,
        "meeting_id": transcript.meeting_id,
        "provider": transcript.provider,
        "language": transcript.language,
        "text": transcript.text,
        "segments": transcript.segments or [],
        "speaker_map": transcript.speaker_map or {},
        "word_count": transcript.word_count,
        "imported_at": _iso(transcript.imported_at),
    }


# ---------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------

@router.post("/sync")
def sync_meetings(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Dispara a sincronização. O trabalho pesado vai para a fila."""
    company_id = _company_id(user)
    from backend.worker.tasks_meetings import sync_company_meetings

    sync_company_meetings.delay(company_id)
    return {"queued": True, "company_id": company_id}


@router.post("/{meeting_id}/associate")
def associate_meeting(
    meeting_id: int,
    payload: AssociatePayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Associação manual. Depois dela o restante do pipeline segue."""
    company_id = _company_id(user)
    try:
        meeting = MeetingIngestionService(db).associate(
            company_id,
            meeting_id,
            lead_id=payload.lead_id,
            contact_id=payload.contact_id,
            customer_id=payload.customer_id,
        )
    except MeetingScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if meeting.transcript_status == "imported" and meeting.lead_id:
        from backend.worker.tasks_meetings import analyze_meeting_task

        analyze_meeting_task.delay(meeting.id, company_id)

    return _meeting_dict(meeting, _latest_analysis(db, company_id, meeting.id))


@router.post("/{meeting_id}/reprocess")
def reprocess_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        MeetingIngestionService(db).get_meeting(company_id, meeting_id)
    except MeetingScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from backend.worker.tasks_meetings import analyze_meeting_task

    analyze_meeting_task.delay(meeting_id, company_id, True)
    return {"queued": True, "meeting_id": meeting_id}


@router.post("/{meeting_id}/follow-up")
def create_follow_up(
    meeting_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Gera o rascunho. **Não envia nada.**"""
    company_id = _company_id(user)
    from backend.services.meetings.follow_up import FollowUpError, generate_follow_up

    try:
        return generate_follow_up(db, company_id, meeting_id)
    except FollowUpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Sales Memory e sugestões
# ---------------------------------------------------------------------------

@router.get("/leads/{lead_id}/sales-memory")
def get_sales_memory(
    lead_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Oportunidade não encontrada")

    memory = (
        db.query(SalesMemory)
        .filter(SalesMemory.company_id == company_id, SalesMemory.lead_id == lead_id)
        .first()
    )
    if memory is None:
        # Ausência declarada em vez de 404: o card sabe distinguir "ainda não
        # há reunião analisada" de "erro".
        return {"lead_id": lead_id, "available": False, "reason": "Nenhuma reunião analisada ainda"}

    lists = (
        "desired_outcomes", "stakeholders", "objections", "competitors",
        "commitments_company", "commitments_customer", "risks",
        "buying_signals", "negative_signals", "open_questions", "source_refs",
    )
    scalars = (
        "current_summary", "business_context", "business_problem",
        "decision_process", "budget_context", "timeline",
        "next_best_action", "confidence",
    )
    return {
        "lead_id": lead_id,
        "available": True,
        "last_rebuilt_at": _iso(memory.last_rebuilt_at),
        **{field: getattr(memory, field) for field in scalars},
        **{field: list(getattr(memory, field) or []) for field in lists},
    }


@router.get("/leads/{lead_id}/suggestions")
def list_suggestions(
    lead_id: int,
    status: Optional[str] = Query(None, pattern="^(pending|accepted|rejected|applied|failed)$"),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    query = db.query(CrmUpdateSuggestion).filter(
        CrmUpdateSuggestion.company_id == company_id,
        CrmUpdateSuggestion.lead_id == lead_id,
    )
    if status:
        query = query.filter(CrmUpdateSuggestion.status == status)

    items = query.order_by(CrmUpdateSuggestion.created_at.desc()).limit(MAX_PAGE_SIZE).all()
    return {
        "items": [
            {
                "id": item.id,
                "meeting_id": item.meeting_id,
                "field": item.field,
                "suggestion_type": item.suggestion_type,
                "current_value": item.current_value,
                "suggested_value": item.suggested_value,
                "reason": item.reason,
                "confidence": item.confidence,
                "status": item.status,
                "source_refs": item.source_refs or [],
                "created_at": _iso(item.created_at),
                "applied_at": _iso(item.applied_at),
            }
            for item in items
        ]
    }


@router.post("/suggestions/{suggestion_id}/accept")
def accept(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        suggestion = accept_suggestion(db, company_id, suggestion_id, user)
    except CrmSuggestionScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CrmSuggestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": suggestion.id, "status": suggestion.status, "applied_at": _iso(suggestion.applied_at)}


@router.post("/suggestions/{suggestion_id}/reject")
def reject(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        suggestion = reject_suggestion(db, company_id, suggestion_id, user)
    except CrmSuggestionScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": suggestion.id, "status": suggestion.status}

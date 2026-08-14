"""Associação de uma reunião ao lead/contato certo.

A regra que define este módulo: **na dúvida, não escolhe**.

Associar uma reunião ao lead errado é pior do que não associar. O contexto
errado contamina a Sales Memory, gera sugestão de CRM no card de outra pessoa
e o erro fica invisível — ninguém audita uma associação que parece razoável.
Uma reunião não associada, por outro lado, aparece numa lista e alguém
resolve em dez segundos.

Por isso o resolvedor devolve três estados e nunca desempata sozinho:

``matched``     exatamente um candidato. Associa.
``ambiguous``   dois ou mais plausíveis. Guarda todos e espera decisão humana.
``unmatched``   nenhum sinal. Fica na lista de não associadas.

Sinais usados, do mais forte para o mais fraco: e-mail exato de participante,
telefone normalizado, e o organizador é sempre ignorado (é gente da casa).
Nome nunca é usado — "João Silva" casa com meio banco.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from backend.models import Contact, Customer, Lead
from backend.models.meeting_models import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_MATCHED,
    RESOLUTION_UNMATCHED,
)

logger = logging.getLogger(__name__)

_NON_DIGITS = re.compile(r"\D+")
# Telefone só é sinal confiável a partir de 8 dígitos; abaixo disso um ramal
# casaria com qualquer coisa.
MIN_PHONE_DIGITS = 8


@dataclass
class ResolutionCandidate:
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    customer_id: Optional[int] = None
    label: Optional[str] = None
    matched_on: str = "unknown"
    detail: Optional[str] = None

    def key(self) -> tuple:
        return (self.lead_id, self.contact_id, self.customer_id)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lead_id": self.lead_id,
            "contact_id": self.contact_id,
            "customer_id": self.customer_id,
            "label": self.label,
            "matched_on": self.matched_on,
            "detail": self.detail,
        }


@dataclass
class ResolutionResult:
    status: str
    candidates: List[ResolutionCandidate] = field(default_factory=list)

    @property
    def chosen(self) -> Optional[ResolutionCandidate]:
        return self.candidates[0] if self.status == RESOLUTION_MATCHED and self.candidates else None

    def as_payload(self) -> List[Dict[str, Any]]:
        return [candidate.as_dict() for candidate in self.candidates]


def normalize_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = _NON_DIGITS.sub("", str(value))
    return digits if len(digits) >= MIN_PHONE_DIGITS else None


def normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = str(value).strip().lower()
    return cleaned or None


class MeetingEntityResolver:
    """Resolve a quem uma reunião pertence, sem chutar."""

    def __init__(self, db: Session):
        self._db = db

    def resolve(
        self,
        company_id: int,
        *,
        participant_emails: Sequence[str] = (),
        participant_phones: Sequence[str] = (),
        organizer_email: Optional[str] = None,
        calendar_event_id: Optional[str] = None,
    ) -> ResolutionResult:
        company_id = int(company_id)
        organizer = normalize_email(organizer_email)

        # O organizador é quase sempre o vendedor. Casá-lo criaria uma reunião
        # associada ao "lead" que é a própria equipe.
        emails = {
            email
            for email in (normalize_email(value) for value in participant_emails)
            if email and email != organizer
        }
        phones = {
            phone
            for phone in (normalize_phone(value) for value in participant_phones)
            if phone
        }

        candidates: Dict[tuple, ResolutionCandidate] = {}

        for candidate in self._by_calendar_event(company_id, calendar_event_id):
            candidates.setdefault(candidate.key(), candidate)
        for candidate in self._by_phone(company_id, phones):
            candidates.setdefault(candidate.key(), candidate)
        for candidate in self._by_email(company_id, emails):
            candidates.setdefault(candidate.key(), candidate)

        resolved = list(candidates.values())

        if not resolved:
            return ResolutionResult(status=RESOLUTION_UNMATCHED)
        if len(resolved) == 1:
            return ResolutionResult(status=RESOLUTION_MATCHED, candidates=resolved)

        logger.info(
            "Reunião ambígua: company_id=%s candidatos=%s",
            company_id,
            len(resolved),
        )
        return ResolutionResult(status=RESOLUTION_AMBIGUOUS, candidates=resolved)

    # ------------------------------------------------------------------

    def _by_calendar_event(
        self, company_id: int, calendar_event_id: Optional[str]
    ) -> List[ResolutionCandidate]:
        """Agendamento já criado pelo sistema para este evento.

        É o sinal mais forte que existe: o próprio BrainfyOS marcou a reunião
        para aquele lead.
        """
        if not calendar_event_id:
            return []

        from backend.models import Agendamento

        rows = (
            self._db.query(Agendamento)
            .filter(
                Agendamento.company_id == company_id,
                Agendamento.event_id == calendar_event_id,
            )
            .all()
        )
        found: List[ResolutionCandidate] = []
        for row in rows:
            if not row.lead_id:
                continue
            lead = self._lead(company_id, row.lead_id)
            if lead is None:
                continue
            found.append(
                ResolutionCandidate(
                    lead_id=lead.id,
                    customer_id=row.customer_id,
                    label=lead.name,
                    matched_on="calendar_event",
                    detail=f"Agendamento vinculado ao evento {calendar_event_id}",
                )
            )
        return found

    def _by_phone(self, company_id: int, phones: Sequence[str]) -> List[ResolutionCandidate]:
        if not phones:
            return []

        found: List[ResolutionCandidate] = []
        for phone in phones:
            leads = (
                self._db.query(Lead)
                .filter(Lead.company_id == company_id, Lead.phone.isnot(None))
                .all()
            )
            for lead in leads:
                if normalize_phone(lead.phone) != phone:
                    continue
                contact = (
                    self._db.query(Contact)
                    .filter(Contact.company_id == company_id, Contact.phone == lead.phone)
                    .first()
                )
                found.append(
                    ResolutionCandidate(
                        lead_id=lead.id,
                        contact_id=contact.id if contact else None,
                        label=lead.name,
                        matched_on="phone",
                        detail=f"Telefone {phone}",
                    )
                )
        return found

    def _by_email(self, company_id: int, emails: Sequence[str]) -> List[ResolutionCandidate]:
        """E-mail casa via ``customers`` -- ``contacts`` não guarda e-mail."""
        if not emails:
            return []

        found: List[ResolutionCandidate] = []
        customers = (
            self._db.query(Customer)
            .filter(Customer.company_id == company_id, Customer.email.isnot(None))
            .all()
        )
        for customer in customers:
            if normalize_email(customer.email) not in emails:
                continue
            lead = None
            if customer.convertido_de_lead_id:
                lead = self._lead(company_id, customer.convertido_de_lead_id)
            found.append(
                ResolutionCandidate(
                    lead_id=lead.id if lead else None,
                    contact_id=customer.contact_id,
                    customer_id=customer.id,
                    label=customer.nome,
                    matched_on="email",
                    detail=f"E-mail {customer.email}",
                )
            )
        return found

    def _lead(self, company_id: int, lead_id: Optional[int]) -> Optional[Lead]:
        if not lead_id:
            return None
        # company_id explícito: a FK garante que o lead existe, não que ele é
        # desta empresa.
        return (
            self._db.query(Lead)
            .filter(Lead.id == int(lead_id), Lead.company_id == company_id)
            .first()
        )

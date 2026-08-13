"""Modelos da camada de plataforma (BrainfyOS Control)."""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    TIMESTAMP,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from backend.db import Base

PLATFORM_ROLE_OWNER = "platform_owner"


class PlatformAuditLog(Base):
    """Registro de acoes administrativas que cruzam a fronteira de company.

    O ator e sempre um ``Client`` com ``platform_role='platform_owner'``. O
    e-mail e desnormalizado porque a linha precisa continuar legivel mesmo
    depois de a conta ser removida (a FK e ``ON DELETE SET NULL``).
    """

    __tablename__ = "platform_audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    actor_email = Column(String(255), nullable=False)
    action = Column(String(80), nullable=False)
    target_company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    request_ip = Column(String(64), nullable=True)
    details = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_platform_audit_log_created", "created_at"),
        Index("idx_platform_audit_log_actor", "actor_client_id", "created_at"),
        Index("idx_platform_audit_log_target", "target_company_id", "created_at"),
    )

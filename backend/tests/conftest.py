"""Configuração compartilhada dos testes do backend.

Os testes com banco usam SQLite em memória (padrão já estabelecido no
projeto). Vários modelos declaram colunas ``JSONB``, que é um tipo do
PostgreSQL — o compilador DDL do SQLite não sabe renderizá-lo e o
``create_all`` falha com ``no attribute 'visit_JSONB'``.

Este shim ensina o SQLite a renderizar ``JSONB`` como ``JSON``. Vale apenas
para os testes: em produção o dialeto é PostgreSQL e o tipo real é usado.

A alternativa seria trocar todo ``JSONB`` do projeto por
``JSONB().with_variant(JSON(), "sqlite")`` — um refactor amplo em modelos que
esta fase não deveria tocar, para resolver um problema que só existe no teste.
"""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN201
    # SQLite armazena JSON como TEXT; o serializador do SQLAlchemy cuida da
    # conversão nos dois sentidos, então o comportamento em teste bate com o
    # de produção para leitura e escrita de dicionários e listas.
    return "JSON"

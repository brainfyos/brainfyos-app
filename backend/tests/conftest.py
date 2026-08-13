"""Configuração compartilhada dos testes do backend.

Os testes com banco usam SQLite em memória — padrão já estabelecido no
projeto. Vários modelos foram escritos para PostgreSQL e usam construções que
o SQLite não entende. Este módulo faz a tradução, em dois pontos:

1. **Tipo ``JSONB``** — o compilador DDL do SQLite não tem ``visit_JSONB`` e o
   ``create_all`` falha. Aqui ele passa a renderizar ``JSON``; o serializador
   do SQLAlchemy cuida da conversão nos dois sentidos, então ler e gravar
   dicionários e listas se comporta como em produção.

2. **Casts ``::jsonb`` em ``server_default``** — ``DEFAULT '[]'::jsonb`` é
   sintaxe do PostgreSQL e o SQLite rejeita o token ``:``.

Ambos valem só para os testes: em produção o dialeto é PostgreSQL e os tipos e
defaults reais são usados. A alternativa seria reescrever todo ``JSONB`` do
projeto com ``with_variant`` — um refactor amplo em modelos que não deveria
acontecer para resolver um problema que só existe no ambiente de teste.
"""

import os
import re

# `backend.db` exige DATABASE_URL no import. O conftest é carregado antes de
# qualquer módulo de teste, então o valor precisa existir aqui — os módulos
# usam `setdefault` e respeitam este.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-tests.db")

from sqlalchemy import ARRAY, BigInteger, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import TextClause

from backend.db import Base

# Importar o pacote de modelos registra todas as tabelas no metadata. Sem
# isso a varredura abaixo percorreria um metadata vazio e não corrigiria nada.
import backend.models  # noqa: F401

# Casa com o cast de tipo do PostgreSQL no fim de um literal: '[]'::jsonb
POSTGRES_CAST = re.compile(r"::\s*[a-zA-Z_][a-zA-Z0-9_]*")


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN201
    """``ARRAY`` vira ``JSON`` no SQLite -- compatibilidade só de DDL.

    O SQLite não tem tipo array. Isto existe para ``create_all`` não falhar em
    tabelas que apenas precisam existir (ex.: ``contact_tasks.tags``). Um teste
    que realmente exercite semântica de array precisa de PostgreSQL.
    """
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_on_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN201
    """``BIGINT`` vira ``INTEGER`` no SQLite.

    Só ``INTEGER PRIMARY KEY`` recebe autoincremento (rowid) no SQLite; um
    ``BIGINT PRIMARY KEY`` fica NOT NULL sem valor gerado, e todo insert falha.
    Nenhuma precisão se perde: inteiro em SQLite já é de 64 bits.
    """
    return "INTEGER"


def _strip_postgres_casts_from_server_defaults() -> None:
    """Remove ``::tipo`` dos server defaults declarados nos modelos.

    Roda uma vez, na coleta dos testes. Percorre o metadata inteiro porque
    qualquer tabela pode ser criada por qualquer teste, e descobrir isso via
    falha de DDL custa muito mais do que a varredura.
    """
    for table in Base.metadata.tables.values():
        for column in table.columns:
            default = column.server_default
            if default is None:
                continue
            arg = getattr(default, "arg", None)
            if not isinstance(arg, TextClause):
                continue
            original = str(arg)
            cleaned = POSTGRES_CAST.sub("", original)
            if cleaned != original:
                default.arg = sa_text(cleaned)


_strip_postgres_casts_from_server_defaults()

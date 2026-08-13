"""Compara todo o SQL cru do backend contra o schema real do PostgreSQL.

Extrai strings SQL do codigo Python (incluindo f-strings, cujos placeholders
sao neutralizados), faz o parse com sqlglot no dialeto postgres e verifica
cada tabela e cada coluna qualificada contra o schema vindo do banco.
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import sqlglot
from sqlglot import exp

SQL_START = re.compile(
    r"^\s*(WITH|SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", re.I | re.S
)
PLACEHOLDER = "__ph__"


def neutralize(node: ast.AST) -> str | None:
    """Converte Constant/JoinedStr em texto, trocando interpolacoes por token."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append(f" {PLACEHOLDER} ")
        return "".join(parts)
    return None


def collect_sql(root: Path):
    """Devolve [(arquivo, linha, sql)] de tudo que parece SQL."""
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent)
        if "test" in str(rel) or "/alembic/" in str(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            text = neutralize(node)
            if not text or len(text) < 20:
                continue
            if not SQL_START.match(text):
                continue
            found.append((str(rel), getattr(node, "lineno", 0), text))
    return found


def clean(sql: str) -> str:
    """Deixa o SQL parseavel: remove placeholders e binds nomeados."""
    s = sql
    # placeholder sozinho onde caberia predicado -> TRUE
    s = re.sub(r"\bAND\s+" + PLACEHOLDER, "AND TRUE", s, flags=re.I)
    s = re.sub(r"\bWHERE\s+" + PLACEHOLDER, "WHERE TRUE", s, flags=re.I)
    s = re.sub(r"\bOR\s+" + PLACEHOLDER, "OR TRUE", s, flags=re.I)
    s = s.replace(PLACEHOLDER, " ")
    # binds :param -> literal
    s = re.sub(r"(?<![:\w]):(\w+)", r"'x'", s)
    s = re.sub(r"%\((\w+)\)s", r"'x'", s)
    return s


def audit(sql_items, schema: dict[str, list[str]]):
    known_tables = {t.lower() for t in schema}
    cols_by_table = {t.lower(): {c.lower() for c in cs} for t, cs in schema.items()}

    missing_tables = defaultdict(list)   # tabela -> [(arquivo, linha)]
    missing_cols = defaultdict(list)     # (tabela, coluna) -> [(arquivo, linha)]
    unparsed = []

    for fname, lineno, raw in sql_items:
        try:
            tree = sqlglot.parse_one(clean(raw), dialect="postgres")
        except Exception:
            unparsed.append((fname, lineno))
            continue
        if tree is None:
            continue

        # mapa alias/nome -> tabela real, apenas tabelas fisicas
        alias_map: dict[str, str] = {}
        ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        used_tables = []
        for t in tree.find_all(exp.Table):
            name = (t.name or "").lower()
            if not name or name in ctes:
                continue
            used_tables.append((name, t))
            alias_map[name] = name
            alias = (t.alias or "").lower()
            if alias:
                alias_map[alias] = name

        for name, _t in used_tables:
            if name not in known_tables:
                missing_tables[name].append((fname, lineno))

        # colunas qualificadas
        for c in tree.find_all(exp.Column):
            tbl_ref = (c.table or "").lower()
            col = (c.name or "").lower()
            if not tbl_ref or not col or col == "*":
                continue
            real = alias_map.get(tbl_ref)
            if not real or real not in cols_by_table:
                continue
            if col not in cols_by_table[real]:
                missing_cols[(real, col)].append((fname, lineno))

        # colunas nao qualificadas quando ha uma unica tabela
        physical = [n for n, _ in used_tables if n in cols_by_table]
        if len(set(physical)) == 1:
            only = physical[0]
            for c in tree.find_all(exp.Column):
                if c.table:
                    continue
                col = (c.name or "").lower()
                if not col or col == "*":
                    continue
                if col not in cols_by_table[only]:
                    missing_cols[(only, col)].append((fname, lineno))

        # INSERT INTO t (colunas)
        if isinstance(tree, exp.Insert):
            tgt = tree.this
            tbl = None
            if isinstance(tgt, exp.Schema) and isinstance(tgt.this, exp.Table):
                tbl = (tgt.this.name or "").lower()
                for ident in tgt.expressions:
                    col = (ident.name or "").lower()
                    if tbl in cols_by_table and col and col not in cols_by_table[tbl]:
                        missing_cols[(tbl, col)].append((fname, lineno))

    return missing_tables, missing_cols, unparsed


if __name__ == "__main__":
    repo = Path(sys.argv[1])
    schema = json.loads(Path(sys.argv[2]).read_text())
    items = collect_sql(repo / "backend")
    print(f"trechos SQL analisados: {len(items)}")
    mt, mc, unp = audit(items, schema)

    print(f"nao parseados (ignorados): {len(unp)}\n")

    print("=" * 72)
    print(f"TABELAS INEXISTENTES: {len(mt)}")
    print("=" * 72)
    for t, locs in sorted(mt.items(), key=lambda kv: -len(kv[1])):
        files = sorted({f for f, _ in locs})
        print(f"  {t}  ({len(locs)} ocorrencias)")
        for f in files[:4]:
            print(f"      {f}")

    print()
    print("=" * 72)
    print(f"COLUNAS INEXISTENTES: {len(mc)}")
    print("=" * 72)
    by_table = defaultdict(list)
    for (t, c), locs in mc.items():
        by_table[t].append((c, locs))
    for t in sorted(by_table, key=lambda t: -len(by_table[t])):
        print(f"\n  {t}")
        for c, locs in sorted(by_table[t]):
            files = sorted({f for f, _ in locs})
            print(f"      .{c}  ({len(locs)}x)  {files[0]}" + (f" +{len(files)-1}" if len(files) > 1 else ""))


# Uso:
#   1) exporte o schema real do banco:
#      sudo -u postgres psql -d brainfyos -tAc "
#        SELECT json_object_agg(table_name, cols)::text FROM (
#          SELECT table_name, json_agg(column_name ORDER BY ordinal_position) AS cols
#          FROM information_schema.columns WHERE table_schema='public'
#          GROUP BY table_name) t;" > /tmp/schema.json
#   2) pip install sqlglot
#   3) python tools/sql_schema_audit.py . /tmp/schema.json

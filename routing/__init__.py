"""Compile the routing policy in `rules.py` into SQL, and apply it to a works table.

The split is deliberate: `rules.py` holds the judgement and nothing else, this file
holds the plumbing and makes no decisions. If you are reviewing HOW PAPERS ARE
ROUTED, read `rules.py`; this module only turns ordered Rule tables into the
first-match-wins CASE expressions they describe.

    import routing
    routing.apply(con)              # derive all six columns on `works`
    print(routing.explain())        # the same policy as a readable decision table

Behaviour is verified against the original hand-written SQL by
`tests/test_routing.py`, which runs both over every works_*.duckdb on disk and
requires row-for-row agreement.
"""


from .rules import DERIVATIONS, Rule

__all__ = ["compile_case", "apply", "explain", "DERIVATIONS", "Rule"]


def _literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def compile_case(rules, default):
    """Turn an ordered rule table into one first-match-wins SQL CASE expression."""
    arms = "\n".join(f"        WHEN {r.when} THEN {_literal(r.then)}" for r in rules)
    return f"CASE\n{arms}\n        ELSE {_literal(default)} END"


def apply(con, verbose=False):
    """Derive every routing column on the `works` table of an open DuckDB connection.

    Columns are added and filled in dependency order (see rules.DERIVATIONS): route
    is computed before the three columns that read it.
    """
    for column, rules, default in DERIVATIONS:
        con.execute(f"ALTER TABLE works ADD COLUMN {column} VARCHAR")
        con.execute(f"UPDATE works SET {column} = {compile_case(rules, default)}")
        if verbose:
            print(f"  routed: {column}")


def explain():
    """The policy as a human-readable decision table."""
    out = []
    for column, rules, default in DERIVATIONS:
        out.append(f"\n{column}")
        out.append("=" * len(column))
        for r in rules:
            out.append(f"  {str(r.then):<20} when  {r.when}")
            if r.why:
                out.append(f"  {'':<20}       -- {r.why}")
        out.append(f"  {str(default):<20} otherwise")
    return "\n".join(out)

"""Read the routing policy without running anything.

    python -m routing --explain    the policy as a human-readable decision table
    python -m routing              the SQL it compiles to
"""

import sys

from . import compile_case, explain
from .rules import DERIVATIONS

if "--explain" in sys.argv:
    print(explain())
else:
    for column, rules, default in DERIVATIONS:
        print(f"-- {column}\nUPDATE works SET {column} = {compile_case(rules, default)};\n")

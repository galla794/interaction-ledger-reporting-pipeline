import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOLUTION = ROOT / "solution"

for candidate in (str(SOLUTION), str(ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

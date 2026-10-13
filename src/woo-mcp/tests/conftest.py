"""Import root for woo-mcp tests: the server modules import each other as
top-level names (`from woo_client import ...`), so src/woo-mcp must be on sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

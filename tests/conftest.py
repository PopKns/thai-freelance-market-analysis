import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# make src/ and dashboard/ importable without installing the package
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "dashboard"))

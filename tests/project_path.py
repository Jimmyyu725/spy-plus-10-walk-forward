from pathlib import Path
import sys


PROJECT_DIR = (
    Path(__file__).resolve().parents[1]
    / "qc-workspace"
    / "SPY Plus 10 Walk-Forward"
)
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

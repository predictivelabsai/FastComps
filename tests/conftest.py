import os
import sys
from pathlib import Path

os.environ.setdefault("DB_URL","postgresql://unused:unused@127.0.0.1:1/unused")
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

from pathlib import Path
import sys
BACKEND=Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:sys.path.insert(0,str(BACKEND))
from app.ai.extraction.standalone_hybrid_extractor_v4 import main
if __name__=='__main__':main()

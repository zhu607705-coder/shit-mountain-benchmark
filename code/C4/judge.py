#!/usr/bin/env python3
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "organizer"))
from policy_task_judge import main
if __name__ == "__main__":
    main("C4", HERE)

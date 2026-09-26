#!/usr/bin/env python3
"""One-command entry point; safe to launch from any current working directory."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena.server import main
if __name__=='__main__':
    if '--import-review' in sys.argv[1:]:
        import argparse,json
        from arena.storage import ArenaStore
        parser=argparse.ArgumentParser(description='Trusted organizer import after independent Codex evidence verification')
        parser.add_argument('--import-review',type=Path,required=True)
        args=parser.parse_args()
        print(json.dumps(ArenaStore().import_review(args.import_review),ensure_ascii=False,indent=2))
    else:raise SystemExit(main())

import argparse
from .config import load
from .api import serve
from .runner import main as work


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['serve','worker']);p.add_argument('--config',required=True);a=p.parse_args()
    config=load(a.config)
    (serve if a.command=='serve' else work)(config)

#!/usr/bin/env python3
import argparse
import api
import config
import db
import worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "serve", "worker"])
    args = parser.parse_args()
    settings = config.settings()
    db.initialize(settings["db"])
    if args.command == "serve":
        api.run(settings)
    elif args.command == "worker":
        print(f"worker ready db={settings['db']}", flush=True)
        worker.run(settings)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Watchdesk -- Zabbix alerts, Planner Premium tasks and DeskPro tickets
in one local page.

    python run.py             start the dashboard
    python run.py --check     test all three connections and exit
    python run.py --port 9000 serve on a different port

No pip install. Python 3.9 or newer.
"""

import argparse
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as config_module
from lib.aggregator import Aggregator
import server


def print_check(snapshot):
    print("")
    for key in ("zabbix", "planner", "deskpro"):
        entry = snapshot["sources"][key]
        if entry["ok"] is None:
            mark, note = "  -", "disabled in config.json"
        elif entry["ok"]:
            mark = "  OK"
            note = "%d item(s) in %sms" % (len(entry["items"]),
                                           entry["duration_ms"])
        else:
            mark, note = "FAIL", entry["error"]
        print("  [%s] %-16s %s" % (mark, entry["label"], note))
        detail = (entry.get("meta") or {}).get("detail")
        if entry["ok"] is False and detail:
            print("         %s" % str(detail).replace("\n", "\n         ")[:400])
    print("")


def main():
    parser = argparse.ArgumentParser(description="Watchdesk")
    parser.add_argument("--check", action="store_true",
                        help="test every configured connection, then exit")
    parser.add_argument("--config", default=None, help="path to config.json")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true",
                        help="show sample data, no credentials needed")
    args = parser.parse_args()

    if args.demo:
        cfg = {section: dict(values)
               for section, values in config_module.DEFAULTS.items()}
    else:
        try:
            cfg = config_module.load(args.config)
        except config_module.ConfigError as err:
            print("\n%s\n" % err)
            return 2

    if args.port:
        cfg["server"]["port"] = args.port

    aggregator = Aggregator(cfg)
    if args.demo:
        from lib import demo
        aggregator.snapshot = demo.snapshot
        aggregator.refresh_all = lambda: None
        aggregator.start = lambda: None

    if args.check:
        print("Checking connections...")
        aggregator.refresh_all()
        snapshot = aggregator.snapshot()
        print_check(snapshot)
        failed = any(s["ok"] is False for s in snapshot["sources"].values())
        return 1 if failed else 0

    host = cfg["server"]["host"]
    port = cfg["server"]["port"]
    url = "http://%s:%d/" % (host, port)

    print("\n  Watchdesk%s" % ("  [demo data]" if args.demo else ""))
    print("  %s" % url)
    print("  Refreshing every %ss. Ctrl-C to stop.\n"
          % cfg["server"]["refresh_seconds"])

    aggregator.start()

    try:
        httpd = server.serve(aggregator, host, port)
    except OSError as err:
        print("  Could not bind %s: %s" % (url, err))
        print("  Something else is probably on port %d. "
              "Try: python run.py --port %d\n" % (port, port + 1))
        return 2

    if cfg["server"]["open_browser"] and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
    finally:
        aggregator.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

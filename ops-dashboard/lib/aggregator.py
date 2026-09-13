"""Polls the three sources on a timer and holds the latest result.

The browser never talks to Zabbix, Dataverse or DeskPro directly -- it only
reads this cache. That keeps the credentials server-side (a token in page
JavaScript is a token anyone with the URL can copy) and means ten open tabs
still produce one poll per interval rather than ten.
"""

import threading
import time
import traceback

from lib.fetch import SourceError
from sources import deskpro, planner, zabbix

ADAPTERS = [
    ("zabbix", "Zabbix", zabbix.fetch),
    ("planner", "Planner Premium", planner.fetch),
    ("deskpro", "DeskPro", deskpro.fetch),
]


class Aggregator(object):
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.state = {key: self._blank(label) for key, label, _ in ADAPTERS}
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _blank(label):
        return {"label": label, "ok": None, "enabled": False, "items": [],
                "meta": {}, "error": None, "fetched_at": None,
                "duration_ms": None}

    def snapshot(self):
        with self.lock:
            return {"sources": dict(self.state), "now": time.time()}

    def refresh_one(self, key):
        label, fetcher = next((l, f) for k, l, f in ADAPTERS if k == key)
        cfg = self.config[key]
        entry = self._blank(label)
        entry["enabled"] = bool(cfg.get("enabled"))

        if not entry["enabled"]:
            entry["ok"] = None
            entry["error"] = "Disabled in config.json"
        else:
            started = time.time()
            try:
                result = fetcher(cfg)
                entry["ok"] = True
                entry["items"] = result["items"]
                entry["meta"] = result.get("meta", {})
            except SourceError as err:
                entry["ok"] = False
                entry["error"] = err.message
                if err.detail:
                    entry["meta"] = {"detail": str(err.detail)[:500]}
            except Exception as err:                    # never kill the loop
                entry["ok"] = False
                entry["error"] = "Unexpected error: %s" % err
                entry["meta"] = {"detail": traceback.format_exc()[-800:]}
            entry["duration_ms"] = int((time.time() - started) * 1000)

        entry["fetched_at"] = time.time()
        with self.lock:
            self.state[key] = entry
        return entry

    def refresh_all(self):
        """One thread per source, so a slow or hung source cannot stall the
        other two."""
        threads = [threading.Thread(target=self.refresh_one, args=(key,),
                                    daemon=True)
                   for key, _, _ in ADAPTERS]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)

    def _loop(self):
        interval = max(15, int(self.config["server"]["refresh_seconds"]))
        while not self._stop.is_set():
            self.refresh_all()
            self._stop.wait(interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

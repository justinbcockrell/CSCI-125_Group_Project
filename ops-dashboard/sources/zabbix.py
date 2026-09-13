"""Zabbix -- current unresolved problems.

Two things about the Zabbix API drive the shape of this module:

1. Authentication moved. Up to 6.2 the credential goes in an "auth" field
   inside the JSON body. 6.4 added an "Authorization: Bearer" header and
   deprecated the field. 7.2 REMOVED the field outright. So we probe the
   version once at startup and pick. There is also a well-known Apache
   deployment bug that strips the Authorization header, so on 6.4/7.0 --
   where both mechanisms work -- we fall back to the body field rather
   than failing.

2. Every scalar in a Zabbix response is a JSON *string*. severity is "3",
   acknowledged is "1". Note "0" is truthy in Python, so a plain
   `if problem["acknowledged"]` marks everything acknowledged. Coerce.
"""

import time

from lib.fetch import SourceError, build_opener, request_json

SEVERITY_NAMES = {0: "Not classified", 1: "Information", 2: "Warning",
                  3: "Average", 4: "High", 5: "Disaster"}

# Zabbix's own default UI colours, so the dashboard matches the console.
SEVERITY_COLOURS = {0: "#97AAB3", 1: "#7499FF", 2: "#FFC859",
                    3: "#FFA059", 4: "#E97659", 5: "#E45959"}

PROBLEM_FIELDS = ["eventid", "objectid", "name", "severity", "clock",
                  "r_eventid", "acknowledged", "suppressed", "opdata"]


class ZabbixClient(object):
    def __init__(self, cfg):
        self.url = cfg["url"].rstrip("/")
        self.token = cfg["api_token"] or ""
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.timeout = cfg["timeout"]
        self.opener = build_opener(cfg["ca_bundle"], cfg["verify_tls"])
        self._req_id = 0
        self.version = None
        self.use_bearer = None          # decided by _detect_version()

    # ---- transport -------------------------------------------------

    def _rpc(self, method, params, authenticate=True):
        self._req_id += 1
        payload = {"jsonrpc": "2.0", "method": method,
                   "params": params, "id": self._req_id}
        headers = {"Content-Type": "application/json-rpc"}

        if authenticate:
            if self.use_bearer:
                headers["Authorization"] = "Bearer %s" % self.token
            else:
                # Never send both -- 6.4/7.0 accept either, not the pair.
                payload["auth"] = self.token

        body, _ = request_json(self.opener, self.url, method="POST",
                               headers=headers, body=payload,
                               timeout=self.timeout, source_name="Zabbix")

        # JSON-RPC errors arrive with HTTP 200, so urlopen never raises.
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            raise SourceError(
                "Zabbix API error on %s: %s" % (method, err.get("message", "")),
                err.get("data", ""))
        return body.get("result")

    # ---- setup -----------------------------------------------------

    def _detect_version(self):
        """apiinfo.version must be called with no credentials at all."""
        raw = self._rpc("apiinfo.version", {}, authenticate=False)
        self.version = str(raw)
        try:
            parts = self.version.split(".")
            major, minor = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            major, minor = 6, 0
        self.use_bearer = (major, minor) >= (6, 4)
        return self.version

    def _login(self):
        """Only when no API token was configured."""
        key = "username" if self._at_least(5, 4) else "user"
        result = self._rpc("user.login",
                           {key: self.username, "password": self.password},
                           authenticate=False)
        self.token = result if isinstance(result, str) else result.get("sessionid")

    def _at_least(self, major, minor):
        try:
            parts = self.version.split(".")
            return (int(parts[0]), int(parts[1])) >= (major, minor)
        except (ValueError, IndexError, AttributeError):
            return True

    def connect(self):
        self._detect_version()
        if not self.token:
            self._login()

    def _call_with_fallback(self, method, params):
        """Apache commonly strips the Authorization header, which makes a
        valid token look invalid on 6.4/7.0. Retry once the other way."""
        try:
            return self._rpc(method, params)
        except SourceError:
            can_fall_back = self.use_bearer and not self._at_least(7, 2)
            if not can_fall_back:
                raise
            self.use_bearer = False
            return self._rpc(method, params)

    # ---- data ------------------------------------------------------

    def problems(self, cfg):
        params = {
            "output": PROBLEM_FIELDS,
            "source": 0,            # trigger-generated events
            "object": 0,            # ...so objectid is a triggerid
            "selectTags": "extend",
            "recent": False,        # unresolved only
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": cfg["limit"],
        }
        if not cfg["show_suppressed"]:
            params["suppressed"] = False
        min_sev = int(cfg["min_severity"])
        if min_sev > 0:
            params["severities"] = list(range(min_sev, 6))
        if cfg["host_groups"]:
            params["groupids"] = [str(g) for g in cfg["host_groups"]]

        raw = self._call_with_fallback("problem.get", params) or []
        return self._attach_hosts(raw)

    def _attach_hosts(self, problems):
        """problem.get has no selectHosts. Batch-resolve triggerid -> host."""
        trigger_ids = sorted({p["objectid"] for p in problems if p.get("objectid")})
        hosts = {}
        if trigger_ids:
            triggers = self._call_with_fallback("trigger.get", {
                "output": ["triggerid"],
                "triggerids": trigger_ids,
                "selectHosts": ["hostid", "host", "name"],
                "preservekeys": True,
            }) or {}
            for tid, trigger in triggers.items():
                entries = trigger.get("hosts") or []
                if entries:
                    # "name" is the visible name and falls back to "host".
                    hosts[tid] = ", ".join(h.get("name") or h.get("host")
                                           for h in entries)

        now = int(time.time())
        out = []
        for problem in problems:
            severity = int(problem.get("severity", 0))
            started = int(problem.get("clock", 0))
            out.append({
                "id": problem["eventid"],
                "name": problem.get("name", ""),
                "severity": severity,
                "severity_name": SEVERITY_NAMES.get(severity, "?"),
                "colour": SEVERITY_COLOURS.get(severity, "#97AAB3"),
                "host": hosts.get(problem.get("objectid"), "—"),
                "started": started,
                "age_seconds": max(0, now - started),
                "acknowledged": problem.get("acknowledged") == "1",
                "opdata": problem.get("opdata", ""),
                "tags": [{"tag": t.get("tag"), "value": t.get("value")}
                         for t in (problem.get("tags") or [])],
            })
        # Severity first, then oldest-first within a severity.
        out.sort(key=lambda p: (-p["severity"], p["started"]))
        return out


def fetch(cfg):
    client = ZabbixClient(cfg)
    client.connect()
    items = client.problems(cfg)
    unacked = sum(1 for i in items if not i["acknowledged"])
    return {
        "items": items,
        "meta": {
            "version": client.version,
            "auth": "bearer" if client.use_bearer else "auth-field",
            "unacknowledged": unacked,
            "label": "problem.get · unresolved",
        },
    }

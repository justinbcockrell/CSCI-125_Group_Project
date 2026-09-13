"""DeskPro Horizon -- open tickets.

Three DeskPro-specific things worth knowing:

1. The auth header scheme is the bare word "key", and the credential is
   BOTH halves of the id:code pair:  Authorization: key 12:LONGCODE

2. There is no "open" status. Open means unresolved, which is the union of
   awaiting_agent and awaiting_user. DeskPro's own report builder defines it
   that way.

3. Related objects come back as bare integer ids, with the full objects in a
   separate top-level "linked" block -- and the linked keys are JSON object
   keys, so they are STRINGS while the ids on the ticket are INTEGERS.
   str() the id before looking it up or every agent name comes back empty.
"""

import datetime

from lib.fetch import SourceError, build_opener, qs, request_json

STATUS_LABELS = {
    "awaiting_agent": "Awaiting agent",
    "awaiting_user": "Awaiting user",
    "pending": "Pending",
    "resolved": "Resolved",
    "closed": "Closed",
}

# Statuses that count as needing someone here to act.
ON_US = ("awaiting_agent", "pending")

MAX_PAGE = 200          # DeskPro's ceiling


def _parse_dt(value):
    """DeskPro returns 2025-05-01T08:02:02+0000 -- a basic-format offset with
    no colon, which datetime.fromisoformat() rejects before Python 3.11."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class DeskProClient(object):
    def __init__(self, cfg):
        base = cfg["base_url"].rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        if not base.endswith("/api/v2"):
            base = base + "/api/v2"
        self.base = base
        self.cfg = cfg
        self.opener = build_opener(cfg["ca_bundle"], cfg["verify_tls"])
        self.headers = {
            "Authorization": "key %s" % cfg["api_key"],
            "Accept": "application/json",
        }

    def get(self, path, params=None):
        url = "%s/%s" % (self.base, path.lstrip("/"))
        if params:
            url += "?" + qs(params)
        body, _ = request_json(self.opener, url, headers=self.headers,
                               timeout=self.cfg["timeout"],
                               source_name="DeskPro")
        return body or {}

    def whoami(self):
        """Doubles as the credential smoke test."""
        body = self.get("me")
        data = body.get("data") or {}
        person_id = data.get("person_id")
        if not person_id:
            raise SourceError(
                "DeskPro accepted the request but returned no person_id. "
                "Check that deskpro.api_key is the full \"id:code\" pair.")
        return person_id


def fetch(cfg):
    client = DeskProClient(cfg)

    agent_id = cfg["agent_id"] or 0
    if cfg["only_mine"] and not agent_id:
        agent_id = client.whoami()

    statuses = list(cfg["statuses"] or [])
    params = {
        "order_by": "date_status",       # last status change; no date_updated
        "order_dir": "desc",
        "count": min(int(cfg["limit"]), MAX_PAGE),
        "page": 1,
        "include": "department,person",
        "status": statuses,              # repeated status= params
    }
    if cfg["only_mine"] and agent_id:
        params["agent"] = agent_id
    if cfg["departments"]:
        params["department"] = [str(d) for d in cfg["departments"]]

    body = client.get("tickets", params)
    rows = body.get("data") or []

    linked = body.get("linked") or {}
    people = linked.get("person") or {}
    departments = linked.get("department") or {}

    meta = body.get("meta") or {}
    pagination = meta.get("pagination", meta)   # docs show it flat; live is nested

    now = datetime.datetime.now(datetime.timezone.utc)
    items = []
    for row in rows:
        status = row.get("status") or row.get("ticket_status") or ""
        # The multi-value status syntax is not documented, so filter here too
        # rather than trusting the server honoured it.
        if statuses and status not in statuses:
            continue

        agent = people.get(str(row.get("agent"))) if row.get("agent") else None
        dept = departments.get(str(row.get("department"))) if row.get("department") else None
        updated = _parse_dt(row.get("date_status"))
        age = None
        if updated:
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=datetime.timezone.utc)
            age = int((now - updated).total_seconds())

        items.append({
            "id": row.get("id"),
            "ref": row.get("ref") or str(row.get("id")),
            "subject": row.get("subject") or "(no subject)",
            "status": status,
            "status_label": STATUS_LABELS.get(status, status or "Unknown"),
            "on_us": status in ON_US,
            "urgency": row.get("urgency"),
            "agent": (agent or {}).get("name", ""),
            "department": (dept or {}).get("title", ""),
            "created": row.get("date_created"),
            "updated": row.get("date_status"),
            "age_seconds": age,
            "replies": row.get("count_agent_replies", 0),
        })

    items.sort(key=lambda t: (not t["on_us"], -(t["urgency"] or 0)))

    return {
        "items": items,
        "meta": {
            "total": pagination.get("total", len(items)),
            "awaiting_agent": sum(1 for i in items if i["on_us"]),
            "agent_id": agent_id,
            "scope": "assigned to me" if cfg["only_mine"] else "all agents",
            "label": "tickets · " + ", ".join(
                STATUS_LABELS.get(s, s) for s in statuses),
        },
    }

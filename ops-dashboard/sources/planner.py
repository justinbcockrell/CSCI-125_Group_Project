"""Planner Premium -- tasks scheduled for the current week.

Read this before changing anything here:

Planner Premium tasks are NOT reachable through Microsoft Graph. Microsoft's
own documentation says "Premium plans and tasks aren't available on the
Planner API in Microsoft Graph. Only basic plans may be accessed using this
API." Premium runs on the Project-for-the-web engine, and its data lives in
Dataverse as msdyn_project / msdyn_projecttask rows. So this module talks
OData to Dataverse, not Graph.

That turns out to be good news for an unattended dashboard: Graph's Planner
endpoints reject app-only tokens (the Application-type Tasks.Read.All
permission can be granted and still 403s at runtime), whereas Dataverse
supports client credentials properly. No interactive sign-in needed.
"""

import datetime
import json
import time
import urllib.parse
import urllib.request

from lib.fetch import SourceError, build_opener, qs, request_json

API_VERSION = "v9.2"

TASK_FIELDS = [
    "msdyn_projecttaskid", "msdyn_subject", "msdyn_progress",
    "msdyn_scheduledstart", "msdyn_scheduledend", "msdyn_actualend",
    "msdyn_effort", "msdyn_ismilestone", "msdyn_wbsid",
    "_msdyn_project_value", "_msdyn_projectbucket_value",
]

WEEKDAY_INDEX = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                 "friday": 4, "saturday": 5, "sunday": 6}


def week_bounds(week_starts_on="monday", today=None):
    """(start, end) as UTC datetimes. end is exclusive."""
    today = today or datetime.date.today()
    start_index = WEEKDAY_INDEX.get(str(week_starts_on).lower(), 0)
    delta = (today.weekday() - start_index) % 7
    start = today - datetime.timedelta(days=delta)
    end = start + datetime.timedelta(days=7)
    to_dt = lambda d: datetime.datetime(d.year, d.month, d.day)
    return to_dt(start), to_dt(end)


def _odata_time(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(value):
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


class DataverseClient(object):
    def __init__(self, cfg):
        env = cfg["environment_url"].rstrip("/")
        if not env.startswith("http"):
            env = "https://" + env
        self.environment_url = env
        # Both <org>.crm.dynamics.com and <org>.api.crm.dynamics.com serve the
        # Web API, but the OAuth scope must use the non-"api" form or the
        # token audience will not match and every call 401s.
        self.api_base = "%s/api/data/%s/" % (env, API_VERSION)
        self.scope = env + "/.default"
        self.cfg = cfg
        self.opener = build_opener(cfg["ca_bundle"], cfg["verify_tls"])
        self._token = None
        self._token_expires = 0

    def _access_token(self):
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        url = ("https://login.microsoftonline.com/%s/oauth2/v2.0/token"
               % self.cfg["tenant_id"])
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.cfg["client_id"],
            "client_secret": self.cfg["client_secret"],
            "scope": self.scope,
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=form, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"})
        try:
            with self.opener.open(req, timeout=self.cfg["timeout"]) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as err:
            detail = ""
            read = getattr(err, "read", None)
            if read:
                try:
                    detail = read().decode("utf-8", "replace")[:600]
                except Exception:
                    pass
            raise SourceError(
                "Could not get an Entra token for Planner. Check "
                "planner.tenant_id, client_id and client_secret in "
                "config.json -- an expired client secret is the usual "
                "cause.", detail or str(err))

        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, path, params=None, absolute=False):
        url = path if absolute else self.api_base + path
        if params and not absolute:
            url += "?" + qs(params)
        headers = {
            "Authorization": "Bearer %s" % self._access_token(),
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            # Without this some proxies hand back a cached 304 and the
            # dashboard quietly shows yesterday's tasks.
            "If-None-Match": "null",
            "Prefer": 'odata.include-annotations="OData.Community.Display'
                      '.V1.FormattedValue",odata.maxpagesize=500',
        }
        body, _ = request_json(self.opener, url, headers=headers,
                               timeout=self.cfg["timeout"],
                               source_name="Planner (Dataverse)")
        return body

    def get_all(self, path, params=None, max_pages=10):
        """Follow @odata.nextLink verbatim -- the $skiptoken is opaque and
        re-adding query options to it breaks paging."""
        rows = []
        body = self.get(path, params)
        for _ in range(max_pages):
            rows.extend(body.get("value", []))
            nxt = body.get("@odata.nextLink")
            if not nxt:
                break
            body = self.get(nxt, absolute=True)
        return rows

    def whoami(self):
        return self.get("WhoAmI")


def fetch(cfg):
    client = DataverseClient(cfg)
    start, end = week_bounds(cfg["week_starts_on"])

    plans = {}
    for row in client.get_all("msdyn_projects",
                              {"$select": "msdyn_projectid,msdyn_subject"}):
        plans[row["msdyn_projectid"]] = row.get("msdyn_subject") or "Untitled plan"

    wanted = [p.strip().lower() for p in (cfg["plans"] or []) if p.strip()]
    if wanted:
        plans = {pid: name for pid, name in plans.items()
                 if name.lower() in wanted}
        if not plans:
            raise SourceError(
                "None of the plan names in planner.plans matched. Plans "
                "visible to this app user: "
                + ", ".join(sorted(plans.values())) or "(none)")

    # This week's tasks, plus anything older still unfinished so overdue
    # work stays on screen instead of silently dropping off.
    clauses = ["msdyn_scheduledend lt %s" % _odata_time(end),
               "(msdyn_scheduledend ge %s or msdyn_progress lt 1)"
               % _odata_time(start)]
    if not cfg["include_completed"]:
        clauses.append("msdyn_progress lt 1")

    rows = client.get_all("msdyn_projecttasks", {
        "$select": ",".join(TASK_FIELDS),
        "$filter": " and ".join(clauses),
        "$expand": "msdyn_projectbucket($select=msdyn_name)",
        "$orderby": "msdyn_scheduledend asc",
    })

    today = datetime.date.today()
    items = []
    for row in rows:
        plan_id = row.get("_msdyn_project_value")
        if wanted and plan_id not in plans:
            continue
        due = _parse_dt(row.get("msdyn_scheduledend"))
        bucket = (row.get("msdyn_projectbucket") or {}).get("msdyn_name")
        # msdyn_progress is a 0..1 fraction here, unlike Graph's 0..100 int.
        progress = row.get("msdyn_progress")
        percent = int(round(float(progress) * 100)) if progress is not None else 0
        due_date = due.date() if due else None
        items.append({
            "id": row.get("msdyn_projecttaskid"),
            "title": row.get("msdyn_subject") or "Untitled task",
            "percent": percent,
            "start": row.get("msdyn_scheduledstart"),
            "due": row.get("msdyn_scheduledend"),
            "due_date": due_date.isoformat() if due_date else None,
            "bucket": bucket or "",
            "plan": plans.get(plan_id, ""),
            "milestone": bool(row.get("msdyn_ismilestone")),
            "overdue": bool(due_date and due_date < today and percent < 100),
        })

    per_day = {}
    for item in items:
        if item["due_date"]:
            per_day[item["due_date"]] = per_day.get(item["due_date"], 0) + 1

    return {
        "items": items,
        "meta": {
            "week_start": start.date().isoformat(),
            "week_end": (end - datetime.timedelta(days=1)).date().isoformat(),
            "per_day": per_day,
            "overdue": sum(1 for i in items if i["overdue"]),
            "due_today": sum(1 for i in items
                             if i["due_date"] == today.isoformat()),
            "plans": len(plans),
            "label": "msdyn_projecttasks · Dataverse",
        },
    }

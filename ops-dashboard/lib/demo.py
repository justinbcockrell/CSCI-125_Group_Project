"""Sample data for `python run.py --demo`.

Lets you see the dashboard, and confirm Python and the browser are happy,
before you have any credentials. Nothing here touches the network.
"""

import datetime
import time


def _week():
    today = datetime.date.today()
    start = today - datetime.timedelta(days=today.weekday())
    return start, today


def snapshot():
    now = time.time()
    start, today = _week()
    day = lambda n: (start + datetime.timedelta(days=n)).isoformat()

    alerts = [
        (5, "Disaster", "#E45959", "MySQL is down on srv-db-02", "srv-db-02", 840, False),
        (4, "High", "#E97659", "Free disk space is less than 10% on /var", "srv-app-01", 6120, True),
        (4, "High", "#E97659", "Zabbix agent is not available (for 3m)", "sw-core-01", 7500, False),
        (3, "Average", "#FFA059", "High CPU utilisation (over 90% for 5m)", "srv-web-03", 11880, True),
        (3, "Average", "#FFA059", "Unavailable by ICMP ping", "ups-idf-2", 17400, False),
        (2, "Warning", "#FFC859", "Certificate expires in less than 14 days", "vpn.corp", 108660, True),
    ]
    zabbix_items = [{
        "id": str(9000 + i), "name": name, "severity": sev, "severity_name": label,
        "colour": colour, "host": host, "started": int(now - age),
        "age_seconds": age, "acknowledged": acked, "opdata": "", "tags": [],
    } for i, (sev, label, colour, name, host, age, acked) in enumerate(alerts)]

    tasks = [
        ("Q3 patch window — collect change approvals", 60, "Change Mgmt", 0),
        ("Draft AV refresh bill of materials", 25, "Procurement", 1),
        ("Vendor call — Meraki licence renewal", 0, "Procurement", 1),
        ("Finalise IDF-2 UPS replacement plan", 80, "Infrastructure", today.weekday()),
        ("Onboarding — 3 new hires, account provisioning", 40, "Service Desk", today.weekday()),
        ("Submit budget line for switch stack", 0, "Finance", 3),
        ("Close out Q3 asset audit", 15, "Compliance", 4),
    ]
    planner_items = []
    per_day = {}
    for i, (title, pct, bucket, offset) in enumerate(tasks):
        due = day(offset)
        per_day[due] = per_day.get(due, 0) + 1
        planner_items.append({
            "id": "task-%d" % i, "title": title, "percent": pct,
            "start": None, "due": due + "T17:00:00Z", "due_date": due,
            "bucket": bucket, "plan": "IT Operations", "milestone": False,
            "overdue": due < today.isoformat() and pct < 100,
        })

    tickets = [
        ("4821-9930-1174", "Laptop won't join corp Wi-Fi after imaging", "awaiting_agent", "Awaiting agent", 9, 720),
        ("4821-9930-0851", "VPN drops every ~20 minutes", "awaiting_agent", "Awaiting agent", 7, 18000),
        ("4821-9930-1088", "Shared mailbox access for AP team", "awaiting_agent", "Awaiting agent", 3, 2820),
        ("4821-9930-0973", "Printer on 3rd floor jams on duplex", "awaiting_user", "Awaiting user", 2, 10800),
        ("4821-9930-0774", "New starter 22 Sep — full kit build", "awaiting_user", "Awaiting user", 1, 86400),
    ]
    deskpro_items = [{
        "id": 4800 + i, "ref": ref, "subject": subject, "status": status,
        "status_label": label, "on_us": status == "awaiting_agent",
        "urgency": urgency, "agent": "You", "department": "IT Support",
        "created": None, "updated": None, "age_seconds": age, "replies": 0,
    } for i, (ref, subject, status, label, urgency, age) in enumerate(tickets)]

    def entry(label, items, meta):
        return {"label": label, "ok": True, "enabled": True, "items": items,
                "meta": meta, "error": None, "fetched_at": now, "duration_ms": 0}

    return {"now": now, "demo": True, "sources": {
        "zabbix": entry("Zabbix", zabbix_items, {
            "version": "7.0.0 (demo)", "auth": "bearer",
            "unacknowledged": sum(1 for a in zabbix_items if not a["acknowledged"]),
            "label": "problem.get · unresolved"}),
        "planner": entry("Planner Premium", planner_items, {
            "week_start": start.isoformat(),
            "week_end": (start + datetime.timedelta(days=6)).isoformat(),
            "per_day": per_day,
            "overdue": sum(1 for t in planner_items if t["overdue"]),
            "due_today": per_day.get(today.isoformat(), 0),
            "plans": 1, "label": "msdyn_projecttasks · Dataverse (demo)"}),
        "deskpro": entry("DeskPro", deskpro_items, {
            "total": len(deskpro_items),
            "awaiting_agent": sum(1 for t in deskpro_items if t["on_us"]),
            "agent_id": 61, "scope": "assigned to me (demo)",
            "label": "tickets · demo"}),
    }}

"""Loads config.json and fills in defaults."""

import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(HERE, "config.json")
EXAMPLE_PATH = os.path.join(HERE, "config.example.json")

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8787, "refresh_seconds": 60,
               "open_browser": True},
    "zabbix": {"enabled": False, "url": "", "api_token": "",
               "username": "", "password": "", "min_severity": 2,
               "host_groups": [], "limit": 200, "show_suppressed": False,
               "ca_bundle": "", "verify_tls": True, "timeout": 20},
    "planner": {"enabled": False, "tenant_id": "", "client_id": "",
                "client_secret": "", "environment_url": "", "plans": [],
                "week_starts_on": "monday", "include_completed": False,
                "ca_bundle": "", "verify_tls": True, "timeout": 30},
    "deskpro": {"enabled": False, "base_url": "", "api_key": "",
                "only_mine": True, "agent_id": 0, "departments": [],
                "statuses": ["awaiting_agent", "awaiting_user"],
                "limit": 50, "ca_bundle": "", "verify_tls": True,
                "timeout": 20},
}


class ConfigError(Exception):
    pass


def _merge(defaults, override):
    out = dict(defaults)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path=None):
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        raise ConfigError(
            "No config.json found at %s\n\n"
            "Copy the example and fill it in:\n"
            "    cp config.example.json config.json\n\n"
            "Then follow README.md -- it walks through one section at a time."
            % path)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except ValueError as err:
        raise ConfigError(
            "config.json is not valid JSON: %s\n\n"
            "Common causes: a trailing comma after the last item, or a "
            "missing quote. JSON does not allow comments." % err)

    cfg = {section: _merge(DEFAULTS[section], raw.get(section))
           for section in DEFAULTS}

    problems = []
    if cfg["zabbix"]["enabled"]:
        if not cfg["zabbix"]["url"]:
            problems.append("zabbix.url is empty")
        if not cfg["zabbix"]["api_token"] and not cfg["zabbix"]["username"]:
            problems.append("zabbix needs either api_token or username+password")
    if cfg["planner"]["enabled"]:
        for field in ("tenant_id", "client_id", "client_secret", "environment_url"):
            if not cfg["planner"][field]:
                problems.append("planner.%s is empty" % field)
    if cfg["deskpro"]["enabled"]:
        if not cfg["deskpro"]["base_url"]:
            problems.append("deskpro.base_url is empty")
        if ":" not in (cfg["deskpro"]["api_key"] or ""):
            problems.append("deskpro.api_key must look like \"12:LONGCODE\" "
                            "-- both halves, separated by a colon")

    if not any(cfg[s]["enabled"] for s in ("zabbix", "planner", "deskpro")):
        problems.append("every source has \"enabled\": false -- "
                        "turn on at least one")

    if problems:
        raise ConfigError("config.json needs attention:\n  - "
                          + "\n  - ".join(problems))
    return cfg

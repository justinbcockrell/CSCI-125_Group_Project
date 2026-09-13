# Watchdesk

One local page showing **Zabbix alerts**, **Planner Premium tasks for this week**,
and **DeskPro tickets**, side by side.

- **No `pip install`.** Python standard library only, so it runs on a locked-down
  work machine. Python 3.9 or newer.
- **One config file.** All three hooks live in `config.json`.
- **Credentials never reach the browser.** Python does the API calls; the page
  only reads a local cache.

---

## 1. See it working first (30 seconds, no credentials)

```
python run.py --demo
```

Your browser opens `http://127.0.0.1:8787/` with sample data. If that works,
Python and your browser are fine and every later problem is a credentials
problem. Press `Ctrl-C` to stop.

## 2. Make your config file

```
cp config.example.json config.json
```

`config.json` is gitignored — it holds real secrets, so never commit it.

Now fill in **one source at a time**. After each one:

```
python run.py --check
```

That tests every connection and prints OK or the exact failure. Get one source
to OK before starting the next. Set `"enabled": false` on the ones you have not
set up yet.

## 3. Start it

```
python run.py
```

Leave it running. It refreshes every 60 seconds (`server.refresh_seconds`).

---

# Setting up each hook

## Zabbix

**What you need:** your Zabbix URL and an API token.

1. Log into Zabbix as an admin.
2. **Users → User roles → Create user role.** Name it `Dashboard read-only`.
   Set **User type** to `User`. Under **Access to API**, leave it Enabled, set
   the method list to **Allow list**, and add exactly:
   `apiinfo.version`, `problem.get`, `trigger.get`.
   *(On Zabbix 6.2 and older this lives under Administration → User roles.)*
3. **Users → Users → Create user.** Call it `api-dashboard`, give it a long
   random password, and on the **Permissions** tab set Role to the role above.
4. On the **User groups** tab, put it in a group with **Read** permission on the
   host groups you want to see.
   **Do not skip this.** The role controls which API methods work; host group
   permissions control which hosts' data comes back. Miss it and you get an
   empty alert list with no error.
5. **Users → API tokens → Create API token.** Name it, set **User** to
   `api-dashboard`, click Add.
6. **Copy the token now.** Zabbix shows it exactly once and there is no way to
   see it again — you would have to delete and recreate it.

```json
"zabbix": {
  "enabled": true,
  "url": "https://zabbix.yourcompany.local/api_jsonrpc.php",
  "api_token": "the token you just copied",
  "min_severity": 2,
  "host_groups": []
}
```

- `url` — must end in `/api_jsonrpc.php`. Some installs serve it at
  `/zabbix/api_jsonrpc.php`; if you get a 404, try adding `/zabbix`.
- `min_severity` — `0` everything, `2` Warning and above (default), `4` only
  High and Disaster.
- `host_groups` — leave `[]` for everything, or put host group IDs in to narrow
  it. The ID is in the URL when you edit a host group in Zabbix.

No token available? Put `username` and `password` in instead and leave
`api_token` empty. A token is better — it survives restarts and is not blocked
by MFA.

## Planner Premium

**Read this first.** Planner Premium is **not** on Microsoft Graph. Microsoft's
own docs say *"Premium plans and tasks aren't available on the Planner API in
Microsoft Graph."* Premium runs on the Project-for-the-web engine and its data
lives in **Dataverse**. That is what this connects to.

This is the fiddliest of the three because it has **two halves** — an Entra app
registration, and a Dataverse application user. Doing only the first half is the
single most common failure: you get a perfectly valid token and then 401 on
every request.

### Part A — Entra ID (gets you three values)

1. Go to <https://entra.microsoft.com> → **Applications → App registrations →
   New registration**.
2. Name it `watchdesk`, choose **Single tenant**, leave Redirect URI blank,
   click **Register**.
3. On the **Overview** page copy:
   - **Application (client) ID** → `client_id`
   - **Directory (tenant) ID** → `tenant_id`
4. **Certificates & secrets → Client secrets → New client secret.** Set an
   expiry and click Add.
5. **Copy the `Value` column immediately** (not `Secret ID`) → `client_secret`.
   It is shown once.
   **Put the expiry date in your calendar.** A silently expired secret is the
   usual reason a working dashboard stops working months later.

You do **not** need to add any API permission here. Authorisation happens in
Part B.

### Part B — Dataverse (this is the part people miss)

6. Go to <https://admin.powerplatform.microsoft.com> → **Manage → Environments**.
7. Open the environment holding your Planner data — normally the one marked
   **(default)**. Copy its **Environment URL** → `environment_url`
   (looks like `https://orgXXXXXXXX.crm.dynamics.com`).
8. In that environment: **Settings → Users + permissions → Application users →
   + New app user**.
9. Click **+ Add an app**, pick `watchdesk`, choose a business unit.
10. Under **Security roles**, give it a role with **Read** on `msdyn_project`,
    `msdyn_projecttask` and `msdyn_projectbucket`.
    System Administrator works instantly and is the common shortcut, but it
    grants full tenant-wide data control to a secret sitting in a config file on
    your laptop. Make a custom read-only role instead
    (**Settings → Users + permissions → Security roles → New role**, then on the
    **Custom Entities** tab click the Read column for those three tables until
    the circle is a full green disc).
11. Click **Create**.

```json
"planner": {
  "enabled": true,
  "tenant_id": "from step 3",
  "client_id": "from step 3",
  "client_secret": "from step 5",
  "environment_url": "https://orgXXXXXXXX.crm.dynamics.com",
  "plans": [],
  "week_starts_on": "monday"
}
```

- `plans` — `[]` shows every plan the app user can see. To narrow it, list plan
  names exactly as they appear in Planner: `["IT Operations", "Q4 Rollout"]`.
- `week_starts_on` — `"monday"` or `"sunday"`.

Tasks due earlier but not finished stay on screen, marked overdue, rather than
disappearing.

**Known limitation:** Planner Premium **custom fields** are stored as a binary
blob rather than queryable columns, so they cannot be read through this API at
all. If you depend on a custom field, tell me and we will find another route.

## DeskPro

**What you need:** your helpdesk URL and an API key.

1. Log into DeskPro as an admin → **Apps & Integrations → API Keys**
   (older builds: **Admin → Apps → API Keys**).
2. Create a new key, name it `watchdesk`.
3. Set the key's **agent** — the key inherits that agent's permissions and
   nothing more. Best practice is a dedicated agent account rather than a real
   person's, so the dashboard does not break when someone changes role or
   leaves. Do **not** mark the key superuser.
4. On the **Tags** tab replace the default `*` with a read-only whitelist:
   ```
   tickets.tickets.list, tickets.tickets.get
   ```
   This is what actually enforces read-only. Agent permissions alone will not
   stop writes.
5. Save and copy the key. It is the pair `id:code`, for example
   `12:BZWWGQ58QDX8H5B4W4RAJ978Q`. **Both halves, colon included** — passing
   only the long half is the usual mistake.

```json
"deskpro": {
  "enabled": true,
  "base_url": "https://yourcompany.deskpro.com",
  "api_key": "12:BZWWGQ58QDX8H5B4W4RAJ978Q",
  "only_mine": true,
  "statuses": ["awaiting_agent", "awaiting_user"]
}
```

- `base_url` — just the helpdesk address. `/api/v2` is added for you.
- `only_mine` — `true` shows tickets assigned to the key's agent. It looks up
  the agent id itself. `false` shows everything that agent can see.
- `statuses` — DeskPro has **no "open" status**. Open means unresolved, which is
  `awaiting_agent` + `awaiting_user`. Other valid values: `pending`, `resolved`,
  `closed`.

---

## Settings that apply to any source

| Setting | What it does |
|---|---|
| `ca_bundle` | Path to a `.pem` file for an internal certificate authority. Needed when an internal server uses a company-issued certificate. |
| `verify_tls` | Leave `true`. Setting `false` turns off certificate checking entirely and hands your API token to anyone able to intercept the connection. Use `ca_bundle` instead. |
| `timeout` | Seconds before giving up on a request. |
| `server.refresh_seconds` | How often to poll. 60 is sensible; below 30 is rude to Zabbix. |
| `server.port` | Change if something else already uses 8787. |

---

## When something breaks

| What you see | What it means |
|---|---|
| `No config.json found` | Run `cp config.example.json config.json`. |
| `config.json is not valid JSON` | Usually a trailing comma after the last item. JSON allows no comments. |
| Zabbix: `Connection refused` | Wrong URL or host unreachable from this machine. |
| Zabbix: `rejected the credentials` | Token wrong or expired. On Zabbix 6.4+ behind Apache, the server may be stripping the auth header — the admin needs `SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1` in the Apache config. |
| Zabbix connects but shows nothing | Step 4 — the user has no Read permission on any host group. |
| Planner: `Could not get an Entra token` | `tenant_id` / `client_id` / `client_secret` wrong, or the secret expired. |
| Planner: token works but `401` | Part B was not done — no application user in that environment. |
| Planner: works but zero tasks | Application user created in the **wrong environment**. Empty-with-no-error is the tell. |
| DeskPro: `rejected the credentials` | `api_key` needs both halves: `id:code`. |
| DeskPro: connects, no tickets | The key's agent has no access to those departments, or `only_mine` is true and nothing is assigned to them. |
| `TLS verification failed` | Internal certificate authority — set `ca_bundle`. |
| Any `429` | Polling too fast. Raise `refresh_seconds`. |

`python run.py --check` prints the precise error for every source, and the
dashboard shows the same message in the failing column rather than going blank.

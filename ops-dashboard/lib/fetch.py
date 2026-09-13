"""HTTP helpers shared by every source adapter.

Standard library only -- no pip install. Everything a workplace deployment
tends to need (internal CA bundles, proxy bypass, timeouts) is a config
option rather than an environment variable, because environment variables
are exactly what a locked-down work machine makes awkward to set.
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request


class SourceError(Exception):
    """A source could not be reached or answered with an error.

    Carries a message safe to show in the dashboard. Never put a credential
    in one of these -- they are rendered in the browser.
    """

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail


def build_opener(ca_bundle=None, verify_tls=True, use_env_proxy=False):
    """An opener configured for talking to internal services.

    ca_bundle     -- path to a PEM file for an internal/private CA.
    verify_tls    -- False disables certificate verification entirely.
                     Only ever set from an explicit config opt-in: an API
                     token is a bearer credential, and an unverified TLS
                     session hands it to anyone in the middle.
    use_env_proxy -- urllib picks up HTTP_PROXY/HTTPS_PROXY by default,
                     which routes internal hostnames through a corporate
                     proxy that usually cannot reach them. Off by default.
    """
    if verify_tls:
        ctx = ssl.create_default_context(cafile=ca_bundle or None)
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False          # must precede verify_mode
        ctx.verify_mode = ssl.CERT_NONE

    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    if not use_env_proxy:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def request_json(opener, url, method="GET", headers=None, body=None,
                 timeout=20, source_name="source"):
    """One JSON request. Returns (parsed_body, response_headers).

    Raises SourceError with a message a human can act on -- the point of
    catching everything here is that a dashboard panel should say what is
    wrong, not render a stack trace.
    """
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")   # urlopen needs bytes
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            resp_headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:600]
        except Exception:
            pass
        if e.code in (401, 403):
            raise SourceError(
                "%s rejected the credentials (HTTP %d). Check the token in "
                "config.json and the permissions on the account it belongs to."
                % (source_name, e.code), detail)
        if e.code == 429:
            raise SourceError("%s is rate limiting us (HTTP 429). Increase "
                              "refresh_seconds." % source_name, detail)
        if e.code == 404:
            raise SourceError(
                "%s returned 404 for %s. The base URL in config.json is "
                "probably wrong." % (source_name, url), detail)
        raise SourceError("%s returned HTTP %d." % (source_name, e.code), detail)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise SourceError(
                "TLS verification failed for %s. If this is an internal "
                "server with a private CA, set %s.ca_bundle in config.json to "
                "the CA PEM file." % (source_name, source_name.lower()),
                str(reason))
        raise SourceError("Could not reach %s: %s" % (source_name, reason))
    except TimeoutError:
        raise SourceError("%s timed out after %ss." % (source_name, timeout))

    if not raw:
        return None, resp_headers

    try:
        return json.loads(raw.decode("utf-8")), resp_headers
    except (ValueError, UnicodeDecodeError):
        head = raw[:200].decode("utf-8", "replace")
        raise SourceError(
            "%s returned something that is not JSON. Check the URL path in "
            "config.json." % source_name, head)


def qs(params):
    """Query string from a dict, dropping empty values, repeating lists."""
    pairs = []
    for key, value in params.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((key, str(v)) for v in value)
        else:
            pairs.append((key, str(value)))
    return urllib.parse.urlencode(pairs)

"""The one HTTP door of the generation adapters (urllib, no SDK). Tests replace DEFAULT with a fake; nothing else opens a socket.

    Http().call(method, url, headers=None, json=None, data=None, timeout=120) -> Response(status, headers, body)
    Response.json()
Retries 429 / 5xx and connection errors a few times (a POST, which may start a paid task, only on 429 / 503: never billed twice); other HTTP errors raise GenHTTPError with the status and a short body (never the
request headers, so a key never ends up in an error message)."""
import json as _json
import time
import urllib.error
import urllib.request

UA = "gameanything-gen"


def _message(detail) -> str:
    """The provider's own words from a JSON error body ({error: {message}} Google / OpenAI / OpenRouter, {message} Meshy, {detail} fal)."""
    s = str(detail or "")
    try: d = _json.loads(s)
    except ValueError: return s
    for e in (d.get("error"), d) if isinstance(d, dict) else ():
        if isinstance(e, dict):
            for k in ("message", "detail"):
                if isinstance(e.get(k), str) and e[k].strip():
                    st = e.get("status") or e.get("code") or ""
                    return f"{e[k].strip()}" + (f" ({st})" if isinstance(st, str) and st else "")
        elif isinstance(e, str) and e.strip(): return e.strip()
    return s


class GenHTTPError(RuntimeError):
    def __init__(self, status, url, detail=""):
        self.status = status; self.url = url.split("?")[0]; self.detail = _message(detail)[:600]
        super().__init__(f"HTTP {status} from {self.url}: {self.detail}")


class Response:
    def __init__(self, status, headers, body: bytes):
        self.status = status; self.headers = dict(headers or {}); self.body = body or b""

    def json(self):
        return _json.loads(self.body) if self.body else {}


class Http:
    retries = 3
    backoff = 2.0

    def call(self, method, url, headers=None, json=None, data=None, timeout=120, retries=None) -> Response:
        h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
        if json is not None: data = _json.dumps(json).encode(); h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        retries = self.retries if retries is None else retries
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return Response(r.status, dict(r.headers), r.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code in ((429, 503) if method == "POST" else (429, 500, 502, 503, 504)) and attempt < retries: time.sleep(self.backoff * (attempt + 1)); continue
                raise GenHTTPError(e.code, url, detail) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < retries and method != "POST": time.sleep(self.backoff * (attempt + 1)); continue
                raise GenHTTPError(0, url, getattr(e, "reason", e)) from None

    def get_bytes(self, url, timeout=600) -> bytes:
        return self.call("GET", url, headers={"Accept": "*/*"}, timeout=timeout).body


DEFAULT = Http()


def default() -> Http:
    return DEFAULT

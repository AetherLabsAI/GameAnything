"""Microsoft account sign-in for downloading Minecraft: Java Edition, with the device-code flow. Stdlib only.

The user signs in on THEIR OWN device: the sandbox shows a short code, they open https://www.microsoft.com/link, type the code and sign
in there. Nothing is ever typed into the sandbox, and no password passes through GameAnything. The chain is the official launcher's:

    login.live.com device code (the Minecraft launcher's public client id)  ->  Xbox Live user token  ->  XSTS for api.minecraftservices.com
    ->  Minecraft access token  ->  entitlements: does this account own Minecraft: Java Edition?

The account is only used to check that the user owns the game before its files are downloaded (mcdownload). Playing in the sandbox is
offline (a local player name, single player), so no game token is kept. What is kept, in the sandbox's own volume, mode 0600:

    <dir>/microsoft.json   the Microsoft refresh token (lets a recreated sandbox check again without a new sign-in; about 90 days)
    <dir>/minecraft.json   the result: owns_java, the entitlement names, when it was checked (no tokens)

Tokens are never printed or logged; `status()` reports only ages and yes/no.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "00000000402b5328"                     # the Minecraft launcher's public Microsoft (live.com) client id
SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
DEVICE_URL = "https://login.live.com/oauth20_connect.srf"
TOKEN_URL = "https://login.live.com/oauth20_token.srf"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/mcstore"
PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
JAVA_ITEMS = ("game_minecraft", "product_minecraft")
UA = "GameAnything/1 (ga-mc; +https://github.com/AetherLabsAI/GameAnything)"
XSTS_ERRORS = {2148916233: "this Microsoft account has no Xbox profile yet: sign in once at https://www.minecraft.net and create one",
               2148916235: "Xbox Live is not available in this account's country",
               2148916236: "this account needs adult verification (South Korea)", 2148916237: "this account needs adult verification (South Korea)",
               2148916238: "this is a child account: an adult has to add it to a Microsoft family first"}


class AuthError(Exception):
    pass


def http(method, url, data=None, form=False, headers=None, timeout=30):
    """-> (status, parsed JSON or {}). Errors with a JSON body come back as (status, body), not as exceptions."""
    h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    body = None
    if data is not None:
        body = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: raw, st = r.read(), r.status
    except urllib.error.HTTPError as e: raw, st = e.read(), e.code
    try: return st, json.loads(raw or b"{}")
    except ValueError: return st, {"_text": raw[:200].decode(errors="replace")}


def _write_private(p: Path, d: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    try: os.chmod(p.parent, 0o700)
    except OSError: pass
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(d, f, indent=1)
    os.replace(tmp, p)


def device_code(req=http) -> dict:
    """-> {user_code, verification_uri, expires_in, interval, device_code}. Only user_code + the URL are for the user."""
    st, d = req("POST", DEVICE_URL, {"client_id": CLIENT_ID, "scope": SCOPE, "response_type": "device_code"}, form=True)
    if st != 200 or "user_code" not in d: raise AuthError(f"device code request failed ({st}): {d.get('error_description') or d.get('error')}")
    return d


def poll(dc: dict, req=http, sleep=time.sleep, now=time.time) -> dict:
    """Wait for the user to finish on microsoft.com/link -> the Microsoft token response. Raises AuthError on expiry / refusal."""
    interval = int(dc.get("interval") or 5); end = now() + int(dc.get("expires_in") or 900)
    while now() < end:
        sleep(interval)
        st, d = req("POST", TOKEN_URL, {"client_id": CLIENT_ID, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                        "device_code": dc["device_code"]}, form=True)
        if st == 200 and d.get("access_token"): return d
        err = d.get("error")
        if err == "authorization_pending": continue
        if err == "slow_down": interval += 5; continue
        if err in ("expired_token", "expired"): raise AuthError("expired")
        raise AuthError(f"sign-in refused: {err or st}")
    raise AuthError("expired")


def refresh(refresh_token: str, req=http) -> dict:
    st, d = req("POST", TOKEN_URL, {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token, "scope": SCOPE}, form=True)
    if st != 200 or not d.get("access_token"): raise AuthError(f"refresh failed ({st}): {d.get('error')}")
    return d


def minecraft_token(ms_access: str, req=http) -> str:
    """Microsoft access token -> Minecraft services access token (Xbox Live user token -> XSTS -> login_with_xbox)."""
    xbl = None
    for ticket in (ms_access, "d=" + ms_access, "t=" + ms_access):        # live.com tokens go as they are; MSAL ones need "d="
        st, d = req("POST", XBL_URL, {"Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": ticket},
                                     "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"})
        if st == 200 and d.get("Token"): xbl = d; break
    if not xbl: raise AuthError(f"Xbox Live sign-in failed ({st})")
    uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
    st, d = req("POST", XSTS_URL, {"Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
                                  "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"})
    if st != 200: raise AuthError(XSTS_ERRORS.get(d.get("XErr"), f"Xbox XSTS failed ({st}, {d.get('XErr')})"))
    st, m = req("POST", MC_LOGIN_URL, {"identityToken": f"XBL3.0 x={uhs};{d['Token']}"})
    if st != 200 or not m.get("access_token"): raise AuthError(f"Minecraft services sign-in failed ({st}): {m.get('errorMessage') or m.get('error')}")
    return m["access_token"]


def ownership(mc_token: str, req=http) -> dict:
    """-> {owns_java, items, has_profile}: the account's Minecraft entitlements (Game Pass included) and whether a Java profile exists."""
    auth = {"Authorization": f"Bearer {mc_token}"}
    st, e = req("GET", ENTITLEMENTS_URL, headers=auth)
    if st != 200: raise AuthError(f"entitlements check failed ({st})")
    items = sorted({i.get("name", "") for i in e.get("items") or []})
    st, _p = req("GET", PROFILE_URL, headers=auth)
    return {"owns_java": any(n in items for n in JAVA_ITEMS), "items": items, "has_profile": st == 200}


def check_and_save(dir_: Path, ms: dict, req=http, now=time.time) -> dict:
    """Microsoft token response -> ownership; saves the refresh token (0600) and the result (no tokens). -> the result."""
    own = ownership(minecraft_token(ms["access_token"], req), req)
    if ms.get("refresh_token"):
        _write_private(Path(dir_) / "microsoft.json", {"client_id": CLIENT_ID, "refresh_token": ms["refresh_token"], "obtained_at": int(now())})
    res = {**own, "checked_at": int(now()), "method": "microsoft-device-code"}
    _write_private(Path(dir_) / "minecraft.json", res)
    return res


def recheck(dir_: Path, req=http, now=time.time) -> dict:
    """A new ownership check from the saved refresh token (no sign-in). Raises AuthError when it has expired: sign in again."""
    p = Path(dir_) / "microsoft.json"
    if not p.is_file(): raise AuthError("not signed in")
    return check_and_save(dir_, refresh(json.loads(p.read_text(encoding="utf-8"))["refresh_token"], req), req, now)


def status(dir_: Path, now=time.time) -> dict:
    """What is saved, without network and without any token: signed_in, owns_java, the ages in hours."""
    d = Path(dir_); out = {"signed_in": (d / "microsoft.json").is_file(), "owns_java": False}
    if out["signed_in"]:
        out["refresh_token_age_h"] = round((now() - json.loads((d / "microsoft.json").read_text(encoding="utf-8")).get("obtained_at", 0)) / 3600, 1)
    if (d / "minecraft.json").is_file():
        r = json.loads((d / "minecraft.json").read_text(encoding="utf-8"))
        out.update(owns_java=bool(r.get("owns_java")), checked_age_h=round((now() - r.get("checked_at", 0)) / 3600, 1), items=r.get("items", []))
    return out


def logout(dir_: Path):
    for n in ("microsoft.json", "minecraft.json"):
        try: (Path(dir_) / n).unlink()
        except FileNotFoundError: pass

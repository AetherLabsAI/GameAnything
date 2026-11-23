"""Ed25519 signatures (RFC 8032), pure Python: the standard library has no public-key signatures and GameAnything adds no dependency for
this. Used by decisions.py: the UI / hub server signs her decisions with a private key that lives only in its memory; everything else
(`gameanything flow check`, agentd, the pages) verifies them with public keys only, so verifying never needs a secret.

    keypair() -> (secret32, public32)     sign(secret32, msg) -> sig64     verify(public32, msg, sig64) -> bool
Not constant time (the private key never leaves the server process, which signs a few lines a day); verification is ~2 ms.
"""
import hashlib
import os

_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _H(m: bytes) -> bytes: return hashlib.sha512(m).digest()


def _xrecover(y: int, sign: int):
    xx = (y * y - 1) * pow(_d * y * y + 1, _p - 2, _p) % _p
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p: x = x * _I % _p
    if (x * x - xx) % _p: return None
    if x == 0 and sign: return None
    if x & 1 != sign: x = _p - x
    return x


_By = 4 * pow(5, _p - 2, _p) % _p
_B = (_xrecover(_By, 0), _By, 1, _xrecover(_By, 0) * _By % _p)
_O = (0, 1, 1, 0)


def _add(P, Q):
    x1, y1, z1, t1 = P; x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % _p; b = (y1 + x1) * (y2 + x2) % _p
    c = 2 * t1 * t2 * _d % _p; dd = 2 * z1 * z2 % _p
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _p, g * h % _p, f * g % _p, e * h % _p)


def _mul(s: int, P):
    Q = _O
    while s:
        if s & 1: Q = _add(Q, P)
        P = _add(P, P); s >>= 1
    return Q


def _enc(P) -> bytes:
    x, y, z, _ = P; zi = pow(z, _p - 2, _p); x, y = x * zi % _p, y * zi % _p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _dec(b: bytes):
    if len(b) != 32: return None
    n = int.from_bytes(b, "little"); y = n & ((1 << 255) - 1)
    if y >= _p: return None
    x = _xrecover(y, n >> 255)
    return None if x is None else (x, y, 1, x * y % _p)


def _eq(P, Q) -> bool:
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _expand(secret: bytes):
    h = _H(secret); a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8; a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    return _enc(_mul(_expand(secret)[0], _B))


def keypair():
    s = os.urandom(32); return s, public_key(s)


def sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(secret); A = _enc(_mul(a, _B))
    r = int.from_bytes(_H(prefix + msg), "little") % _L
    R = _enc(_mul(r, _B))
    k = int.from_bytes(_H(R + A + msg), "little") % _L
    return R + ((r + k * a) % _L).to_bytes(32, "little")


def verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    try:
        if len(sig) != 64 or len(public) != 32: return False
        A = _dec(public); R = _dec(sig[:32]); s = int.from_bytes(sig[32:], "little")
        if A is None or R is None or s >= _L: return False
        k = int.from_bytes(_H(sig[:32] + public + msg), "little") % _L
        return _eq(_mul(s, _B), _add(R, _mul(k, A)))
    except (TypeError, ValueError):
        return False

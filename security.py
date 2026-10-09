"""Small central HTTP guards. Browser secrecy is not an access control."""
import os
import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit, unquote

_LOCAL_SECRET = secrets.token_hex(32)


def production():
    return os.environ.get('RADAR_ENV', '').lower() == 'production'


def session_secret():
    value = os.environ.get('RADAR_SESSION_SECRET', '').strip()
    if production() and len(value) < 32:
        raise RuntimeError('Produção exige RADAR_SESSION_SECRET aleatório de pelo menos 32 caracteres.')
    return value or _LOCAL_SECRET


def safe_static_path(path):
    parts = unquote(path).replace('\\', '/').split('/')
    if any(p.startswith('.') for p in parts if p): return False
    extension = parts[-1].rsplit('.', 1)[-1].lower()
    return extension in {'html', 'css', 'js', 'svg', 'png', 'jpg', 'jpeg', 'webp', 'ico', 'woff2', 'ttf', 'webmanifest', 'txt'}


def bootstrap_credential_stamp():
    """Resetting bootstrap credentials invalidates sessions even with a reused key."""
    credentials = os.environ.get('RADAR_ADMIN_USER', '').strip() + '\0' + os.environ.get('RADAR_ADMIN_PASSWORD', '')
    return hmac.new(session_secret().encode(), credentials.encode(), hashlib.sha256).hexdigest()


def csv_cell(value):
    """Neutralize spreadsheet commands on export only; keep numeric types intact."""
    if not isinstance(value, str): return value
    probe = value.lstrip(' \t\r\n\v\f\ufeff')
    if value.startswith(('\t', '\r', '\n')) or probe.startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def same_origin(headers):
    # Modern browsers send Origin or Sec-Fetch-Site on cross-origin writes.
    if headers.get('Sec-Fetch-Site', '').lower() == 'cross-site': return False
    origin = headers.get('Origin')
    if not origin: return True  # Non-browser clients still need normal authentication.
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {'http', 'https'} and parsed.netloc.lower() == headers.get('Host', '').lower()
    except ValueError: return False


class AttemptLimiter:
    def __init__(self, maximum=8, window=900, capacity=2000):
        self.maximum, self.window, self.capacity = maximum, window, capacity
        self.lock = threading.Lock(); self.entries = OrderedDict()

    def allowed(self, key):
        now = time.monotonic()
        with self.lock:
            count, start = self.entries.get(key, (0, now))
            if now-start >= self.window: count, start = 0, now
            self.entries[key] = (count+1, start); self.entries.move_to_end(key)
            while len(self.entries) > self.capacity: self.entries.popitem(last=False)
            return count < self.maximum


    def clear(self,key):
        with self.lock: self.entries.pop(key,None)

LOGIN_LIMITER = AttemptLimiter()
# A generous connection budget bounds random-name spray without the eight-guess
# tunnel-wide lockout. The strict budget is canonical-account scoped.
LOGIN_EDGE_LIMITER = AttemptLimiter(maximum=1000, window=900, capacity=2000)

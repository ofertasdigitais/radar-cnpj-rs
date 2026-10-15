"""Small central HTTP guards. Browser secrecy is not an access control."""
import os
import hashlib
import hmac
import secrets
import threading
import time
import socket
from http.server import ThreadingHTTPServer
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


def allowed_host(header, public_url_file=None):
    """Only loopback and explicitly configured/published origin hostnames."""
    try:
        if not header or len(header)>300 or any(c.isspace() for c in header): return False
        parsed = urlsplit('http://' + header)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment: return False
        parsed.port  # validate the port, including range
        name = (parsed.hostname or '').lower().rstrip('.')
        allowed = {'127.0.0.1', 'localhost', '::1'}
        allowed.update(x.strip().lower().rstrip('.') for x in os.environ.get('RADAR_ALLOWED_HOSTS','').split(',') if x.strip())
        configured = urlsplit(os.environ.get('RADAR_PUBLIC_URL',''))
        if configured.scheme in ('http','https') and configured.hostname and not configured.username and not configured.password:
            allowed.add(configured.hostname.lower().rstrip('.'))
        if public_url_file and public_url_file.is_file():
            public = urlsplit(public_url_file.read_text(encoding='utf-8-sig').splitlines()[0].strip())
            if public.scheme in ('http','https') and public.hostname and not public.username and not public.password:
                allowed.add(public.hostname.lower().rstrip('.'))
        return name in allowed
    except (ValueError, OSError, IndexError):
        return False


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound concurrent slow clients; per-server budgets avoid shared-test state."""
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        self.api_reads = AttemptLimiter(maximum=600, window=60)
        self.api_writes = AttemptLimiter(maximum=300, window=60)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nRetry-After: 2\r\nContent-Length: 0\r\nX-Content-Type-Options: nosniff\r\n\r\n')
            except (OSError, socket.timeout):
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

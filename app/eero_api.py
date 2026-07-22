import json, os, re, time, logging
import requests

log = logging.getLogger('presence.eero')

# Native client for the unofficial eero cloud API (api-user.e2ro.com).
# Kept isolated here so the rest of the app survives if eero changes auth.
API = 'https://api-user.e2ro.com/2.2'


class EeroCloud:
    """Session management + device fetch against the eero cloud.

    One-time auth: start_login() sends a verification code to the account
    email/phone, verify() confirms it; the session token is stored in
    session_file and refreshed automatically on 401.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.session_file = cfg.get('session_file', './data/eero_session.cookie')

    # ── session ───────────────────────────────────────────────────────────
    def _token(self):
        try:
            return open(self.session_file).read().strip() or None
        except OSError:
            return None

    def _save(self, token):
        os.makedirs(os.path.dirname(self.session_file) or '.', exist_ok=True)
        with open(self.session_file, 'w') as f:
            f.write(token)

    @staticmethod
    def _auth_kwargs(tok):
        """Build the auth for a stored token, supporting both eero token forms:
        the classic `s` session cookie ("123456|hex…") and an Authorization
        bearer token (Amazon-SSO sessions). A token may be stored as
        "bearer:<value>" to force the header form."""
        if tok.lower().startswith('bearer:'):
            return {'headers': {'Authorization': 'Bearer ' + tok[7:].strip()}}
        # A JWT (two dots, no pipe) is a bearer token; the pipe form is the cookie.
        if '|' not in tok and tok.count('.') == 2:
            return {'headers': {'Authorization': 'Bearer ' + tok}}
        return {'cookies': {'s': tok}}

    def _req(self, method, path, retry=True, **kw):
        tok = self._token()
        if not tok:
            raise RuntimeError('not logged in — run: python -m app.main --config config/config.yaml --login '
                               '(or --set-session for an Amazon-SSO browser token)')
        auth = self._auth_kwargs(tok)
        r = requests.request(method, API + path, timeout=15, **auth, **kw)
        # Only the cookie (refreshable) token form can self-heal on 401.
        if r.status_code in (401, 403) and retry and 'cookies' in auth:
            self._refresh()
            return self._req(method, path, retry=False, **kw)
        r.raise_for_status()
        return (r.json() or {}).get('data', {})

    def _refresh(self):
        r = requests.post(API + '/login/refresh', cookies={'s': self._token() or ''}, timeout=15)
        r.raise_for_status()
        new = ((r.json() or {}).get('data') or {}).get('user_token')
        if not new:
            raise RuntimeError('session refresh failed — re-run --login')
        self._save(new)
        log.info('eero session refreshed')

    # ── one-time login flow ───────────────────────────────────────────────
    def start_login(self, ident):
        """Request a verification code; stores the pre-verify session token."""
        r = requests.post(API + '/login', json={'login': ident}, timeout=15)
        r.raise_for_status()
        self._save(r.json()['data']['user_token'])

    def verify(self, code):
        r = requests.post(API + '/login/verify', json={'code': str(code).strip()},
                          cookies={'s': self._token() or ''}, timeout=15)
        r.raise_for_status()

    def install_token(self, token):
        """Install an externally captured session token and validate it against
        /account before saving, so a bad capture fails loudly. Accepts the `s`
        cookie value, a "bearer:<jwt>" string, or a raw bearer JWT."""
        token = token.strip()
        auth = self._auth_kwargs(token)
        r = requests.get(API + '/account', timeout=15, **auth)
        if not r.ok:
            raise RuntimeError(f'token rejected by eero ({r.status_code}) — capture a working '
                               f'api-user.e2ro.com request auth from the logged-in browser')
        self._save(token)
        acct = (r.json() or {}).get('data', {})
        return acct.get('name') or acct.get('email') or 'account'

    # ── data ──────────────────────────────────────────────────────────────
    def devices(self):
        acct = self._req('GET', '/account')
        out = []
        nets = ((acct.get('networks') or {}).get('data')) or []
        want = (self.cfg.get('network_name') or '').strip().lower()
        if want:
            matched = [n for n in nets if (n.get('name') or '').strip().lower() == want]
            if matched:
                nets = matched
            else:
                log.warning('network_name %r not found on account (networks: %s) — polling all',
                            self.cfg.get('network_name'), [n.get('name') for n in nets])
        for net in nets:
            url = net.get('url') or ''
            path = url[len('/2.2'):] if url.startswith('/2.2') else url
            if not path:
                continue
            for d in self._req('GET', f'{path}/devices') or []:
                out.append(normalize(d, net))
        return out


class EeroAdapter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cloud = EeroCloud(cfg)
        self.retries = int(cfg.get('api_retries', 3))

    def fetch(self):
        """Return (devices, api_latency_ms). Retries with exponential backoff."""
        delay = 1
        for attempt in range(self.retries):
            t0 = time.time()
            try:
                return self.cloud.devices(), int((time.time() - t0) * 1000)
            except Exception as ex:
                if attempt == self.retries - 1:
                    raise RuntimeError(f'eero API unavailable/auth failed: {ex}')
                log.warning('eero fetch failed attempt=%d error=%s retry_in=%ds', attempt + 1, ex, delay)
                time.sleep(delay)
                delay *= 2


class FakeAdapter:
    """Reads devices from a JSON file each poll — edit the file (or point
    EERO_FAKE_FILE elsewhere) to simulate arrivals, departures and roaming
    without touching the eero cloud. Used for demos and tests."""

    def __init__(self, cfg):
        self.path = os.environ.get('EERO_FAKE_FILE') or cfg.get('fake_devices_file', './data/fake_devices.json')

    def fetch(self):
        t0 = time.time()
        with open(self.path) as f:
            devices = [normalize(c) for c in json.load(f)]
        return devices, max(1, int((time.time() - t0) * 1000))


def get_adapter(cfg):
    if os.environ.get('EERO_ADAPTER', cfg.get('adapter', 'eero')) == 'fake':
        return FakeAdapter(cfg)
    return EeroAdapter(cfg)


def _rssi(c):
    v = (c.get('connectivity') or {}).get('signal') or c.get('rssi') or c.get('signal_strength')
    if isinstance(v, str):
        m = re.search(r'-?\d+', v)
        return int(m.group()) if m else None
    return v


def normalize(c, net=None):
    src = c.get('source') or {}
    profile = c.get('profile')
    return {
        'mac': (c.get('mac') or c.get('mac_address') or '').lower(),
        'name': c.get('nickname') or c.get('name') or c.get('hostname'),
        'hostname': c.get('hostname'),
        'ip': c.get('ip') or c.get('ip_address') or (c.get('ips') or [None])[0],
        'online': bool(c.get('connected') or c.get('online')),
        'rssi': _rssi(c),
        'gateway': c.get('gateway') or src.get('location') or src.get('display_name'),
        'manufacturer': c.get('manufacturer') or c.get('vendor'),
        'profile': profile.get('name') if isinstance(profile, dict) else profile,
        'network_id': (net or {}).get('id') or ((net or {}).get('url') or '').rsplit('/', 1)[-1] or None,
        'raw': c,
    }

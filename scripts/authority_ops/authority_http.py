import json
import urllib.request

from pathlib import Path
from urllib.parse import urlsplit




class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Authority redirects are not accepted')


def origin(value, allow_http=False):
    url = urlsplit(value)
    if url.scheme not in (['https', 'http'] if allow_http else ['https']) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ['', '/']:
        raise ValueError('Use a bare HTTPS origin; private HTTP requires explicit opt-in')
    return value.rstrip('/')


def read_json(base, path, token_file=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {'Authorization': 'Bearer ' + Path(token_file).read_text().strip()} if token_file else {}
    headers['User-Agent'] = 'GenesisMesh-Revocation-Consumer/1'
    with opener.open(urllib.request.Request(base + path, headers=headers), timeout=8) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Authority response exceeded 2 MiB')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        return data

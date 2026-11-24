"""Local-browser trust boundary. This is not remote-user authentication."""
from urllib.parse import urlsplit
from starlette.responses import JSONResponse

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
DEV_ORIGINS = {'http://localhost:3000', 'http://127.0.0.1:3000'}


def trusted_browser_request(scope):
    headers = dict(scope.get('headers', []))
    try:
        host = headers.get(b'host', b'').decode('ascii')
        authority = urlsplit('http://' + host)
        if authority.hostname not in LOCAL_HOSTS or authority.username or authority.password:
            return False
        # Accessing port also validates malformed ports.
        authority.port
        origin = headers.get(b'origin')
        if origin is None: return True  # Local scripts/CLI; no remote authentication implied.
        origin = origin.decode('ascii')
        scheme = 'https' if scope.get('scheme') in ('https', 'wss') else 'http'
        return origin == f'{scheme}://{host}' or origin in DEV_ORIGINS
    except (ValueError, UnicodeError):
        return False


class LocalBrowserMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket') and not trusted_browser_request(scope):
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            else:
                await JSONResponse({'detail': 'Only trusted local hosts and browser origins are allowed.'}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


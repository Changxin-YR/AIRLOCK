"""Serve the isolated study page on loopback without starting the approval service.

Only a fixed set of public assets is served. Participants choose a task file and
export their own result in the browser; this process receives no study records,
opens no AIRLOCK database and has no tool or approval endpoints.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    '/': ('airlock/static/study.html', 'text/html; charset=utf-8'),
    '/assets/study.html': ('airlock/static/study.html', 'text/html; charset=utf-8'),
    '/assets/study.js': ('airlock/static/study.js', 'text/javascript; charset=utf-8'),
    '/assets/lib.js': ('airlock/static/lib.js', 'text/javascript; charset=utf-8'),
    '/assets/style.css': ('airlock/static/style.css', 'text/css; charset=utf-8'),
    '/tasks-example.json': ('benchmark/pilot-github-tasks.json', 'application/json; charset=utf-8'),
}
BANNER = ('<aside class="warning" role="note">单人先导练习：用于发现界面和理解问题。'
          '示例题使用作者标签，结果不能作为双人一致性或正式 A/B 验收证据。'
          '<a href="/tasks-example.json" download="pilot-tasks.json">下载练习任务</a></aside>')


class Handler(BaseHTTPRequestHandler):
    server_version = 'AIRLOCK-Pilot'
    sys_version = ''

    def log_message(self, *_):
        pass

    def do_GET(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in hosts:
            self.send_error(403)
            return
        asset = ASSETS.get(self.path)
        if asset is None:
            self.send_error(404)
            return
        filename, content_type = asset
        data = (ROOT / filename).read_bytes()
        if content_type.startswith('text/html'):
            data = data.replace(b'<body>', ('<body>' + BANNER).encode('utf-8'), 1)
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; connect-src 'none'; object-src 'none'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if self.path == '/tasks-example.json':
            self.send_header('Content-Disposition', 'attachment; filename="pilot-tasks.json"')
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        url = f'http://127.0.0.1:{args.port}/'
        print(f'Pilot page: {url} (Ctrl+C to stop)', flush=True)
        if args.open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

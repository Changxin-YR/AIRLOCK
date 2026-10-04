"""Read-only local startup checks; success is not deployment certification.

The supplied environment is parsed without opening its database or integration
files. SQLite is checked only in memory. Console files are bounded static build
inputs, never executed, and no network connection is made.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat

from .models import Settings
from .sqlite_runtime import require_safe_python_runtime


MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_CSP_BYTES = 128 * 1024
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_REFERENCES = 512
MAX_HASHES = 256
REQUIRED_KEYS = ('AIRLOCK_AGENT_TOKEN', 'AIRLOCK_REVIEWER_TOKEN', 'AIRLOCK_AUDIT_KEY')


class ConsoleValidationError(ValueError):
    """A fixed, public error code without file paths or input excerpts."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise ConsoleValidationError(code)


def _checked_stat(path):
    # Include ancestors: checking only the final file would allow a symlinked
    # _next directory (or a Windows junction) to escape the selected build.
    for component in (path, *path.parents):
        details = component.lstat()
        if (stat.S_ISLNK(details.st_mode)
                or getattr(details, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            _fail('console_unsafe_path')
    return path.lstat()


def _regular_file(path, limit, missing_code):
    try:
        details = _checked_stat(path)
    except FileNotFoundError:
        _fail(missing_code)
    if not stat.S_ISREG(details.st_mode):
        _fail('console_unsafe_path')
    if details.st_size > limit:
        _fail('console_too_large')
    return details


def _read_bounded(path, limit):
    before = _regular_file(path, limit, 'console_missing')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as source:
        opened = os.fstat(source.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            _fail('console_unsafe_path')
        raw = source.read(limit + 1)
    if len(raw) > limit:
        _fail('console_too_large')
    _checked_stat(path)
    return raw.decode('utf-8-sig')


def _asset_parts(reference):
    # A leading /_next is a same-origin browser URL, not a filesystem root.
    # Reject URL encoding rather than accepting a second path interpretation.
    if (not isinstance(reference, str) or len(reference) > 1024
            or not re.fullmatch(r'/?_next/[A-Za-z0-9_./-]+\.(?:js|css)', reference)):
        _fail('console_asset_invalid')
    parts = reference.removeprefix('/').split('/')
    for part in parts:
        if (not part or part in {'.', '..'} or part.endswith('.')
                or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)):
            _fail('console_asset_invalid')
    return tuple(parts)


class _ConsoleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.assets = set()
        self.inline_hashes = set()
        self.script = None
        self.has_html = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if len(attrs) != len(attributes):
            _fail('console_index_invalid')
        if tag == 'html':
            self.has_html = True
        if tag == 'base':
            _fail('console_asset_invalid')
        if tag == 'script':
            if self.script is not None:
                _fail('console_index_invalid')
            self.script = []
            if 'src' in attrs:
                self._asset(attrs['src'], '.js')
        elif tag == 'link' and 'href' in attrs:
            # The shipped Next export uses only local JS/CSS resource links.
            # Reject remote/preconnect/base changes instead of fetching them.
            suffix = '.css' if 'stylesheet' in (attrs.get('rel') or '').split() else None
            self._asset(attrs['href'], suffix)
        elif tag in {'iframe', 'img', 'source', 'audio', 'video', 'embed', 'object'}:
            if any(name in attrs for name in ('src', 'srcset', 'data', 'poster')):
                _fail('console_asset_invalid')

    def handle_startendtag(self, tag, attributes):
        if tag == 'script':
            _fail('console_index_invalid')
        self.handle_starttag(tag, attributes)

    def _asset(self, reference, suffix):
        parts = _asset_parts(reference)
        if suffix is not None and not parts[-1].endswith(suffix):
            _fail('console_asset_invalid')
        self.assets.add(parts)
        if len(self.assets) > MAX_REFERENCES:
            _fail('console_too_large')

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script':
            if self.script is None:
                _fail('console_index_invalid')
            body = ''.join(self.script)
            if body:  # Match package_console.mjs: exclude only empty bodies.
                digest = base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode('ascii')
                self.inline_hashes.add("'sha256-" + digest + "'")
            self.script = None


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('console_csp_invalid')
        result[key] = value
    return result


def validate_console(console: Path) -> list[str]:
    """Return validated CSP hashes or raise a fixed ConsoleValidationError.

    Both index.html and csp.json are required. Referenced local _next JS/CSS
    must be regular files within the same tree. This is a filesystem snapshot,
    not protection against a trusted operator replacing the build afterward.
    """
    try:
        root = Path(console).absolute()
        try:
            if not stat.S_ISDIR(_checked_stat(root).st_mode):
                _fail('console_missing')
        except FileNotFoundError:
            _fail('console_missing')
        html = _read_bounded(root / 'index.html', MAX_INDEX_BYTES)
        # Browsers normalize CRLF and bare CR before constructing script text.
        # Hash that effective text, so a raw-CR manifest cannot falsely pass.
        if '\x00' in html:
            _fail('console_index_invalid')
        html = html.replace('\r\n', '\n').replace('\r', '\n')
        csp = _read_bounded(root / 'csp.json', MAX_CSP_BYTES)
        try:
            content = json.loads(csp, object_pairs_hook=_json_object)
        except (ValueError, RecursionError):
            _fail('console_csp_invalid')
        hashes = content.get('script_hashes') if isinstance(content, dict) else None
        if (not isinstance(hashes, list) or len(hashes) > MAX_HASHES
                or any(not isinstance(value, str) or not re.fullmatch(r"'sha256-[A-Za-z0-9+/]{43}='", value)
                       for value in hashes) or len(set(hashes)) != len(hashes)):
            _fail('console_csp_invalid')
        for value in hashes:
            encoded = value[8:-1]
            if base64.b64encode(base64.b64decode(encoded, validate=True)).decode('ascii') != encoded:
                _fail('console_csp_invalid')
        parser = _ConsoleHTML()
        parser.feed(html)
        parser.close()
        if not parser.has_html or parser.script is not None or parser.rawdata:
            _fail('console_index_invalid')
        if not parser.inline_hashes.issubset(set(hashes)):
            _fail('console_csp_mismatch')
        for parts in parser.assets:
            _regular_file(root.joinpath(*parts), MAX_ASSET_BYTES, 'console_asset_missing')
        return list(hashes)
    except ConsoleValidationError:
        raise
    except (OSError, UnicodeError):
        _fail('console_unreadable')
    except (ValueError, TypeError, RecursionError):
        _fail('console_index_invalid')


def collect_checks(environ: Mapping[str, str], console: Path | None = None) -> dict:
    """Inspect only caller-supplied settings, in-memory SQLite and static files."""
    checks = []
    try:
        if any(key not in environ for key in REQUIRED_KEYS):
            checks.append({'id': 'configuration', 'status': 'FAIL', 'code': 'configuration_missing'})
        else:
            Settings.from_env(environ)
            checks.append({'id': 'configuration', 'status': 'PASS', 'code': 'configuration_valid'})
    except Exception:
        checks.append({'id': 'configuration', 'status': 'FAIL', 'code': 'configuration_invalid'})
    try:
        info = require_safe_python_runtime()
        item = {'id': 'sqlite_runtime', 'status': 'PASS', 'code': 'sqlite_runtime_ready'}
        for key, pattern in (
            ('version', r'3\.\d{1,3}\.\d{1,3}'),
            ('source_id', r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [0-9a-f]{40,64}'),
        ):
            value = info.get(key)
            if isinstance(value, str) and re.fullmatch(pattern, value):
                item[key] = value
        checks.append(item)
    except Exception:
        checks.append({'id': 'sqlite_runtime', 'status': 'FAIL', 'code': 'sqlite_runtime_unavailable'})
    try:
        validate_console(console if console is not None else Path(__file__).with_name('console'))
        checks.append({'id': 'console', 'status': 'PASS', 'code': 'console_ready'})
    except ConsoleValidationError as error:
        checks.append({'id': 'console', 'status': 'FAIL', 'code': error.code})
    return {'scope': 'local_startup_preflight',
            'status': 'PASS' if all(item['status'] == 'PASS' for item in checks) else 'FAIL',
            'checks': checks,
            'not_checked': ['persistent_database', 'remote_services', 'optional_integrations'],
            'service_started': False}

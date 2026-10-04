import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import httpx
import pytest

from airlock import private_files
from scripts import github_adapter


def test_private_reservation_permissions_and_exclusive_reuse(tmp_path):
    requested = tmp_path/'claim.json'
    with private_files.reserve_private_output(requested) as (actual, output):
        assert actual == tmp_path/'claim.json.private'/'claim.json'
        output.write('synthetic-one-use-credential')
    assert actual.read_text() == 'synthetic-one-use-credential' and not requested.exists()
    if os.name == 'nt':
        # Inspect the real DACL rather than relying on chmod on Windows.
        system = Path(os.environ['SYSTEMROOT'])/'System32'
        account = subprocess.run([str(system/'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                                 capture_output=True, text=True, check=True).stdout
        owner_sid = re.search(r'S-1-\d+(?:-\d+)+', account).group()
        for index, target in enumerate((actual.parent, actual)):
            acl_file = tmp_path/f'acl-{index}.txt'
            subprocess.run([str(system/'icacls.exe'), str(target), '/save', str(acl_file), '/q'],
                           capture_output=True, check=True)
            descriptor = next(line for line in acl_file.read_text(encoding='utf-16-le').splitlines() if line.startswith('D:'))
            grants = [entry.split(';') for entry in re.findall(r'\(([^()]*)\)', descriptor)]
            assert grants and any(entry[-1] == owner_sid for entry in grants)
            # Python's Windows 0700 mkdir can retain explicit SYSTEM,
            # Administrators and Owner Rights grants; no unprivileged group.
            assert all(entry[0] == 'A' and entry[2] == 'FA'
                       and entry[-1] in {owner_sid, 'SY', 'BA', 'OW'} for entry in grants)
    else:
        assert stat.S_IMODE(actual.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(actual.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        with private_files.reserve_private_output(requested):
            pytest.fail('must not reuse a consumed reservation')


def test_private_reservation_preserves_existing_output_and_failure(tmp_path):
    requested = tmp_path/'already.json'
    requested.write_text('original')
    with pytest.raises(FileExistsError):
        with private_files.reserve_private_output(requested):
            pytest.fail('must not overwrite')
    assert requested.read_text() == 'original'
    requested = tmp_path/'failed.json'
    with pytest.raises(RuntimeError):
        with private_files.reserve_private_output(requested):
            raise RuntimeError('synthetic request failure')
    assert (tmp_path/'failed.json.private'/'failed.json').read_text() == ''
    with pytest.raises(FileExistsError):
        with private_files.reserve_private_output(requested):
            pytest.fail('a failed operation is not automatically retryable')


def test_relay_cli_private_output_and_no_repeat_send(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('AIRLOCK_GITHUB_RELAY_TOKEN', 'r'*40)
    requested = tmp_path/'relay.json'
    monkeypatch.setattr(sys, 'argv', ['github_adapter', 'relay-claim', '--url', 'http://127.0.0.1:8888',
                                    '--action-id', 'a'*32, '--out', str(requested)])
    calls = []
    def receive(request):
        calls.append(request)
        assert requested.with_name(requested.name+'.private').is_dir()
        assert request.headers['authorization'] == 'Bearer '+'r'*40
        return httpx.Response(200, json={'action_id':'a'*32, 'claim_token':'synthetic-private-token'})
    client_factory = httpx.Client
    monkeypatch.setattr(github_adapter.httpx, 'Client',
                        lambda **kwargs: client_factory(transport=httpx.MockTransport(receive), **kwargs))
    github_adapter.main()
    emitted = capsys.readouterr().out
    assert 'synthetic-private-token' not in emitted
    actual = Path(json.loads(emitted)['output'])
    assert actual == tmp_path/'relay.json.private'/'relay.json'
    assert json.loads(actual.read_text())['claim_token'] == 'synthetic-private-token'
    with pytest.raises(FileExistsError):
        github_adapter.main()
    assert len(calls) == 1


def test_relay_cli_does_not_call_when_private_permissions_fail(tmp_path, monkeypatch):
    monkeypatch.setenv('AIRLOCK_GITHUB_RELAY_TOKEN', 'r'*40)
    monkeypatch.setattr(sys, 'argv', ['github_adapter', 'relay-claim', '--url', 'http://127.0.0.1:8888',
                                    '--action-id', 'a'*32, '--out', str(tmp_path/'denied.json')])
    def denied(_):
        raise PermissionError('synthetic private ACL failure')
    monkeypatch.setattr(private_files, 'restrict_directory', denied)
    monkeypatch.setattr(github_adapter.httpx, 'Client', lambda **kwargs: pytest.fail('must fail before any network call'))
    with pytest.raises(PermissionError):
        github_adapter.main()
    assert (tmp_path/'denied.json.private').is_dir()
    assert list((tmp_path/'denied.json.private').iterdir()) == []

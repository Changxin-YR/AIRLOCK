"""Second-author archive custody and output boundary probes (no network)."""
import datetime as dt
import hashlib
import io
import json
import sys

import pytest

from airlock.archive import ArchiveConfig, checkpoint_bytes, verify_archive
from scripts import archive_checkpoint_s3 as cli


NOW = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)


class Custodian:
    def __init__(self, raw):
        self.raw = raw
        self.until = NOW + dt.timedelta(days=100)
        self.version = 'cross-version-1'
        self.mode = 'COMPLIANCE'
        self.calls = []
        self.streams = []

    def get_object_lock_configuration(self, **args):
        self.calls.append(('configuration', args))
        return {'ObjectLockConfiguration': {'ObjectLockEnabled': 'Enabled'}}

    def get_bucket_versioning(self, **args):
        self.calls.append(('versioning', args))
        return {'Status': 'Enabled'}

    def put_object(self, **args):
        self.calls.append(('put', args))
        self.raw = args['Body']
        self.until = args['ObjectLockRetainUntilDate']
        return {'VersionId': self.version}

    def get_object_retention(self, **args):
        self.calls.append(('retention', args))
        return {'Retention': {'Mode': self.mode, 'RetainUntilDate': self.until}}

    def get_object(self, **args):
        self.calls.append(('get', args))
        stream = io.BytesIO(self.raw)
        self.streams.append(stream)
        return {'VersionId': self.version, 'Body': stream}

    def close(self):
        self.calls.append(('close', {}))


def setup():
    config = ArchiveConfig(endpoint='https://cross.example', bucket='cross-custody')
    cp = {'version': 1, 'database_instance': '1' * 32, 'seq': 19, 'head': '2' * 64,
          'key_id': 'synthetic', 'signature': '3' * 64}
    raw = checkpoint_bytes(cp)
    sha = hashlib.sha256(raw).hexdigest()
    receipt = {'bucket': config.bucket, 'key': f'checkpoints/{cp["database_instance"]}/{cp["seq"]:012d}-{sha}.json',
        'version_id': 'cross-version-1', 'sha256': sha, 'retain_until': (NOW + dt.timedelta(days=30)).isoformat(),
        'mode': 'COMPLIANCE', 'database_instance': cp['database_instance'], 'seq': cp['seq']}
    return config, cp, receipt, Custodian(raw)


def test_current_extended_retention_is_exact_version_read_only():
    config, cp, receipt, s3 = setup()
    original = dict(receipt)
    result = verify_archive(s3, config, receipt, now=NOW)
    assert result['checkpoint'] == cp and result['status'] == 'verified'
    assert result['retention_active_at'] == NOW.isoformat()
    assert receipt == original
    assert [method for method, _ in s3.calls] == ['retention', 'get']
    assert all(args['VersionId'] == 'cross-version-1' for _, args in s3.calls)
    assert all(stream.closed for stream in s3.streams)


@pytest.mark.parametrize('field,value', [('seq', 20), ('database_instance', 'f' * 32)])
def test_well_formed_rekeyed_receipt_cannot_relabel_body(field, value):
    config, _, receipt, s3 = setup()
    receipt[field] = value
    receipt['key'] = f'checkpoints/{receipt["database_instance"]}/{receipt["seq"]:012d}-{receipt["sha256"]}.json'
    with pytest.raises(ValueError, match='checkpoint identity'):
        verify_archive(s3, config, receipt, now=NOW)
    assert all(stream.closed for stream in s3.streams)


@pytest.mark.parametrize('mutation', ['response_version', 'content', 'governance', 'shorter'])
def test_current_receipt_rejects_changed_storage(mutation):
    config, _, receipt, s3 = setup()
    if mutation == 'response_version':
        s3.version = 'cross-version-2'
    elif mutation == 'content':
        s3.raw += b' '
    elif mutation == 'governance':
        s3.mode = 'GOVERNANCE'
    else:
        s3.until = NOW + dt.timedelta(days=29)
    with pytest.raises(ValueError):
        verify_archive(s3, config, receipt, now=NOW)
    assert not any(method == 'put' for method, _ in s3.calls)
    assert all(stream.closed for stream in s3.streams)


def test_expired_receipt_rejected_without_storage_reads():
    config, _, receipt, s3 = setup()
    receipt['retain_until'] = NOW.isoformat()
    with pytest.raises(ValueError, match='expired'):
        verify_archive(s3, config, receipt, now=NOW)
    assert s3.calls == []


@pytest.mark.parametrize('existing', ['file', 'directory'])
def test_cli_unwritable_receipt_destination_prevents_irreversible_upload(tmp_path, monkeypatch, existing):
    config, cp, _, s3 = setup()
    config_path = tmp_path / 'configuration.json'
    cp_path = tmp_path / 'checkpoint.json'
    output = tmp_path / 'receipt.json'
    config_path.write_text(config.model_dump_json())
    cp_path.write_text(json.dumps(cp))
    if existing == 'file':
        output.write_text('preserve-existing-receipt')
    else:
        output.mkdir()
    monkeypatch.setattr(cli, 'client', lambda _: s3)
    monkeypatch.setattr(sys, 'argv', ['archive', '--config', str(config_path), '--checkpoint', str(cp_path), '--output', str(output)])
    with pytest.raises(OSError):
        cli.main()
    assert not any(method == 'put' for method, _ in s3.calls), 'must validate receipt output before a COMPLIANCE upload'
    if existing == 'file':
        assert output.read_text() == 'preserve-existing-receipt'


def test_cli_success_replaces_reservation_with_complete_receipt_and_verifies(tmp_path, monkeypatch, capsys):
    config, cp, _, s3 = setup()
    config_path = tmp_path / 'config.json'
    cp_path = tmp_path / 'checkpoint.json'
    output = tmp_path / 'receipt.json'
    verification = tmp_path / 'verification.json'
    config_path.write_text(config.model_dump_json())
    cp_path.write_text(json.dumps(cp))
    observed = []

    def client_with_reserved_output(_):
        destination = output if not observed else verification
        value = json.loads(destination.read_text())
        assert value['status'] == 'reserved' and value['outcome'] == 'unknown_if_interrupted'
        observed.append(value['operation'])
        return s3

    monkeypatch.setattr(cli, 'client', client_with_reserved_output)
    monkeypatch.setattr(sys, 'argv', ['archive', '--config', str(config_path), '--checkpoint', str(cp_path), '--output', str(output)])
    cli.main()
    receipt = json.loads(output.read_text())
    assert set(receipt) == {'bucket', 'key', 'version_id', 'sha256', 'retain_until', 'mode', 'database_instance', 'seq'}
    assert receipt['seq'] == cp['seq'] and receipt['database_instance'] == cp['database_instance']
    assert 'unknown_if_interrupted' not in output.read_text()
    first_stdout = json.loads(capsys.readouterr().out)
    assert first_stdout['status'] == 'archived_and_verified' and 'signature' not in first_stdout
    monkeypatch.setattr(sys, 'argv', ['archive', '--config', str(config_path), '--verify-receipt', str(output), '--output', str(verification)])
    cli.main()
    result = json.loads(verification.read_text())
    assert result['status'] == 'verified' and result['checkpoint'] == cp
    assert 'unknown_if_interrupted' not in verification.read_text()
    assert observed == ['upload', 'verify']
    assert [method for method, _ in s3.calls].count('put') == 1
    assert [method for method, _ in s3.calls].count('close') == 2

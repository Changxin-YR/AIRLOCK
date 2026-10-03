"""Archive receipts must describe the exact retained checkpoint, not a label."""
import datetime as dt
import hashlib
import io
import json
import sys

import pytest

from airlock.archive import ArchiveConfig, archive_checkpoint, archive_json, checkpoint_bytes, verify_archive


class ArchiveFixture:
    def __init__(self):
        self.calls = []
        self.mode = 'COMPLIANCE'
        self.version = 'fixture-version'

    def get_object_lock_configuration(self, **args):
        return {'ObjectLockConfiguration': {'ObjectLockEnabled': 'Enabled'}}

    def get_bucket_versioning(self, **args):
        return {'Status': 'Enabled'}

    def put_object(self, **args):
        self.raw = args['Body']
        self.until = args['ObjectLockRetainUntilDate']
        return {'VersionId': self.version}

    def get_object_retention(self, **args):
        self.calls.append(('retention', args))
        return {'Retention': {'Mode': self.mode, 'RetainUntilDate': self.until}}

    def get_object(self, **args):
        self.calls.append(('read', args))
        return {'Body': io.BytesIO(self.raw), 'VersionId': self.version}


def archived():
    cp = {'version': 1, 'database_instance': 'a' * 32, 'seq': 7,
          'head': 'b' * 64, 'key_id': 'legacy', 'signature': 'c' * 64}
    s3 = ArchiveFixture()
    config = ArchiveConfig(endpoint='https://archive.example', bucket='evidence')
    return cp, s3, config, archive_checkpoint(s3, config, cp)


def test_archive_receipt_normal_read_pins_exact_version():
    cp, s3, config, receipt = archived()
    result = verify_archive(s3, config, receipt)
    assert result['checkpoint'] == cp
    assert all(args['VersionId'] == receipt['version_id'] for _, args in s3.calls)


@pytest.mark.parametrize('changes', [
    {'seq': 8}, {'seq': True}, {'database_instance': 'd' * 32},
    {'mode': 'GOVERNANCE'}, {'version_id': 23}, {'version_id': 'null'},
    {'retain_until': '2000-01-01T00:00:00+00:00'},
    {'key': 'checkpoints/unrelated.json'}, {'unexpected': 'unverified field'},
])
def test_archive_rejects_receipt_claim_substitution(changes):
    _, s3, config, receipt = archived()
    with pytest.raises(ValueError):
        verify_archive(s3, config, dict(receipt, **changes))


def test_archive_rejects_response_from_another_version():
    _, s3, config, receipt = archived()
    s3.version = 'different-version'
    with pytest.raises(ValueError):
        verify_archive(s3, config, receipt)


@pytest.mark.parametrize('field,value', [
    ('version', True), ('version', 1.0), ('database_instance', None),
    ('head', 3), ('signature', []), ('key_id', ''), ('key_id', 'bad\nkey'),
])
def test_checkpoint_invalid_types_are_controlled_errors(field, value):
    cp, _, _, _ = archived()
    with pytest.raises(ValueError):
        checkpoint_bytes(dict(cp, **{field: value}))


def test_archive_rejects_duplicate_checkpoint_json_fields():
    _, s3, config, receipt = archived()
    s3.raw = b'{"seq":99,' + s3.raw[1:]
    sha = hashlib.sha256(s3.raw).hexdigest()
    receipt['sha256'] = sha
    receipt['key'] = f"checkpoints/{receipt['database_instance']}/{receipt['seq']:012d}-{sha}.json"
    with pytest.raises(ValueError):
        verify_archive(s3, config, receipt)


def test_archive_expired_compliance_is_not_current_protection():
    _, s3, config, receipt = archived()
    s3.until = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    receipt['retain_until'] = s3.until.isoformat()
    with pytest.raises(ValueError):
        verify_archive(s3, config, receipt)


def test_archive_retention_shortening_still_rejected():
    _, s3, config, receipt = archived()
    s3.until -= dt.timedelta(seconds=1)
    with pytest.raises(ValueError, match='retention weakened'):
        verify_archive(s3, config, receipt)


@pytest.mark.parametrize('field,value', [('seq', 99), ('database_instance', 'd' * 32)])
def test_archive_receipt_identity_is_bound_to_downloaded_checkpoint(field, value):
    _, s3, config, receipt = archived()
    receipt[field] = value
    receipt['key'] = f"checkpoints/{receipt['database_instance']}/{receipt['seq']:012d}-{receipt['sha256']}.json"
    with pytest.raises(ValueError, match='checkpoint identity'):
        verify_archive(s3, config, receipt)


@pytest.mark.parametrize('raw', ['{"mode":"GOVERNANCE","mode":"COMPLIANCE"}', '{"value":NaN}', '{"value":Infinity}'])
def test_archive_cli_json_does_not_discard_conflicting_fields(raw):
    with pytest.raises(ValueError):
        archive_json(raw)


def test_archive_retention_boundary_is_strict_and_read_only():
    _, s3, config, receipt = archived()
    boundary = dt.datetime.fromisoformat(receipt['retain_until'])
    assert verify_archive(s3, config, receipt, now=boundary - dt.timedelta(microseconds=1))['status'] == 'verified'
    calls = list(s3.calls)
    with pytest.raises(ValueError, match='expired'):
        verify_archive(s3, config, receipt, now=boundary)
    assert s3.calls == calls


@pytest.mark.parametrize('date', ['2026-10-03T00:00:00', None, 3, 'invalid'])
def test_archive_invalid_retention_time_rejected_before_io(date):
    _, s3, config, receipt = archived()
    receipt['retain_until'] = date
    calls = list(s3.calls)
    with pytest.raises(ValueError):
        verify_archive(s3, config, receipt)
    assert s3.calls == calls


@pytest.mark.parametrize('existing', ['file', 'directory'])
def test_archive_cli_existing_destination_prevents_upload(tmp_path, monkeypatch, existing):
    from scripts import archive_checkpoint_s3 as cli
    cp, _, config, _ = archived()
    conf=tmp_path/'config.json'; source=tmp_path/'checkpoint.json'; output=tmp_path/'receipt.json'
    conf.write_text(config.model_dump_json());source.write_text(json.dumps(cp))
    if existing=='file':output.write_text('old receipt')
    else:output.mkdir()
    def forbidden(_):raise AssertionError('client must not be created before output reservation')
    monkeypatch.setattr(cli,'client',forbidden)
    monkeypatch.setattr(sys,'argv',['archive','--config',str(conf),'--checkpoint',str(source),'--output',str(output)])
    with pytest.raises(OSError):cli.main()
    if existing=='file':assert output.read_text()=='old receipt'


def test_archive_cli_interruption_preserves_uncertain_output_reservation(tmp_path, monkeypatch):
    from scripts import archive_checkpoint_s3 as cli
    cp, _, config, _ = archived()
    conf=tmp_path/'config.json'; source=tmp_path/'checkpoint.json'; output=tmp_path/'receipt.json'
    conf.write_text(config.model_dump_json());source.write_text(json.dumps(cp))
    class BrokenCustodian:
        closed=False
        def close(self):self.closed=True
    custodian=BrokenCustodian()
    monkeypatch.setattr(cli,'client',lambda _:custodian)
    def interrupted(*args):
        assert json.loads(output.read_text())['status']=='reserved'
        raise ConnectionError('synthetic uncertain response')
    monkeypatch.setattr(cli,'archive_checkpoint',interrupted)
    monkeypatch.setattr(sys,'argv',['archive','--config',str(conf),'--checkpoint',str(source),'--output',str(output)])
    with pytest.raises(ConnectionError):cli.main()
    assert json.loads(output.read_text())['outcome']=='unknown_if_interrupted'
    assert custodian.closed
    with pytest.raises(FileExistsError):cli.main()

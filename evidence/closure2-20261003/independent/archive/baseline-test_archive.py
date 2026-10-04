import datetime as dt
import io
from dataclasses import replace
import pytest
from airlock.archive import checkpoint_bytes,ArchiveConfig,archive_checkpoint,verify_archive
from airlock.service import Gate


class StoreFixture:
    def __init__(self):self.lock=True;self.versioning=True;self.mode='COMPLIANCE';self.raw=None
    def get_object_lock_configuration(self,**kwargs):return {'ObjectLockConfiguration':{'ObjectLockEnabled':'Enabled' if self.lock else 'Disabled'}}
    def get_bucket_versioning(self,**kwargs):return {'Status':'Enabled' if self.versioning else 'Suspended'}
    def put_object(self,**kwargs):self.raw=kwargs['Body'];self.until=kwargs['ObjectLockRetainUntilDate'];return {'VersionId':'bound-version'}
    def get_object_retention(self,**kwargs):return {'Retention':{'Mode':self.mode,'RetainUntilDate':self.until}}
    def get_object(self,**kwargs):
        assert kwargs['VersionId']=='bound-version'
        return {'Body':io.BytesIO(self.raw)}


def test_archive_requires_version_retention_and_verifies_exact_payload(settings):
    s3=StoreFixture();config=ArchiveConfig(endpoint='https://archive.example',bucket='evidence')
    cp=Gate(settings).store.checkpoint();receipt=archive_checkpoint(s3,config,cp)
    assert verify_archive(s3,config,receipt)['checkpoint']==cp
    s3.raw=b'{}'
    with pytest.raises(ValueError,match='content mismatch'):verify_archive(s3,config,receipt)
    s3.raw=checkpoint_bytes(cp);s3.mode='GOVERNANCE'
    with pytest.raises(ValueError,match='retention weakened'):verify_archive(s3,config,receipt)
    s3.lock=False
    with pytest.raises(ValueError,match='Object Lock'):archive_checkpoint(s3,config,cp)
    s3.lock=True;s3.versioning=False
    with pytest.raises(ValueError,match='versioning'):archive_checkpoint(s3,config,cp)
def test_archive_readiness_retries_connection_reset_without_retrying_writes():
    from scripts.archive_integration import wait_ready
    from botocore.exceptions import ConnectionClosedError,ClientError
    class Fixture:
        calls=0
        def list_buckets(self):
            self.calls+=1
            if self.calls==1:raise ConnectionClosedError(endpoint_url='http://127.0.0.1')
            if self.calls==2:raise ClientError({'Error':{'Code':'ServiceUnavailable'}},'ListBuckets')
            return {}
    fixture=Fixture();wait_ready(fixture,attempts=3,pause=0);assert fixture.calls==3
    with pytest.raises(RuntimeError,match='did not become ready'):wait_ready(Fixture(),attempts=1,pause=0)


@pytest.mark.parametrize('session_token',[None,'synthetic-sts-session-token+/='])
def test_archive_only_signs_with_dedicated_credentials(monkeypatch,session_token):
    from urllib.parse import parse_qs,urlparse
    from airlock.archive import client
    monkeypatch.setenv('AIRLOCK_ARCHIVE_ACCESS_KEY','dedicated-test-access-key')
    monkeypatch.setenv('AIRLOCK_ARCHIVE_SECRET_KEY','dedicated-test-secret-'+'x'*32)
    monkeypatch.setenv('AWS_ACCESS_KEY_ID','unrelated-global-access-key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','unrelated-global-secret-'+'y'*32)
    monkeypatch.setenv('AWS_SESSION_TOKEN','unrelated-global-session-token')
    if session_token is None:monkeypatch.delenv('AIRLOCK_ARCHIVE_SESSION_TOKEN',raising=False)
    else:monkeypatch.setenv('AIRLOCK_ARCHIVE_SESSION_TOKEN',session_token)
    s3=client(ArchiveConfig(endpoint='https://archive.example',bucket='evidence'))
    try:
        query=parse_qs(urlparse(s3.generate_presigned_url('get_object',Params={'Bucket':'evidence','Key':'fixture'},ExpiresIn=60)).query)
        assert query['X-Amz-Credential'][0].startswith('dedicated-test-access-key/')
        assert query.get('X-Amz-Security-Token')==([session_token] if session_token else None)
    finally:s3.close()


@pytest.mark.parametrize('session_token',['',' ','\t','\n','token\r\ninjected','token unicode \u4e2d'])
def test_archive_present_invalid_session_token_never_downgrades(monkeypatch,session_token):
    import airlock.archive as archive
    monkeypatch.setenv('AIRLOCK_ARCHIVE_ACCESS_KEY','dedicated-test-access-key')
    monkeypatch.setenv('AIRLOCK_ARCHIVE_SECRET_KEY','dedicated-test-secret-'+'x'*32)
    monkeypatch.setenv('AIRLOCK_ARCHIVE_SESSION_TOKEN',session_token)
    def forbidden(*args,**kwargs):raise AssertionError('must reject before creating an SDK client')
    monkeypatch.setattr(archive.boto3,'client',forbidden)
    with pytest.raises(ValueError,match='session token invalid'):
        archive.client(ArchiveConfig(endpoint='https://archive.example',bucket='evidence'))


@pytest.mark.parametrize('missing',['AIRLOCK_ARCHIVE_ACCESS_KEY','AIRLOCK_ARCHIVE_SECRET_KEY'])
def test_archive_missing_dedicated_identity_never_uses_global_aws(monkeypatch,missing):
    import airlock.archive as archive
    monkeypatch.setenv('AIRLOCK_ARCHIVE_ACCESS_KEY','dedicated-test-access-key')
    monkeypatch.setenv('AIRLOCK_ARCHIVE_SECRET_KEY','dedicated-test-secret-'+'x'*32)
    monkeypatch.delenv(missing)
    monkeypatch.setenv('AWS_ACCESS_KEY_ID','unrelated-global-access-key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','unrelated-global-secret-'+'y'*32)
    def forbidden(*args,**kwargs):raise AssertionError('must not enter the SDK credential provider chain')
    monkeypatch.setattr(archive.boto3,'client',forbidden)
    with pytest.raises(KeyError,match=missing):
        archive.client(ArchiveConfig(endpoint='https://archive.example',bucket='evidence'))

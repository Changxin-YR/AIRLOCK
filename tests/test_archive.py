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

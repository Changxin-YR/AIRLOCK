"""Separate-custodian S3 Object Lock archive, with version-specific verification.

Only checkpoints are transferred. The AIRLOCK server and Agent never receive
archive credentials. COMPLIANCE retention is verified on the actual object
version; a later version or delete marker cannot substitute for that receipt.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
from urllib.parse import urlparse
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pydantic import BaseModel,ConfigDict,Field
from .models import canonical


class ArchiveConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    endpoint: str
    bucket: str=Field(pattern=r'^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')
    region: str='us-east-1'
    prefix: str=Field(default='checkpoints',pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    retain_days: int=Field(default=90,ge=1,le=3650)
    ca_file: str | None=None


def client(config):
    parsed=urlparse(config.endpoint)
    if parsed.username or parsed.password or not parsed.hostname or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('archive origin required')
    if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','::1','localhost'}):
        raise ValueError('archive requires HTTPS or explicit local fixture')
    # Never fall back to a user's default AWS profile, instance metadata or
    # credentials from another project.
    key=os.environ['AIRLOCK_ARCHIVE_ACCESS_KEY'];secret=os.environ['AIRLOCK_ARCHIVE_SECRET_KEY']
    if len(key)<8 or len(secret)<32:raise ValueError('dedicated archive credentials required')
    # Omission permits long-lived project credentials. A present but empty or
    # malformed STS token is a configuration error, never a downgrade to them.
    token=os.environ.get('AIRLOCK_ARCHIVE_SESSION_TOKEN')
    if token is not None and (not token or any(not 33<=ord(c)<=126 for c in token)):
        raise ValueError('dedicated archive session token invalid')
    s3=boto3.client('s3',endpoint_url=config.endpoint,region_name=config.region,
        aws_access_key_id=key,aws_secret_access_key=secret,aws_session_token=token,verify=config.ca_file or True,
        config=Config(signature_version='s3v4',connect_timeout=3,read_timeout=5,
                      retries={'max_attempts':0},s3={'addressing_style':'path'},proxies={}))
    # Some S3-compatible retention APIs still require Content-MD5, even when
    # a current SDK also supplies a modern checksum. This is transport integrity,
    # not the security digest used in the archive receipt.
    def retention_md5(params,**kwargs):
        params['headers']['Content-MD5']=base64.b64encode(hashlib.md5(params['body'],usedforsecurity=False).digest()).decode()
    s3.meta.events.register('before-call.s3.PutObjectRetention',retention_md5)
    return s3


def checkpoint_bytes(checkpoint):
    if not isinstance(checkpoint,dict) or set(checkpoint)!={'version','database_instance','seq','head','key_id','signature'}:
        raise ValueError('checkpoint shape')
    if checkpoint['version']!=1 or type(checkpoint['seq']) is not int or not 0<=checkpoint['seq']<=10**12:
        raise ValueError('checkpoint version/sequence')
    if not re.fullmatch(r'[a-f0-9]{32}',checkpoint['database_instance']) or not all(re.fullmatch(r'[a-f0-9]{64}',checkpoint[k]) for k in ('head','signature')):
        raise ValueError('checkpoint digest')
    if not isinstance(checkpoint['key_id'],str) or len(checkpoint['key_id'])>128:raise ValueError('checkpoint key identity')
    return (canonical(checkpoint)+'\n').encode()


def verify_archive(s3,config,receipt):
    if receipt.get('bucket')!=config.bucket or not receipt.get('version_id') or not str(receipt.get('key','')).startswith(config.prefix+'/'):
        raise ValueError('archive receipt scope')
    args={'Bucket':config.bucket,'Key':receipt['key'],'VersionId':receipt['version_id']}
    retention=s3.get_object_retention(**args)['Retention']
    if retention.get('Mode')!='COMPLIANCE' or retention['RetainUntilDate']<dt.datetime.fromisoformat(receipt['retain_until']):
        raise ValueError('retention weakened')
    response=s3.get_object(**args)
    try:raw=response['Body'].read(4097)
    finally:response['Body'].close()
    if len(raw)>4096 or hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('archive content mismatch')
    checkpoint=json.loads(raw);checkpoint_bytes(checkpoint)
    return {'status':'verified','checkpoint':checkpoint,'version_id':receipt['version_id'],
            'retain_until':retention['RetainUntilDate'].isoformat(),
            'signature_verification':'must also verify against server audit chain and separately retained HMAC keys'}


def archive_checkpoint(s3,config,checkpoint,now=None):
    body=checkpoint_bytes(checkpoint);sha=hashlib.sha256(body).hexdigest()
    if s3.get_object_lock_configuration(Bucket=config.bucket).get('ObjectLockConfiguration',{}).get('ObjectLockEnabled')!='Enabled':
        raise ValueError('Object Lock must be enabled')
    if s3.get_bucket_versioning(Bucket=config.bucket).get('Status')!='Enabled':raise ValueError('versioning required')
    until=((now or dt.datetime.now(dt.timezone.utc))+dt.timedelta(days=config.retain_days)).replace(microsecond=0)
    key=f'{config.prefix}/{checkpoint["database_instance"]}/{checkpoint["seq"]:012d}-{sha}.json'
    result=s3.put_object(Bucket=config.bucket,Key=key,Body=body,ContentType='application/json',
        ContentMD5=base64.b64encode(hashlib.md5(body,usedforsecurity=False).digest()).decode(),
        IfNoneMatch='*',ObjectLockMode='COMPLIANCE',ObjectLockRetainUntilDate=until)
    receipt={'bucket':config.bucket,'key':key,'version_id':result.get('VersionId'),'sha256':sha,
        'retain_until':until.isoformat(),'mode':'COMPLIANCE','database_instance':checkpoint['database_instance'],'seq':checkpoint['seq']}
    verify_archive(s3,config,receipt)
    return receipt

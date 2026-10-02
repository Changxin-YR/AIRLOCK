"""Actual S3 Object Lock contract in a uniquely owned, disposable container.

This tests API retention semantics, not resistance to a compromised Docker host.
No existing containers, buckets, volumes or cloud credentials are used.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from botocore.exceptions import ClientError,BotoCoreError
from airlock.archive import ArchiveConfig,client,archive_checkpoint,verify_archive
from airlock.models import Settings,Invocation
from airlock.service import Gate


def wait_ready(s3,attempts=100,pause=.1):
    # A newly published container port can reset connections before the S3
    # listener is ready. Retry this read-only readiness probe, never a mutation.
    for _ in range(attempts):
        try:s3.list_buckets();return
        except (BotoCoreError,ClientError):time.sleep(pause)
    raise RuntimeError('S3 fixture did not become ready')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',help='Explicit existing test image; otherwise read the source build report')
    parser.add_argument('--image-report',type=Path,default=Path('evidence/archive-image.json'));args=parser.parse_args()
    selected_image=args.image or json.loads(args.image_report.read_text())['runtime_image_id']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    name='airlock-archive-'+uuid.uuid4().hex[:12]
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    access='airlock-'+secrets.token_hex(8);secret=secrets.token_urlsafe(36)
    with tempfile.TemporaryDirectory(prefix='airlock-archive-') as temp:
        root=Path(temp);envfile=root/'minio.env'
        envfile.write_text(f'MINIO_ROOT_USER={access}\nMINIO_ROOT_PASSWORD={secret}\n',encoding='utf-8');envfile.chmod(0o600)
        created=False
        try:
            result=subprocess.run(['docker','run','--detach','--name',name,'--user','10001:10001','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges:true','--tmpfs','/data:rw,noexec,nosuid,size=64m,uid=10001,gid=10001',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--env-file',str(envfile),'-p',f'127.0.0.1:{port}:9000',
                selected_image,'server','/data','--address',':9000'],capture_output=True,text=True,timeout=180)
            if result.returncode:raise RuntimeError('Archive fixture container could not start: '+result.stderr[:500])
            created=True
            os.environ['AIRLOCK_ARCHIVE_ACCESS_KEY']=access;os.environ['AIRLOCK_ARCHIVE_SECRET_KEY']=secret
            config=ArchiveConfig(endpoint=f'http://127.0.0.1:{port}',bucket='airlock-evidence',retain_days=1)
            s3=client(config)
            wait_ready(s3)
            s3.create_bucket(Bucket=config.bucket,ObjectLockEnabledForBucket=True)
            gate=Gate(Settings(root/'target.sqlite','a'*32,'r'*32,'k'*32))
            action=gate.submit(Invocation(sql='DELETE FROM customers WHERE id=1',idempotency_key='archive-pending'))
            checkpoint=gate.store.checkpoint();receipt=archive_checkpoint(s3,config,checkpoint)
            result=verify_archive(s3,config,receipt)
            assert result['checkpoint']==checkpoint and action['state']=='pending'
            denied=[];errors={}
            for label,operation in [
                ('delete_exact_version',lambda:s3.delete_object(Bucket=config.bucket,Key=receipt['key'],VersionId=receipt['version_id'])),
                ('shorten_compliance',lambda:s3.put_object_retention(Bucket=config.bucket,Key=receipt['key'],VersionId=receipt['version_id'],Retention={'Mode':'COMPLIANCE','RetainUntilDate':dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=10)})),
                ('downgrade_to_governance',lambda:s3.put_object_retention(Bucket=config.bucket,Key=receipt['key'],VersionId=receipt['version_id'],Retention={'Mode':'GOVERNANCE','RetainUntilDate':dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)}))]:
                try:operation()
                except ClientError as exc:
                    # S3 uses AccessDenied; this pinned MinIO release reports
                    # some WORM violations as HTTP 400 InvalidRequest.
                    error=exc.response['Error'];status=exc.response['ResponseMetadata']['HTTPStatusCode']
                    assert status in {400,403} and error['Code'] in {'AccessDenied','InvalidRequest','InvalidArgument'}
                    assert verify_archive(s3,config,receipt)['checkpoint']==checkpoint
                    errors[label]={'http_status':status,'code':error['Code'],'message':error['Message']}
                    denied.append(label)
                else:raise AssertionError('Object Lock violation: '+label)
            # A new version is legal in S3. Retrieval must stay pinned to the
            # archived version, even when the newest body is unrelated.
            s3.put_object(Bucket=config.bucket,Key=receipt['key'],Body=b'unrelated new version')
            assert verify_archive(s3,config,receipt)['checkpoint']==checkpoint
            anchor=root/'anchor.json';anchor.write_text(json.dumps(result['checkpoint']))
            from dataclasses import replace
            anchored=Gate(replace(gate.settings,audit_anchor_file=anchor))
            assert anchored.store.verify_audit()['valid']
            with anchored.store.transaction() as conn:conn.execute('DELETE FROM audit')
            assert not anchored.store.verify_audit()['valid']
            with gate.store.connection() as conn:assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1206
            image=json.loads(subprocess.check_output(['docker','image','inspect',selected_image,'--format','{{json .RepoDigests}}']))
            image_id=subprocess.check_output(['docker','image','inspect',selected_image,'--format','{{.Id}}'],text=True).strip()
            report={'mode':'real_docker_s3_object_lock','image_digests':image,'runtime_image_id':image_id,'receipt':receipt,
                'checks':denied+['version_pinned_after_new_version','retrieved_anchor_detects_tail_deletion','unapproved_target_unchanged'],
                'actual_denials':errors,
                'credential_scope':'new synthetic fixture only; never read default AWS credentials',
                'retention_scope':'COMPLIANCE API semantics; temporary test container removed, not permanent production archive',
                'exit_code':0}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
            print(json.dumps(report))
        finally:
            if created:
                logs=subprocess.run(['docker','logs',name],capture_output=True,text=True,timeout=20)
                redacted=(logs.stdout+logs.stderr).replace(access,'[REDACTED]').replace(secret,'[REDACTED]')
                args.output.with_name(args.output.stem+'-container.log').write_text(redacted,encoding='utf-8')
                subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=30,check=True)


if __name__=='__main__':main()

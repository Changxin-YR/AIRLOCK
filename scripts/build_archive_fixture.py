"""Build the official archived MinIO source for isolated test use only.

No third-party replacement image is trusted. Record source/binary/image hashes;
the upstream source and AGPL license are pinned and included in the image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

SOURCE='https://github.com/minio/minio.git'
COMMIT='7aac2a2c5b7c882e68c1ce017d8256be2feea27f'


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='airlock-archive-build-') as folder:
        root=Path(folder)
        def run(command,**kwargs):return subprocess.run(command,cwd=root,check=True,**kwargs)
        run(['git','init','-q']);run(['git','remote','add','origin',SOURCE]);run(['git','fetch','--depth','1','origin',COMMIT]);run(['git','checkout','--detach','FETCH_HEAD'])
        observed=run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
        if observed!=COMMIT:raise ValueError('source identity mismatch')
        env=os.environ|{'CGO_ENABLED':'0','GOOS':'linux','GOARCH':'amd64'}
        run(['go','build','-p','2','-trimpath','-o','minio','.'],env=env,timeout=900)
        binary=hashlib.sha256((root/'minio').read_bytes()).hexdigest()
        (root/'Dockerfile.fixture').write_text('FROM scratch\nCOPY minio /minio\nCOPY LICENSE /LICENSE\nUSER 10001:10001\nENTRYPOINT ["/minio"]\n',encoding='utf-8')
        (root/'Dockerfile.fixture.dockerignore').write_text('*\n!minio\n!LICENSE\n!Dockerfile.fixture\n',encoding='utf-8')
        tag='airlock-archive-fixture:'+uuid.uuid4().hex[:12]
        run(['docker','build','-f','Dockerfile.fixture','-t',tag,'.'],timeout=120)
        image=run(['docker','image','inspect','--format','{{.Id}}',tag],text=True,capture_output=True).stdout.strip()
        report={'source':SOURCE,'source_commit':COMMIT,'binary_sha256':binary,'runtime_image_id':image,'local_tag':tag,
            'scope':'archived upstream source built only for throwaway S3 contract tests, not a production distribution recommendation'}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()

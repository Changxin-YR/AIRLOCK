"""Run on a separate custodian host with project-specific S3 credentials."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from airlock.archive import ArchiveConfig,client,archive_checkpoint,verify_archive


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path);parser.add_argument('--verify-receipt',type=Path)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if bool(args.checkpoint)==bool(args.verify_receipt):parser.error('choose checkpoint upload or receipt verification')
    config=ArchiveConfig.model_validate_json(args.config.read_text(encoding='utf-8'));s3=client(config)
    result=(archive_checkpoint(s3,config,json.loads(args.checkpoint.read_text(encoding='utf-8'))) if args.checkpoint
            else verify_archive(s3,config,json.loads(args.verify_receipt.read_text(encoding='utf-8'))))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='\n') as out:out.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'result_file':str(args.output),'version_id':result['version_id'],'status':result.get('status','archived_and_verified')}))


if __name__=='__main__':main()

import copy,contextlib,hashlib,io,json,subprocess,types
from pathlib import Path
root=Path.cwd();sha='4e512df4c65e9b94b7f210ed5483e612efb5eec1';name='scripts/verify_evidence.py'
raw=subprocess.check_output(['git','show',sha+':'+name]);m=types.ModuleType('baseline_gate');m.__file__=str(root/name);exec(compile(raw,str(root/name),'exec'),m.__dict__)
directory=root/'evidence/single-person-20261003/ci/verified';original=m.load
results=[]
for corrupt in (False,True):
 def load(d,n):
  result=original(d,n)
  if corrupt and n=='latency.json':
   for row in result['raw_read_pairs']:row['proxy_ms']+=300;row['added_ms']+=300
   for row in result['raw_writes']:row['static_ms']=1000;row['preview_ms']=7000
  return result
 m.load=load
 try:
  with contextlib.redirect_stdout(io.StringIO()):m.verify(directory)
  results.append({'probe':'over_threshold_raw_samples_with_unchanged_summary' if corrupt else 'original_positive_control','accepted':True})
 except Exception as e:results.append({'probe':str(corrupt),'accepted':False,'error':str(e)})
print(json.dumps({'baseline_commit':sha,'validator_sha256':hashlib.sha256(raw).hexdigest(),'probes':results,'meaning':'Hypothetical edited summaries, no actual performance regression or changed original evidence'},indent=2))

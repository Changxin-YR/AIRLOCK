"""Compare the committed historical n=1 interval with the current implementation."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmark.research import bootstrap_mean

baseline = '31cf0e76156f0b5a408756d45068f1a318cf856c'
raw = subprocess.run(['git', 'show', baseline + ':benchmark/research.py'],
                     cwd=ROOT, check=True, capture_output=True, text=True).stdout
namespace = {'__name__': 'historical_research_replay'}
exec(compile(raw, baseline + ':benchmark/research.py', 'exec'), namespace)
before = namespace['bootstrap_mean']([1250])
after = bootstrap_mean([1250])
if before['ci95'] != [1250, 1250] or after['ci95'] is not None or after['mean'] != 1250:
    raise AssertionError('single-participant regression result differs')
print(json.dumps({'status': 'PASS', 'historical_source': baseline, 'before': before,
                  'after': after, 'source': 'synthetic observation', 'real_humans': 0}, indent=2))

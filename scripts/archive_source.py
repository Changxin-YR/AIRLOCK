"""Archive this commit's source without recursively embedding past evidence ZIPs."""
import subprocess
from pathlib import Path

names=subprocess.run(['git','ls-tree','--name-only','HEAD'],text=True,capture_output=True,check=True).stdout.splitlines()
names=[n for n in names if n!='evidence']
Path('evidence').mkdir(exist_ok=True)
subprocess.run(['git','archive','--format=zip','HEAD','-o','evidence/source.zip',*names],check=True)
print('Archived tracked source and documentation; historical evidence remains separately versioned in Git.')

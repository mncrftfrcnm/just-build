import json, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent
for name,code,valid in [('good',0,True),('bad',1,False)]:
    p=subprocess.run([sys.executable,'-B',str(root/'app.py'),str(root/'examples'/f'{name}.csv'),'--json'],capture_output=True,text=True)
    assert p.returncode==code,(p.returncode,p.stderr)
    assert json.loads(p.stdout)['valid']==valid
print('Black-box fixture journey passed')

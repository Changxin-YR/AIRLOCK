import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

BASE = Path('var/closure2-20261003')
SHA = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()


def file_info(path):
    raw = path.read_bytes()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def result(directory, stem):
    receipt = json.loads((directory/(stem+'.log.status.json')).read_text())
    tests = list(ET.parse(directory/(stem+'.xml')).getroot().iter('testcase'))
    failed = sum(any(child.tag in ('failure','error') for child in case) for case in tests)
    skipped = sum(case.find('skipped') is not None for case in tests)
    return {'receipt':stem+'.log.status.json','command':receipt['command'],
        'exit_code':receipt['exit_code'],'tests':len(tests),'failed':failed,'skipped':skipped,
        'passed':len(tests)-failed-skipped,'tested_commit_sha':receipt['tested_commit_sha'],
        'tracked_source_dirty':receipt['tracked_source_dirty']}


def save(directory, report):
    (directory/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest = {'source_commit_at_review':SHA,'note':'Working tree source hashes identify pre-commit validation; not a frozen full-CI claim.',
        'files':{str(p.relative_to(directory)).replace('\\','/'):file_info(p) for p in sorted(directory.rglob('*'))
                 if p.is_file() and p.name not in ('MANIFEST.json',) and '__pycache__' not in p.parts}}
    (directory/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


directory = BASE/'transport'
save(directory, {
    'status':'PASS','scope':'Bounded HTTP/MCP adapter; isolated synthetic SQLite, local HTTP/TLS fixtures and MockTransport only.',
    'source_commit_at_review':SHA,'tracked_source_dirty':True,
    'application_files':{p:file_info(Path(p)) for p in ['airlock/network.py','airlock/upstream.py','airlock/mcp_upstream.py','airlock/mcp_http.py']},
    'changed_files':['airlock/network.py','airlock/upstream.py','airlock/mcp_upstream.py','tests/test_transport_hardening.py'],
    'runs':{s:result(directory,s) for s in ['baseline','repaired-original-probes','reconcile-baseline','reconcile-repaired','hardening','shared-client-compatibility']},
    'findings':[
        {'id':'T1','severity':'P1','issue':'MCP preview accepted non-finite JSON and crashed during review digest, leaving no durable blocked action; ambiguous keys and invalid Unicode also crossed response parsing.',
         'repair':'Strict UTF-8, unique keys, finite numbers and at most 32 nested levels before state construction; canonical errors become generic upstream errors; corrupted preview persists blocked with valid audit.'},
        {'id':'T2','severity':'P1','issue':'A peer dripping response headers bypassed the ten-second total request budget; baseline returned only after 11.583 seconds.',
         'repair':'One context-local deadline clamps each socket read/write/TLS step across the HTTP or multi-step MCP exchange. DNS waits at most two seconds within that deadline using at most four daemon lookup slots; timed-out workers cannot send.'},
        {'id':'T3','severity':'P2','issue':'Valid CR-only SSE events were dropped, and response decompression ran before application byte limits.',
         'repair':'Incremental CR/CRLF/LF and BOM handling, strict per-event JSON, identity encoding negotiation and rejection of compressed responses before decoding.'},
        {'id':'T4','severity':'P1','issue':'Unknown remote actions queried replacement target registrations; removed/revoked registrations escaped as authorization errors despite an already possible effect.',
         'repair':'Reconcile checks the original upstream config digest and keeps unknown without sending on config drift or revocation. Restoring the same registration permits GET-only recovery; no execution resend.'}
    ],
    'independent_second_direction':'../cross-transport/RESULT.json: 9 independent checks passed after original SSE replay failed; independent reviewer recovery_governance_audit.',
    'limits':['No production resolver/network reliability or formal MCP conformance claim.',
              'A timed-out OS DNS lookup may finish later in one of four daemon slots; the worker has no HTTP send path.',
              'Upstream effect+receipt is not a local distributed exactly-once guarantee; unknown must retain uncertainty.',
              'No real credentials, model calls, human participants or business logs were used.'],
    'unresolved_reproducible_findings':[]
})
directory = BASE/'cross-telemetry'
save(directory, {
    'status':'PASS','reviewer':'transport_adapter_audit; independent author from telemetry implementation',
    'source_commit_at_review':SHA,'tracked_source_dirty':True,
    'source_files':{p:file_info(Path(p)) for p in ['airlock/telemetry.py','airlock/network.py']},
    'runs':{s:result(directory,s) for s in ['first','repaired']},
    'finding':{'severity':'P1','issue':'Exporter advertised gzip but rejected the normal collector gzip response, causing repeated export failure.',
               'fix_by_implementation_author':'Send Accept-Encoding: identity; rerun the same nine independent probes.'},
    'checks':['Valid content encoding negotiation succeeds without changing pending approvals.',
              'Array/null/malformed partial-success/duplicate nested-key acknowledgements retain the original span.',
              'Redirect cannot contact another loopback collector.',
              'A concurrent newly enqueued span is not deleted by an in-flight prior batch acknowledgement.',
              'A dripping body expires; retry sends the identical deterministic span and counts one durable acknowledgement.'],
    'unresolved_findings':[],
    'limits':['Synthetic local collector only; production delivery remains at least once, not exactly once.',
              'No human, external service, model API, private credential or representative business log was used.']
})
print(json.dumps({'transport':str(BASE/'transport/RESULT.json'),'cross_telemetry':str(BASE/'cross-telemetry/RESULT.json')}))

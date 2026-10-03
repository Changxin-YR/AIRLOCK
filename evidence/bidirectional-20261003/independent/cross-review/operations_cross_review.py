"""Cross-author checks: synthetic local fixtures only, never real human evidence."""
import csv,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
sys.path.insert(0,str(Path.cwd()))
import httpx
from airlock.github_adapter import AdapterConfig,ExecuteRequest,IssueAdapter,IssueArguments,ObservedIssue,RelayCompletion
from airlock.models import GateError
from benchmark.research import Annotation,read_jsonl,loads_strict,study_report,kappa
from benchmark.closure import governance_report
from benchmark.pilot import load_annotations,summarize

out=Path('var/bidirectional-20261003/cross-review')
checks=[]
def record(name,details=None):checks.append({'name':name,'status':'PASS','details':details})
def rejects(name,fn,exceptions=(ValueError,GateError)):
 try:fn()
 except exceptions as error:record(name,{'exception':type(error).__name__,'code':getattr(error,'code',None)})
 else:raise AssertionError(name+' incorrectly accepted')
def cfg(mode='direct'):
 return AdapterConfig(repository_node_id='R_cross123',repository_full_name='fixture/project',public_repository=True,
  mode=mode,api_pinned_addresses=['140.82.112.6'] if mode=='direct' else [])
def make_request(adapter):
 args=IssueArguments(title='Synthetic cross-check',body='Not a real project mutation')
 return ExecuteRequest(action_id='a'*32,request_hash='b'*64,expected_version=adapter._plan_digest(args),arguments=args)
def observed(row):
 return ObservedIssue(repository_node_id='R_cross123',repository_full_name='fixture/project',issue_node_id='I_cross123',number=11,
   url='https://github.com/fixture/project/issues/11',title=row['title'],body=row['body'])
def persisted(adapter):
 with adapter.connection() as conn:return conn.execute('SELECT document FROM github_claims').fetchone()[0]
with tempfile.TemporaryDirectory() as folder:
 base=Path(folder)
 for first,second in [('github_response','github_readback'),('github_readback','github_response')]:
  adapter=IssueAdapter(cfg(),base/(first+'.sqlite3'));claim=[]
  def lost(row):claim.append(row);raise httpx.ReadTimeout('synthetic loss')
  adapter.api.create=lost
  request=make_request(adapter);assert adapter.execute(request)['state']=='unknown'
  issue=observed(claim[0]);receipt=adapter._complete(request.action_id,issue,first,None);before=persisted(adapter)
  assert adapter._complete(request.action_id,issue,second,None)==receipt
  assert persisted(adapter)==before
  record('direct_identical_effect_preserves_first_'+first,{'verification':receipt['result']['receipt_verification']})
  replacements={'repository_node_id':'R_other123','repository_full_name':'fixture/other','issue_node_id':'I_other123',
    'number':12,'url':'https://github.com/fixture/project/issues/12','title':'Substituted title','body':claim[0]['body']+' altered'}
  for field,value in replacements.items():
   rejects(first+'_rejects_replaced_'+field,lambda field=field,value=value:adapter._complete(request.action_id,issue.model_copy(update={field:value}),second,None))
   assert persisted(adapter)==before
  rejects(first+'_rejects_operator_attested_relabel',lambda:adapter._complete(request.action_id,issue,'operator_attested',None))
  rejects(first+'_rejects_different_existing_reconcile_target',lambda:adapter.reconcile_direct(request.action_id,'I_different'))
  assert persisted(adapter)==before
 adapter=IssueAdapter(cfg(),base/'parallel.sqlite3');claim=[]
 adapter.api.create=lost;request=make_request(adapter);adapter.execute(request);issue=observed(claim[0]);barrier=Barrier(2)
 def complete(method):barrier.wait(timeout=5);return adapter._complete(request.action_id,issue,method,None)
 with ThreadPoolExecutor(max_workers=2) as pool:receipts=list(pool.map(complete,['github_response','github_readback']))
 assert receipts[0]==receipts[1] and adapter.receipt(request.action_id)==receipts[0]
 record('simultaneous_direct_completion_has_one_immutable_receipt')
 relay=IssueAdapter(cfg('relay'),base/'relay.sqlite3');request=make_request(relay);relay.execute(request);claim=relay.claim(request.action_id)
 completion=RelayCompletion(claim_token=claim['claim_token'],binding_digest=claim['binding_digest'],observed_issue=observed(claim),observation_reference='synthetic-evidence-a')
 receipt=relay.complete_relay(request.action_id,completion);before=persisted(relay)
 assert relay.complete_relay(request.action_id,completion)==receipt
 rejects('relay_reference_change_is_not_normalized',lambda:relay.complete_relay(request.action_id,completion.model_copy(update={'observation_reference':'synthetic-evidence-b'})))
 rejects('relay_claim_change_rejected',lambda:relay.complete_relay(request.action_id,completion.model_copy(update={'claim_token':'x'*40})))
 assert persisted(relay)==before
 record('relay_exact_repeat_preserves_receipt')
 annotation={'case_id':'case-one','annotator_id':'fixture-person','human':True,'independent':True,'dangerous':False,'decision':'pass','rationale':'Synthetic compatibility check, not human evidence'}
 path=base/'valid.jsonl';path.write_text(json.dumps(annotation)+'\n',encoding='utf-8-sig')
 assert read_jsonl(path,Annotation)[0].model_dump()['human'] is True
 record('explicit_boolean_utf8_bom_jsonl_accepted')
 for field in ('human','independent'):
  for value in (1,1.0,'true',False,None):
   rejects('annotation_'+field+'_rejects_'+repr(value),lambda field=field,value=value:Annotation.model_validate(annotation|{field:value}))
 for raw in ['{"human":false,"human":true}','{"nested":{"source":"automation","source":"human"}}','{"value":NaN}']:
  rejects('strict_json_rejects_ambiguity_'+str(len(checks)),lambda raw=raw:loads_strict(raw))
 path=base/'pilot.csv'
 pilot={'case_id':'case-one','annotator_id':'fixture-person','source':'human','human':'true','independent':'true','dangerous':'false',
   'decision':'pass','risk_level':'low','reversibility':'reversible','rationale':'Synthetic compatibility check'}
 with path.open('w',encoding='utf-8-sig',newline='') as file:
  writer=csv.DictWriter(file,fieldnames=list(pilot));writer.writeheader();writer.writerow(pilot)
 rows,_=load_annotations(path);summary,_=summarize(['case-one'],rows,csv_input=True)
 assert summary['acceptance_metrics'] is None and summary['kappa'] is None
 record('legitimate_explicit_csv_is_still_descriptive_pilot')
 gold={'alpha':{'gold':'approve'},'beta':{'gold':'reject','check':{'answer':'all'}},'gamma':{'gold':'more_information','check':{'answer':'unknown'}}}
 session={'kind':'airlock-study-v1','participant_id':'fixture-person','source':'human','consent':True,'task_file_sha256':'synthetic-bound-hash',
  'responses':[{'case_id':'alpha','arm':'A','choice':'reject','correct':True,'visible_ms':1500,'comprehension_correct':True},
               {'case_id':'beta','arm':'B','choice':'reject','correct':False,'visible_ms':2000,'comprehension_correct':True,'comprehension_choice':'wrong'},
               {'case_id':'gamma','arm':'B','choice':'more_information','correct':False,'visible_ms':1000,'comprehension_correct':False,'comprehension_choice':'unknown'}]}
 report=study_report([session],gold,'synthetic-bound-hash')
 assert report['correct_decisions']=={'numerator':2,'denominator':3,'value':2/3}
 assert report['comprehension_correct']=={'numerator':1,'denominator':2,'value':.5}
 assert report['acceptance_metrics'] is None and report['paired_time_delta']['ci95'] is None
 assert 'comprehension_correct' not in report['participants'][0]['observations'][0]
 assert session['responses'][0]['comprehension_correct'] is True
 record('gold_recomputes_correctness_and_only_gold_backed_comprehension_denominator')
 assert study_report([session|{'source':'automation'}],gold)['human_participants']==0
 assert study_report([session|{'consent':1}],gold)['human_participants']==0
 rejects('study_bound_hash_mismatch',lambda:study_report([session],gold,'wrong-hash'))
 record('nonhuman_or_numeric_consent_never_counted')
 assert kappa([True,True,False,False],[True,False,False,False])['kappa']==.5
 assert kappa([True],[True])['kappa'] is None
 record('independent_kappa_arithmetic_and_degenerate_denominator')
 governance={'id':'fixture-row','source':'authorized_log','authorized':True,'authorization_reference':'synthetic-test-only',
  'participant_id':'fixture-person','date':'2024-02-29','task_id':'alpha','baseline_approvals':4,'actual_approvals':2,
  'eligible_requests':4,'displayed_groups':2,'readonly_pass':0,'duplicates_suppressed':0,'batch_reviewed':2,
  'incorrect_decisions':0,'same_task_quality':True}
 for day in ('2026-02-29','1900-02-29','2026-00-01','2026-10-32','2026-10-03T00:00:00','20261003','2026-W40-6','2026-10-03 '):
  rejects('governance_rejects_non_calendar_'+day,lambda day=day:governance_report([governance|{'date':day}]))
 for day in ('2024-02-29','2000-02-29','2026-10-03'):
  r=governance_report([governance|{'date':day},governance|{'date':day,'task_id':'beta'}]);assert r['active_user_days']==1 and r['daily_approvals']['value']==4
  record('governance_legitimate_day_groups_two_tasks_'+day)
 rejects('governance_exact_task_day_duplicate',lambda:governance_report([governance,governance]))
 assert governance_report([governance|{'authorized':1}])['active_user_days']==0
 assert governance_report([governance|{'authorization_reference':' '}])['active_user_days']==0
 assert governance_report([])['daily_approvals']['value'] is None
 record('governance_numeric_authorization_blank_reference_and_empty_denominator')
result={'status':'PASS','tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
 'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['airlock/github_adapter.py','benchmark/research.py','benchmark/closure.py','benchmark/pilot.py']},
 'checks':checks,'check_count':len(checks),'findings':[],
 'limitations':['Synthetic local database and modelled API responses only; no live GitHub mutation or API key.','All human/authorized_log fixture declarations are automated test data, not genuine participants or business evidence.','Governance dates are validated as ISO calendar days; source authenticity and study-period eligibility remain external provenance validation.']}
(out/'operations-cross-review.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False))

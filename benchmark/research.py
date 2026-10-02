"""Source-backed corpus, independent labels and offline-safe research analysis.

Author labels, generated variants and browser automation are never human gold.
The production gate is not changed by any ablation in this module.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from airlock.models import Invocation, canonical


class Case(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id: str=Field(min_length=1,max_length=100)
    family: str=Field(min_length=1,max_length=100)
    split: Literal['dev','test','holdout']
    source_type: Literal['synthetic','public_incident','authorized_log','expert']
    source_reference: str=Field(min_length=1,max_length=1000)
    source_version: str=Field(min_length=1,max_length=200)
    authorization_reference: str | None=Field(default=None,max_length=1000)
    reconstruction_limitations: str | None=Field(default=None,max_length=2000)
    source_artifact_sha256: str | None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    business_intent: str=Field(min_length=1,max_length=2000)
    request: Invocation
    expected_decision: Literal['pass','need_approval','block']
    dangerous: bool
    risk_level: Literal['low','medium','high','critical','unknown']='unknown'
    reversibility: Literal['reversible','compensatable','irreversible','unknown']='unknown'
    adapter: str='sqlite_customers'
    snapshot_reference: str='unknown'
    expected_changed_rows: int | None=Field(ge=0,le=5000)
    impact_origin: str=Field(min_length=1,max_length=1000)
    scenario: Literal['read','write','destructive','injection','recovery','remote','other']

    @model_validator(mode='after')
    def source_provenance(self):
        if self.source_type=='authorized_log' and not self.authorization_reference:raise ValueError('log authorization reference required')
        if self.source_type=='public_incident' and (not self.reconstruction_limitations or not self.source_artifact_sha256):
            raise ValueError('public reconstruction requires source hash and limitations')
        return self


class Annotation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    case_id: str
    annotator_id: str=Field(min_length=3,max_length=100)
    human: Literal[True]
    independent: Literal[True]
    dangerous: bool
    decision: Literal['pass','need_approval','block']
    risk_level: Literal['low','medium','high','critical','unknown']='unknown'
    reversibility: Literal['reversible','compensatable','irreversible','unknown']='unknown'
    rationale: str=Field(min_length=3,max_length=2000)


def read_jsonl(path,model):
    return [model.model_validate_json(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def validate_corpus(cases):
    if not cases or len({c.id for c in cases})!=len(cases): raise ValueError('empty corpus or duplicate case ID')
    families={}
    payloads={}
    for case in cases:
        if families.setdefault(case.family,case.split)!=case.split: raise ValueError('family leakage across splits')
        request=case.request.model_dump(exclude={'idempotency_key'})
        key=canonical({'request':request,'intent':case.business_intent})
        if payloads.setdefault(key,case.split)!=case.split: raise ValueError('duplicate request and intent across splits')
    return {'cases':len(cases),'families':len(families),'sources':dict(Counter(c.source_type for c in cases)),
        'splits':dict(Counter(c.split for c in cases)),
        'sha256':hashlib.sha256(('\n'.join(canonical(c.model_dump()) for c in cases)+'\n').encode()).hexdigest()}


def kappa(left,right):
    if len(left)!=len(right): raise ValueError('unpaired labels')
    if not left: return {'n':0,'observed_agreement':None,'expected_agreement':None,'kappa':None}
    n=len(left); a,b=Counter(left),Counter(right)
    observed=sum(x==y for x,y in zip(left,right))/n
    expected=sum(a[label]*b[label] for label in a.keys()|b.keys())/(n*n)
    return {'n':n,'observed_agreement':observed,'expected_agreement':expected,
            'kappa':(observed-expected)/(1-expected) if expected<1 else None}


def annotations_report(cases,annotations):
    ids={c.id for c in cases}; grouped={}; annotators=set()
    for row in annotations:
        if row.case_id not in ids: raise ValueError('annotation references unknown case')
        key=(row.case_id,row.annotator_id)
        if key in grouped: raise ValueError('duplicate annotation')
        grouped[key]=row; annotators.add(row.annotator_id)
    if annotations and len(annotators)!=2: raise ValueError('exactly two independent annotators required')
    people=sorted(annotators)
    pairs=[(grouped[(i,people[0])],grouped[(i,people[1])]) for i in sorted(ids)
        if len(people)==2 and all((i,p) in grouped for p in people)]
    disagreements=[a.case_id for a,b in pairs if (a.dangerous,a.decision,a.risk_level,a.reversibility)!=(b.dangerous,b.decision,b.risk_level,b.reversibility)]
    return {'annotators':people,'paired_cases':len(pairs),'corpus_cases':len(ids),
        'danger_kappa':kappa([a.dangerous for a,b in pairs],[b.dangerous for a,b in pairs]),
        'decision_kappa':kappa([a.decision for a,b in pairs],[b.decision for a,b in pairs]),
        'risk_kappa':kappa([a.risk_level for a,b in pairs],[b.risk_level for a,b in pairs]),
        'reversibility_kappa':kappa([a.reversibility for a,b in pairs],[b.reversibility for a,b in pairs]),
        'unadjudicated_case_ids':disagreements,'status':'BLOCKED_EXTERNAL' if len(pairs)<len(ids) or disagreements else 'READY_FOR_ADJUDICATED_EVALUATION',
        'provenance':'human and independence are declared by supplied records; authenticate study identities separately'}


def ratio(num,den): return {'numerator':num,'denominator':den,'value':num/den if den else None}


def classification(rows):
    positives=[r for r in rows if r['dangerous']]; negatives=[r for r in rows if not r['dangerous']]
    predicted=[r for r in rows if r['prediction']!='pass']
    tp=sum(r['prediction']!='pass' for r in positives)
    # A policy's review/block result measures protective coverage, not whether
    # a semantic classifier recognized danger. Unknown predictions stay visible.
    known=[r for r in rows if type(r.get('predicted_dangerous')) is bool]
    risk_positive=[r for r in known if r['dangerous']]
    risk_negative=[r for r in known if not r['dangerous']]
    risk_tp=sum(r['predicted_dangerous'] for r in risk_positive)
    risk_fp=sum(r['predicted_dangerous'] for r in risk_negative)
    impact=[r for r in rows if r.get('expected_changed_rows') is not None and r.get('actual_changed_rows') is not None]
    nonzero=[r for r in impact if r['expected_changed_rows']!=0]
    zeros=[r for r in impact if r['expected_changed_rows']==0]
    return {'n':len(rows),'confusion':dict(Counter(r['expected_decision']+'->'+r['prediction'] for r in rows)),
        'danger_recall':ratio(risk_tp,len(risk_positive)),'danger_precision':ratio(risk_tp,risk_tp+risk_fp),
        'safe_false_positive_rate':ratio(risk_fp,len(risk_negative)),
        'semantic_prediction_coverage':ratio(len(known),len(rows)),
        'semantic_unknown_case_ids':[r.get('id') for r in rows if type(r.get('predicted_dangerous')) is not bool],
        'conservative_danger_detection':ratio(risk_tp,len(positives)) if known else ratio(0,0),
        'protection_recall':ratio(tp,len(positives)),'protection_precision':ratio(tp,len(predicted)),
        'safe_extra_gating_rate':ratio(sum(r['prediction']!='pass' for r in negatives),len(negatives)),
        'expected_pass_extra_gating_rate':ratio(sum(r['prediction']!='pass' for r in rows if r['expected_decision']=='pass'),sum(r['expected_decision']=='pass' for r in rows)),
        'exact_policy_accuracy':ratio(sum(r['prediction']==r['expected_decision'] for r in rows),len(rows)),
        'impact_exact':ratio(sum(r['expected_changed_rows']==r['actual_changed_rows'] for r in impact),len(impact)),
        'impact_mae':statistics.mean(abs(r['expected_changed_rows']-r['actual_changed_rows']) for r in impact) if impact else None,
        'impact_coverage':ratio(len(impact),len(rows)),
        'impact_within_5_percent':ratio(sum(abs(r['expected_changed_rows']-r['actual_changed_rows'])/r['expected_changed_rows']<=.05 for r in nonzero),len(nonzero)),
        'impact_relative_errors':[{'id':r.get('id'),'relative_error':(r['actual_changed_rows']-r['expected_changed_rows'])/r['expected_changed_rows']} for r in nonzero],
        'zero_impact_cases':len(zeros),'zero_impact_false_changes':[r.get('id') for r in zeros if r['actual_changed_rows']!=0]}


def bootstrap_mean(values,seed=2073,repeats=2000):
    if not values: return {'n':0,'mean':None,'ci95':None}
    rng=random.Random(seed)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(repeats))
    return {'n':len(values),'mean':statistics.mean(values),'ci95':[means[int(.025*repeats)],means[min(repeats-1,int(.975*repeats))]],
        'method':'percentile bootstrap over independent participants; descriptive, not power evidence'}


def study_report(sessions,task_gold=None,task_file_sha256=None):
    included=[]; excluded=[]; seen=set()
    for session in sessions:
        identifier=session.get('participant_id')
        if session.get('kind')!='airlock-study-v1' or not identifier or identifier in seen or session.get('source')!='human' or session.get('consent') is not True:
            excluded.append({'participant_id':identifier,'reason':'nonhuman, no consent, duplicate or invalid metadata'}); continue
        seen.add(identifier); cells={}
        if task_file_sha256 and session.get('task_file_sha256')!=task_file_sha256:raise ValueError('study task file mismatch')
        for event in session.get('responses',[]):
            event=dict(event)
            arm=event.get('arm'); ms=event.get('visible_ms'); correct=event.get('correct')
            if arm not in {'A','B'} or type(ms) not in (int,float) or not math.isfinite(ms) or ms<0 or type(correct)!=bool:
                raise ValueError('invalid study observation')
            case=event.get('case_id')
            if case in cells: raise ValueError('same participant saw the same case twice')
            if task_gold is not None:
                if case not in task_gold or event.get('choice') not in {'approve','reject','more_information'}:raise ValueError('unknown study choice or case')
                event['correct']=event['choice']==task_gold[case]['gold']
                check=task_gold[case].get('check')
                if check: event['comprehension_correct']=event.get('comprehension_choice')==check['answer']
            cells[case]=event
        arms={a:[r for r in cells.values() if r['arm']==a] for a in ('A','B')}
        if not all(arms.values()): excluded.append({'participant_id':identifier,'reason':'incomplete paired arms'}); continue
        means={a:statistics.mean(r['visible_ms'] for r in arms[a]) for a in arms}
        accuracy={a:statistics.mean(r['correct'] for r in arms[a]) for a in arms}
        observations=list(cells.values())
        approvals=[r for r in observations if r.get('choice')=='approve']
        included.append({'participant_id':identifier,'visible_ms':means,'accuracy':accuracy,
            'observations':observations,'fast_approval_proxy':ratio(sum(r['visible_ms']<1000 for r in approvals),len(approvals)),
            'delta_B_minus_A_ms':means['B']-means['A'],'accuracy_delta_B_minus_A':accuracy['B']-accuracy['A']})
    observations=[r for p in included for r in p['observations']]
    times=sorted(r['visible_ms'] for r in observations)
    return {'status':'BLOCKED_EXTERNAL' if not included else 'OBSERVED_SELF_REPORTED_HUMANS',
        'human_participants':len(included),'excluded':excluded,'participants':included,
        'paired_time_delta':bootstrap_mean([r['delta_B_minus_A_ms'] for r in included]),
        'paired_accuracy_delta':bootstrap_mean([r['accuracy_delta_B_minus_A'] for r in included]),
        'all_decisions_visible_ms':{'n':len(times),'mean':statistics.mean(times) if times else None,
            'median':statistics.median(times) if times else None,'p95':times[math.ceil(.95*len(times))-1] if times else None},
        'correct_decisions':ratio(sum(r['correct'] for r in observations),len(observations)),
        'gold_verification':'recomputed_from_supplied_task_file' if task_gold is not None else 'unverified_browser_supplied_correctness',
        'comprehension_correct':ratio(sum(r['comprehension_correct'] for r in observations if type(r.get('comprehension_correct')) is bool),sum(type(r.get('comprehension_correct')) is bool for r in observations)),
        'limitations':['No causal efficiency claim without recruitment, business gold, counterbalancing and adequate sample size.',
            'Exported browser timing and human identity are untrusted telemetry, never authorization.',
            'Visibility duration excludes hidden tabs; correctness is supplied task gold, not a policy guess.']}


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='command',required=True)
    corpus=sub.add_parser('corpus'); corpus.add_argument('cases',type=Path); corpus.add_argument('--annotations',type=Path); corpus.add_argument('--freeze',type=Path)
    study=sub.add_parser('study'); study.add_argument('sessions',type=Path,nargs='*')
    parser.add_argument('--output',type=Path,required=True); args=parser.parse_args()
    if args.command=='corpus':
        cases=read_jsonl(args.cases,Case); result=validate_corpus(cases)
        result['annotations']=annotations_report(cases,read_jsonl(args.annotations,Annotation) if args.annotations else [])
        if args.freeze:
            if args.freeze.exists() and json.loads(args.freeze.read_text())!=result: raise ValueError('frozen manifest differs; create a NEW corpus version')
            args.freeze.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    else: result=study_report([json.loads(p.read_text(encoding='utf-8')) for p in args.sessions])
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()

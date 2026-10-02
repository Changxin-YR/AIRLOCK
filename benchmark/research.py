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
    disagreements=[a.case_id for a,b in pairs if (a.dangerous,a.decision)!=(b.dangerous,b.decision)]
    return {'annotators':people,'paired_cases':len(pairs),'corpus_cases':len(ids),
        'danger_kappa':kappa([a.dangerous for a,b in pairs],[b.dangerous for a,b in pairs]),
        'decision_kappa':kappa([a.decision for a,b in pairs],[b.decision for a,b in pairs]),
        'unadjudicated_case_ids':disagreements,'status':'BLOCKED_EXTERNAL' if len(pairs)<len(ids) or disagreements else 'READY_FOR_ADJUDICATED_EVALUATION',
        'provenance':'human and independence are declared by supplied records; authenticate study identities separately'}


def ratio(num,den): return {'numerator':num,'denominator':den,'value':num/den if den else None}


def classification(rows):
    positives=[r for r in rows if r['dangerous']]; negatives=[r for r in rows if not r['dangerous']]
    predicted=[r for r in rows if r['prediction']!='pass']
    tp=sum(r['prediction']!='pass' for r in positives)
    impact=[r for r in rows if r.get('expected_changed_rows') is not None and r.get('actual_changed_rows') is not None]
    return {'n':len(rows),'confusion':dict(Counter(r['expected_decision']+'->'+r['prediction'] for r in rows)),
        'danger_recall':ratio(tp,len(positives)),'danger_precision':ratio(tp,len(predicted)),
        'safe_false_positive_rate':ratio(sum(r['prediction']!='pass' for r in negatives),len(negatives)),
        'exact_policy_accuracy':ratio(sum(r['prediction']==r['expected_decision'] for r in rows),len(rows)),
        'impact_exact':ratio(sum(r['expected_changed_rows']==r['actual_changed_rows'] for r in impact),len(impact)),
        'impact_mae':statistics.mean(abs(r['expected_changed_rows']-r['actual_changed_rows']) for r in impact) if impact else None,
        'zero_impact_cases':sum(r['expected_changed_rows']==0 for r in impact)}


def bootstrap_mean(values,seed=2073,repeats=2000):
    if not values: return {'n':0,'mean':None,'ci95':None}
    rng=random.Random(seed)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(repeats))
    return {'n':len(values),'mean':statistics.mean(values),'ci95':[means[int(.025*repeats)],means[min(repeats-1,int(.975*repeats))]],
        'method':'percentile bootstrap over independent participants; descriptive, not power evidence'}


def study_report(sessions):
    included=[]; excluded=[]; seen=set()
    for session in sessions:
        identifier=session.get('participant_id')
        if session.get('kind')!='airlock-study-v1' or not identifier or identifier in seen or session.get('source')!='human' or session.get('consent') is not True:
            excluded.append({'participant_id':identifier,'reason':'nonhuman, no consent, duplicate or invalid metadata'}); continue
        seen.add(identifier); cells={}
        for event in session.get('responses',[]):
            arm=event.get('arm'); ms=event.get('visible_ms'); correct=event.get('correct')
            if arm not in {'A','B'} or type(ms) not in (int,float) or not math.isfinite(ms) or ms<0 or type(correct)!=bool:
                raise ValueError('invalid study observation')
            case=event.get('case_id')
            if case in cells: raise ValueError('same participant saw the same case twice')
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

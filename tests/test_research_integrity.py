"""Synthetic counterexamples for research declarations and metric provenance."""
import json
import subprocess
import sys

import pytest

from benchmark.closure import governance_report
from benchmark.research import Annotation, loads_strict, read_jsonl, study_report


def annotation(**updates):
    return dict(case_id='fixture-case',annotator_id='fixture-person',human=True,
                independent=True,dangerous=False,decision='pass',
                rationale='Synthetic test record, not human evidence') | updates


@pytest.mark.parametrize('field',['human','independent'])
@pytest.mark.parametrize('value',[1,1.0,'true',False,None])
def test_formal_annotation_requires_actual_true_booleans(field,value):
    with pytest.raises(ValueError,match='explicit true boolean'):
        Annotation.model_validate(annotation(**{field:value}))


@pytest.mark.parametrize('identity',['   ','person-a ',' person-a','person\na'])
def test_formal_annotator_identity_rejects_whitespace_aliases(identity):
    with pytest.raises(ValueError):
        Annotation.model_validate(annotation(annotator_id=identity))


def test_blank_rationale_cannot_complete_formal_annotations():
    with pytest.raises(ValueError,match='nonblank annotation rationale'):
        Annotation.model_validate(annotation(rationale='   '))


def test_formal_jsonl_rejects_contradictory_source_declaration(tmp_path):
    path=tmp_path/'annotations.jsonl'
    raw=json.dumps(annotation()).replace('"human": true','"human": false, "human": true')
    path.write_text(raw+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='duplicate JSON field'):
        read_jsonl(path,Annotation)
    # Normal UTF-8 BOM exports retain explicit true statements and their IDs.
    path.write_text(json.dumps(annotation())+'\n',encoding='utf-8-sig')
    assert read_jsonl(path,Annotation)[0].human is True


def session(**updates):
    return dict(kind='airlock-study-v1',participant_id='synthetic-person',source='human',consent=True,
                task_file_sha256='test-task-hash',responses=[
                    dict(case_id='one',arm='A',choice='approve',correct=True,visible_ms=2000,comprehension_correct=True),
                    dict(case_id='two',arm='B',choice='reject',correct=False,visible_ms=2500,comprehension_correct=True),
                ]) | updates


def test_bound_task_gold_excludes_browser_invented_comprehension_successes():
    gold={'one':{'gold':'approve'},'two':{'gold':'reject','check':{'answer':'many'}}}
    result=study_report([session()],gold,'test-task-hash')
    assert result['correct_decisions']=={'numerator':2,'denominator':2,'value':1}
    assert result['comprehension_correct']=={'numerator':0,'denominator':1,'value':0}
    assert 'comprehension_correct' not in result['participants'][0]['observations'][0]
    assert result['acceptance_metrics'] is None
    assert result['paired_time_delta']['ci95'] is None
    gold['two'].pop('check')
    assert study_report([session()],gold)['comprehension_correct']['value'] is None


@pytest.mark.parametrize('identity',[' ','person ',' person',1,[]])
def test_study_invalid_identity_does_not_create_participant(identity):
    result=study_report([session(participant_id=identity)])
    assert result['human_participants']==0
    assert result['acceptance_metrics'] is None


def governance(**updates):
    return dict(id='fixture-row',source='authorized_log',authorized=True,
                authorization_reference='synthetic-test-declaration',participant_id='fixture-person',
                date='2026-10-03',task_id='fixture-task',baseline_approvals=2,actual_approvals=1,
                eligible_requests=2,displayed_groups=1,readonly_pass=0,duplicates_suppressed=0,
                batch_reviewed=0,incorrect_decisions=0,same_task_quality=True) | updates


@pytest.mark.parametrize('day',['2026-99-99','2026-02-29','20261003','2026-W40-6',None,1,'2026-10-03 '])
def test_governance_invalid_calendar_day_cannot_inflate_active_user_days(day):
    with pytest.raises(ValueError,match='calendar date'):
        governance_report([governance(date=day)])


def test_governance_real_day_groups_tasks_and_preserves_empty_denominator():
    result=governance_report([governance(),governance(task_id='second-task')])
    assert result['active_user_days']==1 and result['daily_approvals']['value']==2
    assert governance_report([])['daily_approvals']['value'] is None
    with pytest.raises(ValueError,match='duplicate'):
        governance_report([governance(),governance()])
    assert governance_report([governance(authorization_reference=' ')])['tasks']==0
    assert governance_report([governance(source='synthetic')])['tasks']==0


def test_research_cli_round_trip_and_duplicate_source_rejection(tmp_path):
    tasks=tmp_path/'tasks.json';export=tmp_path/'session.json';output=tmp_path/'report.json'
    tasks.write_text(json.dumps({'tasks':[{'id':'one','gold':'approve'},{'id':'two','gold':'reject'}]}),encoding='utf-8')
    import hashlib
    export.write_text(json.dumps(session(task_file_sha256=hashlib.sha256(tasks.read_bytes()).hexdigest())),encoding='utf-8')
    command=[sys.executable,'-m','benchmark.closure','--output',str(output),'study','--tasks',str(tasks),str(export)]
    completed=subprocess.run(command,capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    report=json.loads(output.read_text(encoding='utf-8'))
    assert report['human_participants']==1 and report['acceptance_metrics'] is None
    assert report['comprehension_correct']['denominator']==0
    rejected=tmp_path/'rejected.json';command[command.index(str(output))]=str(rejected)
    export.write_text(export.read_text(encoding='utf-8').replace('"source": "human"','"source": "model", "source": "human"'),encoding='utf-8')
    completed=subprocess.run(command,capture_output=True,text=True)
    assert completed.returncode!=0 and not rejected.exists()


@pytest.mark.parametrize('payload',['{"authorized":false,"authorized":true}','{"nested":{"source":"model","source":"human"}}','{"cost":NaN}'])
def test_strict_json_rejects_ambiguous_or_nonfinite_evidence(payload):
    with pytest.raises(ValueError):loads_strict(payload)

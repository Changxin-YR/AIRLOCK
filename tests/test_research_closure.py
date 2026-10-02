import hashlib
import json
import pytest
from benchmark.closure import prepare,evaluate,governance_report,Prediction
from benchmark.research import Case,Annotation,study_report


def case(**overrides):
    return Case.model_validate({'id':'one','family':'family-one','split':'dev','source_type':'synthetic','source_reference':'test fixture',
        'source_version':'1','business_intent':'authorized change','request':{'sql':'DELETE FROM customers WHERE id=1','idempotency_key':'research-fixture'},
        'expected_decision':'need_approval','dangerous':False,'risk_level':'low','reversibility':'compensatable',
        'expected_changed_rows':1,'impact_origin':'fixture construction','scenario':'write'}|overrides)


def test_prepare_never_creates_fake_annotations_and_missing_gold_blocks(tmp_path):
    c=case();result=prepare([c],tmp_path/'research')
    assert result['human_records_created']==0
    template=json.loads((tmp_path/'research/annotator-a.template.jsonl').read_text())
    assert template['human'] is None and template['dangerous'] is None
    prediction=Prediction(id=c.id,prediction='need_approval',predicted_dangerous=False,actual_changed_rows=1,
        reason='fixture',latency_ms=1,predictor_version='unit-test')
    report=evaluate([c],[prediction])
    assert report['status']=='BLOCKED_EXTERNAL' and report['acceptance_metrics'] is None
    assert report['candidate_metrics']['safe_false_positive_rate']['value']==0
    labels=[Annotation(case_id=c.id,annotator_id=p,human=True,independent=True,dangerous=False,decision='need_approval',risk_level='low',
        reversibility='compensatable',rationale='unit test records only') for p in ('person-one','person-two')]
    report=evaluate([c],[prediction],labels)
    assert report['acceptance_metrics']['safe_extra_gating_rate']['value']==1
    assert report['acceptance_metrics']['expected_pass_extra_gating_rate']['value'] is None
    # Disagreement only on reversibility must still require adjudication.
    labels[1]=labels[1].model_copy(update={'reversibility':'unknown'})
    assert evaluate([c],[prediction],labels)['status']=='BLOCKED_EXTERNAL'
    with pytest.raises(ValueError,match='exactly cover'):evaluate([c],[])
    with pytest.raises(ValueError,match='tuning'):evaluate([case(split='holdout')],[prediction],tuning=True)


def test_study_recomputes_correctness_and_comprehension_from_bound_gold():
    gold={'one':{'gold':'reject','check':{'answer':'many'}},'two':{'gold':'approve'}}
    session={'kind':'airlock-study-v1','participant_id':'test-person','source':'human','consent':True,'task_file_sha256':'bound',
        'responses':[{'case_id':'one','arm':'A','choice':'approve','correct':True,'visible_ms':400,'comprehension_choice':'one'},
                     {'case_id':'two','arm':'B','choice':'approve','correct':True,'visible_ms':1500}]}
    result=study_report([session],gold,'bound')
    assert result['correct_decisions']['value']==.5 and result['comprehension_correct']['value']==0
    with pytest.raises(ValueError,match='mismatch'):study_report([session],gold,'different')


def test_governance_keeps_quality_mismatch_and_zero_denominators_visible():
    base={'id':'a','source':'authorized_log','authorized':True,'authorization_reference':'test-only','participant_id':'fixture-user',
        'date':'2026-10-02','task_id':'one','baseline_approvals':0,'actual_approvals':0,'eligible_requests':0,'displayed_groups':0,
        'readonly_pass':5,'duplicates_suppressed':0,'batch_reviewed':0,'incorrect_decisions':0,'same_task_quality':True}
    result=governance_report([base])
    assert result['daily_approvals']['value']==0 and result['quality_matched_approval_reduction']['value'] is None
    assert result['eligible_fold_rate']['value'] is None
    mismatch=base|{'id':'b','task_id':'two','baseline_approvals':10,'actual_approvals':1,'same_task_quality':False}
    result=governance_report([base,mismatch])
    assert result['active_user_days']==1 and result['quality_mismatch_tasks']==1
    assert result['quality_matched_approval_reduction']['value'] is None
    assert governance_report([base|{'source':'synthetic'}])['status']=='BLOCKED_EXTERNAL'


def test_real_source_claims_require_provenance_fields():
    with pytest.raises(ValueError):case(source_type='authorized_log')
    with pytest.raises(ValueError):case(source_type='public_incident')

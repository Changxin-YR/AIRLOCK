import pytest
from benchmark.research import kappa,classification,study_report,Case,validate_corpus,annotations_report,Annotation

def test_kappa_independent_hand_calculation_and_degenerate():
    result=kappa([True,True,False,False],[True,False,False,False])
    assert result['observed_agreement']==.75 and result['expected_agreement']==.5 and result['kappa']==.5
    assert kappa([],[])['kappa'] is None
    assert kappa([True],[True])['kappa'] is None

def test_no_fake_zero_denominators_or_human_results():
    assert classification([])['danger_recall']['value'] is None
    result=study_report([{'kind':'airlock-study-v1','participant_id':'bot','source':'automation','consent':True}])
    assert result['human_participants']==0 and result['paired_time_delta']['mean'] is None

def test_family_leakage_and_independent_annotations():
    data={'id':'case-a','family':'family-a','split':'dev','source_type':'synthetic','source_reference':'author',
        'source_version':'1','business_intent':'read only','request':{'sql':'SELECT 1','idempotency_key':'research-001'},
        'expected_decision':'pass','dangerous':False,'expected_changed_rows':0,'impact_origin':'no writes', 'scenario':'read'}
    a=Case.model_validate(data); b=Case.model_validate(dict(data,id='case-b',split='test'))
    with pytest.raises(ValueError,match='leakage'): validate_corpus([a,b])
    assert annotations_report([a],[])['status']=='BLOCKED_EXTERNAL'
    labels=[Annotation(case_id=a.id,annotator_id=p,human=True,independent=True,dangerous=False,decision='pass',rationale='Business intent permits read') for p in ('one','two')]
    assert annotations_report([a],labels)['paired_cases']==1
    with pytest.raises(ValueError): annotations_report([a],[labels[0],labels[0]])

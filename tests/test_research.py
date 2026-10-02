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


def test_semantic_risk_is_separate_from_review_floor_and_unknown_impact():
    rows=[{'id':'danger','dangerous':True,'expected_decision':'need_approval','prediction':'need_approval','predicted_dangerous':False,'expected_changed_rows':100,'actual_changed_rows':106},
          {'id':'safe-write','dangerous':False,'expected_decision':'need_approval','prediction':'need_approval','predicted_dangerous':False,'expected_changed_rows':0,'actual_changed_rows':0},
          {'id':'unknown','dangerous':True,'expected_decision':'block','prediction':'block','expected_changed_rows':None,'actual_changed_rows':None}]
    result=classification(rows)
    assert result['protection_recall']['value']==1
    assert result['danger_recall']['value']==0 and result['safe_false_positive_rate']['value']==0
    assert result['semantic_prediction_coverage']['value']==2/3 and result['semantic_unknown_case_ids']==['unknown']
    assert result['impact_within_5_percent']=={'numerator':0,'denominator':1,'value':0}
    assert result['zero_impact_cases']==1 and result['zero_impact_false_changes']==[]
    assert result['impact_coverage']['value']==2/3

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

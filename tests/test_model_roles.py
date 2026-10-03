import pytest
from pydantic import ValidationError
from benchmark.model_roles import ModelAnnotation, paired_model_report, blind_study_tasks
from benchmark.research import Annotation, study_report


def model(actor='model-a', **kw):
    return ModelAnnotation(case_id='case-1', annotator_id=actor, dangerous=False,
                           decision='need_approval', risk_level='low', reversibility='compensatable',
                           impact_units_observed=1, rationale='Fixture model, not human.', uncertainty='', **kw)


def test_model_labels_cannot_claim_or_enter_human_annotation():
    with pytest.raises(ValidationError):
        model(human=True)
    with pytest.raises(ValidationError):
        model(independent_human=True)
    with pytest.raises(ValidationError):
        Annotation.model_validate(model().model_dump())


def test_model_agreement_preserves_disagreement_without_human_acceptance():
    a = model().model_dump()
    b = model('model-b').model_dump() | {'decision': 'block'}
    r = paired_model_report([a], [b])
    assert r['fields']['decision']['agreement_count'] == 0
    assert r['fields']['decision']['disagreement_case_ids'] == ['case-1']
    assert r['human_cohen_kappa'] is None and r['acceptance_metrics'] is None
    assert r['human_participants'] == 0
    with pytest.raises(ValueError):
        paired_model_report([a, a], [b])
    with pytest.raises(ValueError):
        paired_model_report([a], [b | {'case_id': 'other'}])
    with pytest.raises(ValueError):
        paired_model_report([a], [a])


def test_model_study_packet_blinds_gold_and_hides_diff_in_a():
    tasks = [{'id': label, 'intent': 'allowed one row', 'sql': 'DELETE FROM customers',
              'diff': 'all rows', 'gold': 'reject', 'check': {'answer': 'all rows'}}
             for label in ('authorized-one', 'unauthorized-all')]
    packets = blind_study_tasks(tasks)
    assert [r['case_id'] for r in packets] == ['study-001', 'study-002']
    assert packets[0]['arm'] == 'A' and 'diff' not in packets[0]
    assert packets[1]['arm'] == 'B' and packets[1]['diff'] == 'all rows'
    assert all('gold' not in r and 'check' not in r for r in packets)
    assert not any(original['id'] in str(packets) for original in tasks)
    assert tasks[0]['id'] == 'authorized-one'  # Private source remains unchanged.
    rejected = study_report([{'kind': 'airlock-study-v1', 'participant_id': 'model-actor',
                              'source': 'model', 'consent': True, 'responses': []}])
    assert len(rejected['excluded']) == 1


def test_roleplay_keeps_private_id_mapping_and_reuses_supplied_ledger_without_exposing_ids(tmp_path, monkeypatch):
    import json
    import sys
    from benchmark.model_roles import LabelChoice
    from scripts import model_roleplay

    cases = tmp_path / 'cases.json'
    tasks = tmp_path / 'tasks.json'
    config = tmp_path / 'provider.json'
    ledger = tmp_path / 'existing-project-ledger'
    output = tmp_path / 'model-output'
    cases.write_text(json.dumps([{'case_id': 'maintenance-one', 'intent': 'Create a maintenance issue'}]))
    tasks.write_text(json.dumps({'tasks': [
        {'id': 'authorized-private-id', 'intent': 'Allowed row', 'sql': 'UPDATE customers SET balance=balance+1 WHERE id=1',
         'diff': 'hidden-in-A', 'gold': 'approve', 'check': {'answer': 'secret-gold'}},
        {'id': 'unauthorized-private-id', 'intent': 'Read only', 'sql': 'DELETE FROM customers',
         'diff': 'visible-in-B', 'gold': 'reject', 'check': {'answer': 'secret-gold'}},
    ]}))
    calls = []
    class FixtureAdvisor:
        def __init__(self, config_file, database):
            assert config_file == config and database == ledger
        def ledger_summary(self):
            return {'calls': 77 + len(calls), 'budget': 3, 'currency': 'CNY'}
        def generate(self, context, schema, prompt):
            calls.append(context)
            advice = (model().model_dump(include=set(LabelChoice.model_fields)) if schema is LabelChoice
                      else {'choice': 'reject', 'reason': 'Synthetic fixture decision only.'})
            return {'status': 'ok', 'advice': advice}
    monkeypatch.setattr(model_roleplay, 'SemanticAdvisor', FixtureAdvisor)
    monkeypatch.setattr(sys, 'argv', ['model_roleplay.py', '--cases', str(cases), '--tasks', str(tasks),
                                     '--provider-config', str(config), '--ledger', str(ledger), '--output-dir', str(output)])
    model_roleplay.main()
    saved = json.loads((output / 'deepseek-roleplay.json').read_text(encoding='utf-8'))
    assert saved['before']['calls'] == 77 and saved['after']['calls'] == 80
    assert [x['case_id'] for x in saved['study']] == ['authorized-private-id', 'unauthorized-private-id']
    assert [x['blind_case_id'] for x in saved['study']] == ['study-001', 'study-002']
    assert set(calls[1]) == {'arm', 'intent', 'request'}
    assert set(calls[2]) == {'arm', 'intent', 'request', 'diff'}
    assert calls[2]['diff'] == 'visible-in-B'
    for secret in ('private-id', 'study-001', 'study-002', 'secret-gold', 'hidden-in-A'):
        assert secret not in json.dumps(calls[1:])

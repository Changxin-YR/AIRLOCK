import pytest
from benchmark.evaluate import load, keyword_baseline
from benchmark.generate import cases


def test_family_split_and_data_origin():
    rows=cases()
    assert len(rows)==200
    assert {r['family'] for r in rows if r['split']=='test'}.isdisjoint({r['family'] for r in rows if r['split']=='dev'})
    assert {r['provenance'] for r in rows}=={'synthetic_authored_policy_case'}


def test_tuning_cannot_load_test():
    with pytest.raises(ValueError,match='Tuning mode'):
        load('test',tuning=True)


def test_baseline_is_independent():
    assert keyword_baseline("SELECT 'DELETE' AS text")=='need_approval'

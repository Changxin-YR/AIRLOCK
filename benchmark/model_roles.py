"""Model-only annotation and decision records, separate from human acceptance."""
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LabelChoice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    dangerous: bool
    decision: Literal['pass', 'need_approval', 'block']
    risk_level: Literal['low', 'medium', 'high', 'critical', 'unknown']
    reversibility: Literal['reversible', 'compensatable', 'irreversible', 'unknown']
    impact_units_observed: int | None = Field(ge=0, le=5000)
    rationale: str = Field(min_length=3, max_length=300)
    uncertainty: str = Field(max_length=200)


class ModelAnnotation(LabelChoice):
    source: Literal['model'] = 'model'
    human: Literal[False] = False
    independent_human: Literal[False] = False
    annotator_id: str = Field(min_length=3, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)


class StudyChoice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    choice: Literal['approve', 'reject']
    reason: str = Field(min_length=3, max_length=300)


def paired_model_report(left, right):
    """Describe paired model outputs; never establish an independent gold label."""
    left = [ModelAnnotation.model_validate(x) for x in left]
    right = [ModelAnnotation.model_validate(x) for x in right]
    a, b = {x.case_id: x for x in left}, {x.case_id: x for x in right}
    if not a or len(a) != len(left) or len(b) != len(right) or a.keys() != b.keys():
        raise ValueError('model annotations must uniquely cover the same nonempty cases')
    if len({x.annotator_id for x in left}) != 1 or len({x.annotator_id for x in right}) != 1:
        raise ValueError('one declared model actor per side required')
    if left[0].annotator_id == right[0].annotator_id:
        raise ValueError('distinct model actor identifiers required')
    fields = ('dangerous', 'decision', 'risk_level', 'reversibility', 'impact_units_observed')
    return {
        'kind': 'model_annotation_comparison', 'source': 'model',
        'model_annotators': [left[0].annotator_id, right[0].annotator_id],
        'paired_cases': len(a), 'human_participants': 0, 'human_gold_records': 0,
        'human_cohen_kappa': None, 'acceptance_metrics': None,
        'fields': {f: {
            'agreement_count': sum(getattr(a[k], f) == getattr(b[k], f) for k in a),
            'denominator': len(a),
            'agreement_rate': sum(getattr(a[k], f) == getattr(b[k], f) for k in a) / len(a),
            'pairs': dict(Counter(str(getattr(a[k], f)) + '->' + str(getattr(b[k], f)) for k in a)),
            'disagreement_case_ids': [k for k in sorted(a) if getattr(a[k], f) != getattr(b[k], f)],
        } for f in fields},
        'limitations': ['Model identifiers do not prove statistical independence',
                       'Agreement is not correctness or human agreement',
                       'No human, business-gold or causal A/B acceptance established'],
    }


def blind_study_tasks(tasks):
    """A model sees only the same information available in its assigned arm."""
    if not tasks or len({x['id'] for x in tasks}) != len(tasks):
        raise ValueError('nonempty unique task IDs required')
    # Original IDs may encode the expected label. Keep their mapping solely in
    # the researcher's private results, not in the model-visible packet.
    return [{'case_id': f'study-{i + 1:03d}', 'arm': 'B' if i % 2 else 'A',
             'intent': t['intent'], 'request': t['sql'],
             **({'diff': t['diff']} if i % 2 else {})}
            for i, t in enumerate(tasks)]

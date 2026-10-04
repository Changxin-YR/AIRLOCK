"""Private, explicitly self-declared single-human annotation pilots.

These records are never independent gold or a substitute for the two-person
annotations_report contract. Blank declarations remain blank. Model/automation
records cannot be promoted using a command-line source override. A declaration
cannot authenticate the person who supplied it; verify participation separately.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from airlock.private_files import restrict_directory


MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 10000
CASE_ID_PATTERN = r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}'


class PilotInputError(ValueError):
    pass


class PilotAnnotation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    case_id: str = Field(min_length=1, max_length=100)
    annotator_id: str | None = Field(default=None, min_length=3, max_length=100)
    source: Literal['human'] | None = None
    human: Literal[True] | None = None
    independent: bool | None = None
    dangerous: bool | None = None
    decision: Literal['pass', 'need_approval', 'block'] | None = None
    risk_level: Literal['low', 'medium', 'high', 'critical', 'unknown'] | None = None
    reversibility: Literal['reversible', 'compensatable', 'irreversible', 'unknown'] | None = None
    impact_units_observed: int | None = Field(default=None, ge=0, le=5000)
    rationale: str | None = Field(default=None, min_length=3, max_length=2000)
    uncertainty: str | None = Field(default=None, max_length=2000)


FIELDS = tuple(PilotAnnotation.model_fields)
REQUIRED_FOR_COMPLETION = ('annotator_id', 'source', 'human', 'dangerous', 'decision',
                           'risk_level', 'reversibility', 'rationale')


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, suffixes):
    path = Path(path)
    if path.suffix.lower() not in suffixes:
        raise PilotInputError('unsupported_input_format')
    with path.open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise PilotInputError('input_too_large')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        raise PilotInputError('input_must_be_utf8') from None
    return raw, text


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PilotInputError('duplicate_json_field')
        result[key] = value
    return result


def _loads(text):
    try:
        return json.loads(text, object_pairs_hook=_json_object)
    except json.JSONDecodeError:
        raise PilotInputError('invalid_json') from None


def load_cases(path):
    raw, text = _read(path, {'.json', '.jsonl'})
    data = ([_loads(line) for line in text.splitlines() if line.strip()]
            if Path(path).suffix.lower() == '.jsonl' else _loads(text))
    if isinstance(data, dict):
        data = data.get('cases')
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_RECORDS:
        raise PilotInputError('nonempty_case_list_required')
    cases = []
    seen = set()
    for row in data:
        if not isinstance(row, dict):
            raise PilotInputError('invalid_case_record')
        identifier = row.get('case_id', row.get('id'))
        # IDs are copied into a spreadsheet template. Reject formula prefixes,
        # whitespace/control characters and non-identifiers; never silently
        # alter the source ID or lose its mapping.
        if not isinstance(identifier, str) or re.fullmatch(CASE_ID_PATTERN, identifier) is None:
            raise PilotInputError('invalid_case_id')
        if 'case_id' in row and 'id' in row and row['case_id'] != row['id']:
            raise PilotInputError('ambiguous_case_id')
        if identifier in seen:
            raise PilotInputError('duplicate_case_id')
        seen.add(identifier)
        cases.append(identifier)
    return cases, raw


def load_annotations(path):
    raw, text = _read(path, {'.csv', '.jsonl'})
    if Path(path).suffix.lower() == '.jsonl':
        rows = [(number, _loads(line)) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    else:
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        fields = reader.fieldnames
        if not fields or 'case_id' not in fields or len(set(fields)) != len(fields) or not set(fields) <= set(FIELDS):
            raise PilotInputError('invalid_csv_header')
        rows = []
        try:
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise PilotInputError('invalid_csv_row_width')
                rows.append((reader.line_num, row))
        except csv.Error:
            raise PilotInputError('invalid_csv') from None
    if len(rows) > MAX_RECORDS:
        raise PilotInputError('too_many_annotation_rows')
    return rows, raw


def _normalize(row, csv_input, explicit_source):
    if not isinstance(row, dict):
        raise PilotInputError('annotation_object_required')
    candidate = dict(row)
    if csv_input:
        for key, value in candidate.items():
            value = value.strip()
            if not value:
                candidate[key] = None
            elif key in {'human', 'independent', 'dangerous'}:
                if value not in {'true', 'false'}:
                    raise PilotInputError('boolean_must_be_explicit_true_or_false')
                candidate[key] = value == 'true'
            elif key == 'impact_units_observed':
                if not value.isascii() or not value.isdigit():
                    raise PilotInputError('impact_must_be_nonnegative_integer_or_blank')
                candidate[key] = int(value)
            else:
                candidate[key] = value
    # Source and human declarations are independently required. Neither an ID
    # nor --source human can convert an explicit model/false declaration.
    if candidate.get('source') not in (None, 'human') or candidate.get('human') not in (None, True):
        raise PilotInputError('nonhuman_annotation_rejected')
    if candidate.get('human') is not None and candidate['human'] is not True:
        raise PilotInputError('human_must_be_explicit_boolean')
    if explicit_source is not None:
        if candidate.get('source') is not None and candidate['source'] != explicit_source:
            raise PilotInputError('source_declaration_conflict')
        candidate['source'] = explicit_source
    for key in ('annotator_id', 'rationale'):
        if isinstance(candidate.get(key), str) and not candidate[key].strip():
            candidate[key] = None
    try:
        return PilotAnnotation.model_validate(candidate)
    except ValidationError:
        raise PilotInputError('invalid_annotation_schema') from None


def summarize(case_ids, numbered_rows, *, csv_input=False, explicit_source=None):
    if explicit_source not in (None, 'human'):
        raise PilotInputError('nonhuman_annotation_rejected')
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise PilotInputError('nonempty_unique_case_ids_required')
    known = set(case_ids)
    seen = set()
    annotators = set()
    declared = set()
    normalized = []
    issues = []
    complete = []
    for line, raw in numbered_rows:
        row = _normalize(raw, csv_input, explicit_source)
        if row.case_id not in known:
            raise PilotInputError('unknown_case_id')
        if row.case_id in seen:
            raise PilotInputError('duplicate_annotation_row')
        seen.add(row.case_id)
        if row.annotator_id:
            annotators.add(row.annotator_id)
        if len(annotators) > 1:
            raise PilotInputError('single_annotator_required_use_two_person_workflow')
        if row.source == 'human' and row.human is True and row.annotator_id:
            declared.add(row.annotator_id)
        missing = [field for field in REQUIRED_FOR_COMPLETION if getattr(row, field) is None]
        if missing:
            issues.append({'case_id': row.case_id, 'input_line': line, 'code': 'incomplete_annotation', 'missing_fields': missing})
        else:
            complete.append(row.case_id)
        normalized.append({'kind': 'single_person_pilot_annotation', **row.model_dump(),
                           'input_line': line, 'complete': not missing,
                           'parsed_input_row_sha256': _digest(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode())})
    missing_cases = [identifier for identifier in case_ids if identifier not in seen]
    issues += [{'case_id': identifier, 'code': 'missing_annotation'} for identifier in missing_cases]
    report = {
        'kind': 'single_person_annotation_pilot',
        'status': ('AWAITING_EXPLICIT_HUMAN_INPUT' if not declared else
                   'SINGLE_HUMAN_PILOT_COMPLETE' if len(complete) == len(case_ids) else 'SINGLE_HUMAN_PILOT_PARTIAL'),
        'declared_human_annotators': len(declared), 'annotator_ids': sorted(declared),
        'independent_human_gold_records': 0, 'kappa': None, 'human_cohen_kappa': None,
        'acceptance_metrics': None, 'formal_evaluation_status': 'BLOCKED_EXTERNAL',
        'coverage': {'cases_total': len(case_ids), 'rows_supplied': len(normalized),
                     'complete_annotations': len(complete), 'complete_fraction': len(complete) / len(case_ids),
                     'incomplete_annotations': len(normalized) - len(complete),
                     'missing_case_ids': missing_cases, 'complete_case_ids': complete},
        'unknown_counts': {field: sum(row[field] in (None, 'unknown') for row in normalized)
                           for field in ('dangerous', 'risk_level', 'reversibility', 'impact_units_observed')},
        'issues': issues,
        'limitations': [
            'Single-person descriptive pilot only; no independent agreement, adjudicated gold or formal threshold acceptance.',
            'Human identity and participation are self-declared; schema validation cannot authenticate a human or detect relabelled model text.',
            'Blank labels and unknown impact remain unresolved; no historical business logs or representative coverage are inferred.',
            'Original two-independent-annotator requirements remain unchanged.',
        ],
    }
    return report, normalized


def _private_directory(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    restrict_directory(output)
    return output


def _write(output, name, raw):
    with open(output / name, 'xb', opener=lambda name, flags: os.open(name, flags, 0o600)) as destination:
        destination.write(raw)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def prepare(case_path, output):
    cases, raw = load_cases(case_path)
    manifest = {'kind': 'single_person_pilot_template', 'status': 'AWAITING_EXPLICIT_HUMAN_INPUT',
                'human_records_created': 0, 'case_count': len(cases), 'acceptance_metrics': None,
                'case_source': {'path': str(Path(case_path).resolve()), 'sha256': _digest(raw)},
                'instructions': '本人填写一个匿名 annotator_id；source=human 和 human=true 必须本人明确声明。独立填写情况按事实填写 independent。未知保留空白或 unknown；本先导不产生双人 κ 或正式验收指标。'}
    out = _private_directory(output)
    _write(out, 'case-source.original' + Path(case_path).suffix.lower(), raw)
    _write(out, 'manifest.json', _json_bytes(manifest))
    rows = [dict.fromkeys(FIELDS) | {'case_id': identifier} for identifier in cases]
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    _write(out, 'single-person.template.csv', ('\ufeff' + text.getvalue()).encode())
    _write(out, 'single-person.template.jsonl', ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode())
    return manifest


def import_annotations(case_path, annotation_path, output, *, source_reference, explicit_source=None):
    if not isinstance(source_reference, str) or not source_reference.strip() or len(source_reference) > 1000:
        raise PilotInputError('explicit_source_reference_required')
    cases, case_raw = load_cases(case_path)
    rows, annotation_raw = load_annotations(annotation_path)
    report, normalized = summarize(cases, rows, csv_input=Path(annotation_path).suffix.lower() == '.csv', explicit_source=explicit_source)
    report['provenance'] = {
        'source_reference': source_reference, 'explicit_source_argument': explicit_source,
        'case_input': {'path': str(Path(case_path).resolve()), 'sha256': _digest(case_raw)},
        'annotation_input': {'path': str(Path(annotation_path).resolve()), 'sha256': _digest(annotation_raw)},
        'raw_input_copies_preserved': True,
    }
    out = _private_directory(output)
    _write(out, 'case-source.original' + Path(case_path).suffix.lower(), case_raw)
    _write(out, 'annotations.original' + Path(annotation_path).suffix.lower(), annotation_raw)
    _write(out, 'pilot-annotations.jsonl', ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in normalized).encode())
    _write(out, 'pilot-report.json', _json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'import'):
        command = commands.add_parser(name)
        command.add_argument('--cases', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True, help='New private directory; existing outputs are never overwritten')
        if name == 'import':
            command.add_argument('--annotations', type=Path, required=True)
            command.add_argument('--source-reference', required=True, help='Actual local provenance supplied by the operator')
            command.add_argument('--source', choices=['human'], help='Explicit source declaration for legacy CSV/JSONL lacking source; human must still be true in each completed row')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            report = prepare(args.cases, args.output)
        else:
            report = import_annotations(args.cases, args.annotations, args.output,
                                        source_reference=args.source_reference, explicit_source=args.source)
        print(json.dumps({'status': report['status'], 'output': str(args.output.resolve()),
                          'acceptance_metrics': None}, ensure_ascii=False))
    except (OSError, ValueError) as error:
        code = str(error) if isinstance(error, PilotInputError) else 'output_exists_or_io_error'
        print(json.dumps({'status': 'REJECTED', 'error_code': code, 'acceptance_metrics': None}))
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()

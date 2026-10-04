"""Replay blinded model decisions in the real study UI as automation, not humans."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.model_roles import ModelAnnotation, paired_model_report
from benchmark.research import study_report
from scripts.support import server


def normalize_submodel(document):
    if document.get('source') != 'model' or document.get('human') is not False or document.get('independent_human') is not False:
        raise ValueError('explicit nonhuman submodel provenance required')
    return [ModelAnnotation.model_validate({k: row[k] for k in ModelAnnotation.model_fields})
            for row in document['annotations']]


def participant_id(prefix):
    # Explicit controlled replay, not participant randomization or a user sample.
    for n in range(1000):
        value = prefix + '-' + str(n)
        raw = hashlib.sha256(value.encode()).digest()
        if raw[0] % 2 == 0 and raw[1] % 2 == 0:
            return value
    raise ValueError('controlled replay identifier unavailable')


async def run(args):
    from playwright.async_api import async_playwright
    raw = args.tasks.read_bytes(); task_hash = hashlib.sha256(raw).hexdigest()
    tasks = json.loads(raw)['tasks']
    live = json.loads(args.deepseek.read_text(encoding='utf-8'))
    sub = json.loads(args.submodel_annotations.read_text(encoding='utf-8'))
    sub_study = json.loads(args.submodel_study.read_text(encoding='utf-8'))
    if live['task_file_sha256'] != task_hash or sub_study['task_file_sha256'] != task_hash:
        raise ValueError('model decisions refer to a different task file')
    if sub_study.get('source') != 'model' or sub_study.get('human') is not False:
        raise ValueError('model study provenance required')
    left = [ModelAnnotation.model_validate(x['annotation']) for x in live['annotations']]
    right = normalize_submodel(sub)
    comparison = paired_model_report([x.model_dump() for x in left], [x.model_dump() for x in right])
    deep_rows = [{'case_id': x['case_id'], 'arm': x['arm'], **x['provider']['advice']} for x in live['study']]
    # The fresh model actor receives only opaque IDs. Map back privately AFTER
    # collecting its answers; semantic source IDs must never reach that actor.
    expected_ids = [f'study-{i + 1:03d}' for i in range(len(tasks))]
    if [row['case_id'] for row in sub_study['rows']] != expected_ids:
        raise ValueError('submodel study must use the opaque blind packet IDs')
    actor = sub_study.get('actor', '')
    if not re.fullmatch(r'[A-Za-z0-9-]{3,80}', actor):
        raise ValueError('safe explicit model actor identifier required')
    sub_rows = [dict(row, case_id=tasks[i]['id']) for i, row in enumerate(sub_study['rows'])]
    actors = [('deepseek', deep_rows), (actor, sub_rows)]
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'kind': 'real_browser_model_pilot', 'human_participants': 0,
              'task_file_sha256': task_hash, 'model_annotation_comparison': comparison,
              'sessions': [], 'business_side_effects': 0,
              'scope': 'Blinded model choices replayed via native Playwright on synthetic study page',
              'human_acceptance_metrics': None, 'model_latency_is_human_time': False,
              'submodel_blinding': 'opaque IDs, fresh actor without earlier conversation',
              'submodel_raw_sha256': hashlib.sha256(args.submodel_study.read_bytes()).hexdigest()}
    errors = []
    with server() as (url, _keys, _client):
        async with async_playwright() as p:
            executable = os.environ.get('CHROMIUM_PATH')
            browser = await p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
            try:
                for actor, rows in actors:
                    by_id = {x['case_id']: x for x in rows}
                    if len(by_id) != len(rows) or set(by_id) != {t['id'] for t in tasks}:
                        raise ValueError('actor must uniquely cover the exact task set')
                    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    api_calls = []
                    page.on('request', lambda request: api_calls.append(request.url) if '/v1/' in request.url else None)
                    await page.goto(url + '/assets/study.html')
                    await page.locator('#participant').fill(participant_id('model-' + actor))
                    await page.locator('#source').select_option('automation')
                    await page.locator('#consent').check()
                    await page.locator('#tasks').set_input_files(str(args.tasks.resolve()))
                    await page.locator('#start-study').click()
                    for i, task in enumerate(tasks):
                        row = by_id[task['id']]
                        arm = 'B' if i % 2 else 'A'
                        if row['arm'] != arm or row['choice'] not in {'approve', 'reject'}:
                            raise ValueError('actor arm/choice mismatch')
                        await page.locator('#study-summary').wait_for()
                        assert await page.locator('#study-summary p').inner_text() == task['intent']
                        assert await page.locator('#study-summary .result').count() == (1 if arm == 'B' else 0)
                        if i == 1:
                            await page.screenshot(path=str(args.output / (actor + '-study.png')), full_page=True)
                        await page.locator('#study-' + row['choice']).click()
                        # This run uses the frozen example with no comprehension keys;
                        # never answer unseen questions using researcher gold.
                        if task.get('check'):
                            raise ValueError('model pilot requires separately blinded comprehension answers')
                    async with page.expect_download() as pending:
                        await page.locator('#export-study').click()
                    download = await pending.value
                    exported = args.output / (actor + '-automation.json')
                    await download.save_as(str(exported))
                    session = json.loads(exported.read_text(encoding='utf-8'))
                    assert session['source'] == 'automation' and session['task_file_sha256'] == task_hash
                    assert len(session['responses']) == len(tasks) and not api_calls
                    exclusion = study_report([session], {t['id']: t for t in tasks}, task_hash)
                    assert len(exclusion['excluded']) == 1
                    report['sessions'].append({'actor': actor, 'export': exported.name,
                        'responses': len(tasks), 'synthetic_author_gold_correct': sum(x['correct'] for x in session['responses']),
                        'source': 'automation', 'human_pipeline_excluded': True,
                        'ui_visible_ms_scope': 'automation instrumentation only', 'business_api_calls': len(api_calls)})
                    await page.close()
                if errors:
                    raise AssertionError('browser errors: ' + repr(errors))
            finally:
                await browser.close()
    report['status'] = 'PASS_MODEL_UI_PILOT'
    (args.output / 'model-pilot-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'model_actors': len(actors),
                      'automated_decisions': sum(s['responses'] for s in report['sessions']),
                      'human_participants': 0, 'business_side_effects': 0}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tasks', type=Path, required=True)
    p.add_argument('--deepseek', type=Path, required=True)
    p.add_argument('--submodel-annotations', type=Path, required=True)
    p.add_argument('--submodel-study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    asyncio.run(run(p.parse_args()))

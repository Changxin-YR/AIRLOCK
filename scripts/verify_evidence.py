"""Validate raw evidence independently of exit receipts; safe under python -O."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_LOGS = ['pytest.log','frontend-check.log','frontend-tests.log','benchmark-dev.log',
                 'benchmark-test.log','browser-native.log','docker-smoke.log','dependency-audit.log',
                 'latency.log','ablation.log','study-analysis.log','comparison.log','next-build.log','npm-audit.log',
                 'browser-edges.log','container-integrations.log','upstream-isolation.log','archive-build.log','archive-integration.log','research-pipeline.log',
                 'sqlite-runtime-build.log','sqlite-runtime-linked.log','pilot-browser.log','acceptance-matrix.log']
REQUIRED_TESTS = {'test_official_mcp_sdk_pending_approval_and_result',
    'test_process_death_inside_gate_decision_is_atomic','test_concurrent_approvals_execute_once',
    'test_real_sse_reconnect_cursor_only_delivers_newer_events','test_http_complete_flow',
    'test_server_filtered_pending_queue_survives_long_read_history','test_state_filter_is_validated_and_applied',
    'test_remote_effect_survives_receipt_audit_failure_reconciles','test_clock_rollback_across_restart_cannot_extend_approval',
    'test_static_unc_path_rejected_before_filesystem_resolution','test_agent_does_not_retry_rejected_writes_or_access_review_endpoint',
    'test_audit_export_omits_free_text_and_secrets_and_requires_reviewer','test_sse_fragmented_unicode_notifications_and_bounds',
    'test_sse_lease_ends_when_authenticated_identity_changes',
    'test_github_real_http_gate_review_relay_receipt_and_audit',
    'test_github_unknown_timeout_and_crash_never_resend',
    'test_oidc_pkce_real_tls_loopback_and_private_export',
    'test_oidc_callback_total_read_deadline_preserves_next_login',
    'test_model_labels_cannot_claim_or_enter_human_annotation',
    'test_actual_delivery_persistent_dedup_recovery_and_no_sensitive_payload',
    'test_lost_response_retries_same_event_and_orders_recovery_after_alert',
    'test_private_reservation_permissions_and_exclusive_reuse',
    'test_relay_cli_does_not_call_when_private_permissions_fail',
    'test_model_study_packet_blinds_gold_and_hides_diff_in_a',
    'test_submit_uses_one_connection_and_two_full_commits',
    'test_failed_submit_keeps_expiration_and_high_water_committed',
    'test_reused_connection_reauthorizes_prepared_sql_and_restores_limits',
    'test_sqlite_guard_rejects_unconfirmed_runtime_before_enabling_wal',
    'test_sqlite_runtime_rejection_never_opens_persistent_database[False-store]',
    'test_sqlite_runtime_rejection_never_opens_persistent_database[False-github_adapter]',
    'test_sqlite_runtime_rejection_never_opens_persistent_database[True-store]',
    'test_sqlite_runtime_rejection_never_opens_persistent_database[True-github_adapter]',
    'test_sqlite_confirmed_runtime_preserves_wal_and_full_sync',
    'test_sqlite_pinned_runtime_survives_minimal_child_environment',
    'test_sqlite_builder_rejects_archive_or_official_source_hash_mismatch',
    'test_sqlite_binary_provenance_hashes_actual_mapping_and_matches_build',
    'test_sqlite_binary_provenance_rejects_missing_or_ambiguous_mapping',
    'test_pilot_server_only_serves_fixed_public_assets',
    'test_bootstrap_single_person_has_no_population_interval_even_with_many_decisions',
    'test_original_annotations_report_still_requires_exactly_two_independent_people',
    'test_snapshot_is_observation_not_execution_or_approval',
    'test_private_pack_hashes_empty_labels_and_correlated_counts',
    'test_repeated_create_claims_do_not_multiply_observed_issue_effects',
    'test_inbox_concurrent_replays_insert_once_and_conflicts_are_atomic',
    'test_inbox_read_and_write_credentials_are_separate_and_never_url_auth',
    'test_inbox_unsafe_runtime_leaves_existing_database_unopened',
    'test_actual_local_sender_receiver_alert_recovery_and_receiver_restart',
    'test_acceptance_ledger_positive_control_keeps_external_blockers',
    'test_acceptance_rejects_changed_archived_log',
    'test_acceptance_unarchived_receipt_cannot_establish_frozen_pass',
    'test_latency_gate_recomputes_preserved_real_samples',
    'test_latency_gate_keeps_negative_paired_differences',
    'test_outbox_rejects_foreign_database_before_mutation_or_delivery',
    'test_old_schema_with_different_sql_formatting_retains_semantics',
    'test_out_of_order_observations_cannot_create_false_recovery_or_realert',
    'test_formal_jsonl_rejects_contradictory_source_declaration',
    'test_bound_task_gold_excludes_browser_invented_comprehension_successes',
    'test_governance_real_day_groups_tasks_and_preserves_empty_denominator',
    'test_research_cli_round_trip_and_duplicate_source_rejection'}
REQUIRED_BROWSER = {'agent_credential_rejected_by_reviewer_console','approval_disabled_without_informed_confirmation',
    'browser_rejection_preserves_all_1206_rows','browser_approval_executes_real_update_once',
    'critical_action_requires_exact_1206_scope_phrase','390px_mobile_has_no_horizontal_overflow',
    'audit_replay_and_hmac_verification_render','logout_removes_authenticated_console',
    'no_browser_javascript_errors','pending_queue_survives_more_than_100_newer_reads',
    'metrics_use_real_samples_and_unknown_model_cost','batch_ui_lists_bound_members_and_enforces_confirmation',
    'recovery_is_a_separate_informed_approval','study_import_counterbalance_visibility_and_export_automation_only'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def verify_junit(path):
    tree = ET.parse(path)
    cases = list(tree.iter('testcase'))
    require(bool(cases), 'JUnit has no tests')
    for case in cases:
        require(not any(case.find(tag) is not None for tag in ('failure','error','skipped')),
                'JUnit failed/error/skipped: ' + case.get('name','unnamed'))
    for suite in tree.iter('testsuite'):
        require(all(int(suite.get(key,'0')) == 0 for key in ('failures','errors','skipped')),
                'JUnit suite reports failures/errors/skips')
    require(REQUIRED_TESTS <= {c.get('name') for c in cases}, 'JUnit missing mandatory tests')
    return len(cases)


def verify_benchmark(report, expected_cases, expected_families, corpus_sha):
    rows = report['rows']
    require(report['cases']==len(rows)==expected_cases, 'benchmark case count')
    require(report['families']==len({r['family'] for r in rows})==expected_families, 'benchmark families')
    require(len({r['id'] for r in rows}) == len(rows), 'duplicate benchmark case')
    require(report['corpus_sha256']==corpus_sha, 'benchmark hash')
    require(report['human_ab']=='not_run' and report['cohens_kappa'] is None, 'synthetic provenance')
    allowed = {'pass','block','need_approval'}
    require(all(r['airlock'] in allowed and r['expected'] in allowed for r in rows), 'invalid prediction')
    accuracy = sum(r['airlock']==r['expected'] for r in rows)/len(rows)
    reads = [r for r in rows if r['expected']=='pass']
    require(bool(reads),'benchmark lacks pass denominator')
    fpr = sum(r['airlock']!='pass' for r in reads)/len(reads)
    impacts = [r for r in rows if r['expected_changed_rows'] is not None]
    matches = sum(r['expected_changed_rows']==r['actual_changed_rows'] for r in impacts)
    require(accuracy >= .9 and fpr <= .1 and matches==len(impacts), 'benchmark regression threshold')
    require(report['airlock']['exact_accuracy']==accuracy and report['airlock']['supported_read_fpr']==fpr,
            'benchmark summary disagrees with raw rows')
    require(report['impact_denominator']==len(impacts) and report['impact_exact_match_count']==matches,
            'impact summary disagrees with raw rows')


def verify_latency(report, expected_samples=60):
    """Recompute paired differences and summaries independently from raw rows."""
    def number(value, label, signed=False):
        require(type(value) in (int, float) and math.isfinite(value) and
                (signed or value >= 0), 'latency invalid sample: ' + label)
        return value

    def equal(actual, expected, label):
        number(actual, label, signed=True)
        require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9),
                'latency raw/summary mismatch: ' + label)

    def distribution(summary, values, label, with_mean=False):
        ordered = sorted(values)
        require(type(summary['n']) is int and summary['n'] == len(values),
                'latency summary count: ' + label)
        for percentile in (50, 95, 99):
            equal(summary['p' + str(percentile)], ordered[math.ceil(len(values) * percentile / 100) - 1], label)
        if with_mean:
            equal(summary['mean'], sum(values) / len(values), label + '.mean')

    require(type(report['samples']) is int and report['samples'] == expected_samples,
            'latency configured sample count')
    reads, writes = report['raw_read_pairs'], report['raw_writes']
    require(len(reads) == expected_samples and len(writes) == min(expected_samples, 30),
            'latency raw sample count')
    require([row['pair'] for row in reads] == list(range(expected_samples)), 'latency pair identity')
    require([row['sample'] for row in writes] == list(range(len(writes))), 'latency write identity')
    require(len({row['action_id'] for row in reads}) == len(reads), 'latency duplicate action')
    for row in reads:
        require(row['order'] in (['direct', 'proxy'], ['proxy', 'direct']), 'latency arm order')
        direct = number(row['direct_ms'], 'direct_ms')
        proxy = number(row['proxy_ms'], 'proxy_ms')
        equal(row['added_ms'], proxy - direct, 'paired added_ms')
    for field in ('direct_ms', 'proxy_ms', 'added_ms'):
        distribution(report['read'][field], [row[field] for row in reads], field, with_mean=True)
    for field in ('submit_receipt_ms', 'approval_request_to_effect_ms', 'static_ms', 'preview_ms', 'evaluation_ms'):
        values = [number(row[field], field) for row in writes]
        distribution(report['write'][field], values, field)
    def p95(values):
        return sorted(values)[math.ceil(len(values) * .95) - 1]
    require(p95([row['static_ms'] for row in writes]) < 300 and
            p95([row['preview_ms'] for row in writes]) < 5000 and
            p95([row['proxy_ms'] - row['direct_ms'] for row in reads]) < 100,
            'latency threshold; inspect raw samples')


def verify(directory):
    commit=(directory/'commit.txt').read_text(encoding='utf-8-sig').strip()
    for name in REQUIRED_LOGS:
        status = load(directory, name+'.status.json')
        require(status['exit_code']==0, name+': failed command')
        require(bool(status.get('command')), name+': missing command')
        require(status.get('tested_commit_sha')==commit and status.get('tracked_source_dirty') is False,name+': unbound or dirty source')
        require((directory/name).stat().st_size > 0, name+': empty raw log')
    tests = verify_junit(directory/'pytest.xml')
    sqlite_pin = load(ROOT/'configs', 'sqlite-runtime.json')
    sqlite_build = load(directory, 'sqlite-runtime-build.json')
    sqlite_linked = load(directory, 'sqlite-runtime-linked.json')
    require(sqlite_build['pin'] == sqlite_pin and sqlite_build['child_exit_code'] == 0,
            'SQLite source build provenance mismatch')
    require(sqlite_linked.get('pin_verified') is True and sqlite_linked['sqlite_threadsafety'] > 0,
            'SQLite linked runtime unverified')
    for field in ('version', 'source_id'):
        require(sqlite_build['verified_python_runtime'][field] == sqlite_linked[field] == sqlite_pin[field],
                'SQLite loaded runtime differs from source pin')
    for field in ('archive_sha256', 'amalgamation_sha3_256'):
        require(sqlite_linked[field] == sqlite_pin[field], 'SQLite source digest mismatch')
    require(sqlite_linked.get('build_report_verified') is True and
            sqlite_linked['build_report_sha256'] == hashlib.sha256((directory/'sqlite-runtime-build.json').read_bytes()).hexdigest(),
            'SQLite linked build report digest mismatch')
    require(len(sqlite_linked['loaded_shared_library_files']) == 1 and
            sqlite_linked['loaded_shared_library_files'][0]['sha256'] == sqlite_build['library_sha256'],
            'SQLite mapped binary differs from this build')
    browser = load(directory,'browser-report.json')
    require(browser['mode']=='native_browser_e2e' and not browser['errors'] and not browser['not_proven'],
            'native browser failed or weakened')
    require(REQUIRED_BROWSER <= set(browser['passed']), 'missing browser checks')
    for name in ('console-desktop.png','console-mobile.png','console-groups.png','console-metrics.png','study-example.png'):
        data = (directory/name).read_bytes()
        require(len(data)>100 and data.startswith(b'\x89PNG\r\n\x1a\n'), 'missing/invalid screenshot: '+name)
    container = load(directory,'docker-report.json')
    edges=load(directory,'browser-edges.json')
    require(len(edges['passed'])>=8 and not edges['errors'] and not edges['csp_violations'],'Next browser counterexamples failed')
    pilot=load(directory,'pilot-browser.json')
    require(pilot['mode']=='native_browser_e2e' and pilot['status']=='PASS' and not pilot['errors'] and not pilot['csp_violations'],
            'pilot native browser flow failed')
    require({'pilot_public_assets_load_without_approval_service',
             'eight_practice_decisions_exported_and_excluded_from_human_metrics',
             'pilot_390px_no_horizontal_overflow', 'sender_alert_dedup_and_recovery_render_as_two_events',
             'inbox_read_token_not_in_url_or_browser_storage', 'inbox_390px_no_horizontal_overflow',
             'inbox_logout_clears_authenticated_content', 'no_browser_javascript_or_csp_errors'} <= set(pilot['passed']),
            'missing pilot browser checks')
    require(pilot['human_participants']==pilot['external_notifications']==pilot['business_side_effects']==0,
            'pilot automation provenance')
    for name in ('pilot-desktop.png','pilot-mobile.png','inbox-desktop.png','inbox-mobile.png'):
        data=(directory/name).read_bytes()
        require(len(data)>100 and data.startswith(b'\x89PNG\r\n\x1a\n'), 'missing pilot screenshot: '+name)
    integrations=load(directory,'container-integrations.json')
    remote=load(directory,'upstream-isolation.json')
    require(remote['status']=='PASS' and remote['mode']=='real_docker_protected_upstream' and len(remote['probe']['checks'])>=6,'protected remote network isolation failed')
    archive=load(directory,'archive-integration.json')
    archive_image=load(directory,'archive-image.json')
    require(archive_image['source_commit']=='7aac2a2c5b7c882e68c1ce017d8256be2feea27f' and archive['runtime_image_id']==archive_image['runtime_image_id'],'archive source/image provenance')
    require(archive['exit_code']==0 and len(archive['checks'])>=6 and len(archive['actual_denials'])==3,'S3 retention/truncation contract failed')
    research=load(directory/'research-pipeline','report.json')
    require(research['status']=='PASS' and research['human_participants']==research['paired_human_labels']==0,'research provenance failed')
    require(load(directory/'research-pipeline','evaluation.json')['acceptance_metrics'] is None,'missing human gold was promoted into acceptance')
    require(integrations['envoy']['status']==integrations['otel']['status']=='PASS','real integration tests failed')
    require(container['mode']=='real_docker_compose', 'Docker mode')
    require(container['rows_before_independent_approval']==1206 and container['rows_after_approval_and_restart']==0,
            'Docker target effect')
    require(container['probe']['uid']!=0 and container['probe']['effective_capabilities']==0, 'Docker isolation')
    require(all(container['probe']['sqlite_runtime'][key] == sqlite_pin[key] for key in ('version', 'source_id')),
            'Docker SQLite runtime differs from pinned source')
    require(container['probe']['sqlite_runtime'].get('build_report_verified') is True,
            'Docker mapped SQLite binary does not match its build report')
    corpus_sha = load(ROOT/'benchmark','manifest.json')['sha256']
    for split,n,families in [('dev',120,24),('test',80,16)]:
        verify_benchmark(load(directory,'benchmark-'+split+'.json'),n,families,corpus_sha)
    corpus = (directory/'synthetic-cases.jsonl').read_bytes()
    require(hashlib.sha256(corpus).hexdigest()==corpus_sha, 'missing or changed raw corpus')
    require(load(directory,'study-analysis.json')['human_participants']==0,'automated study counted as human')
    require(not any(d['vulns'] for d in load(directory,'dependency-audit.json')['dependencies']),'known dependency vulnerability')
    latency=load(directory,'latency.json')
    verify_latency(latency)
    print(f'Verified all {tests} JUnit cases, exit receipts, screenshots, Docker and raw benchmark rows.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,default=ROOT/'evidence')
    args=parser.parse_args()
    verify(args.directory)

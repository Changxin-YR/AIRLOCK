"""Static guardrails supplement, but do not replace, the real Docker boundary test."""
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parent.parent


def config():
    return yaml.safe_load((ROOT/'compose.yaml').read_text())


def test_tmpfs_option_is_one_quoted_mount_not_two_yaml_items():
    for service in config()['services'].values():
        assert service['tmpfs']==['/tmp:size=32m,mode=1777']
        assert service['read_only'] is True
        assert service['user']=='10001:10001'
        assert service['cap_drop']==['ALL']
        assert service['security_opt']==['no-new-privileges:true']


def test_agent_has_no_target_volume_or_executor_network():
    services=config()['services'];agent=services['agent']
    assert not agent.get('volumes')
    assert not set(agent['networks']) & set(services['runner']['networks'])
    assert agent['env_file']=='runtime/agent/.env'
    assert not any('SECRET' in key for key in agent['environment'])
    assert 'ports' not in services['runner']
    assert services['gateway']['ports']==['127.0.0.1:8080:8080']


def test_host_compose_env_files_are_separate_from_container_data():
    for role in ('gateway','runner'):
        service=config()['services'][role]
        assert service['env_file']==f'runtime/compose/{role}.env'
        assert service['volumes']==[f'./runtime/{role}:/data']
    assert config()['networks']['execution']['internal'] is True

"""Read repository safety settings without reading secrets or changing policy."""
import json
import subprocess
from pathlib import Path


def github(path):
    result = subprocess.run(['gh', 'api', path], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub settings unavailable for ' + path.split('/actions/')[0])
    return json.loads(result.stdout)


def check():
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    results = []
    for repo in config['repositories']:
        info = github('repos/' + repo)
        forks = github('repos/' + repo + '/actions/permissions/fork-pr-workflows-private-repos')
        safe = (info.get('private') is True and info.get('default_branch') == 'main'
                and all(forks.get(key) is False for key in ('run_workflows_from_fork_pull_requests',
                    'send_write_tokens_to_workflows', 'send_secrets_and_variables')))
        results.append({'repository': repo, 'private': info.get('private'),
                        'default_branch': info.get('default_branch'), 'forks': forks, 'safe': safe})
    print(json.dumps(results, indent=2))
    if not all(r['safe'] for r in results):
        raise SystemExit('Review repository settings before runner qualification')


if __name__ == '__main__': check()

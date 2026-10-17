"""Arteamis release authority, immutable call graphs and qualification gates."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import controller
import provision
import stack
from test_controller import MemoryState, failed_job, billing_annotations


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.gh = Mock()
        self.repo = 'arteamis-system/backend'
        self.run = {'id': 1, 'run_attempt': 1, 'path': '.github/workflows/release.yml',
                    'event': 'workflow_dispatch', 'head_branch': 'main', 'head_sha': 'a' * 40,
                    'actor': {'login': 'owner'}}
        self.config = {'manual_releases': [self.repo], 'routing_verified': True}
        self.ctrl = controller.Controller(self.gh, MemoryState(), Mock(), self.config, now=1000)

    def test_existing_manual_release_on_current_main_is_trusted(self):
        self.gh.call.side_effect = [{'permission': 'write'}, {'object': {'sha': 'a' * 40}}]
        self.assertTrue(self.ctrl.trusted(self.repo, self.run))

    def test_manual_release_ref_event_actor_and_workflow_cannot_be_substituted(self):
        for change in ({'head_branch': 'deploy/prod'}, {'path': '.github/workflows/prepare-production-config.yml'},
                       {'event': 'repository_dispatch'}, {'head_sha': 'b' * 40}):
            with self.subTest(change=change):
                self.gh.call.side_effect = [{'permission': 'write'}, {'object': {'sha': 'a' * 40}}]
                self.assertFalse(self.ctrl.trusted(self.repo, {**self.run, **change}))
        self.gh.call.side_effect = [{'permission': 'read'}]
        self.assertFalse(self.ctrl.trusted(self.repo, self.run))
        self.gh.call.side_effect = [{'permission': 'write'}]
        self.assertFalse(self.ctrl.trusted('arteamis-system/product', self.run))

    def test_billing_failed_manifest_and_unstarted_deployment_allow_original_run_retry(self):
        self.ctrl.trusted = Mock(return_value=True)
        self.ctrl.source_compatible = Mock(return_value=True)
        self.gh.variable.return_value = None
        jobs = [failed_job(name='read manifest', check_run_url=f'https://api.github.com/repos/{self.repo}/check-runs/8'),
                {'id': 9, 'name': 'build', 'conclusion': 'skipped'},
                {'id': 10, 'name': 'deploy', 'conclusion': 'skipped'}]
        self.gh.pages.side_effect = lambda repo, path, *args: billing_annotations()[7] if 'annotations' in path else jobs
        self.gh.call.side_effect = [{**self.run, 'conclusion': 'failure'}, None]
        self.assertTrue(self.ctrl.takeover(self.repo, self.run))
        self.gh.call.assert_any_call(self.repo, 'POST', '/actions/runs/1/rerun-failed-jobs')
        record = self.ctrl.state.get('retry:' + self.repo + ':1')
        self.assertEqual((record['sha'], record['event'], record['branch']), ('a'*40, 'workflow_dispatch', 'main'))

    def test_any_attempt_with_deployment_execution_prevents_retry(self):
        self.ctrl.trusted = Mock(return_value=True)
        self.ctrl.source_compatible = Mock(return_value=True)
        failed = [failed_job(name='deploy / deploy api', check_run_url=f'https://api.github.com/repos/{self.repo}/check-runs/8')]
        for evidence in ({'runner_id': 42}, {'steps': [{'name': 'preflight'}]}, {'runner_name': 'runner'}):
            for name in ('deploy', 'deploy / deploy api', 'pipeline / deploy-vm / deploy api', 'pipeline / deploy-mirror / release'):
                history = [*failed, {'id': 11, 'name': name, 'run_attempt': 1, 'conclusion': 'success', **evidence}]
                self.gh.pages.side_effect = lambda repo, path, *args: (billing_annotations()[7] if 'annotations' in path
                    else history if 'filter=all' in path else failed)
                self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.gh.call.assert_not_called()
        self.gh.set_variable.assert_not_called()

    def test_successful_ci_dependents_cannot_be_replayed(self):
        self.ctrl.trusted = Mock(return_value=True)
        self.ctrl.source_compatible = Mock(return_value=True)
        jobs = [failed_job(check_run_url=f'https://api.github.com/repos/{self.repo}/check-runs/8'),
                {'id': 9, 'name': 'summary', 'conclusion': 'success', 'runner_id': 2}]
        self.gh.pages.side_effect = lambda repo, path, *args: billing_annotations()[7] if 'annotations' in path else jobs
        self.assertFalse(self.ctrl.takeover(self.repo, {**self.run, 'event': 'push', 'path': '.github/workflows/ci.yml'}))
        self.gh.call.assert_not_called()

    def test_missing_historical_names_fail_closed(self):
        self.assertFalse(controller.release_unstarted([]))
        self.assertFalse(controller.release_unstarted([{'runner_id': 1}]))

    def test_recursive_reusables_and_cycles_and_unrouted_optional_dependencies(self):
        def workflow(reference): return json.dumps({'jobs': {'call': {'uses': reference}}})
        prefix = 'arteamis-system/platform/.github/workflows/'
        outer = workflow(prefix + '_dispatch.yml@' + 'a'*40)
        middle = workflow(prefix + 'ci-test.yml@' + 'b'*40)
        leaf = json.dumps({'jobs': {'test': {'runs-on': controller.SELECTOR}}})
        fetch = lambda path, sha: middle if sha == 'a'*40 else leaf
        self.assertTrue(controller.compatible_workflow(outer, fetch))
        self.assertFalse(controller.compatible_workflow(outer, lambda *_: outer))
        self.assertFalse(controller.compatible_workflow(outer, lambda *_: middle))
        self.assertFalse(controller.compatible_workflow(outer.replace('a'*40, 'main'), fetch))
        self.assertFalse(controller.compatible_workflow(outer, lambda *_: json.dumps({'jobs': {'test': {'runs-on': 'ubuntu-latest'}}}), {'call'}))

    def test_qualification_scope_never_supplies_application_jobs(self):
        config = {'max_instances': 2, 'qualification_only': True, 'canary_repository': 'arteamis-system/qualification', 'repositories': {self.repo: ['release.yml']}}
        self.assertEqual(controller.Controller(self.gh, MemoryState(), self.ctrl.pool, config).tick(), self.ctrl.pool.fulfill.return_value)
        self.gh.call.assert_not_called()
        self.assertEqual(self.ctrl.pool.fulfill.call_args.args[2], [])

    def test_disable_still_reconciles_but_does_not_launch(self):
        state = MemoryState(); state.put('control', {'disabled': True})
        ctrl = controller.Controller(self.gh, state, self.ctrl.pool, {'max_instances': 2})
        self.assertEqual(ctrl.tick(), {'disabled': True})
        ctrl.pool.reconcile.assert_called_once()
        ctrl.pool.fulfill.assert_not_called()

    def test_stale_queued_jobs_do_not_receive_new_capacity(self):
        self.ctrl.config.update({'max_instances': 2, 'repositories': {self.repo: ['release.yml']},
                                 'enforce_fork_policy': False})
        self.ctrl.now = 10000
        self.ctrl.trusted = Mock(return_value=True)
        self.ctrl.source_compatible = Mock(return_value=True)
        self.gh.call.return_value = {'private': True}
        run = {**self.run, 'status': 'queued', 'conclusion': None, 'created_at': '1970-01-01T00:00:00Z'}
        self.gh.pages.side_effect = [[run], [{'id': 7, 'status': 'queued', 'labels': controller.aws_labels(1)}]]
        self.ctrl.tick()
        self.assertEqual(self.ctrl.pool.fulfill.call_args.args[2], [])

    def test_fork_policy_drift_blocks_supply(self):
        self.ctrl.config.update({'max_instances': 2, 'repositories': {self.repo: ['release.yml']}})
        self.gh.call.side_effect = [{'private': True}, {'run_workflows_from_fork_pull_requests': True}]
        self.ctrl.tick()
        self.gh.pages.assert_not_called()
        self.assertEqual(self.ctrl.pool.fulfill.call_args.args[2], [])

    def test_original_run_labels_are_distinct_and_jit_requests_match_them(self):
        self.assertNotEqual(controller.aws_labels(1), controller.aws_labels(2))
        self.assertEqual(controller.aws_labels(9)[-1], 'arteamis-run-9')



class QualificationTests(unittest.TestCase):
    def test_full_activation_requires_live_recovery_and_exact_source_image(self):
        sha = 'a'*40
        proof = {'scope': 'all', 'source_commit': sha, 'ami': 'ami-reviewed',
                 'bake_sha256': provision.hashlib.sha256((provision.ROOT/'bake.sh').read_bytes()).hexdigest()}
        for key in provision.BASE_EVIDENCE + provision.FULL_EVIDENCE:
            proof[key] = {'verified': True, 'references': ['https://github.com/arteamis-system/platform/actions/runs/1']}
        with patch.object(provision.subprocess, 'check_output', return_value=sha+'\n'):
            provision.validate_evidence(proof, 'ami-reviewed')
            for key in provision.BASE_EVIDENCE + provision.FULL_EVIDENCE:
                changed = {**proof, key: {'verified': False}}
                with self.assertRaises(ValueError): provision.validate_evidence(changed, 'ami-reviewed')
            with self.assertRaises(ValueError): provision.validate_evidence(proof, 'ami-other')
            with self.assertRaises(ValueError): provision.validate_evidence({**proof, 'source_commit': 'b'*40}, 'ami-reviewed')

    def test_reaper_stays_scheduled_and_has_no_app_access(self):
        runtime = stack.runtime('ami-test', 'controller/test.zip', {'SubnetId':'s','SecurityGroupId':'sg',
            'RunnerProfileArn':'profile','ArtifactBucket':'bucket'}, enabled=False)
        self.assertEqual(runtime['Resources']['ReaperSchedule']['Properties']['State'], 'ENABLED')
        env = runtime['Resources']['Controller']['Properties']['Environment']['Variables']
        self.assertEqual(env['QUALIFICATION_ONLY'], 'true')
        reaper = json.dumps(stack.foundation()['Resources']['ReaperRole'])
        self.assertNotIn('ssm:', reaper)
        self.assertNotIn('dynamodb:', reaper)

    def test_no_shared_gol_authority_or_persistent_network_compute(self):
        text = json.dumps(stack.foundation()) + json.dumps(stack.boundary())
        self.assertNotIn('gol-', text.lower())
        self.assertNotIn('NatGateway', text)
        self.assertNotIn('AWS::EC2::EIP', text)
        egress = stack.foundation()['Resources']['SecurityGroup']['Properties']['SecurityGroupEgress']
        self.assertIn(22, [r['FromPort'] for r in egress])


if __name__ == '__main__': unittest.main()

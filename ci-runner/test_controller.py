import datetime as dt
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import controller
import pool
import provision
import reaper
import setup_policy
import stack


class MemoryState:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return self.items.get(key, {}).copy()

    def put(self, key, value):
        self.items[key] = value.copy()

    def claim(self, key, value):
        if key in self.items:
            return False
        self.put(key, value)
        return True

    def delete(self, key):
        self.items.pop(key, None)


def failed_job(**changes):
    return {"id": 7, "status": "completed", "conclusion": "failure", "runner_id": 0, "runner_name": "", "steps": [], "labels": ["ubuntu-latest"],
            "check_run_url": "https://api.github.com/repos/arteamis-system/platform/check-runs/8", **changes}


def billing_annotations():
    return {7: [{"annotation_level": "failure", "message": controller.BILLING}]}


class CapacityStatusTests(unittest.TestCase):
    def test_status_is_read_only_and_omits_private_or_unknown_fields(self):
        state = MemoryState()
        state.put("slot:0", {"repo": "arteamis-system/platform", "phase": "ambiguous", "created_at": 12,
                             "name": "arteamis-ci-public", "launch_error_code": "RequestLimitExceeded",
                             "jit": "private", "token": "private", "client_token": "private"})
        client = Mock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Reservations": [{"Instances": [{"InstanceId": "i-ci", "State": {"Name": "running"}},
                                              {"InstanceId": "i-old", "State": {"Name": "terminated"}}]}]}]
        before = json.dumps(state.items, sort_keys=True)
        result = pool.Pool(client, "lt-ci").status(state)
        self.assertEqual(result["slots"][0], {"slot": 0, "repo": "arteamis-system/platform", "phase": "ambiguous",
                                             "created_at": 12, "name": "arteamis-ci-public", "launch_error_code": "RequestLimitExceeded"})
        self.assertEqual(result["slots"][1], {"slot": 1})
        self.assertEqual(result["instances"], [{"id": "i-ci", "state": "running"}])
        self.assertEqual(json.dumps(state.items, sort_keys=True), before)
        client.run_instances.assert_not_called()
        client.terminate_instances.assert_not_called()


class ClassificationTests(unittest.TestCase):
    def test_captured_real_billing_annotation(self):
        fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("billing-rejection.json").read_text())
        self.assertTrue(controller.billing_only(fixture["jobs"], {int(k): v for k, v in fixture["annotations"].items()}))

    def test_exact_billing_before_execution(self):
        self.assertTrue(controller.billing_only([failed_job()], billing_annotations()))

    def test_unknown_missing_mixed_and_executed_fail_closed(self):
        cases = [([], billing_annotations()), ([failed_job()], {}),
                 ([failed_job(runner_id=10)], billing_annotations()),
                 ([failed_job(runner_name="GitHub Actions")], billing_annotations()),
                 ([failed_job(steps=[{"name": "Checkout"}])], billing_annotations()),
                 ([failed_job(conclusion="cancelled")], billing_annotations()),
                 ([failed_job(status="in_progress")], billing_annotations()),
                 ([failed_job()], {7: [{"annotation_level": "failure", "message": "test failed"}]}),
                 ([failed_job()], {7: [{"annotation_level": "failure", "message": controller.BILLING + " and a code error"}]}),
                 ([failed_job(), failed_job(id=9)], billing_annotations()),
                 ([failed_job()], {7: billing_annotations()[7] + [{"annotation_level": "failure", "message": "another error"}]})]
        for jobs, annotations in cases:
            with self.subTest(jobs=jobs, annotations=annotations):
                self.assertFalse(controller.billing_only(jobs, annotations))

    def test_successful_or_skipped_jobs_do_not_weaken_failed_job_checks(self):
        jobs = [failed_job(), {"id": 4, "conclusion": "success", "runner_id": 2}, {"id": 5, "conclusion": "skipped"}]
        self.assertTrue(controller.billing_only(jobs, billing_annotations()))

    def test_original_workflow_must_support_routing_in_every_job(self):
        workflow = json.dumps({"jobs": {"a": {"runs-on": controller.SELECTOR}, "b": {"runs-on": controller.SELECTOR}}})
        self.assertTrue(controller.compatible_workflow(workflow, Mock()))
        for value in ("ubuntu-latest", ["self-hosted"], "${{ vars.UNTRUSTED }}"):
            bad = json.dumps({"jobs": {"a": {"runs-on": controller.SELECTOR}, "b": {"runs-on": value}}})
            self.assertFalse(controller.compatible_workflow(bad, Mock()))

    def test_reusable_workflow_requires_exact_supported_pin(self):
        child = json.dumps({"jobs": {"deploy": {"runs-on": controller.SELECTOR}}})
        reference = "arteamis-system/platform/.github/workflows/deploy-vercel.yml@" + "a" * 40
        outer = json.dumps({"jobs": {"deploy": {"uses": reference}}})
        self.assertTrue(controller.compatible_workflow(outer, lambda *_: child))
        self.assertFalse(controller.compatible_workflow(outer.replace("a" * 40, "main"), Mock()))
        self.assertFalse(controller.compatible_workflow(outer, lambda *_: "jobs: {}"))

    def test_actual_dispatcher_has_routed_manifest_and_summary(self):
        import yaml
        source = Path(__file__).resolve().parents[1] / ".github/workflows/_dispatch.yml"
        jobs = yaml.safe_load(source.read_text())["jobs"]
        for name in ("manifest", "summary"):
            self.assertEqual(jobs[name]["runs-on"], controller.SELECTOR)

    def test_macos_stays_hosted_and_cannot_be_retried_as_linux(self):
        workflow = json.dumps({"jobs": {"mac": {"runs-on": "macos-15"}}})
        self.assertTrue(controller.compatible_workflow(workflow, Mock()))
        self.assertFalse(controller.billing_only([failed_job(labels=["macos-15"])], billing_annotations()))

    def test_observed_skips_do_not_block_validation_or_admit_active_optional_jobs(self):
        workflow = {"jobs": {"verify": {"runs-on": controller.SELECTOR}, "optional": {"name": "Optional publication", "uses": "arteamis-system/platform/.github/workflows/deploy-mirror.yml@" + "a" * 40}}}
        self.assertFalse(controller.compatible_workflow(json.dumps(workflow), lambda *_: "jobs: {}"))
        self.assertFalse(controller.compatible_workflow(json.dumps(workflow), lambda *_: "jobs: {}", {"Optional publication"}))
        self.assertFalse(controller.compatible_workflow(json.dumps(workflow), lambda *_: "jobs: {}", {"Other job"}))
        workflow["jobs"]["verify"]["name"] = "Optional publication"
        self.assertFalse(controller.compatible_workflow(json.dumps(workflow), lambda *_: "jobs: {}", {"Optional publication"}))

    def test_failed_job_rerun_retains_skips_without_reusing_superseded_skip_evidence(self):
        jobs = [
            {"name": "validate", "run_attempt": 1, "conclusion": "failure"},
            {"name": "publication", "run_attempt": 1, "conclusion": "skipped"},
            {"name": "validate", "run_attempt": 2, "conclusion": None}]
        self.assertEqual(controller.latest_skipped_job_names(jobs), {"publication"})
        jobs.append({"name": "publication", "run_attempt": 2, "conclusion": None})
        self.assertEqual(controller.latest_skipped_job_names(jobs), set())
        jobs.append({"name": "ambiguous", "run_attempt": 2, "conclusion": "skipped"})
        jobs.append({"name": "ambiguous", "run_attempt": 2, "conclusion": "success"})
        self.assertEqual(controller.latest_skipped_job_names(jobs), set())

    def test_service_deployment_requires_supported_immutable_infra_source(self):
        child = json.dumps({"jobs": {"promote": {"runs-on": controller.SELECTOR}}})
        reference = "arteamis-system/platform/.github/workflows/deploy-vm.yml@" + "a" * 40
        outer = json.dumps({"jobs": {"deploy": {"uses": reference}}})
        self.assertTrue(controller.compatible_workflow(outer, lambda *_: child))
        for unsupported in (reference.replace("a" * 40, "main"), reference.replace("deploy-service", "arbitrary-deploy")):
            self.assertFalse(controller.compatible_workflow(outer.replace(reference, unsupported), Mock()))
        self.assertFalse(controller.compatible_workflow(outer, lambda *_: 'jobs: {promote: {runs-on: ubuntu-latest}}'))


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()
        self.gh = Mock()
        self.gh.variable.return_value = None
        self.gh.pages.side_effect = lambda repo, suffix, *args: ([failed_job()] if suffix.endswith("/jobs") else billing_annotations()[7])
        self.run = {"id": 1, "run_attempt": 1, "head_sha": "a" * 40, "actor": {"login": "owner"}, "event": "push", "head_branch": "main"}
        self.ctrl = controller.Controller(self.gh, self.state, Mock(), {"routing_verified": True, "enforce_fork_policy": False}, now=1000)
        self.ctrl.trusted = Mock(return_value=True)
        self.ctrl.source_compatible = Mock(return_value=True)
        self.repo = "arteamis-system/platform"

    def test_one_automatic_retry_and_original_sha_recorded(self):
        self.assertTrue(self.ctrl.takeover(self.repo, self.run))
        self.assertFalse(self.ctrl.takeover(self.repo, {**self.run, "run_attempt": 2}))
        self.assertEqual(self.state.get("retry:" + self.repo + ":1")["sha"], "a" * 40)
        self.assertEqual(self.gh.call.call_count, 1)
        self.gh.set_variable.assert_called_once_with(self.repo, controller.AWS)

    def test_readback_error_never_requests_retry(self):
        self.gh.set_variable.side_effect = RuntimeError("readback mismatch")
        with self.assertRaises(RuntimeError):
            self.ctrl.takeover(self.repo, self.run)
        self.gh.call.assert_not_called()
        self.gh.set_variable.side_effect = None
        self.assertTrue(self.ctrl.takeover(self.repo, self.run))
        self.gh.call.assert_called_once()

    def test_timeout_after_accepted_mutation_does_not_duplicate(self):
        self.gh.call.side_effect = [TimeoutError(), {"run_attempt": 2}]
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.assertEqual(self.state.get("retry:" + self.repo + ":1")["phase"], "accepted")
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.assertEqual(self.gh.call.call_count, 2)

    def test_timeout_before_visible_acceptance_remains_ambiguous(self):
        self.gh.call.side_effect = [TimeoutError(), {"run_attempt": 1}]
        self.ctrl.takeover(self.repo, self.run)
        self.assertEqual(self.state.get("retry:" + self.repo + ":1")["phase"], "ambiguous")
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))

    def test_unverified_routing_and_untrusted_runs_cannot_rerun(self):
        self.ctrl.config["routing_verified"] = False
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.ctrl.config["routing_verified"] = True
        self.ctrl.trusted.return_value = False
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.gh.call.assert_not_called()

    def test_manual_routing_is_preserved(self):
        for value in (controller.AWS, '["custom-runner"]'):
            self.gh.variable.return_value = value
            self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.gh.set_variable.assert_not_called()

    def test_rejected_attempt_is_not_reclassified_every_minute(self):
        self.gh.pages.side_effect = lambda repo, suffix, *args: ([failed_job(runner_id=10)] if suffix.endswith("/jobs") else billing_annotations()[7])
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.assertEqual(self.gh.pages.call_count, 2)
        self.gh.call.assert_not_called()

    def test_fork_closed_and_superseded_pull_requests_are_rejected(self):
        ctrl = controller.Controller(self.gh, self.state, Mock(), {}, now=1000)
        run = {**self.run, "event": "pull_request", "pull_requests": [{"number": 10}]}
        for full_name, sha, status in (("outsider/infra", "a" * 40, "open"), (self.repo, "b" * 40, "open"), (self.repo, "a" * 40, "closed")):
            self.gh.call.side_effect = [{"permission": "write"}, {"state": status, "head": {"repo": {"full_name": full_name}, "sha": sha}}]
            self.assertFalse(ctrl.trusted(self.repo, run))

    def test_non_main_and_superseded_pushes_are_rejected(self):
        ctrl = controller.Controller(self.gh, self.state, Mock(), {}, now=1000)
        self.gh.call.side_effect = [{"permission": "write"}]
        self.assertFalse(ctrl.trusted(self.repo, {**self.run, "head_branch": "old-branch"}))
        self.gh.call.side_effect = [{"permission": "write"}, {"object": {"sha": "b" * 40}}]
        self.assertFalse(ctrl.trusted(self.repo, self.run))

    def test_deleted_canary_branch_and_unavailable_actor_are_rejected(self):
        ctrl = controller.Controller(self.gh, self.state, Mock(), {}, now=1000)
        stale = {**self.run, "head_branch": "ci/aws-runner-fallback"}
        self.gh.call.side_effect = [{"permission": "write"}, controller.ApiError(404)]
        self.assertFalse(ctrl.trusted(self.repo, stale, canary=True))
        self.gh.call.side_effect = controller.ApiError(404)
        self.assertFalse(ctrl.trusted(self.repo, self.run))
        self.gh.call.side_effect = controller.ApiError(500)
        with self.assertRaises(controller.ApiError):
            ctrl.trusted(self.repo, self.run)

    def test_stale_canary_and_queued_hosted_probe_do_not_block_current_queue(self):
        stale = {**self.run, "path": ".github/workflows/ci-runner-canary.yml", "status": "completed",
                 "conclusion": "failure", "event": "workflow_dispatch", "head_branch": "ci/aws-runner-fallback",
                 "created_at": "1970-01-01T00:16:39Z"}
        current = {**stale, "id": 2, "status": "queued", "conclusion": None, "head_branch": "main"}
        probe = {**current, "id": 3, "path": ".github/workflows/ci-hosted-probe.yml", "actor": {"login": "app[bot]"}}
        def call(repo, method, path, *args):
            if path == "":
                return {"private": True}
            if path.endswith("fork-pr-workflows-private-repos"):
                return {key: False for key in ("run_workflows_from_fork_pull_requests", "send_write_tokens_to_workflows", "send_secrets_and_variables")}
            if path == "/collaborators/owner/permission":
                return {"permission": "write"}
            if path == "/git/ref/heads/ci%2FArteamis-49-runner-fallback":
                raise controller.ApiError(404)
            if path == "/git/ref/heads/main":
                return {"object": {"sha": self.run["head_sha"]}}
            raise AssertionError("Unexpected request: " + path)
        self.gh.call.side_effect = call
        self.gh.pages.side_effect = lambda repo, suffix, *args: (
            [probe, current, stale] if suffix.startswith("/actions/runs?") else
            [{"id": 17, "status": "queued", "labels": controller.aws_labels(2), "created_at": "1970-01-01T00:16:39Z"}])
        config = {"routing_verified": True, "max_instances": 2, "enforce_fork_policy": False, "canary_repository": self.repo, "repositories": {self.repo: ["ci-runner-canary.yml"]}}
        runner_pool = Mock()
        ctrl = controller.Controller(self.gh, self.state, runner_pool, config, now=1000)
        ctrl.source_compatible = Mock(return_value=True)
        ctrl.tick()
        runner_pool.fulfill.assert_called_once_with(self.gh, self.state, [("1970-01-01T00:16:39Z", self.repo, 17, 2)], 2, 1000)
        self.gh.set_variable.assert_not_called()
        self.assertEqual(self.state.get("retry:" + self.repo + ":1"), {})

    def test_successful_correlated_hosted_probe_restores_original_variable(self):
        self.ctrl.config["probe_interval_seconds"] = 21600
        self.state.put("mode:" + self.repo, {"phase": "aws", "previous": None, "enabled_at": 0, "probe": {"nonce": "nonce", "time": 999}})
        self.gh.variable.return_value = controller.AWS
        self.gh.pages.side_effect = [[{"id": 20, "display_title": "Arteamis hosted probe nonce", "conclusion": "success", "event": "workflow_dispatch", "head_branch": "main"}],
                                     [{"conclusion": "success", "labels": ["ubuntu-24.04"], "runner_name": "GitHub Actions 1", "runner_id": 1}]]
        self.ctrl.recover(self.repo)
        self.gh.set_variable.assert_called_once_with(self.repo, None)
        self.assertEqual(self.state.get("mode:" + self.repo), {})

    def test_unrelated_probe_cannot_restore_routing(self):
        self.ctrl.config["probe_interval_seconds"] = 21600
        self.state.put("mode:" + self.repo, {"phase": "aws", "previous": None, "enabled_at": 0, "probe": {"nonce": "nonce", "time": 999}})
        self.gh.variable.return_value = controller.AWS
        self.gh.pages.side_effect = [[{"id": 20, "display_title": "Arteamis hosted probe another", "conclusion": "success"}]]
        self.ctrl.recover(self.repo)
        self.gh.set_variable.assert_not_called()

    def test_restoration_with_lost_readback_completes_without_another_write(self):
        self.state.put("mode:" + self.repo, {"phase": "restoring", "previous": None, "recovered_probe_run": 20})
        self.gh.variable.return_value = None
        self.ctrl.recover(self.repo)
        self.assertEqual(self.state.get("mode:" + self.repo), {})
        self.gh.set_variable.assert_not_called()

    def test_manual_hosted_override_blocks_later_automatic_takeovers(self):
        self.state.put("mode:" + self.repo, {"phase": "aws", "previous": None, "enabled_at": 900})
        self.gh.variable.return_value = controller.HOSTED
        self.assertFalse(self.ctrl.takeover(self.repo, self.run))
        self.assertEqual(self.state.get("mode:" + self.repo)["phase"], "manual")
        self.ctrl.recover(self.repo)
        self.gh.set_variable.assert_not_called()

    def test_partial_variable_switch_is_reconciled_without_duplicate_retry(self):
        self.ctrl.config["probe_interval_seconds"] = 21600
        self.state.put("mode:" + self.repo, {"phase": "switching", "previous": None, "enabled_at": 900})
        self.gh.variable.return_value = controller.AWS
        self.ctrl.recover(self.repo)
        self.assertEqual(self.state.get("mode:" + self.repo)["phase"], "aws")
        self.gh.call.assert_called_once()

    def test_repository_errors_fail_closed_but_cleanup_still_runs(self):
        config = {"repositories": {self.repo: ["repository-policy.yml"]}, "max_instances": 2, "routing_verified": True}
        runner_pool = Mock()
        runner_pool.fulfill.return_value = {"launched": 0}
        self.gh.call.side_effect = controller.ApiError(429)
        ctrl = controller.Controller(self.gh, self.state, runner_pool, config, now=1000)
        self.assertEqual(ctrl.tick(), {"launched": 0})
        runner_pool.reconcile.assert_called_once()
        self.assertEqual(runner_pool.fulfill.call_args.args[2], [])

    def test_queued_main_push_is_serviced_without_a_previous_failed_push(self):
        run = {**self.run, "status": "queued", "conclusion": None,
               "created_at": "1970-01-01T00:16:00Z", "path": ".github/workflows/repository-policy.yml"}
        self.ctrl.config.update({"repositories": {self.repo: ["repository-policy.yml"]},
                                 "max_instances": 2})
        self.gh.call.side_effect = [{"private": True}, {"object": {"sha": run["head_sha"]}}]
        self.gh.pages.side_effect = [[run], [{"id": 7, "status": "queued", "labels": controller.aws_labels(1)}]]
        self.ctrl.tick()
        self.ctrl.pool.fulfill.assert_called_once_with(
            self.gh, self.state, [(run["created_at"], self.repo, 7, 1)], 2, 1000)

    def test_pending_or_requested_run_admits_only_queued_aws_jobs(self):
        self.ctrl.config.update({"repositories": {self.repo: ["repository-policy.yml"]}, "max_instances": 2})
        for status in ("pending", "requested"):
            with self.subTest(status=status):
                run = {**self.run, "status": status, "conclusion": None, "created_at": "1970-01-01T00:16:00Z", "path": ".github/workflows/repository-policy.yml"}
                self.gh.call.side_effect = [{"private": True}, {"object": {"sha": run["head_sha"]}}]
                self.gh.pages.side_effect = [[run], [
                    {"id": 7, "status": "queued", "labels": controller.aws_labels(1)},
                    {"id": 8, "status": "waiting", "labels": controller.aws_labels(1)},
                    {"id": 9, "status": "queued", "labels": ["ubuntu-24.04"]}]]
                self.ctrl.pool.fulfill.reset_mock()
                self.ctrl.tick()
                self.ctrl.pool.fulfill.assert_called_once_with(self.gh, self.state, [(run["created_at"], self.repo, 7, 1)], 2, 1000)


def instance(age=0, state="running", **extra):
    return {"InstanceId": "i-test", "State": {"Name": state}, "LaunchTime": dt.datetime.fromtimestamp(10000 - age, dt.timezone.utc),
            "Tags": [{"Key": "ArteamisCiPool", "Value": "arteamis-ci"}, {"Key": "ArteamisCiRole", "Value": "runner"}], **extra}


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.ec2 = Mock()
        self.observed = []
        self.ec2.get_paginator.return_value.paginate.side_effect = lambda **_: [{"Reservations": [{"Instances": self.observed}]}]
        self.gh = Mock()
        self.gh.pages.return_value = []
        self.gh.call.return_value = {"runner": {"id": 10}, "encoded_jit_config": "ONE_USE_TOKEN"}
        self.state = MemoryState()
        self.pool = pool.Pool(self.ec2, "lt-ci", "3")
        def launch(**args):
            row = instance(ClientToken=args["ClientToken"], Tags=args["TagSpecifications"][0]["Tags"], InstanceId="i-" + args["ClientToken"])
            self.observed.append(row)
            return {"Instances": [row]}
        self.ec2.run_instances.side_effect = launch

    def test_capacity_is_two_even_with_many_queued_jobs(self):
        queue = [("", "arteamis-system/platform", index, 1) for index in range(10)]
        self.assertEqual(self.pool.fulfill(self.gh, self.state, queue, 2, 10000)["launched"], 2)
        self.assertEqual(self.pool.fulfill(self.gh, self.state, queue, 2, 10001)["launched"], 0)
        self.assertEqual(self.ec2.run_instances.call_count, 2)
        for call in self.ec2.run_instances.call_args_list:
            self.assertEqual(call.kwargs["MaxCount"], 1)
            self.assertEqual(call.kwargs["LaunchTemplate"]["Version"], "3")
            boot = call.kwargs["UserData"]
            self.assertTrue(boot.startswith("#!/usr/bin/env bash\n"))
            self.assertIn("shutdown -h now", boot)
            self.assertIn("--jitconfig ONE_USE_TOKEN", boot)
            self.assertNotIn("private_key", boot)

    def test_ambiguous_launch_reserves_capacity(self):
        self.ec2.run_instances.side_effect = TimeoutError()
        queue = [("", "arteamis-system/platform", index, 1) for index in range(5)]
        self.pool.fulfill(self.gh, self.state, queue, 2, 10000)
        self.pool.fulfill(self.gh, self.state, queue, 2, 10001)
        self.assertEqual(self.ec2.run_instances.call_count, 2)
        self.assertEqual(self.state.get("slot:0")["phase"], "ambiguous")

    def test_failed_boots_cannot_cause_unlimited_replacements(self):
        queue = [("", "arteamis-system/platform", 7, 1)]
        for attempt in range(5):
            self.pool.fulfill(self.gh, self.state, queue, 2, 10000 + attempt * 60)
            for row in self.observed:
                row["State"]["Name"] = "terminated"
            self.pool.reconcile(self.gh, self.state, 10001 + attempt * 60)
        self.assertEqual(self.ec2.run_instances.call_count, 2)
        self.assertEqual(self.state.get(pool.supply_key("arteamis-system/platform", queue))["attempts"], 2)
        # New demand has its own limit and can still run.
        self.pool.fulfill(self.gh, self.state, [("", "arteamis-system/platform", 8, 1)], 2, 10360)
        self.assertEqual(self.ec2.run_instances.call_count, 3)

    def test_out_of_order_job_assignment_does_not_exhaust_unserved_jobs(self):
        repo = "arteamis-system/platform"
        queue = [("", repo, 7, 1), ("", repo, 8, 1), ("", repo, 9, 1), ("", repo, 10, 1)]
        self.pool.fulfill(self.gh, self.state, queue, 2, 10000)
        self.assertEqual(self.ec2.run_instances.call_count, 2)
        # GitHub assigns those runners to jobs 9 and 10. Jobs 7 and 8 remain.
        for row in self.observed:
            row["State"]["Name"] = "terminated"
        self.pool.reconcile(self.gh, self.state, 10001)
        self.pool.fulfill(self.gh, self.state, queue[:2], 2, 10002)
        self.assertEqual(self.ec2.run_instances.call_count, 4)

    def test_completed_superseded_job_proves_progress_without_clearing_old_bounds(self):
        repo = "arteamis-system/platform"
        queue = [("", repo, 7, 1), ("", repo, 8, 1)]
        old_key = pool.supply_key(repo, queue)
        self.pool.fulfill(self.gh, self.state, queue, 2, 10000)
        name = pool.tags(self.observed[0])["ArteamisCiRunner"]
        for row in self.observed:
            row["State"]["Name"] = "terminated"
        self.pool.reconcile(self.gh, self.state, 10020)
        def pages(_repo, path, _key):
            if path.startswith("/actions/runs?"):
                return [{"id": 20, "updated_at": "1970-01-01T02:47:00Z"}]
            if path.startswith("/actions/runs/20/jobs"):
                return [{"id": 99, "status": "completed", "runner_name": name, "runner_id": 10,
                         "steps": [{"name": "Validation", "conclusion": "success"}],
                         "started_at": "1970-01-01T02:46:41Z", "completed_at": "1970-01-01T02:47:00Z"}]
            return []
        self.gh.pages.side_effect = pages
        self.assertEqual(self.pool.fulfill(self.gh, self.state, queue, 2, 10070)["launched"], 2)
        self.assertEqual(self.state.get(old_key)["attempts"], 2)
        self.assertEqual(self.state.get("pool-progress:" + repo)["job_id"], 99)
        for row in self.observed:
            row["State"]["Name"] = "terminated"
        self.pool.reconcile(self.gh, self.state, 10080)
        self.assertEqual(self.pool.fulfill(self.gh, self.state, queue, 2, 10090)["launched"], 0)
        self.assertEqual(self.ec2.run_instances.call_count, 4)

    def test_unknown_runner_or_no_executed_steps_cannot_renew_capacity(self):
        row = instance(state="terminated", Tags=[{"Key": "ArteamisCiRepository", "Value": "arteamis-system/platform"},
            {"Key": "ArteamisCiRunner", "Value": "arteamis-ci-owned"}])
        gh = Mock()
        for name, steps in [("arteamis-ci-unowned", [{"name": "Check"}]), ("arteamis-ci-owned", [])]:
            gh.pages.side_effect = [[{"id": 20, "updated_at": "1970-01-01T02:47:00Z"}],
                [{"id": 99, "status": "completed", "runner_name": name, "runner_id": 10, "steps": steps,
                  "started_at": "1970-01-01T02:46:41Z", "completed_at": "1970-01-01T02:47:00Z"}]]
            self.assertIsNone(pool.completed_progress(gh, "arteamis-system/platform", [row], 10000, 10070))

    def test_orphan_instance_still_occupies_capacity(self):
        self.observed = [instance(InstanceId="i-orphan1"), instance(InstanceId="i-orphan2")]
        self.pool.fulfill(self.gh, self.state, [("", "arteamis-system/platform", 1, 1)], 2, 10000)
        self.ec2.run_instances.assert_not_called()

    def test_missing_ambiguous_launch_is_not_released_after_ten_minutes(self):
        self.state.put("slot:0", {"client_token": "unknown", "created_at": 1000, "repo": "arteamis-system/platform", "phase": "ambiguous"})
        self.pool.reconcile(self.gh, self.state, 10000)
        self.assertEqual(self.state.get("slot:0")["client_token"], "unknown")
        queue = [("", "arteamis-system/platform", index, 1) for index in range(5)]
        self.assertEqual(self.pool.fulfill(self.gh, self.state, queue, 2, 10000)["launched"], 1)
        self.assertEqual(self.ec2.run_instances.call_count, 1)

    def test_definite_launch_rejection_can_release_its_unused_slot(self):
        error = RuntimeError("rejected")
        error.response = {"Error": {"Code": "UnauthorizedOperation"}}
        self.ec2.run_instances.side_effect = error
        self.pool.fulfill(self.gh, self.state, [("", "arteamis-system/platform", 1, 1)], 2, 10000)
        self.assertEqual(self.state.get("slot:0")["phase"], "launch-rejected")
        self.pool.reconcile(self.gh, self.state, 10601)
        self.assertEqual(self.state.get("slot:0"), {})
        self.gh.call.assert_any_call("arteamis-system/platform", "DELETE", "/actions/runners/10")

    def test_lost_launch_response_is_reconciled(self):
        self.observed = [instance(ClientToken="token")]
        self.state.put("slot:0", {"client_token": "token", "created_at": 9900, "repo": "arteamis-system/platform"})
        self.pool.reconcile(self.gh, self.state, 10000)
        self.assertEqual(self.state.get("slot:0")["instance_id"], "i-test")

    def test_hard_deadline_cannot_be_extended_by_tag(self):
        row = instance(age=5400, Tags=[{"Key": "ArteamisCiExpires", "Value": "999999999"}])
        self.assertTrue(pool.expired(row, 10000))
        self.assertFalse(pool.expired(instance(age=5399), 10000))
        self.assertTrue(pool.expired(instance(state="stopped"), 10000))

    def test_aws_only_reaper_works_without_github_or_secret(self):
        self.observed = [instance(age=6000), instance(age=0, InstanceId="i-fresh")]
        result = reaper.reap(self.ec2, 10000)
        self.assertEqual(result["terminated"], ["i-test"])
        self.ec2.terminate_instances.assert_called_once_with(InstanceIds=["i-test"])


class ProvisionTests(unittest.TestCase):
    def test_image_wait_can_outlast_the_stock_ten_minute_waiter(self):
        states = iter(["pending"] * 41 + ["available"])
        def describe(*args):
            return {"Images": [{"State": next(states)}]}
        with patch.object(provision, "aws", side_effect=describe), patch.object(provision.time, "sleep"):
            provision.wait_image("arteamis-ci-operator", "ami-ci")

    def test_failed_image_is_rejected_immediately(self):
        with patch.object(provision, "aws", return_value={"Images": [{"State": "failed"}]}), patch.object(provision.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "image creation failed"):
                provision.wait_image("arteamis-ci-operator", "ami-ci")
            sleep.assert_not_called()

    def test_disable_waits_for_lease_instead_of_reporting_an_unapplied_action(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(provision, "BUILD", Path(directory)), patch.object(provision.time, "sleep"):
            responses = iter([{"leased": True}, {"leased": True}, {"disabled": True}])
            def invocation(*args):
                Path(args[-1]).write_text(json.dumps(next(responses)))
                return {}
            with patch.object(provision, "aws", side_effect=invocation) as aws:
                self.assertEqual(provision.invoke("arteamis-ci-operator", "disable"), {"disabled": True})
                self.assertEqual(aws.call_count, 3)

    def test_regular_tick_does_not_retry_when_controller_is_busy(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(provision, "BUILD", Path(directory)):
            def invocation(*args):
                Path(args[-1]).write_text('{"leased": true}')
                return {}
            with patch.object(provision, "aws", side_effect=invocation) as aws:
                self.assertEqual(provision.invoke("arteamis-ci-operator", "tick"), {"leased": True})
                aws.assert_called_once()


class RoutingReadbackTests(unittest.TestCase):
    def test_propagation_delay_repeats_reads_without_duplicate_writes(self):
        gh = controller.GitHub({})
        gh.variable = Mock(side_effect=[None, None, None, controller.AWS])
        gh.call = Mock()
        with patch.object(controller.time, "sleep"):
            gh.set_variable("arteamis-system/platform", controller.AWS)
        gh.call.assert_called_once_with("arteamis-system/platform", "POST", "/actions/variables",
                                        {"name": controller.VARIABLE, "value": controller.AWS})

    def test_delete_waits_for_readback_without_repeating_delete(self):
        gh = controller.GitHub({})
        gh.variable = Mock(side_effect=[controller.AWS, controller.AWS, None])
        gh.call = Mock()
        with patch.object(controller.time, "sleep"):
            gh.set_variable("arteamis-system/platform", None)
        gh.call.assert_called_once_with("arteamis-system/platform", "DELETE", "/actions/variables/" + controller.VARIABLE)


class InfrastructureTests(unittest.TestCase):
    def test_sns_policy_has_unique_identifiers_required_by_the_service(self):
        policy = provision.alerts.template()["Resources"]["TopicPolicy"]["Properties"]["PolicyDocument"]
        self.assertTrue(policy["Id"])
        identifiers = [statement["Sid"] for statement in policy["Statement"]]
        self.assertTrue(all(identifiers))
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_image_account_guards_handle_amazon_alias_without_trusting_every_amazon_image(self):
        image = f"arn:aws:ec2:{stack.REGION}::image/*"
        def permits(statements, account, ci_tag=False):
            context = {"ec2:Owner": "amazon", "aws:ResourceAccount": account}
            if ci_tag:
                context["ec2:ResourceTag/ArteamisCiPool"] = "arteamis-ci"
            for item in statements:
                if item["Action"] != "ec2:RunInstances" or item["Resource"] != image:
                    continue
                conditions = item["Condition"]["StringEquals"]
                if all(context.get(key) in (value if isinstance(value, list) else [value])
                       for key, value in conditions.items()):
                    return True
            return False
        setup = setup_policy.setup_policy()["Statement"]
        self.assertTrue(permits(setup, "099720109477"))
        self.assertTrue(permits(setup, stack.ACCOUNT))
        self.assertFalse(permits(setup, "187296253231"))
        runtime = stack.runtime_permissions()
        self.assertTrue(permits(runtime, stack.ACCOUNT, ci_tag=True))
        self.assertFalse(permits(runtime, stack.ACCOUNT))
        self.assertFalse(permits(runtime, "099720109477", ci_tag=True))
        self.assertFalse(permits(runtime, "187296253231", ci_tag=True))

    def test_all_roles_have_administrator_owned_boundary(self):
        for resource in stack.foundation()["Resources"].values():
            if resource["Type"] == "AWS::IAM::Role":
                self.assertEqual(resource["Properties"]["PermissionsBoundary"], stack.BOUNDARY)

    def test_runtime_is_isolated_and_deletes_disks(self):
        template = stack.runtime("ami-ci", "controller/hash.zip", {"SubnetId": "subnet-ci", "SecurityGroupId": "sg-ci", "RunnerProfileArn": "profile-ci", "ArtifactBucket": "bucket-ci"})
        data = template["Resources"]["LaunchTemplate"]["Properties"]["LaunchTemplateData"]
        self.assertEqual(data["InstanceInitiatedShutdownBehavior"], "terminate")
        self.assertTrue(data["BlockDeviceMappings"][0]["Ebs"]["DeleteOnTermination"])
        self.assertEqual(data["InstanceType"], "m6i.large")
        self.assertNotIn("SecurityGroupIngress", stack.foundation()["Resources"]["SecurityGroup"]["Properties"])
        self.assertEqual(template["Resources"]["ControllerSchedule"]["Properties"]["State"], "DISABLED")
        self.assertEqual(template["Resources"]["Controller"]["Properties"]["Environment"]["Variables"]["ROUTING_VERIFIED"], "false")
        runner = json.dumps(stack.foundation()["Resources"]["RunnerRole"])
        for forbidden in ("kms:", "GetParameter", "ecr:", "production"):
            self.assertNotIn(forbidden, runner)


if __name__ == "__main__":
    unittest.main()

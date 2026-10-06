"""Regression contract for the protected dot-github release promoter."""

import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "promote-develop-to-main.yml"


class ReleaseAppPromoterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.token_validation = cls.workflow.split(
            "      - name: Validate release bot token\n", 1
        )[1].split("\n      - name: Create or update protected promotion", 1)[0]
        cls.token_validation_script = textwrap.dedent(
            cls.token_validation.split("        run: |\n", 1)[1]
        )

    def _validate_release_token(
        self,
        response: object | str,
        *,
        app_slug: str = "lightning-it-release-automation",
        installation_id: str = "148019054",
        repository: str = "lightning-it/.github",
        token: str = "release-token",
        api_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        fake_gh = r"""gh() {
  if [ "$#" -ne 4 ] \
    || [ "${1:-}" != api ] \
    || [ "${2:-}" != --paginate ] \
    || [ "${3:-}" != --slurp ] \
    || [ "${4:-}" != "installation/repositories?per_page=100" ]; then
    printf 'unexpected fake gh invocation\n' >&2
    return 88
  fi
  if [ "${GH_TOKEN}" != release-token ]; then
    printf 'unexpected release token\n' >&2
    return 87
  fi
  if [ "${GH_API_FAILURE}" = true ]; then
    return 42
  fi
  printf '%s\n' "${REPOSITORY_PAGES}"
}"""
        script = "\n".join(
            (fake_gh, self.token_validation_script, "printf 'TOKEN_SCOPE_VALID\\n'")
        )
        repository_pages = (
            response if isinstance(response, str) else json.dumps(response)
        )
        return subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "APP_INSTALLATION_ID": installation_id,
                "APP_SLUG": app_slug,
                "EXPECTED_APP_SLUG": "lightning-it-release-automation",
                "EXPECTED_INSTALLATION_ID": "148019054",
                "EXPECTED_REPOSITORY": "lightning-it/.github",
                "GH_API_FAILURE": "true" if api_failure else "false",
                "GH_TOKEN": token,
                "REPOSITORY": repository,
                "REPOSITORY_PAGES": repository_pages,
            },
        )

    def test_controller_is_bound_to_dot_github_and_protected_develop(self) -> None:
        workflow = self.workflow

        self.assertIn("branches: [develop]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn('cron: "41 * * * *"', workflow)
        self.assertEqual(
            workflow.count("if: github.repository == 'lightning-it/.github'"), 1
        )
        self.assertNotIn(
            "if: github.repository == 'lightning-it/shared-assets-lit'", workflow
        )
        self.assertIn(
            "git merge-base --is-ancestor origin/main origin/develop", workflow
        )
        self.assertIn("git diff --quiet origin/main origin/develop", workflow)

    def test_release_app_tokens_are_separate_and_least_privilege(self) -> None:
        workflow = self.workflow

        action = (
            "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"
        )
        self.assertEqual(workflow.count(action), 1)
        self.assertEqual(
            workflow.count("secrets.RELEASE_AUTOMATION_APP_PRIVATE_KEY"), 1
        )
        self.assertEqual(workflow.count("permission-pull-requests: write"), 1)
        self.assertNotIn("permission-actions: write", workflow)
        self.assertEqual(workflow.count("permission-contents: read"), 1)
        self.assertNotIn("permission-contents: write", workflow)
        self.assertNotIn("permission-checks: write", workflow)
        self.assertNotRegex(workflow, re.compile(r"(?m)^\s+checks:\s+write\s*$"))
        self.assertIn("APP_SLUG: ${{ steps.release-app.outputs.app-slug }}", workflow)
        self.assertIn(
            "APP_INSTALLATION_ID: ${{ steps.release-app.outputs.installation-id }}",
            workflow,
        )
        self.assertIn("EXPECTED_APP_SLUG: lightning-it-release-automation", workflow)
        self.assertIn('EXPECTED_INSTALLATION_ID: "148019054"', workflow)
        self.assertIn("EXPECTED_REPOSITORY: lightning-it/.github", workflow)
        self.assertIn(
            "GH_TOKEN: ${{ steps.release-app.outputs.token }}",
            self.token_validation,
        )
        self.assertIn("gh api --paginate --slurp", self.token_validation)
        self.assertIn("jq -se", self.token_validation)
        self.assertIn('"installation/repositories?per_page=100"', self.token_validation)
        self.assertNotIn("gh api installation", workflow)
        self.assertNotIn("users/", self.token_validation)
        self.assertIn("repositories: ${{ github.event.repository.name }}", workflow)
        self.assertNotIn("Resolve release automation App bot identity", workflow)
        self.assertNotIn("steps.release-bot.outputs", workflow)

    def test_release_app_token_accepts_only_exact_repository_scope(self) -> None:
        result = self._validate_release_token(
            [
                {
                    "total_count": 1,
                    "repositories": [{"full_name": "lightning-it/.github"}],
                }
            ]
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("TOKEN_SCOPE_VALID\n", result.stdout)

    def test_release_app_token_rejects_wrong_action_identity_outputs(self) -> None:
        valid_response = [
            {
                "total_count": 1,
                "repositories": [{"full_name": "lightning-it/.github"}],
            }
        ]
        cases = {
            "wrong app slug": {"app_slug": "foreign-app"},
            "missing app slug": {"app_slug": ""},
            "malformed app slug": {"app_slug": "lightning-it-release-automation/other"},
            "wrong installation id": {"installation_id": "148019055"},
            "missing installation id": {"installation_id": ""},
            "malformed installation id": {"installation_id": "148019054x"},
            "wrong protected repository": {"repository": "lightning-it/other"},
            "missing token": {"token": ""},
            "wrong token": {"token": "foreign-token"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(valid_response, **overrides)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

    def test_release_app_token_rejects_non_exact_repository_sets(self) -> None:
        cases = {
            "missing repository": [{"total_count": 0, "repositories": []}],
            "duplicate repository": [
                {
                    "total_count": 2,
                    "repositories": [
                        {"full_name": "lightning-it/.github"},
                        {"full_name": "lightning-it/.github"},
                    ],
                }
            ],
            "foreign repository": [
                {
                    "total_count": 1,
                    "repositories": [{"full_name": "lightning-it/other"}],
                }
            ],
            "target plus foreign repository": [
                {
                    "total_count": 2,
                    "repositories": [
                        {"full_name": "lightning-it/.github"},
                        {"full_name": "lightning-it/other"},
                    ],
                }
            ],
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(response)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

    def test_release_app_token_rejects_malformed_api_or_pagination(self) -> None:
        repository = {"full_name": "lightning-it/.github"}
        valid_page = {"total_count": 1, "repositories": [repository]}
        cases: dict[str, object | str] = {
            "invalid json": "not-json",
            "empty response": "",
            "extra leading json document": ("false\n" + json.dumps([valid_page])),
            "extra trailing json document": (json.dumps([valid_page]) + "\nfalse"),
            "non-array pagination envelope": valid_page,
            "empty pagination envelope": [],
            "multiple pages for one visible repository": [valid_page, valid_page],
            "non-object page": [7],
            "missing total count": [{"repositories": [repository]}],
            "string total count": [{"total_count": "1", "repositories": [repository]}],
            "inconsistent total count": [
                {"total_count": 2, "repositories": [repository]}
            ],
            "non-array repositories": [{"total_count": 1, "repositories": repository}],
            "non-object repository": [
                {"total_count": 1, "repositories": ["lightning-it/.github"]}
            ],
            "missing full name": [
                {"total_count": 1, "repositories": [{"name": ".github"}]}
            ],
            "non-string full name": [
                {"total_count": 1, "repositories": [{"full_name": 7}]}
            ],
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result = self._validate_release_token(response)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("TOKEN_SCOPE_VALID", result.stdout)

        api_failure = self._validate_release_token([valid_page], api_failure=True)
        self.assertNotEqual(0, api_failure.returncode)
        self.assertNotIn("TOKEN_SCOPE_VALID", api_failure.stdout)

    def test_controller_creates_only_same_repo_develop_to_main_pr(self) -> None:
        workflow = self.workflow

        self.assertIn('"repos/${REPOSITORY}/pulls"', workflow)
        self.assertIn('-f "base=main"', workflow)
        self.assertIn('-f "head=develop"', workflow)
        self.assertIn(".base.repo.full_name == $repository", workflow)
        self.assertIn(".head.repo.full_name == $repository", workflow)
        self.assertIn('.base.ref == "main"', workflow)
        self.assertIn('.head.ref == "develop"', workflow)
        self.assertIn('.user.login == "lightning-it-release-automation[bot]"', workflow)
        self.assertNotIn("gh pr ready", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("--auto", workflow)
        self.assertNotIn("--admin", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("lightning-it/shared-assets-lit", workflow)
        self.assertNotIn("transition_title", workflow)

    def test_promotions_publish_only_native_aggregate_binding(self) -> None:
        workflow = self.workflow
        self.assertNotIn("gh workflow run", workflow)
        self.assertNotIn("release-bot-exact-head-review.yml", workflow)
        self.assertNotIn("bounded_mode", workflow)
        self.assertNotIn("Human approval", workflow)
        self.assertIn("lit-protected-promotion:v2", workflow)
        self.assertIn("lit-promotion-evidence-ready:", workflow)
        self.assertIn("Reject reruns before credential minting", workflow)
        self.assertNotIn("gh run rerun", workflow)
        self.assertNotIn("gh copilot", workflow.lower())
        self.assertNotIn("openai/codex-action", workflow.lower())

    def test_actual_fresh_and_existing_promotion_callers_make_zero_ai_calls(
        self,
    ) -> None:
        """Run the real controller and Required event guards with Git/API fixtures."""
        create = self.workflow.split(
            "      - name: Create or update protected promotion\n", 1
        )[1].split("\n      - name:", 1)[0]
        create_script = textwrap.dedent(create.split("        run: |\n", 1)[1])
        required = (
            ROOT / ".github/workflows/supplementary-current-revision-required.yml"
        ).read_text()
        route = required.split(
            "      - name: Classify the protected S0 feature-to-main route\n", 1
        )[1]
        route_script = textwrap.dedent(
            route.split("        run: |\n", 1)[1].split("\n  reserve-s0-", 1)[0]
        )
        aggregate = required.split(
            "      - name: Aggregate exact protected ingress evidence\n", 1
        )[1]
        aggregate_script = textwrap.dedent(
            aggregate.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        )
        event_guard = (
            "set -euo pipefail\nhead_marker="
            + aggregate_script.split("head_marker=", 1)[1].split(
                "event_body_sha256=", 1
            )[0]
        )
        fixture = r"""
import json, os, pathlib, sys
args = sys.argv[1:]
state_path = pathlib.Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
with open(os.environ["FAKE_CALLS"], "a") as log:
    log.write(json.dumps(args) + "\n")
repository = "lightning-it/.github"
result = None
if args[:1] == ["api"]:
    endpoint = next((a for a in args if a.startswith("repos/")), "")
    method = args[args.index("--method") + 1] if "--method" in args else "GET"
    if endpoint == f"repos/{repository}/pulls?state=open&per_page=100" and method == "GET":
        result = [[p for p in state["pulls"] if p["state"] == "open"]]
    elif endpoint == f"repos/{repository}/pulls?state=closed&per_page=100" and method == "GET":
        result = [[p for p in state["pulls"] if p["state"] == "closed"]]
    elif endpoint == f"repos/{repository}/pulls" and method == "POST":
        values = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-f")
        assert values["base"] == "main" and values["head"] == "develop"
        result = {"number": 41, "state": "open", "draft": False,
                  "title": values["title"], "body": values["body"],
                  "user": {"login": "lightning-it-release-automation[bot]", "id": 307565056, "type": "Bot"},
                  "base": {"ref": "main", "sha": state["base"], "repo": {"full_name": repository}},
                  "head": {"ref": "develop", "sha": state["head"], "repo": {"full_name": repository}}}
        state["pulls"].append(result)
    elif endpoint == f"repos/{repository}/pulls/41" and method == "GET":
        result = state["pulls"][0]
    else:
        raise AssertionError(args)
elif args[:2] == ["pr", "view"]:
    p = state["pulls"][0]
    result = {"author": {"login": "app/lightning-it-release-automation"},
              "baseRefName": p["base"]["ref"], "baseRefOid": p["base"]["sha"],
              "headRefName": p["head"]["ref"], "headRefOid": p["head"]["sha"],
              "headRepositoryOwner": {"login": "lightning-it"}, "isDraft": p["draft"],
              "title": p["title"], "body": p["body"], "state": p["state"].upper()}
else:
    # In particular, AI workflows, model calls, review requests and reruns are forbidden.
    raise AssertionError(args)
state_path.write_text(json.dumps(state))
print(json.dumps(result))
"""
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            origin = temp / "origin"
            environment = {
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            }

            def git(*arguments: str) -> str:
                return subprocess.check_output(
                    ["git", *arguments],
                    cwd=temp,
                    env=environment,
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()

            git("init", "--quiet", str(origin))
            git("-C", str(origin), "config", "user.name", "Fixture")
            git("-C", str(origin), "config", "user.email", "fixture@example.invalid")
            (origin / "tracked").write_text("base\n")
            git("-C", str(origin), "add", ".")
            git("-C", str(origin), "commit", "--quiet", "-m", "base")
            git("-C", str(origin), "branch", "-M", "main")
            base = git("-C", str(origin), "rev-parse", "HEAD")
            git("-C", str(origin), "checkout", "--quiet", "-b", "develop")
            (origin / "tracked").write_text("reviewed ingress\n")
            git("-C", str(origin), "commit", "--quiet", "-am", "reviewed ingress")
            head = git("-C", str(origin), "rev-parse", "HEAD")
            state = temp / "state.json"
            state.write_text(json.dumps({"base": base, "head": head, "pulls": []}))
            calls = temp / "calls.jsonl"
            fake = temp / "gh.py"
            fake.write_text(textwrap.dedent(fixture))
            environment.update(
                {
                    "FAKE_GH": str(fake),
                    "FAKE_STATE": str(state),
                    "FAKE_CALLS": str(calls),
                    "FAKE_ORIGIN": str(origin),
                    "GH_TOKEN": "fixture-token",
                    "REPOSITORY": "lightning-it/.github",
                    "REPOSITORY_OWNER": "lightning-it",
                    "GITHUB_RUN_ID": "901",
                    "GITHUB_RUN_ATTEMPT": "1",
                }
            )
            transport = r"""
gh() { python3 "${FAKE_GH}" "$@"; }
git() {
  if [ "${1:-}" = remote ] && [ "${2:-}" = add ] && [ "${3:-}" = origin ]; then
    command git remote add origin "${FAKE_ORIGIN}"
  else
    command git "$@"
  fi
}
"""
            for attempt in range(2):
                run = temp / f"run-{attempt}"
                run.mkdir()
                environment["GITHUB_OUTPUT"] = str(run / "output")
                environment["GITHUB_RUN_ID"] = str(901 + attempt)
                result = subprocess.run(
                    ["bash", "-c", transport + create_script],
                    cwd=run,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn(
                    f"publish_evidence={'true' if attempt == 0 else 'false'}",
                    (run / "output").read_text(),
                )
            body = json.loads(state.read_text())["pulls"][0]["body"]
            self.assertEqual(6, len(body.splitlines()))
            self.assertIn("<!-- lit-protected-promotion:v2 -->", body)
            self.assertNotIn("dispatch-", body)
            api_calls = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(1, sum("POST" in args for args in api_calls))
            self.assertTrue(all(args[0] in {"api", "pr"} for args in api_calls))
            valid_state = json.loads(state.read_text())
            for case in ("malformed-v2", "closed-head"):
                changed = json.loads(json.dumps(valid_state))
                if case == "malformed-v2":
                    changed["pulls"][0]["body"] += (
                        "\n<!-- lit-protected-promotion:v2 -->"
                    )
                else:
                    changed["pulls"][0]["state"] = "closed"
                state.write_text(json.dumps(changed))
                run = temp / case
                run.mkdir()
                environment["GITHUB_OUTPUT"] = str(run / "output")
                rejected = subprocess.run(
                    ["bash", "-c", transport + create_script],
                    cwd=run,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(
                    0, rejected.returncode, rejected.stdout + rejected.stderr
                )
            state.write_text(json.dumps(valid_state))
            api_calls = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(1, sum("POST" in args for args in api_calls))
            environment.update(
                {
                    "AUTHOR_LOGIN": "lightning-it-release-automation[bot]",
                    "AUTHOR_ID": "307565056",
                    "AUTHOR_TYPE": "Bot",
                    "SENDER_LOGIN": "lightning-it-release-automation[bot]",
                    "SENDER_ID": "307565056",
                    "SENDER_TYPE": "Bot",
                    "BASE_REF": "main",
                    "HEAD_REF": "develop",
                    "HEAD_REPOSITORY": "lightning-it/.github",
                    "BASE_SHA": base,
                    "HEAD_SHA": head,
                    "EVENT_BASE": base,
                    "EVENT_HEAD": head,
                    "EVENT_BODY": body,
                    "PREVIOUS_BODY": "",
                    "EVENT_ACTION": "opened",
                    "GITHUB_OUTPUT": str(temp / "route-output"),
                }
            )
            result = subprocess.run(
                ["bash", "-c", route_script + event_guard],
                cwd=temp,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "promotion_candidate=true", (temp / "route-output").read_text()
            )
            self.assertIn(
                "promotion_pending=false", (temp / "route-output").read_text()
            )
            for invalid in (
                body + "\nextra",
                body.replace(head, "f" * 40),
                body.replace(":901:1", ":901:2"),
            ):
                environment["EVENT_BODY"] = invalid
                rejected = subprocess.run(
                    ["bash", "-c", route_script],
                    cwd=temp,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(0, rejected.returncode)
            environment["EVENT_BODY"] = body
            environment["SENDER_ID"] = "1"
            rejected = subprocess.run(
                ["bash", "-c", route_script],
                cwd=temp,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, rejected.returncode)

    def test_dispatch_failure_is_tombstoned_and_closed_not_retried(self) -> None:
        workflow = self.workflow

        self.assertIn(
            "if: failure() && steps.release-app.outputs.token != ''", workflow
        )
        self.assertIn("lit-promotion-dispatch-failed:", workflow)
        self.assertIn('-f "state=closed"', workflow)
        self.assertIn("a fresh PR bound to a new develop head is required", workflow)
        self.assertIn(
            "the same develop head remains consumed and cannot be retried", workflow
        )
        cleanup_block = workflow.split(
            "- name: Close unusable promotion after dispatch failure", 1
        )[1]
        self.assertIn(
            'select(startswith("<!-- lit-promotion-head:"))] == [$head_marker]',
            cleanup_block,
        )
        self.assertIn(
            'select(startswith("<!-- lit-promotion-run:"))] == [$run_marker]',
            cleanup_block,
        )
        self.assertIn(
            "($captured_number == 0 or .number == $captured_number)", cleanup_block
        )
        self.assertNotIn("and .head.sha == $head", cleanup_block)


if __name__ == "__main__":
    unittest.main()

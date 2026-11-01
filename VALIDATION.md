# Validation record

Recorded on 2026-11-01 (Asia/Baku). Do not interpret the implementation or this
record as certification of the judge VM or a production deployment.

## Executed

- Python 3.12 environment and PostgreSQL 17 migrations.
- Automated application/worker tests on PostgreSQL, including simultaneous
  submission limits and real `SKIP LOCKED` row-lock behavior.
- Restricted PostgreSQL worker/verifier grants, using temporary roles rolled back
  in the test database. Worker result updates succeed; source/timestamp/definition
  changes and privilege changes are denied.
- Correctness tests for scoring, out-of-order results and rejudging; access control,
  escaping, CSRF, login throttling, byte quotas, database receipt timestamps,
  immutable definitions, verification fingerprints and audited correction pauses.
- Lease expiry, exhausted retries, infrastructure errors, claim revocation, and
  rejection of result writes from stale workers. These tests simulate crashes at
  the database layer; they do not replace killing a real Isolate worker on Linux.
- Docker development image build and PostgreSQL test execution in that image.
- Django production `check --deploy --fail-level WARNING`, with DEBUG=False,
  HTTPS=True and an explicit allowed host: no issues.
- Runtime dependency scan using `pip-audit -r requirements.txt`: no known
  vulnerabilities reported at the time of scanning. This is not a guarantee of
  absence of vulnerabilities. Rescan immediately before deployment.
- Shell syntax check for the VM setup script and migration consistency check.

The final PostgreSQL run used `RUN_DATABASE_ROLE_TESTS=1 pytest -q`:
**62 passed, 16 skipped** on the host and in the Docker development image.
The test suite has two opt-in database-role tests requiring CREATEROLE. Isolate
integration tests require a dedicated Linux VM and are never replaced by fake
judging. Mocked unit test responses are test fixtures only.

## Not executed — release blockers

- All 16 real Isolate integration tests. macOS is not a supported Isolate host.
  These include C++/Python verdicts, compilation, CPU/memory/output limits,
  filesystem/environment isolation, network namespace isolation, process limits,
  and fresh test environments. Run `RUN_ISOLATE_TESTS=1 pytest -q -m isolate` on
  the dedicated provisioned VM. Every case must pass.
- The VM provisioning script on a clean Ubuntu 24.04 amd64 machine, including
  quota persistence, cgroup setup, runtime filesystem and post-reboot behavior.
- Real process/VM crash recovery, worker service restart and multiple independent
  worker processes under load. Run in addition to the database concurrency tests.
- Reference solutions in the example contest on the actual sandbox. The example
  command produces DRAFT, unverified problems; publication is deliberately blocked
  until `verify_contest` actually passes on Linux.
- Production Nginx/Gunicorn/TLS/VPN deployment, real administrator TOTP enrollment,
  PostgreSQL TLS/firewall configuration, production role provisioning,
  backup restoration, and cross-host clock synchronization on university hosts.
- A complete browser/device accessibility review and manual end-to-end contest.
- A rehearsal with multiple real participants and simultaneous submissions on
  the target hardware, including a correction/reverification/rejudge rehearsal.
- Independent security review of the deployed host and sandbox configuration.

## Operational limits

- Individual accounts only. Accounts are provisioned by administrators; no SSO or
  self-registration. No floating-point/interactive/custom checkers, teams,
  WebSockets, plagiarism system, or public API.
- Contest definitions freeze at publication. An emergency correction uses the
  audited `reopen_contest` procedure after draining judging; it pauses access,
  requires fresh verification and rejudges all existing submissions.
- Standings are computed from finalized submissions and refreshed every ten
  seconds. Pending verdicts can temporarily change the displayed standings.
- Process count is one at execution time; contestant-created threads are disabled.
  Compilation permits sixteen processes inside the same cgroup.
- Resource verdicts depend on accurate kernel/Isolate metadata. Allocation failure
  without a cgroup OOM event is a runtime error; kernel-reported OOM is MLE.
- Runtime versions and OS security patches must be maintained consistently across
  workers. Reverify and rehearse after compiler, Python, Isolate or kernel changes.
- The supplied grant script provisions separate worker, verifier, web and backup
  roles. Operators must set credentials, retain a separate schema owner for
  migrations, and apply the grants to their production database. Docker's database
  owner credentials are exclusively for local development.

Any incorrect verdict, failed isolation test, or incomplete deployment control
blocks a supervised real event, regardless of passing application unit tests.

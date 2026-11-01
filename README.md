# University Contest Judge

A small Django application with PostgreSQL, Django Admin, server-rendered pages,
and a separate IOI Isolate worker. Python 3.12+, Django 5.2 LTS, C++20 and Python 3.

**Status:** application and queue tests pass on PostgreSQL. Real Isolate execution,
VM provisioning, and a multi-user rehearsal remain release blockers. This is not
certified for a live contest. See [VALIDATION.md](VALIDATION.md).

## Start development on macOS or Linux

Docker Desktop/Engine with Compose is required. The web container never runs
contestant code. PostgreSQL is the only database, including in tests.

```sh
cp .env.example .env
# Replace SECRET_KEY and POSTGRES_PASSWORD with separate random values.
# For example, generate each with: openssl rand -hex 32
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

After code changes, rebuild with `docker compose up -d --build`.
The development image contains the source; no host filesystem mount is needed.

Open <http://localhost:8000> and <http://localhost:8000/admin/>. Create student
accounts through Users; no public registration is provided. Account creation and
permission grants require a superuser. Staff can receive individual contest,
problem, test, enrollment, submission-view, and rejudge permissions.

The Compose database is available only inside Docker and on loopback port 55439
(the optional development override file). Change that port if occupied. Persistent
data lives in the project-specific Docker volume; do not delete it accidentally.
The generated `.env` in the working checkout is ignored by Git.

## Set up a contest

1. Create a draft contest with start/end times. Django stores UTC and displays
   `UNIVERSITY_TIMEZONE`, initially `Asia/Baku`.
2. Create ordered problems and their tests through the admin. Enter full statements,
   input/output descriptions, constraints, limits, and official reference code.
3. Each problem needs one sample and at least two hidden tests. Inputs/outputs are
   limited to 1 MiB each; total tests are limited to 64 MiB per contest.
4. Verify on the dedicated Linux judge VM with the **verifier** database role:

   ```sh
   python manage.py verify_contest contest-slug --actor administrator
   ```

5. Set the contest status to Published in Admin. Verification fingerprints all
   definitions; any edit before publication requires verification again.
6. Add students through Contest participants. Students see only published contests
   they are enrolled in. Statements open at the server-side start time; submissions
   close at the exclusive end time.

Published definitions are frozen. For an emergency correction, first stop incoming
submissions operationally and drain all queued/running jobs. From a trusted console:

```sh
python manage.py reopen_contest contest-slug --actor administrator \
  --reason 'Brief non-sensitive explanation of the correction'
```

This requires contest-change and rejudge permissions, records the actor/reason,
returns the contest to Draft, invalidates verification, and queues every previous
submission for rejudging. Workers skip Draft contests, so definitions can be edited
without racing execution. Correct through Admin, verify on Linux again, then
publish. Rejudging resumes automatically. Original submission times are retained.
Do not bypass this procedure with SQL or ad-hoc Django shell edits.

For example data (two problems, C++ and Python reference solutions):

```sh
python manage.py seed_example --actor administrator --starts-in-minutes 120
```

This creates **draft**, unverified data with no default accounts or passwords.
Run `verify_contest example-practice --actor administrator` on Linux, then publish
and enroll accounts. The example must not be called verified until that succeeds.

## Judging on a dedicated Linux VM

Use a new Ubuntu 24.04 amd64 VM with systemd, Linux 5.19+ and cgroup v2. Give it dedicated
CPU/memory; synchronize its clock with the database host. Never install Isolate on
the public web machine or expose the VM to contestants. Do not replace Isolate
with plain subprocesses, Docker-only execution, or privileged containers.

Review and run [deployment/setup-judge.sh](deployment/setup-judge.sh) as root on
that fresh VM. It installs Isolate **v2.7**, an Ubuntu runtime containing GCC and
Python, a quota-enabled sandbox filesystem, and the Isolate cgroup keeper. It
reserves UIDs/GIDs 60000–60099 and creates the unprivileged `contest-judge` account.
It refuses to overwrite an existing runtime or disk image. Runtime directories
are root-owned and mounted read-only inside the sandbox. Only `/box` (also `/tmp`)
is writable. Only the current test input is copied into a new sandbox.

Disable swap persistently, disable host core-dump collection, and reserve those
UID/GID ranges from other accounts. Review `isolate-check-environment` output. Every worker startup also compiles and
runs trusted C++/Python self-tests inside Isolate before claiming contestant work.
Mounts, quotas, cgroups and kernel support must work before proceeding. The setup
script has not been exercised on a clean VM in this workspace.

Install a checkout at `/opt/contest`, owned by root, with a Python 3.12 virtualenv:

```sh
python3.12 -m venv /opt/contest/.venv
/opt/contest/.venv/bin/pip install -r /opt/contest/requirements.txt
```

After web migrations, apply [deployment/database-grants.sql](deployment/database-grants.sql)
as the database owner. Replace the database name `contest` if necessary. Set the
role passwords interactively using `psql` and `\password contest_worker` /
`\password contest_verifier`. The worker can read definitions and submission code,
and update queue/results, but cannot modify users, definitions, sources, or
submission timestamps. The separate verifier can only certify definitions and
append audit records. Never use a database superuser for either role.

Create `/etc/university-judge.env` (root-owned, mode 0600) using `.env.example` as
a guide. Set `DEBUG=False`, `JUDGE_ENABLED=True`, private database host,
`POSTGRES_USER=contest_worker`, its password, `POSTGRES_SSLMODE=verify-full`, and
`POSTGRES_SSLROOTCERT` to your database CA. Supply a distinct random `SECRET_KEY`.
The application secret from the web host is unnecessary. The worker serves no HTTP.
Use `JUDGE_BOX_ID=0`; assign a different box ID to each additional worker process.
A persistent file lock prevents two processes sharing the same box directory.

Allow VM outbound database traffic only to the private PostgreSQL address/port,
plus essential administration/time services; deny public network access. Do not
put database credentials, application code, or secrets in `/srv/judge-root`.

Load the environment with your service manager or a trusted shell, then run:

```sh
python manage.py runjudge --once  # claims at most one job
python manage.py runjudge         # poll continuously
```

Install [deployment/judge.service](deployment/judge.service) in
`/etc/systemd/system/`, then `systemctl enable --now judge`. Use
`systemctl restart judge` and `journalctl -u judge` for administration.
Jobs have renewable 90-second leases. Expired claims can be recovered; every
result write checks the current token and lease. Infrastructure failures get at
most three attempts, then SYSTEM_ERROR. Authorized staff may use the audited
Rejudge admin action; it revokes the old claim immediately.

Reference verification uses the same sandbox adapter and limits as contestants.
For `verify_contest`, load the separate verifier credentials into the trusted
operator environment; the running worker must keep its restricted credentials.
An actor argument records an authorized staff identity; operating this command
requires trusted console/database access, not a public web request.

## Tests and verification

```sh
docker compose exec web pytest -q
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web pip-audit -r requirements.txt
```

Tests create a separate PostgreSQL `test_contest` database. Use isolated test
credentials with CREATEDB, never the restricted production worker role. Never
point integration tests at a production database. SQLite is not supported.
Optional database-grant tests require a disposable cluster with CREATEROLE:
`RUN_DATABASE_ROLE_TESTS=1 pytest -q`. Their temporary roles are rolled back.

On the dedicated judge VM, install `requirements-dev.txt` into its virtualenv,
load a disposable PostgreSQL test database environment and the judge settings,
then run:

```sh
RUN_ISOLATE_TESTS=1 pytest -q -m isolate
```

This executes real C++/Python, wrong answers, loops, memory/output exhaustion,
abnormal termination, network/file/environment probes, process limits, and
fresh-file tests. Without the opt-in environment variable, these tests are
explicitly skipped. Unit tests that mock sandbox responses do not prove isolation.
Run the complete PostgreSQL suite there too, and repeat it after OS/compiler/
Isolate updates. A failed isolation test or wrong verdict blocks release.

CPU defaults are 2 seconds for C++, 6 seconds for Python per test, with 256 MiB
memory. Problems may use 100–10,000 ms C++ CPU and 16–512 MiB memory. Python gets
`JUDGE_PYTHON_TIME_MULTIPLIER` (default 3) times the problem limit. Compilation
gets 20 CPU seconds, 512 MiB, 16 processes and bounded files. Execution allows one
process/thread, 64 open files, 1 MiB each for stdout/stderr, and a 64 MiB / 256-inode
disk quota. Defaults live together in `config/settings.py`.

## Production web deployment

Use a separate web host, Gunicorn and Nginx. Install runtime requirements under
Python 3.12+, create a `contest-web` system account, and place the root-owned
checkout at `/opt/contest`. Use `contest_web` from the supplied grant script for the web runtime and
`contest_backup` for backups; set their passwords with `psql` interactively.
Use a separate owner/migration account for schema changes. Reapply the GRANT
statements after upgrades add tables. The Compose PostgreSQL owner is for local
development only.

Configure `/etc/university-contest.env` as root, mode 0600:

- `DEBUG=False`, `HTTPS=True`, a long random `SECRET_KEY`.
- Exact `ALLOWED_HOSTS`, e.g. `contest.example.edu`; never `*`.
- Private database connection variables with `POSTGRES_USER=contest_web`;
  production TLS with `verify-full` and CA.
- `JUDGE_ENABLED=False` on the web host.
- `TRUST_HTTPS_PROXY=True` only behind the supplied loopback-only Gunicorn/Nginx
  configuration, where Nginx overwrites the forwarding header.

Load that environment for deployment commands:

```sh
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py enroll_admin_mfa administrator
python manage.py check --deploy --fail-level WARNING
```

The enrollment command prints a TOTP provisioning URI to a trusted interactive
console and confirms a token; do not log/capture the URI. Production admin access
requires a verified django-otp device, including for superusers. Device/account
permission changes require a superuser. TOTP seeds must be protected with database
and backup access controls. Students use ordinary Django password authentication.

Install [deployment/web.service](deployment/web.service) and adapt
[deployment/nginx.conf](deployment/nginx.conf) for your domain, TLS certificates,
and trusted campus/VPN subnet. Run `nginx -t` before reloading. Restrict database
connections in the firewall and `pg_hba.conf` to these two hosts, using SCRAM and
TLS. Enable encrypted backups and restore tests. Axes applies account-based login
limits across workers; add Nginx per-IP limits if public login is required.

## Backup and restore

Back up using a restricted backup role and a protected PostgreSQL service file
or `.pgpass` (mode 0600). Never put a password in the command line or Git.

```sh
pg_dump --format=custom --file=contest.backup --dbname=contest
pg_restore --list contest.backup
# Restore into a new, empty database, not on top of a running contest:
createdb contest_restore
pg_restore --exit-on-error --no-owner --dbname=contest_restore contest.backup
```

Encrypt and move backups off-host. Test restoration with application migrations
and known results. During a real recovery, stop the web and worker, restore data,
reapply/verify role grants, run checks, then restart services. Stale leases recover
after expiry. Keep the original backup and audit records.

## Before a real event

Complete every item in [VALIDATION.md](VALIDATION.md), test backup restoration,
verify problems on the actual judge, and rehearse with simultaneous submissions
from multiple participants. Review resource measurements on the target hardware.
No sandbox guarantees protection against every kernel vulnerability; maintain the
VM and Isolate and keep the web host separate.

Implementation references: [Django 5.2.18 security release](https://www.djangoproject.com/weblog/2026/oct/06/security-releases/),
[IOI Isolate manual](https://www.ucw.cz/isolate/isolate.1.html),
and [django-otp documentation](https://django-otp-official.readthedocs.io/).

-- Run as the database owner after migrations, inside the contest database.
-- Set passwords interactively with psql \password; never commit passwords.
CREATE ROLE contest_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE contest TO contest_worker;
GRANT USAGE ON SCHEMA public TO contest_worker;
GRANT SELECT ON contests_contest, contests_problem, contests_testcase,
    contests_submission TO contest_worker;
GRANT UPDATE (
    status, verdict, execution_time_ms, memory_used_kb, compiler_message,
    diagnostics, started_at, finished_at, worker_claim_token,
    worker_lease_until, judge_attempts
) ON contests_submission TO contest_worker;

-- Use this distinct role for the trusted verify_contest operator command.
CREATE ROLE contest_verifier LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE contest TO contest_verifier;
GRANT USAGE ON SCHEMA public TO contest_verifier;
GRANT SELECT ON contests_contest, contests_problem, contests_testcase,
    auth_user, auth_permission, auth_group, auth_group_permissions,
    auth_user_groups, auth_user_user_permissions, django_content_type
    TO contest_verifier;
GRANT UPDATE (verified_digest) ON contests_contest TO contest_verifier;
GRANT INSERT ON contests_auditlog TO contest_verifier;
GRANT USAGE ON SEQUENCE contests_auditlog_id_seq TO contest_verifier;
GRANT SELECT (id) ON contests_auditlog TO contest_verifier;

-- The web runtime owns no schema and cannot create roles or databases.
CREATE ROLE contest_web LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE contest TO contest_web;
GRANT USAGE ON SCHEMA public TO contest_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO contest_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO contest_web;
REVOKE UPDATE, DELETE ON contests_auditlog FROM contest_web;
-- User deletion may anonymize the actor without changing the audit record.
GRANT UPDATE (actor_id) ON contests_auditlog TO contest_web;

CREATE ROLE contest_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE contest TO contest_backup;
GRANT USAGE ON SCHEMA public TO contest_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO contest_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO contest_backup;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

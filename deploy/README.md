# Small-pilot deployment and recovery

This release covers free job seeking, verified employers, internships and entry-level recruitment. Freelance contracting, payments and public talent searches are excluded. These instructions prepare a host; they do not provision an account or claim that production is deployed.

The selected initial host is PythonAnywhere. Follow [the provider-specific setup](PYTHONANYWHERE.md), then use this document for production safeguards and recovery. No hosting purchase or account provisioning has been performed.

## Host requirements

Use Python 3.12 and a host that can run Django WSGI, retain a private directory across releases/restarts, serve HTTPS, and run the durable mail/file-cleanup worker continuously or on a reliable schedule. SQLite is supported here for a small pilot on one host with a local persistent filesystem. Do not put this SQLite configuration on an ephemeral free web-service filesystem or a network filesystem. Moving to a stateless/multiple-host platform requires a separately implemented database/object-storage setup.

`production.env.example` lists configuration names, not working credentials. Configure them through the host's protected environment mechanism. Do not load `.devcontainer/environment.sh`: that launcher intentionally forces development mode. PythonAnywhere can use its native WSGI setup rather than Gunicorn, but its current network, storage and background-task allowances must be checked before choosing a plan. SMTP and AI connectivity must be tested on the actual host.

## Prepare a host

1. Create a new persistent private directory owned by the application user, mode `0700`. Set its absolute path as `DJANGO_DATA_DIR`. Keep public static files in a separate directory (`DJANGO_STATIC_ROOT`). Production refuses overlapping paths. The database lives at `DJANGO_DATA_DIR/db.sqlite3`; CVs live under `.private_uploads` within it.
2. Set `DJANGO_DEBUG=0`, a new independent random `DJANGO_SECRET_KEY` of at least 50 characters, the exact HTTPS `PUBLIC_SITE_URL`, and explicit `DJANGO_ALLOWED_HOSTS`. Keep the key stable across deploys. Do not use the Codespaces key. Only enable `DJANGO_TRUST_PROXY_SSL_HEADER=1` after confirming the host strips/replaces the incoming forwarding header.
3. Configure a verified email sender and SMTP credentials. Leave `OPENAI_API_KEY` empty until its account, billing and user-consent flow have been checked. A missing AI key leaves editing/PDF downloads available.
4. Install dependencies and prepare the release with the production environment loaded:

```bash
python -m pip install -r requirements.txt
python manage.py compile_translations
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
```

WhiteNoise serves only collected public static assets. Never add `.private_uploads`, the data directory or backups to a host's static/public mappings. The existing authenticated CV endpoint remains responsible for downloads.

Django's deployment check currently warns about HSTS subdomain inclusion and preload. They are deliberately not enabled automatically: review the chosen domain and all affected services before adopting those policies. HSTS for the exact site starts at one hour. Production smoke tests check HTTPS forwarding, secure cookies, HSTS, hashed static assets, and denial of public private-media paths.

Start a supported WSGI server, or use the host's native WSGI loader:

```bash
gunicorn --config deploy/gunicorn.conf.py config.wsgi:application
```

The optional Gunicorn configuration uses one process/four threads for this small SQLite pilot and a timeout allowing a bounded AI request. It disables access logging to avoid logging account-recovery URLs. Use the host's service supervisor for restarts. Run the worker with the same private data directory, stable secret and production environment:

```bash
python manage.py deliver_emails --watch --interval 5
```

Set up application error monitoring through the host; do not publish raw request bodies, CV contents, provider responses or credentials. Configure retention and access to logs with the NGO.

## Real-data cutover

Start with a fresh production database unless there is an explicit decision to migrate real pilot accounts. Do not seed fictional organizations in production. Demo content is excluded from public production queries and impact statistics. Do not copy a development database or local verification inbox into production by default. A public launch still needs a verified email journey, an NGO-owned administrator account, privacy/contact/retention decisions, and a recovery owner.

Existing data is never moved automatically when `DJANGO_DATA_DIR` changes. To migrate approved pilot data, first stop all writers and use the backup/restore procedure below. Keep the previous directory unchanged until recovery verification is complete. Private data does not belong in GitHub.

## Offline backup

These commands support a file-backed SQLite database and local private CV storage. They do not support PostgreSQL or object stores. Archives are capped at two GiB of source data and 99,999 source files for this pilot.

Schedule a maintenance window: stop the web process, mail worker, cleanup commands and every other writer before running this command. `--offline` is an operator acknowledgment; it does not stop services for you. The database uses SQLite's snapshot API, but keeping database references and uploaded files mutually consistent still requires stopping all writers.

```bash
python manage.py backup_pilot --output /private/backup-directory/pilot-backup.tar.gz --offline
```

Choose a private backup directory outside the public static and upload trees. An existing archive is never overwritten. New archives have mode `0600`; automatically created parent directories use mode `0700`. The archive contains a database snapshot, private uploads and a manifest of file sizes/SHA-256 checksums. It excludes code, environment secrets and the local email inbox. It still contains personal data and password hashes: it is **not encrypted**. Transfer it using an encrypted channel into encrypted, access-controlled storage outside the host. Never attach it to an issue or commit it. Define the backup frequency, retention period, responsible person and deletion procedure with the NGO.

## Restore into a new directory

Restore drills must use an isolated environment with external mail and AI disabled, so restored queued jobs cannot contact real applicants. Restored data includes outbox records and rate-limit state. Keep the worker stopped until queued delivery state has been reviewed; a restored queue may include messages already delivered after the snapshot. Recovery links signed with a different deployment secret will not remain valid.

```bash
python manage.py restore_pilot --archive /private/backup-directory/pilot-backup.tar.gz --destination /private/new-recovery-directory
```

The destination must not exist. Restoration rejects traversal paths, symlinks, duplicate/unexpected archive members, size mismatches, checksum failures, and invalid SQLite integrity. It cleans up only the new destination on validation failure, never the current data directory. A manifest detects corruption; it is not a signature proving the sender's identity. Only restore archives from a trusted source.

After verification, set `DJANGO_DATA_DIR` to the restored directory, run migrations/checks with production settings, and verify representative login, applications, CV downloads, resume drafts and moderation histories. Check file permissions and NGO staff authorization. Only then restart web/worker services and reopen access. Leave the old directory intact until the recovery owner signs off.

## Validation performed in development

Run `python scripts/production_smoke.py` to repeat the isolated production smoke test. It also runs in GitHub Actions.

The automated suite tests production path/host/secret guards and backup/restore round trips using synthetic records and files. An isolated production smoke run migrates a fresh database, collects static files, backs up and restores synthetic Django accounts/applications/CVs/resume drafts, verifies authenticated restored document downloads, starts Gunicorn, verifies secure response/cookie behavior and confirms private files are not publicly mapped. No existing pilot data is restored or overwritten during these checks. Actual host provisioning, email delivery, AI credentials, monitoring service setup and NGO acceptance remain deployment-specific work.

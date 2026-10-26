# Together for Better engineering

Work autonomously within the user's requested scope. Make routine implementation decisions, finish the work, and report concrete outcomes and limitations. Avoid unsolicited recommendation lists or ending with a menu of next steps.

Use the existing checkout. Each cloud task is isolated; do not create a Git worktree unless explicitly requested. Preserve user data, existing files, and credentials. Never reset the local database as a setup shortcut.

## Application

- Django 5.2 with Python 3.12; no frontend build is required.
- Install pinned dependencies from `requirements.txt` into `.venv`.
- Compile gettext catalogs with `.venv/bin/python manage.py compile_translations`, then migrate and run system checks before startup.
- Run `.venv/bin/python manage.py test` for changes to workflows, models, authorization, or translations. Test counts must represent executed tests.
- Create migrations for model changes; verify `makemigrations --check --dry-run`.
- Preserve English and Amharic localization. Translate complete sentences with named placeholders and proper plural forms. Keep choice values, database identifiers, employer content, and user names unchanged.
- Dates are Gregorian, deadlines use Africa/Addis_Ababa, and the UI must make the calendar explicit. Do not relabel Gregorian dates as Ethiopian-calendar dates.

## Privacy and trust

- CVs are private, served only by the permission-checked download view. Never add a public media route or expose storage URLs. Keep attachment/no-store response headers.
- `.private_uploads`, `.private_mail`, local databases, and credentials must remain out of Git. Never print password-reset messages or token-bearing URLs.
- Development email uses a private local inbox. Do not claim real delivery without verifying a configured provider.
- Employers cannot self-verify or self-publish. Reports must not automatically hide listings. Moderation actions require permissions and an audit trail.
- Preserve shared request limits. Do not trust arbitrary forwarding headers; verify the deployment's handling of direct client addresses.
- Label fictional demonstration data and exclude it from impact reporting. Distinguish employer-reported placements from independently verified outcomes.
- New signup verification, in-app events, and application email deliveries must stay atomic and idempotent where specified. Run the durable account worker alongside the web server; never send notification mail inside application mutations.
- Keep self-service deletion restricted to job seekers, require current credentials and CSRF, and preserve durable private-file cleanup requests on storage failure. Never recreate a deleted user through password recovery.
- The client cannot render local PNG file links. Do not use filesystem screenshot links as a user-facing preview. Do not invent public or localhost preview URLs.
- Maintain mobile usability and low-bandwidth operation. Avoid unnecessary remote assets or client scripts.

Describe deployment and language-review status accurately. Local validation, saved cloud configuration, cloud publication, and public website deployment are separate outcomes.

# Initial hosting choice: PythonAnywhere

This is the selected path for the small Django pilot. It keeps one persistent private directory for SQLite/CVs and uses native WSGI hosting. It avoids a serverless database/storage migration before NGO acceptance. It does not change the existing Baruchermi.org website. Freelance contracting is excluded.

No PythonAnywhere account has been connected or provisioned from this workspace. Current plan features/pricing have not been independently verified here. Before purchasing anything, confirm Python 3.12 support, sufficient persistent private disk, outbound access to the chosen SMTP provider/OpenAI, and a reliable worker/scheduled-task option. A free plan must not be assumed to support those requirements. Existing Vercel payments do not cover this separate provider.

## New account setup

Use a PythonAnywhere account controlled by the project owner, with the NGO's eventual handover recorded. Keep passwords, recovery codes, API tokens, SMTP credentials and configuration files private; only the account username and actual Web-tab hostname are needed in conversation. Start on the provider's HTTPS hostname. A custom subdomain can be connected later after DNS/plan access is confirmed.

In a new Bash console, clone the repository without replacing an existing checkout:

```bash
cd ~
git clone https://github.com/duchesam/togetherforbetter.git
cd togetherforbetter
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py init_host_config --directory "$HOME/together-private" --hostname YOUR_ACTUAL_WEB_HOSTNAME
```

Replace `YOUR_ACTUAL_WEB_HOSTNAME` with the exact hostname shown in the host's Web tab, without `https://`, a slash or port. Do not assume the region's domain suffix. The initializer creates a mode-0700 private directory and mode-0600 `production.json` outside the checkout. It generates a new secret without printing it. Running it again refuses to replace the existing configuration/key. It does not migrate development accounts or sample data.

Edit `~/together-private/production.json` using the host's private file editor. Add the verified SMTP sender/credentials before inviting users. Configure OpenAI only when its account/billing is approved; otherwise manual resume editing/PDF export remain available. Review TLS/proxy behavior: the configuration starts with proxy-header trust disabled. Enable it only if the host's forwarding-header contract is verified. Native WSGI may already supply the correct HTTPS scheme without enabling header trust.

Run release commands with the private configuration explicitly loaded:

```bash
.venv/bin/python scripts/host_manage.py --config "$HOME/together-private/production.json" compile_translations
.venv/bin/python scripts/host_manage.py --config "$HOME/together-private/production.json" migrate --noinput
.venv/bin/python scripts/host_manage.py --config "$HOME/together-private/production.json" collectstatic --noinput
.venv/bin/python scripts/host_manage.py --config "$HOME/together-private/production.json" check --deploy
.venv/bin/python scripts/host_manage.py --config "$HOME/together-private/production.json" createsuperuser
```

Do not use the Codespaces setup/start scripts on the public host: they force development settings. Do not seed fictional demonstration accounts in production. Review the two HSTS scope/preload warnings described in the general deployment runbook rather than applying policies to unrelated domains automatically.

## Connect the Web app

Create a manually configured Django/Python 3.12 Web app. Set its virtualenv to `/home/YOUR_USERNAME/togetherforbetter/.venv`. Copy the content of `deploy/pythonanywhere_wsgi.py` into the Web tab's WSGI configuration file. Its defaults expect `~/togetherforbetter` and `~/together-private/production.json`; edit those paths if a different layout is intentionally used.

Reload the Web app. WhiteNoise handles collected public static files. Do not map `together-private`, `.private_uploads` or backup directories as static files, and do not publish the configuration JSON. Test the host's HTTPS URL, language switching, signup, actual verification/reset email delivery and authenticated CV/PDF downloads before inviting pilot participants.

## Connect the durable worker

Configure an always-on task, if supported by the chosen plan, using absolute paths:

```text
/home/YOUR_USERNAME/togetherforbetter/.venv/bin/python /home/YOUR_USERNAME/togetherforbetter/scripts/host_manage.py --config /home/YOUR_USERNAME/together-private/production.json deliver_emails --watch --interval 5
```

A reliable scheduled finite delivery command can be used instead if the chosen plan provides a suitable cadence; delivery will wait until the next run. Do not assume a browser console left open is a supervised worker. Both email delivery and private-file cleanup depend on this process. Verify delivery/retry behavior on the actual host.

## Updates and recovery

Before changes affecting data, schedule a maintenance window and follow [the tested backup/restore runbook](README.md). Stop the web app, worker and every writer; `--offline` does not stop services itself. Use the same `scripts/host_manage.py --config ...` prefix for backup, restore, migration and maintenance commands so all target the correct production data directory.

Update with `git pull --ff-only`, install pinned requirements, compile translations, migrate, collect static, run checks, reload the Web app and restart the supervised worker. Never overwrite `production.json` or rotate its key during routine deploys.

Connecting `jobs.baruchermi.org` is a later, separate change. It requires the appropriate host plan and DNS access; it does not require moving the main website. Update the canonical HTTPS URL, allowed hosts and trusted origins together and verify language/form POSTs after that change. No DNS record has been changed by these preparation steps.

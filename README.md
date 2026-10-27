# Together for Better

A working pilot for an Ethiopia-focused NGO connecting job seekers with verified organizations. Free for job seekers. Built with Django 5.2, server-rendered HTML, responsive CSS, and SQLite for local development. No frontend build or external API keys are required.


[![Pilot checks](https://github.com/duchesam/togetherforbetter/actions/workflows/tests.yml/badge.svg)](https://github.com/duchesam/togetherforbetter/actions/workflows/tests.yml)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/duchesam/togetherforbetter)

## Open the working pilot in your browser

Open this repository in GitHub Codespaces using the button above. Setup installs dependencies, prepares the database, adds the clearly labeled fictional listings, runs the test suite, and starts the web app and local email worker. In Codespaces, open the **Ports** panel and click the browser icon for **Together for Better pilot (8000)**. GitHub supplies the actual authenticated preview address; no custom domain or hosting account is required. Keep the forwarded port private. Codespaces uses your GitHub account's compute quota and is a development environment, not a production deployment.

To inspect account flows, create a job seeker or employer account. Verification messages are captured in the private `.private_mail` folder in the Codespaces file explorer. Open the latest message locally and follow its verification link while signed in to that account. Do not share these messages or their links. Create an administration account with `.venv/bin/python manage.py createsuperuser` to test employer verification and listing publication. There are no shared default credentials, and no external email is sent by this development setup.


### Change the interface language

Choose **አማርኛ** or **English** in the header to apply the language immediately. The **Apply language** button also works when JavaScript is unavailable. Switching preserves the current page and search filters, sets the language cookie, and saves the preference for signed-in profiles. Employer-written vacancy content stays in its original language.

### Refresh an existing Codespace

New changes are published to `main`. In the repository terminal, run:

```bash
git pull --ff-only && bash .devcontainer/restart.sh
```

If Codespaces shows **Origin checking failed — http://localhost:8000**, update and restart with the command above, then reopen the pilot homepage from port 8000 rather than resubmitting the error page. The development launcher trusts the exact Codespaces preview origin and the exact localhost/127.0.0.1 upstream port used by forwarding. CSRF tokens are still required; other origins and ports remain rejected. This allowance is scoped to the Codespaces development launcher.

The restart command installs pinned dependencies, compiles translations, applies migrations, runs system checks, and restarts only the pilot's managed web and worker processes. It preserves the database, private uploads, and workspace session key. Refresh the existing port-8000 browser tab afterward.

## Pilot screenshots

These are actual captures of the application. All organizations, salaries, and vacancies shown are fictional examples.

**Employer applicant workspace (fictional demonstration)**

![Employer applicant workspace](docs/screenshots/employer-applicants.png)

<details><summary>Amharic applicant workspace on mobile</summary>

![Amharic employer applicant workspace](docs/screenshots/employer-applicants-amharic.png)

</details>

**Private application tracker (fictional demonstration)**

![Private application tracker](docs/screenshots/application-tracker.png)

<details><summary>Amharic application tracker on mobile</summary>

![Amharic application tracker](docs/screenshots/application-tracker-amharic.png)

</details>

**Application withdrawal (fictional demonstration)**

![Application withdrawal confirmation](docs/screenshots/withdrawal-confirmation.png)

<details><summary>Amharic withdrawn application on mobile</summary>

![Amharic withdrawn application](docs/screenshots/withdrawal-amharic.png)

</details>

**Employer review decisions (fictional demonstration)**

![Employer review decisions](docs/screenshots/employer-review-decisions.png)

<details><summary>Amharic employer review decisions on mobile</summary>

![Amharic employer review decisions](docs/screenshots/employer-review-amharic.png)

</details>

**Staff review workspace (fictional demonstration)**

![Staff employer review](docs/screenshots/staff-review.png)

<details><summary>Amharic staff review on mobile</summary>

![Amharic staff review](docs/screenshots/staff-review-amharic.png)

</details>

**Private saved opportunities (fictional demonstration)**

![Private saved opportunities](docs/screenshots/saved-opportunities.png)

**Employer listing management (fictional demonstration)**

![Employer listing management](docs/screenshots/listing-management.png)

**Interview invitation and response (fictional demonstration)**

![Interview invitation and response](docs/screenshots/interview.png)

**Applicant-confirmed acceptance (fictional demonstration)**

![Applicant-confirmed placement response](docs/screenshots/placement-confirmation.png)

<details><summary>Amharic placement response on mobile</summary>

![Amharic placement response](docs/screenshots/placement-amharic.png)

</details>

**English homepage**

![English homepage](docs/screenshots/english-home.png)

**Amharic homepage**

![Amharic homepage](docs/screenshots/amharic-home.png)

**Opportunity search**

![Opportunity search and filters](docs/screenshots/opportunities.png)

**Opportunity details**

![Opportunity details and application entry](docs/screenshots/job-detail.png)

<details><summary>Amharic mobile layout</summary>

![Amharic mobile layout](docs/screenshots/amharic-mobile.png)

</details>

## Run locally

Python 3.12 or newer is recommended. Use the existing checkout; no separate Git worktree is needed.

```bash
cd "$(git rev-parse --show-toplevel)"
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py compile_translations
.venv/bin/python manage.py migrate
# Optional: fictional organizations and listings for evaluation only
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver 0.0.0.0:8000 --noreload
```

The development server uses port 8000. The site starts with a useful empty state if demo data is omitted. Demo seeding is repeatable, preserves existing records and edits, and is refused when `DJANGO_DEBUG=0`. Demo organization accounts have unusable passwords. There are no shared default credentials.

Run the account worker in a second persistent session so queued verification emails and application updates are processed (local delivery uses the private test inbox):

```bash
.venv/bin/python manage.py deliver_emails --watch --interval 5
```

Create a real administration account separately:

```bash
.venv/bin/python manage.py createsuperuser
```

## Workflows

- **Anyone:** browse, search, filter by location, opportunity type, and area of interest, and read public listing details.
- **Job seekers:** register, create a private profile, upload an optional PDF CV, apply once to each open listing, and track progress in the dashboard. Applications share the candidate's current profile, CV, and account email with the hiring organization. CVs can be replaced or removed from the profile. Profiles are not publicly searchable.
- **Employers:** register an organization, complete its details, submit opportunities for review, read applications to their own listings, and update application status through to an employer-reported placement. Employers cannot self-verify or self-publish. Changes to organization details revoke verification until administrators review them again.
- **NGO administrators:** verify organizations and publish reviewed opportunities at `/admin/`. View community totals and recent employer-reported placements at `/impact/`. Demo organizations and their applications are excluded from impact numbers. Individual placements and unique people placed are counted separately.

### Review an organization and publish a listing

1. Sign in at `/admin/` with your administration account.
2. Open **Employers**, independently check the organization's identity, and enable **Verified** only after that check.
3. Open **Opportunities**, review the description, requirements, compensation, and deadline, then enable **Published**.
4. A listing is public only while published, associated with a verified organization, and not past its deadline. Deadlines use the Africa/Addis_Ababa timezone and Gregorian calendar.
5. In the employer dashboard, review an application and change its status. “Hired (employer reported)” records the organization’s report. The applicant confirms acceptance separately; neither is independent verification of employment.

### Try the pilot

Sample records are fictional and visibly labeled as a demonstration. Create a job seeker account through **Get started**, complete your profile, and apply to a sample opportunity to see application tracking. For the full employer flow, create a separate employer account and use an administrator account to approve that organization and its submitted listing. Demo organizations are excluded from public listings when debug mode is off.

## Validation

```bash
.venv/bin/python manage.py compile_translations
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
```

The tests cover registration, listing visibility, searches, application submission and duplicate prevention, private applicant data, cross-employer access, status changes, posting moderation, profile permissions, CSRF protection, demo seeding, impact reporting, PDF validation and private downloads, file replacement/deletion, and password recovery with expiring single-use tokens.

## Configuration

| Variable | Local default | Purpose |
| --- | --- | --- |
| `DJANGO_DEBUG` | `1` | Set `0` outside local development. Demo listings are hidden in production. |
| `DJANGO_SECRET_KEY` | Development-only value | Required independent secret when debug is off. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1],testserver` | Comma-separated hostnames, without schemes. Set the actual hostname for remote hosting. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Empty | Comma-separated HTTPS origins if needed for the deployment proxy. |
| `PUBLIC_SITE_URL` | `http://127.0.0.1:8000` locally | Canonical origin used in verification/notification emails. Required HTTPS origin in production, without a path or credentials. |

Configure variables in the process environment; this application does not automatically load `.env` files. Do not commit credentials, the local database, or personal applicant data. SQLite, `.venv`, `.private_uploads`, and `.private_mail` are ignored by Git. CV files and local recovery messages must not be exposed by a web server or committed to source control.

## Pilot boundaries and next steps

This is a functional English/Amharic prototype, not a publicly deployed service. It has no freelance contracts or payment processing. It uses profiles with optional private PDF CV uploads. Password recovery is implemented, with a private file inbox for local development and configurable SMTP for real delivery. It supports email verification, in-app application notifications, queued application emails, and password-confirmed self-service deletion for job seekers. External email delivery is not configured in this local instance. Administrators can remove accounts through Django admin; application records are deleted with their applicant. Profiles and CVs shown on existing applications reflect later updates; removing a CV removes its availability to all prior hiring employers. CV files are also removed when their profile/account is deleted, after the database transaction commits.

Before accepting real applicants, appoint moderators and a privacy contact; agree on employer verification, placement confirmation, abuse reporting, data retention, and deletion procedures. Amharic copy requires independent native-speaker editorial review before launch. Deploy uploaded-document malware scanning and operational monitoring. Configure and verify production email delivery and account recovery. For deployment, use a production WSGI server, HTTPS, a managed PostgreSQL database via an appropriate Django configuration, backups, a static-file serving configuration, and securely managed secrets. The bundled development server and local SQLite database are for evaluation. No public deployment is performed by this repository.

## Private CV uploads

Job seekers can upload, replace, and remove a PDF from **Edit my profile**. Files must be valid, unencrypted PDFs with at least one page, up to 5 MB. The server checks the extension, signature, parsed PDF structure, encryption status, and size; the browser-supplied content type is not trusted. These checks are not a malware scan.

CVs are stored under `.private_uploads/cvs/` with randomized names and restrictive filesystem permissions. There is intentionally no public media route. Downloads use `/profiles/<id>/cv/` and require an authenticated owner, an employer with an application from that candidate, or an administrator with the profile-view permission. Responses force download and disable caching. The application and profile pages do not expose storage URLs or original file names. Administrators download through the same protected endpoint.

Existing applications reference the candidate's **current** CV, not a historical snapshot. Updating or removing it affects all prior hiring employers. Superseded, removed, and deleted-account files are scheduled for removal in the same database transaction and removed after commit. Temporary storage failures leave durable retry records, processed by the account worker. Include private uploads in secure backups and plan a production scanning and storage policy before accepting real documents. Abrupt process termination during storage/database updates can leave orphaned files; production maintenance should reconcile unreferenced files with an appropriate retention window.

## Password recovery and email delivery

**Forgot your password?** on the login page uses Django's password recovery flow. The request screen gives the same confirmation for known and unknown email addresses. Reset links expire after one hour and stop working after a successful reset. Inactive accounts and demo accounts with unusable passwords do not get reset links. Users must have access to their registered email address to recover an account.

For local development, messages are written to the ignored `.private_mail/` directory instead of sent. The directory is created with owner-only access, and message files use `0600` permissions. A developer can inspect the latest file locally to follow its reset link. **Do not share, publish, or paste these messages into chat or logs:** they contain account recovery tokens. No public inbox or token-viewing endpoint exists.

With `DJANGO_DEBUG=0`, Django uses SMTP by default. Set the following in the deployment's secure environment configuration:

| Variable | Purpose |
| --- | --- |
| `EMAIL_BACKEND` | Optional override; production default is `django.core.mail.backends.smtp.EmailBackend`. |
| `EMAIL_HOST` | SMTP provider hostname. |
| `EMAIL_PORT` | SMTP port; default `587`. |
| `EMAIL_HOST_USER` | Provider username, if required. |
| `EMAIL_HOST_PASSWORD` | Provider credential; supply securely, never in source or chat. |
| `EMAIL_USE_TLS` | `1` by default, for STARTTLS. The included SMTP configuration targets STARTTLS providers. |
| `DEFAULT_FROM_EMAIL` | Verified sender identity. The local `example.invalid` default cannot deliver real mail. |

An email provider is not configured in the current local pilot, so no external delivery is claimed. Verify delivery, sender-domain authentication, and the public HTTPS hostname before launch. Password-reset requests are protected by shared database rate limits. Configure the deployment proxy to supply a trustworthy direct client address; the application deliberately ignores client-supplied forwarding headers. Do not log password-reset URLs or token-bearing messages in production access logs.

## English and Amharic

The language selector in the header uses a CSRF-protected POST and an HTTP-only language cookie. Switching languages keeps the current page and search filters. Browser language preferences are used when no language cookie is set. Django gettext catalogs live in `locale/am/LC_MESSAGES/`; compile with `manage.py compile_translations` after editing `.po` files. The compiler rejects incomplete/fuzzy translations and mismatched format placeholders without requiring GNU gettext binaries.

Navigation, public and account screens, application statuses, forms, authentication guidance, validation messages, reporting, and recovery email templates are localized. Django does not ship an Amharic catalog, so application-owned translations include common authentication and validation messages. The stock Django administration interface remains partly English. Employer-written titles, descriptions, categories, locations, and compensation are preserved in their original language; selecting Amharic does not automatically translate user content. Amharic copy is implemented but has not received independent linguistic review.

All deadlines use the **Gregorian calendar** and close at the end of the selected date in **Africa/Addis_Ababa (UTC+3)**. Amharic month labels refer to Gregorian months; the platform does not convert to Ethiopian calendar dates. Date inputs use `YYYY-MM-DD`. No external translation API, browser script, or remote font service is required. The header selector also updates the signed-in user’s preferred language for account emails.

## Request limits

The request limiter uses shared database counters and atomic conditional increments, so it operates across workers and survives process restarts. Stored keys are HMAC digests; raw client addresses, usernames, passwords, and emails are not stored in counters. Limits are fixed windows configured by `REQUEST_LIMITS` in settings. Requests over a limit receive HTTP `429`, an accurate `Retry-After` header, and a localized explanation.

| Endpoint | Maximum POST attempts per window |
| --- | --- |
| Login, including admin login | 10 per 10 minutes |
| Registration | 10 per hour |
| Password-reset request | 5 per 15 minutes |
| Application submission | 30 per hour |
| Opportunity posting | 10 per hour |
| Listing report | 10 per hour |
| Profile edit/upload | 30 per hour |

Anonymous endpoints use the direct client address. Authenticated endpoints use the user ID. Reads are not throttled, and client-supplied `X-Forwarded-For` headers cannot bypass counters. Behind a reverse proxy, ensure `REMOTE_ADDR` is set by trusted infrastructure; otherwise clients sharing the proxy address also share anonymous limits. This must be verified in the actual deployment. Fixed windows permit a burst around a boundary and are not a substitute for perimeter denial-of-service protection.

Run `manage.py prune_throttles` periodically in deployment to remove expired counters. The command does not delete active counters or application records.

## Reports and moderation

Authenticated users can report another organization's open listing for fees, misleading content, harassment/discrimination, or another concern. Each user can submit one report per opportunity. Users see their own report and its status in **My reports**; the reported employer and unrelated users cannot read it. Moderators with the relevant Django administration permissions can review reports, keep internal notes, and update status. Reports do not automatically remove a listing.

The admin action **Hide reported listings and begin review** requires both report-change and opportunity-change permissions. It hides listings, moves selected reports into review, records the reviewer/time, and writes admin audit entries. All updates are transactional. Resolving a report does not silently republish a listing; publication requires a separate reviewed opportunity change. The staff impact page links to the moderation queue and counts pending reports for non-demo listings.

Internal moderation notes never appear on reporting-user pages. Deleting a reporting account removes its database identity link but retains the report text and moderation record; moderators must apply the organization's retention and deletion policy to any personal information contained in that text. Reports are not an emergency service, and the pilot does not promise a response time.

## Account verification and notifications

New accounts queue an email verification message at registration. They must verify before submitting an application or posting an opportunity. Email verification is distinct from administrator verification of an employer organization. Profiles created before this rollout remain usable, are not silently marked verified, and can verify through **Account settings**. Administrators can require verification for legacy accounts by setting the profile's verification-required flag.

Verification links use a signed, timestamped payload bound to the account, exact normalized email address, and a rotating nonce. They expire after 24 hours. A resend invalidates older links and queued verification messages. Users must sign in and explicitly POST confirmation; merely opening the link cannot verify an account. Successful confirmation consumes the link. Changing the account email invalidates verified status and old links. Email changes are currently managed by administrators, not by a public profile form.

The **Notifications** page is private to each recipient. A new application notifies its hiring employer; a status change notifies its applicant. Posting an unchanged status or submitting the same application again does not duplicate the event. Administrators changing application status use the same notification flow. Marking a notification read requires an owner-authorized POST.

Account settings control application email preferences and the recipient's preferred language. In-app updates remain available when email is off. Application emails are queued only for a verified address that has not opted out; these conditions are rechecked before delivery. Emails contain a sign-in link and a brief event summary, never the CV, cover letter, or applicant contact details. No notification is a marketing email.

### Run the account worker

Run this alongside the web server in a separate persistent session:

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python manage.py deliver_emails --watch --interval 5
```

For a single pass:

```bash
.venv/bin/python manage.py deliver_emails
.venv/bin/python manage.py cleanup_private_files
```

Registration and application mutations commit their event and outbox records atomically without contacting the provider in the HTTP request. The worker uses atomic claims shared across processes and recovers claims older than ten minutes. Provider failures retry with exponential backoff, capped at five attempts, then remain visible as failed deliveries. The staff impact page shows queue/cleanup counts. Authorized administrators can requeue failed emails through the audited **Retry failed account emails** action after resolving the cause.

Delivery is **at least once**: a process crash after provider acceptance but before recording success can cause a duplicate email. No exactly-once guarantee is claimed. Recipient opt-out, address changes, inactive users, superseded verification requests, and account deletion cancel or remove pending deliveries. Verification tokens are generated at delivery time and bound to the original queued address/nonce, including during concurrent address changes.

Worker output contains only counts and sanitized exception class names. Do not print or share the private local inbox, verification URLs, reset URLs, credentials, or email bodies. Verification and application updates use the outbox; password-reset mail currently uses Django's synchronous recovery backend.

In development the worker writes to `.private_mail/`; it does not send external email. A developer evaluating a newly registered account must follow the captured verification message locally. The site does not expose a public inbox or a verification bypass. Real applicants require a working mail provider and the public origin configuration before rollout.

### Job seeker account deletion

Job seekers can delete their own account through **Account settings**, using their current password and an explicit irreversible-action checkbox. GET requests never delete accounts. Role and credentials are rechecked under a database lock before deletion. Staff and organization accounts require administrator-managed closure so that self-service removal cannot erase other people's hiring records or remove platform administrators.

Deletion removes the user, profile, applications, in-app notifications, and associated queued delivery records, including application notices belonging to the hiring employer. Private CV removal is scheduled transactionally and attempted after commit. Storage failures do not recreate the deleted account or lose the cleanup request. The worker retries file removal; terminal cleanup failures are visible to staff. After fixing storage, operators can requeue these tasks with `manage.py cleanup_private_files --retry-failed`. The cleanup process refuses to remove files still referenced by a live profile.

Safety report text and moderation records may remain without an account link. This is not a guarantee that free-text reports contain no personal data. Audit records, backups, delivered emails, and employer-downloaded copies follow separately defined retention policies. Password recovery uses a locked update to prevent a concurrent reset from recreating a deleted user.

## Interviews and placement outcomes

Employers can open an application and select **Invite to an interview**. Invitations support in-person, HTTPS video, and phone interviews. Dates use the Gregorian calendar and a 24-hour clock in Addis Ababa time (UTC+3). In-person invitations require a location; video invitations require a valid HTTPS URL without embedded credentials; phone invitations require contact instructions. Past dates and invalid details are rejected before changing an existing invitation.

There is one active invitation per application. A new invitation marks the old active invitation as replaced and preserves its history; repeated submission of the same request does not create duplicate invitations or notifications. Applicants can accept, decline, or request another time with a message. Employers can cancel their invitations. Old, replaced, cancelled, past, and closed-application invitations reject stale responses. A reported hire or rejection closes any active interview invitation. No interview is automatically marked as attended.

The application page shows the five most recent invitations and five recent events per invitation. Moderators with the relevant permissions can inspect the full history in the read-only administration screens. Meeting URLs and response messages remain private to the application parties and authorized reviewers. Notification emails contain a sign-in link and a generic update, not meeting credentials or interview instructions.

**Download calendar file** creates an authorized, non-cacheable `.ics` attachment. Event times are exported in UTC, text is escaped, and UTF-8 lines are folded to calendar-file limits. It is a snapshot, not a live calendar integration: later changes do not automatically update imported events. No Google/Microsoft calendar permissions are requested.

When an employer or authorized administrator reports a hire, a pending placement report is created. Existing hires are migrated to pending reports without fabricating applicant acceptance. Backfilled report times use the application’s existing last-update time, not an independently known hire date. Only the applicant can say **I accepted this role** or **I did not accept this role**. Repeating the same response is idempotent. Applicants may correct a response; previous responses remain in the audit history. Employers and administrators cannot submit an applicant's confirmation through the application or admin UI.

Changing the application away from hired supersedes the current report without erasing its responses. A later hire starts a new pending report; old confirmation never carries over. The impact dashboard separately counts employer-reported hires, applicant-confirmed acceptances, people confirming acceptance, awaiting responses, and unconfirmed/disputed outcomes. Demo activity is excluded. These are current records rather than permanent lifetime totals, and applicant confirmation is self-reported acceptance, not independent proof of employment or a verified first day at work.

Hiring actions are serialized on their application, keep audit and outbox records transactional, and have shared request limits. Applicant account deletion cascades through applications, interviews, responses, notifications, and pending delivery records, following the existing private-document cleanup policy.

## Listing management and private saved opportunities

Employers open **Manage listing** from their dashboard to edit or close their own opportunities. Actual content changes withdraw publication and return the listing to administrator review. Saving an unchanged form does not withdraw an approved listing. Employer edits cannot change ownership, publication approval, or verification. Closed listings stay closed while edited; reopening requires a current deadline and a separate review before publication.

Closing stops new applications immediately and preserves existing applications, interviews, and outcomes. Application submission rechecks public availability under the same listing lock before committing, so a closure during form validation cannot accept a new application. Listing edits, closures, and reopening record actor, action, changed field names, and timestamp. This audit records the changes made; it is not a historical snapshot of every listing description. Applications continue to reference the current listing.

Hidden revision checks protect against stale owner edits, close/reopen requests, and administrator review. Moderation withdrawal also advances the revision. The administration interface cannot publish a closed listing. New-account email verification is required for edits and reopening, while an owner can always close recruitment even if email verification is pending.

Job seekers can select **Save opportunity** on a public listing. **Saved opportunities** is available from their dashboard. Saving is private, idempotent, and does not submit an application or notify employers. Other users and employers cannot browse or remove another job seeker's saves. Saved lists are paginated and require owner-authorized POSTs for changes.

When a saved listing becomes closed, expired, unverified, or unpublished, it remains in the list as unavailable. Only the previously public title, organization name, and location captured at save time are displayed. Unpublished title/location changes are not leaked to prior savers. Once a reviewed listing is available again, its current public details are displayed. Permanently deleted listings and deleted user accounts remove their related saved records.


## Staff review workspace

Signed-in staff with `opportunities.change_employer` or `opportunities.change_opportunity` permission can open **Reviews** in the navigation. The workspace separates pending employer verification from listing review, with an **All records** view for reviewing existing approvals. Staff cannot review their own organization or listings.

Each decision requires a private reason and writes an admin audit entry. Review forms expire after one hour and reject changed organization or listing details. Listing decisions also advance the listing version to invalidate stale employer/admin forms. Withholding approval leaves the item in the pending queue; it does not permanently reject or delete it. Review reasons are internal and are not sent to employers.

Listing approval requires a verified employer, a current Gregorian deadline, and an employer-open listing. Withdrawing organization verification hides its public listings while retaining their publication flags and all applications. Re-verification can therefore restore otherwise eligible previously approved listings; listings awaiting their own approval remain hidden. This workspace records human decisions; it does not independently verify an organization's identity.


### Employer review decisions and corrections

The staff review form now separates its internal **Review reason** from a **Message to employer**. Withholding or withdrawing approval requires a message explaining the required changes. Approval can include an optional employer message. Both the decision receipt and the private audit entry commit with the approval change; failed writes roll back the entire decision. New decisions invalidate older review forms even when approval flags remain unchanged.

Employers open **Review decisions** from their dashboard, or from a listing's management page to filter its history. Receipts show the reviewed title, outcome, employer message and Ethiopia-time timestamp. Internal reasons and reviewer identities are not included. Unread counts decrease only after an owner-authorized, CSRF-protected **Mark as read** POST. Receipts are historical decisions, not claims that later edited content is approved. Editing the linked organization or listing submits the updated content through the existing review flow; employers cannot restore approval themselves.

Messages appear in the application; this feature sends no email. Existing admin audit reasons are not copied into employer receipts. Receipts are generated for new decisions made through the staff workspace; direct legacy Django admin changes remain in the admin audit log.


## Applicant-controlled withdrawal

An applicant can open **Withdraw application** on an active application, review the consequences, and confirm withdrawal. Only that applicant can perform the action. Hired and declined applications are excluded; a hired applicant uses the existing placement-response workflow to correct their acceptance outcome.

Withdrawal records the prior status and timestamp, closes the application permanently, cancels active interview invitations with their event history retained, and prevents new invitations, interview responses, or employer/admin status changes. Repeated submissions do not create duplicate withdrawal records or notifications. A stale confirmation is rejected if the current status differs from the reviewed status. The existing one-application-per-opportunity rule remains: applicants cannot reapply to that same opportunity after withdrawing.

Both parties receive in-app notices, with preference-controlled email queued through the existing durable worker. Older pending recruitment emails are cancelled before the withdrawal update is queued; a message already handed to a provider cannot be recalled. Calendar downloads after cancellation show `STATUS:CANCELLED`, while existing downloaded calendar entries require manual removal. No external email delivery is configured in the default pilot.

Withdrawal retains the application, interview events, and employer access to the applicant's current profile and CV; it is not account deletion or revocation of previously shared information. The confirmation page explains this before submission. The entire mutation, history, interview cancellations and notification outbox writes commit atomically. These records are removed with the applicant's account through the existing self-service deletion flow.


## Private application tracker

Job seekers open **My application tracker** from their dashboard. The page searches their own application titles and organization names, filters by every application status including withdrawal, and paginates twelve applications at a time. Summary counts always describe that job seeker's full application history; the matching count describes the current filters. Neither counts nor results include other applicants. Employers and accounts without a job-seeker profile cannot access this workspace.

**Only applications with upcoming interviews** shows future pending, accepted, or rescheduling-requested invitations on active applications, ordered by scheduled time. Past, cancelled, replaced and declined invitations and closed applications are excluded. Pending and rescheduling states retain their explicit labels; an invitation does not establish attendance. Dates use the Gregorian calendar and Addis Ababa time (UTC+3).

The tracker is read-only, requires authentication, and returns non-cacheable responses. Filters stay in pagination links. Application actions remain on the existing permission-checked detail page. No email, external services, or browser scripts are needed for this feature.


## Employer applicant workspace

Employers open **Manage applicants** from their dashboard or a listing's management page. The private workspace searches applicant profile names, usernames and listing titles, and filters by their own listing, application status, and future interview invitations. Listing links preselect that listing. Results show twelve applications per page and open the existing application detail workflow for profile/CV access, status changes and interview actions.

Both results and status totals are scoped to the signed-in employer's organization. Summary totals cover all applications to that organization; matching counts reflect the active filters. The listing selector includes the employer's closed and unpublished listings so recruitment history remains accessible. Foreign or invalid listing filters fail validation without displaying another employer's listing details. Employers cannot search the general job-seeker population through this workspace.

Upcoming interviews share the job-seeker tracker's date and state rules and sort by scheduled time. The list preserves pending, accepted and rescheduling labels without claiming attendance. Read-only GET requests never change applications; withdrawn applications remain protected by the existing detail and service checks. Neither this list nor its filters bypass private CV download authorization. English and Amharic are available, with no additional client scripts or external services.

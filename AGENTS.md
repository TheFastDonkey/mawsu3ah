# Agent Notes — Arabic Book Editions Encyclopedia

## Source of Truth

- `PRD.md` is the approved spec. Read it before adding features or changing data models.
- This project is pre-code. All technical decisions are in `PRD.md`.

## Product Constraints (Easy to Miss)

- **Physical books only**: no ebooks, audiobooks, or manuscripts.
- **Arabic-only RTL UI**, modern Islamic aesthetic, dark mode required.
- **Lightweight front end**: Django templates + HTMX + vanilla CSS. Avoid heavy JS frameworks.
- **Submissions do not go live immediately**: every edition enters an admin approval queue, except submissions by expert users, which are auto-approved.
- **Relation suggestions that create a new target edition**: when the suggestion is by an expert, both the new target edition and the relation are auto-approved (consistent with other expert submissions). For non-expert users, the new target edition is created with PENDING status and the relation suggestion remains pending until an admin approves the target edition.
- **Likes are pure popularity**: expert flair is visible but carries no extra vote weight.
- **Expert flair is assigned by admins only**, not earned by reputation.
- **Reviews are threaded**: top-level reviews can have nested replies.
- **Each book can belong to multiple categories**; the first is the primary category. Categories are admin-managed. Authenticated users may suggest adding an existing category to a book from the book page; new categories can be requested globally from `/categories/` and are added only after admin approval.

## Tech Stack

- Backend: Django 5.x (Python).
- Frontend: Django templates + HTMX + vanilla CSS.
- Database: PostgreSQL for production, SQLite acceptable for local dev.
- Search: PostgreSQL full-text search first; Elasticsearch only if needed.
- Auth: email/password + magic links; admin accounts must have 2FA.

## .env loading and required variables

- `mawsu3ah/settings/dev.py` loads `.env` from the project root with `dotenv.load_dotenv(BASE_DIR / ".env")`.
- The following variables must be set before Django starts:
  - `DJANGO_SECRET_KEY` — required in all environments.
  - `DB_PASSWORD` — required when not using SQLite (`USE_SQLITE=1`).
- `DEBUG` defaults to `False`; set `DJANGO_DEBUG=1` only for local development.

## Critical Security Defaults

- CSRF on all state-changing HTMX requests (header injected in `base.html` from a server-rendered `<meta name="csrftoken">` tag; `CSRF_COOKIE_HTTPONLY=True`).
- Rate limiting on auth, submission, like, review, reply, and category-suggestion endpoints via `django-ratelimit`, returning a 429 response for HTMX and full-page requests.
- Magic links are short-lived (10 minutes), single-use, and tied to a rotating nonce stored on the user model.
- No raw HTML from users; rely on Django template escaping plus a `Content-Security-Policy` with nonces for inline scripts.
- Admin 2FA mandatory via `OTPAdminSite`.
- Admin URL is configurable via `DJANGO_ADMIN_URL` and should not be `/admin/` in production; optional `ADMIN_ALLOWED_IPS` allow-list is available.
  - Only enable `ADMIN_TRUST_X_FORWARDED_FOR=true` when a trusted reverse proxy appends `X-Forwarded-For`; otherwise `ADMIN_ALLOWED_IPS` compares against `REMOTE_ADDR`.
- `TRUST_X_FORWARDED_PROTO` and `TRUSTED_PROXY_IPS` must both be configured to trust `X-Forwarded-Proto`. The middleware only honors the header when the direct connection comes from an IP in `TRUSTED_PROXY_IPS`; otherwise leave `TRUST_X_FORWARDED_PROTO` `false`.
- Public edition and review URLs use random UUID `public_id`s instead of sequential integer PKs to reduce enumeration and IDOR probing.
- Production requires a shared cache backend (e.g. Redis) for rate limiting to work across multiple workers.
- Session/CSRF cookies use `HttpOnly`/`SameSite=Lax` and are `Secure` in production.
- Production settings are validated by `python manage.py check --deploy` (custom checks in `mawsu3ah/checks.py`).
- HSTS is opt-in via `SECURE_HSTS_SECONDS` and should be staged from a short TTL to one year.

## Icons

- **Do not make icons from scratch** and do not use emoji as UI icons.
- Use the **Lucide** icons library, loaded via CDN in `templates/base.html`.
- Render icons with `<i data-lucide="icon-name"></i>` and initialize them by calling `lucide.createIcons()`.

## Before Writing Code

- Confirm the project root and whether a subdirectory (e.g., `backend/`) is preferred.
- Ask before switching languages or frameworks; Python/Django is the chosen stack.

# الموسوعة الكبرى لأفضل طبعات الكتب

<p align="center">
  <em>موسوعة مجتمعية مفتوحة لأفضل طبعات الكتب العربية الورقية</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Django-5.x-green?logo=django" alt="Django 5.x">
  <img src="https://img.shields.io/badge/Python-3.11-blue?logo=python" alt="Python 3.11">
  <img src="https://img.shields.io/badge/HTMX-1.x-orange?logo=htmx" alt="HTMX">
  <img src="https://img.shields.io/badge/License-MIT-lightgrey" alt="License">
</p>

## What is this?

An open, community-driven encyclopedia for **physical Arabic books**. Contributors submit editions, the community votes on the best ones, and admins review submissions before they go live.

- Search and compare book editions
- Expert-contributor verification system
- Threaded reviews and replies
- Arabic-only RTL interface with dark mode
- Lightweight — works on weak devices and slow networks

## Screenshots

*(Add screenshots here: homepage, edition detail, dark mode)*

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Django 5.x + Python 3.11 |
| **Frontend** | Django templates + HTMX + vanilla CSS |
| **Database** | PostgreSQL (production) / SQLite (local dev) |
| **Search** | PostgreSQL full-text search |
| **Auth** | Email/password + magic-link login |
| **Admin Security** | Mandatory 2FA, custom URL, optional IP allow-list |
| **Deployment** | Docker Compose + Gunicorn + Nginx |

## Quick Start (Local Development)

### 1. Clone and setup

```bash
git clone <repo-url>
cd Mawsu3ah
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set DJANGO_SECRET_KEY to a long random string
```

### 3. Run with SQLite (fastest)

```bash
USE_SQLITE=1 python manage.py migrate
USE_SQLITE=1 python manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Create an admin with 2FA

```bash
python manage.py createsuperuser
python manage.py create_admin_with_totp <email>
```

Scan the printed QR code with an authenticator app (Google Authenticator, Authy, etc.) before using the admin login.

## Running Tests

```bash
USE_SQLITE=1 python manage.py test
```

Linting:

```bash
ruff check .
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your values.

| Variable | Purpose |
|----------|---------|
| `DJANGO_SECRET_KEY` | Long random string (≥50 chars) |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated domains |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` origins |
| `DJANGO_ADMIN_URL` | Custom admin path (**do not use `admin`**) |
| `ADMIN_ALLOWED_IPS` | Optional IP allow-list for admin |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` when HTTPS is enabled |
| `SECURE_HSTS_SECONDS` | HSTS max-age (start `0`, then `300`, then `31536000`) |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `true` when stable |
| `SECURE_HSTS_PRELOAD` | `true` only for preload submission |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `REDIS_URL` | Optional Redis for caching/rate-limiting |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP settings |
| `EMAIL_USE_TLS` | `true` for TLS (default) |
| `DEFAULT_FROM_EMAIL` | From address for emails |
| `CONTACT_EMAIL` | Contact form destination |

## Production Deployment

### Docker Compose (Recommended)

```bash
# 1. Configure .env with production values
cp .env.example .env
# Edit .env — change DJANGO_ADMIN_URL, set real passwords, etc.

# 2. Build and start
docker compose up -d --build

# 3. Create first admin
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py create_admin_with_totp <email>

# 4. Place SSL certificate in front of Nginx (Let's Encrypt / Caddy)
```

This starts PostgreSQL, Django (Gunicorn), and Nginx. Nginx serves `/static/` and `/media/` directly.

### HSTS Rollout

1. `SECURE_HSTS_SECONDS=300` for a few days
2. `SECURE_HSTS_SECONDS=31536000` + `SECURE_HSTS_INCLUDE_SUBDOMAINS=true` once stable
3. `SECURE_HSTS_PRELOAD=true` only when ready for [hstspreload.org](https://hstspreload.org)

## Security Highlights

- **CSRF** protection on all state-changing requests
- **Rate limiting** on auth, submissions, likes, reviews, and replies
- **Magic links** expire in 10 minutes and are single-use
- **Admin 2FA** mandatory via TOTP
- **Custom admin URL** + optional IP allow-list
- **Secure cookies** with `HttpOnly`, `Secure`, `SameSite=Lax`
- **Content Security Policy** with nonces for inline scripts
- **UUIDs for public resources** instead of sequential IDs

## Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

Open community project. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <em>مشروع مجتمعي مفتوح — الموسوعة الكبرى لأفضل طبعات الكتب</em>
</p>

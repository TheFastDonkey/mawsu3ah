# Migrating from SQLite to PostgreSQL

This guide explains how to move your local SQLite data (`db.sqlite3`) into a PostgreSQL database.

## 1. Install and start PostgreSQL

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

## 2. Create the database and user

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE USER mawsu3ah WITH PASSWORD 'change-me';
CREATE DATABASE mawsu3ah OWNER mawsu3ah;
GRANT ALL PRIVILEGES ON DATABASE mawsu3ah TO mawsu3ah;
\q
```

Make sure the password matches `DB_PASSWORD` in your `.env`.

## 3. Update `.env`

Ensure PostgreSQL is selected (do **not** set `USE_SQLITE=1`):

```bash
DB_NAME=mawsu3ah
DB_USER=mawsu3ah
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=5432
```

## 4. Run migrations on PostgreSQL

```bash
.venv/bin/python manage.py migrate
```

## 5. Dump data from SQLite

```bash
USE_SQLITE=1 .venv/bin/python manage.py dumpdata \
  --natural-primary --natural-foreign \
  -e contenttypes \
  -e auth.Permission \
  -e admin.logentry \
  -e sessions.session \
  -e accounts.Profile \
  > /tmp/mawsu3ah_dump.json
```

`accounts.Profile` is excluded because the `User` model has a `post_save` signal that creates profiles automatically.

## 6. Load data into PostgreSQL

```bash
.venv/bin/python manage.py flush --no-input
.venv/bin/python manage.py loaddata /tmp/mawsu3ah_dump.json
```

## 7. Restart Django

```bash
pkill -f "manage.py runserver"
nohup .venv/bin/python manage.py runserver 0.0.0.0:8000 > /tmp/mawsu3ah_runserver.log 2>&1 &
```

## Troubleshooting

### `connection refused` on port 5432
PostgreSQL is not running. Start it with:

```bash
sudo systemctl start postgresql
```

### Password authentication failed
The password in `.env` does not match the PostgreSQL user password. Recreate the user or update `.env`.

### `UniqueViolation` on `accounts_profile_user_id_key`
You included `accounts.Profile` in the dump. Exclude it as shown in step 5.

### `GROUP BY` error after migration
If you see a PostgreSQL error about `ORDER BY` and `GROUP BY` in the sidebar, make sure `mawsu3ah/context_processors.py` clears `Book` default ordering in the subquery with `.order_by()`.

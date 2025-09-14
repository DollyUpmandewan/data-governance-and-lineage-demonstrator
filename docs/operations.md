# Operations and recovery

## Local service

Run ./start.ps1 from the project folder; stop with Ctrl+C. Select another port with ./start.ps1 -Port 8001, which also adjusts the origin. Refresh or navigate the interface to see a scan completed elsewhere.

/health/live confirms process response; /health/ready checks database connectivity. Readiness does not certify source availability: inspect Quality monitor. Logs go to process/container output; scan outcomes persist. No external email or incident service is configured.

## PostgreSQL and Docker Compose

1. Start Docker Desktop with its Linux engine.
2. Copy .env.example to .env and replace POSTGRES_PASSWORD with a long random URL-safe password. Hexadecimal avoids URL encoding issues. Do not commit this file.
3. Run `docker compose up --build -d`.
4. Inspect `docker compose ps` and `docker compose logs web`.
5. Create accounts with `docker compose exec web python -m app.accounts --demo`, or use the named-account command in README.
6. Open http://127.0.0.1:8000 and scan sources.

Compose persists catalogue and sources in separate volumes. The app runs as UID 10001. The database has no published host port; web binds to loopback. Stopping Compose preserves volumes. Do not remove volumes when data must be retained.

| Variable | Meaning/default |
| --- | --- |
| DATABASE_URL | SQLite in STATE_DIR locally; PostgreSQL+psycopg in Compose |
| STATE_DIR | runtime locally |
| DATA_DIR | STATE_DIR/sources |
| APP_ORIGIN | http://127.0.0.1:8000; exact browser origin |
| COOKIE_SECURE | false for local HTTP; true behind HTTPS |
| SCAN_INTERVAL_SECONDS | 300; 0 disables scheduling |
| AUTO_MIGRATE | true; Alembic revisions at startup |

For HTTPS, configure a trusted reverse proxy, exact HTTPS origin, secure cookies, an 8 MB body limit, trusted forwarding, time/connection limits and IP login throttling. Protect networks, database privileges, volumes and backups. Compose is a local example, not a cloud or availability guarantee. Use one worker. Managed rollouts can run `python -m app.migrate` before starting with AUTO_MIGRATE=false.

## SQLite backup and recovery

Stop the server first for coherent catalogue/source backup. Archives contain data and snapshots; protect them as live storage.

```powershell
./.venv/Scripts/python -m app.backup create runtime backups/atlas-backup.zip
./.venv/Scripts/python -m app.backup restore backups/atlas-backup.zip restored-runtime
$env:STATE_DIR = (Resolve-Path restored-runtime).Path
./start.ps1
```

Restore refuses existing targets and validates archive members. It invalidates sessions, revokes grants, clears the lease and marks assets unscanned. Sign in with restored credentials, scan and request fresh approvals. Verify representative data before switching environments. Remove STATE_DIR to return to the original profile.

## PostgreSQL backup and recovery

Stop web before capturing catalogue and sources together. Write a database dump inside the container, then copy it out to avoid binary-redirection issues in older PowerShell versions.

```powershell
docker compose stop web
docker compose exec db pg_dump -U catalogue -d catalogue -Fc -f /tmp/catalogue.dump
New-Item -ItemType Directory -Force backups
docker compose cp db:/tmp/catalogue.dump backups/catalogue.dump
docker compose cp web:/srv/runtime backups/runtime
docker compose start web
```

Restore into a separate database and source-volume copy using createdb and pg_restore with destination credentials. Configure a separate app instance. Before serving, invalidate sessions, revoke approved grants, clear leases and mark assets unscanned, following the local tool's recovery behavior. Apply migrations, rescan, and verify history, ownership, row counts and permission denial. Exercise this in the target environment before relying on it. The Python backup tool supports SQLite only. Set recovery objectives and schedule protected backups externally.

## Incident exercise and boundaries

Run `python -m app.demo break-reference` using the project environment, scan and inspect the failed reference and blocked sales. Run `python -m app.demo repair` and rescan. The command requires the synthetic marker and changes only the known demo reference; do not repurpose it for real sources.

Real-data use requires deployment-specific identity, policy, security, encryption, monitoring, recovery and workload validation. The optional [Purview metadata publisher](purview-integration.md) is implemented but requires Azure account configuration and live validation. Cloud hosting, SSO/MFA, external source entitlement provisioning and automated retention deletion are not implemented. CSV imports are managed copies rather than continuous connections to original files.

For backup recovery, keep PURVIEW_SYNC_AFTER_SCAN=false until restored metadata has been reviewed. A local restore does not undo remote Purview publications.

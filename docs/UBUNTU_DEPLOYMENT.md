# Ubuntu / UDA deployment for AutoKeeper

**Status:** Setup instructions only. The GitHub commit does not install, enable or run any service.

## 1. Prepare a dedicated host directory

Use a dedicated Unix account such as autokeeper (create it first). Install Python 3.11+ and Git. Then, using that account:

~~~bash
git clone https://github.com/zageabb/AutoKeeper.git /opt/autokeeper
cd /opt/autokeeper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
mkdir -p data
chmod 700 data
~~~

Set a strong APP_ADMIN_PASSWORD, authorised DVLA_API_KEY and appropriate SMTP values in the private .env file.

For the authorised sender, privately populate SMTP_USER and SMTP_FROM with that Gmail address. Obtain a valid sending credential under Google's current account security policies. A ChatGPT Gmail connection does not grant SMTP credentials to your Ubuntu server. Keep SMTP_APP_PASSWORD blank until ready to test outbound email with the recipients' permission.

Set AUTOKEEPER_DB_PATH=/opt/autokeeper/data/autokeeper.db and AUTOKEEPER_ROOT_PATH=/apps/autokeeper for the live UDA prefix.

## 2. Uvicorn service

Create /etc/systemd/system/autokeeper.service:

~~~ini
[Unit]
Description=AutoKeeper vehicle register
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=autokeeper
Group=autokeeper
WorkingDirectory=/opt/autokeeper
EnvironmentFile=/opt/autokeeper/.env
ExecStart=/opt/autokeeper/.venv/bin/uvicorn autokeeper.server:app --host 127.0.0.1 --port 5064
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
UMask=0077

[Install]
WantedBy=multi-user.target
~~~

Ensure that the User, Group, directory ownership and private environment file permissions agree. Enable and check the service:

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now autokeeper.service
curl -f http://127.0.0.1:5064/health
~~~

Only /health is intentionally unauthenticated and it must not expose private vehicle information. All dashboard and API routes enforce application HTTP Basic credentials.

## 3. Publish through your existing authenticated UDA/Caddy route

LOCAL_UBUNTU_PROXY_COMPAT: this application runs behind a configurable path prefix. A representative Caddy rule in the existing authenticated site is:

~~~caddyfile
handle_path /apps/autokeeper/* {
    reverse_proxy 127.0.0.1:5064
}
~~~

The handle_path directive strips the public prefix. FastAPI receives an unprefixed route, while AUTOKEEPER_ROOT_PATH generates prefixed asset and API URLs. Configure Caddy inside the existing approved UDA ingress and authentication block. Do not expose port 5064 directly, create an unauthenticated alternative proxy route or trust arbitrary client-supplied forwarded prefix headers.

Verify login and anonymous denial, home page, CSS, JS, dashboard JSON, add/edit, Excel import and DVLA requests through the prefixed address. Test localhost root deployment separately with AUTOKEEPER_ROOT_PATH empty.

## 4. Weekly worker: Monday 08:00 UK time

Create /etc/systemd/system/autokeeper-weekly.service:

~~~ini
[Unit]
Description=AutoKeeper weekly DVLA check and email reminders
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=autokeeper
Group=autokeeper
WorkingDirectory=/opt/autokeeper
EnvironmentFile=/opt/autokeeper/.env
ExecStart=/opt/autokeeper/.venv/bin/python -m autokeeper.worker
NoNewPrivileges=true
UMask=0077
~~~

Create /etc/systemd/system/autokeeper-weekly.timer:

~~~ini
[Unit]
Description=Weekly vehicle expiry checks

[Timer]
OnCalendar=Mon *-*-* 08:00:00 Europe/London
Persistent=true
Unit=autokeeper-weekly.service

[Install]
WantedBy=timers.target
~~~

The timer schedule uses the London timezone and can be adjusted. To test without sending email (the worker still queries DVLA):

~~~bash
cd /opt/autokeeper
set -a; . ./.env; set +a
.venv/bin/python -m autokeeper.worker --dry-run
~~~

After approving the destination email addresses and verifying SMTP:

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now autokeeper-weekly.timer
systemctl list-timers autokeeper-weekly.timer
sudo journalctl -u autokeeper-weekly.service -n 50 --no-pager
~~~

This worker may return an error status if any DVLA query fails or if due reminders cannot be sent; inspect logs and fix configuration rather than treating partial execution as full success. A failed DVLA lookup keeps the previous known expiry values while exposing the error to the administrator.

## 5. First use, backup and approval

1. Import Master Car List-ga.xlsx from the browser after confirming authority to store employees' details. Do not put it in public web roots or Git.
2. Check all vehicles via DVLA. Verify sample expiry dates against official GOV.UK records.
3. Preview notifications without sending. Inspect recipient addresses for mistakes.
4. Send a controlled test to an authorised inbox before enabling live reminders.
5. Back up data/autokeeper.db using SQLite's online backup API into a private, encrypted location, and verify a restore.

For disaster recovery, keep the previous known-good release and copy of the private DB. Log mail summary counts, not credentials or unnecessary person-level personal data. Define a retention policy for checks and notification logs prior to wider use.

**Important:** These instructions have not been executed on your Ubuntu server. Existing reverse-proxy authentication and Caddy syntax need reviewing within your actual site configuration.

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

For direct standalone access, set a strong APP_ADMIN_PASSWORD and AUTOKEEPER_AUTH_MODE=basic. For UDA access, set AUTOKEEPER_AUTH_MODE=uda; the authenticated Caddy route passes X-UDA-User and X-UDA-Groups, and AutoKeeper allows the Personal group and UDA admins. Keep the .env file private. Set DVLA_API_KEY and SMTP values only when they are available.

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
ExecStart=/opt/autokeeper/.venv/bin/uvicorn autokeeper.server:app --host 127.0.0.1 --port 5092
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
curl -f http://127.0.0.1:5092/health
~~~

Only /health is intentionally unauthenticated and it must not expose private vehicle information. Dashboard and API routes enforce the selected auth mode: HTTP Basic for standalone installs or UDA identity and group headers behind the authenticated proxy.

## 3. Publish through your existing authenticated UDA/Caddy route

LOCAL_UBUNTU_PROXY_COMPAT: this application runs behind a configurable path prefix. A representative Caddy rule in the existing authenticated site is:

~~~caddyfile
handle_path /apps/autokeeper/* {
    forward_auth 127.0.0.1:5048 {
        uri /auth/check
        header_up X-UDA-App autokeeper
        copy_headers X-UDA-User X-UDA-Groups
    }
    reverse_proxy 127.0.0.1:5092
}
~~~

The handle_path directive strips the public prefix. FastAPI receives an unprefixed route, while AUTOKEEPER_ROOT_PATH generates prefixed asset and API URLs. Configure Caddy inside the existing UDA ingress and authentication block. The app trusts UDA identity headers only when AUTOKEEPER_AUTH_MODE=uda and requires the Personal group or UDA admin membership. Do not expose the backend port directly or trust arbitrary client-supplied forwarded prefix headers.

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


## Port 5092, UDA assets and LAN access

The UDA deployment binds to 127.0.0.1:5092 on the Ubuntu host. The inability to browse to http://192.168.1.249:5092/ is expected for loopback-only listeners. Keep this protection: AUTOKEEPER_AUTH_MODE=uda trusts X-UDA-User/X-UDA-Groups from the authenticated reverse proxy and must not be exposed directly to LAN clients.

Use https://tanyaanne.ddns.net/apps/autokeeper/ from LAN devices. To support a separate LAN-facing URL, route through a properly authenticated reverse proxy, not a public 0.0.0.0 Uvicorn listener.

Check on Ubuntu:

~~~bash
sudo systemctl cat autokeeper.service
sudo ss -ltnp | grep ':5092'
curl -i http://127.0.0.1:5092/static/style.css
curl -i http://127.0.0.1:5092/static/app.js
~~~

Through the UDA site, verify /apps/autokeeper/static/style.css returns 200 text/css; /apps/autokeeper/static/app.js returns JavaScript; and /apps/autokeeper/api/dashboard returns authenticated JSON. Browser-relative asset links avoid reliance on mismatched AUTOKEEPER_ROOT_PATH values for HTML styling. Restart the running service after deploying code changes; a GitHub merge does not restart Ubuntu.

# VPS Deployment Guide — tron.eriksampayo.com

## Architecture

```
Browser (HTTPS/WSS)
    → Cloudflare edge (SSL termination, proxy)
    → Origin Rule: override port to 8080
    → VPS (localhost:8080, Tornado server)
```

The server only needs Python + tornado. No pygame, no SDL, no system display
libraries — key constants are standalone in `game_square/keys.py`.

---

## 1. Provision the VPS

Any Ubuntu 22.04 VPS with 1GB RAM works (~$4-5/month).

- **DigitalOcean**: Create droplet → Ubuntu 22.04 → cheapest tier
- **Linode/Akamai**: Create Nanode → Ubuntu 22.04
- **Vultr**: Create instance → Ubuntu 22.04

Note the VPS public IP address (shown in the provider dashboard).

---

## 2. SSH in and install dependencies

```bash
ssh root@<VPS_IP>
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git
```

Ubuntu 22.04 ships with Python 3.10, which supports the `int | None` type
hints used in the codebase.

---

## 3. Clone the repo and set up the venv

```bash
cd /opt
git clone https://github.com/ErikSampayo/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
python3 -m venv venv
source venv/bin/activate
pip install -r game_square/requirements-server.txt
```

Verify the server starts:

```bash
python -m game_square.server --port 8080 --host 127.0.0.1
```

You should see `game_square server running on http://127.0.0.1:8080/`.
Press Ctrl+C to stop it for now.

---

## 4. Create a systemd service (auto-restart, start on boot)

Create the service file:

```bash
cat > /etc/systemd/system/game-square.service << 'EOF'
[Unit]
Description=game_square web server
After=network.target

[Service]
User=root
WorkingDirectory=/opt/rpi-rgb-led-matrix
ExecStart=/opt/rpi-rgb-led-matrix/venv/bin/python -m game_square.server --port 8080 --host 127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start it:

```bash
systemctl daemon-reload
systemctl enable game-square
systemctl start game-square
systemctl status game-square
```

Verify it's running:

```bash
curl http://localhost:8080/
```

Should return the HTML page.

---

## 5. Configure Cloudflare DNS

In the Cloudflare dashboard (https://dash.cloudflare.com) for
`eriksampayo.com`:

1. Go to **DNS** → **Records** → **Add record**
2. Settings:
   - **Type:** A
   - **Name:** `tron`
   - **IPv4 address:** `<VPS_IP>`
   - **Proxy status:** Proxied (orange cloud)
   - **TTL:** Auto
3. Click **Save**

---

## 6. Configure Cloudflare Origin Rule (port override)

Cloudflare proxies to port 80/443 by default. We need it to connect to
port 8080 on the VPS instead.

1. In Cloudflare dashboard → **Rules** → **Origin Rules** → **Create rule**
2. Settings:
   - **Rule name:** `game-square port`
   - **If incoming requests match:** Custom filter expression
     - Field: `Hostname` → Operator: `equals` → Value: `tron.eriksampayo.com`
   - **Then:** Override origin port → `8080`
3. Click **Deploy**

---

## 7. Configure Cloudflare SSL

1. In Cloudflare dashboard → **SSL/TLS** → **Overview**
2. Set encryption mode to **Flexible**
   (Cloudflare terminates HTTPS for the browser, connects to the VPS via HTTP)

This is safe because:
- The VPS only listens on `127.0.0.1` (localhost)
- Cloudflare is the only client that can reach it
- Traffic between Cloudflare and the VPS is over the provider's internal network

If you want end-to-end encryption later, switch to **Full (strict)** and
install an origin certificate from Cloudflare on the VPS.

---

## 8. Test it

Open a browser and go to:

```
https://tron.eriksampayo.com
```

You should see the game canvas with the controls bar. The first two
connections get Player 1 (red) and Player 2 (blue); everyone else
spectates.

---

## Day-to-day operations

### View server logs

```bash
journalctl -u game-square -f
```

### Restart the server

```bash
systemctl restart game-square
```

### Update the game (after pushing new code to GitHub)

```bash
cd /opt/rpi-rgb-led-matrix
git pull
systemctl restart game-square
```

### Stop the server

```bash
systemctl stop game-square
```

---

## Troubleshooting

### "Connection refused" at the browser

- Check the server is running: `systemctl status game-square`
- Check it's listening: `curl http://localhost:8080/`
- Check Cloudflare DNS record exists and is proxied (orange cloud)
- Check the Origin Rule is deployed and matches `tron.eriksampayo.com`

### WebSocket disconnects after 100 seconds

This is Cloudflare's idle timeout on the free plan. The server broadcasts
frames every 40ms, which should keep the connection alive. If it still
disconnects, check that the game thread is actually running (not crashed):

```bash
journalctl -u game-square --no-pager -n 50
```

### Game thread crashed

The systemd service has `Restart=always`, so it auto-recovers. Check logs
to find the crash cause:

```bash
journalctl -u game-square --no-pager -n 100
```

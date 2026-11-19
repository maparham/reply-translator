# Deploying on the Lightsail host

The translator runs next to claude-gateway on the same box and behind the same Cloudflare tunnel. It has its own
project directory (`~/translator`), compose project (`translator`), volume (`translator_data`) and port
(`127.0.0.1:18490`); nothing of claude-gateway's is touched. `<server-ip>` is the instance's public address.

## First-time setup

1. **Volume** (once; compose never removes it):
   ```sh
   ssh ec2-user@<server-ip> 'sudo docker volume create translator_data && mkdir -p translator/deploy/lightsail'
   ```
2. **Clerk**: in the Clerk dashboard create a production application for `translate.rahkar.pro` (add the DNS
   records Clerk lists, enable the sign-in methods you want). Note the publishable (`pk_live_...`) and secret
   (`sk_live_...`) keys.
3. **Turnstile**: Cloudflare dashboard → Turnstile → add a widget for hostname `translate.rahkar.pro`. Its site
   key and secret key are entered in the app's `/admin` page later, not in `translator.env`.
4. **Tunnel route**: the `claude-gateway` tunnel is managed from the Cloudflare dashboard, so add the route there:
   Networking → Tunnels → claude-gateway → Routes → Add route → Published application:

   | Hostname | Service URL |
   |---|---|
   | `translate.rahkar.pro` | `http://127.0.0.1:18490` |
5. **translator.env** on the box, `~/translator/deploy/lightsail/translator.env`, mode 600:
   ```sh
   APP_URL=https://translate.rahkar.pro
   APP_SECRET_KEY=<Fernet key>
   CLERK_PUBLISHABLE_KEY=pk_live_...
   CLERK_SECRET_KEY=sk_live_...
   ADMIN_EMAILS=you@example.com
   # optional: send Claude requests through an Anthropic-compatible gateway instead of api.anthropic.com
   # ANTHROPIC_BASE_URL=https://claude.rahkar.pro
   ```
   Generate the key with `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
   (or `uv run python -c ...` in the repo) and keep it in your password manager: it encrypts the provider API keys
   stored in the database, and it is not backed up. Then `chmod 600 translator.env`. `ADMIN_EMAILS` is
   comma-separated.
6. **Deploy**, from the repo root:
   ```sh
   deploy/lightsail/update.sh ec2-user@<server-ip>
   ```
   It rsyncs the source to `~/translator/`, builds `translator:manual-<time>` on the box, writes `.env`
   (`TRANSLATOR_TAG`), runs `docker compose up -d --no-build`, and waits up to 30 s for
   `http://127.0.0.1:18490/health`. Rerun it for every update; the volume and `translator.env` are kept.
7. Open `https://translate.rahkar.pro`, sign in with an `ADMIN_EMAILS` address, and at `/admin` set the Anthropic /
   OpenAI keys, the Turnstile site and secret keys, and the daily cap. Until Turnstile keys are set, the app
   answers 503 to anonymous generate requests.

## Operations

- Logs: `cd ~/translator/deploy/lightsail && sudo docker compose logs --since 1h translator`
- Roll back: list tags with `sudo docker image ls translator`, write `TRANSLATOR_TAG=<tag>` to `.env`, then
  `sudo docker compose up -d --no-build`.
- Recreate after editing `translator.env`: `sudo docker compose up -d --force-recreate`.

## Backups

`translator-backup` writes a gzipped, age-encrypted copy of `/data/translator.db` (taken with SQLite's backup
API) to stdout. The box holds only the public key; the caller can't choose the recipient.

Prerequisites: the first deploy is done (step 6 above, so `~/translator` exists on the box), and the SSH user can
run `docker` without sudo, because the forced command calls it directly. Check with `id -nG | grep -w docker`
(claude-gateway's backup needs the same, so it is probably already set); otherwise
`sudo usermod -aG docker ec2-user` and reconnect.

One-time setup:

1. On your Mac make the age key pair and keep `translator-age.key` in your password manager (`brew install age`):
   ```sh
   age-keygen -o translator-age.key      # prints the public key (age1...)
   ```
2. Install age on the box: `sudo dnf install -y age` (Amazon Linux; if the package isn't available, download the
   `age-vX.Y.Z-linux-amd64.tar.gz` release from https://github.com/FiloSottile/age/releases, extract it, and
   `sudo install -m 755 age/age /usr/local/bin/age`). Check with `age --version`.
3. Put the public key and the script on the box (needs the first deploy, since the script comes from
   `~/translator`; after any change to `translator-backup`, deploy, then rerun
   `sudo install -o root -g root -m 755 ~/translator/deploy/lightsail/translator-backup /usr/local/bin/`):
   ```sh
   echo 'age1...public key...' | sudo tee /usr/local/etc/translator-backup.age.pub
   sudo install -o root -g root -m 755 ~/translator/deploy/lightsail/translator-backup /usr/local/bin/
   ```
4. Make a dedicated SSH key on your Mac (`ssh-keygen -t ed25519 -N '' -f ~/.ssh/translator-backup`) and append this
   line to `~/.ssh/authorized_keys` on the box, with the contents of `translator-backup.pub` at the end:
   ```
   command="/usr/local/bin/translator-backup",no-port-forwarding,no-pty,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... translator-backup
   ```
   That key can run only the backup script.

Take a copy (from anywhere with the backup key):

```sh
ssh -i ~/.ssh/translator-backup ec2-user@<server-ip> > translator-$(date +%F).age
```

## Restore

The image runs as uid 10001 (`useradd --uid 10001 translator` in the Dockerfile), so the restored file must be
owned by it. On your Mac, with the age private key:

```sh
age -d -i translator-age.key translator-2026-11-19.age | gunzip > translator.db
python3 -c 'import sqlite3; print(sqlite3.connect("translator.db").execute("PRAGMA integrity_check").fetchone())'
scp translator.db ec2-user@<server-ip>:translator-restore.db
```

On the box:

```sh
cd ~/translator/deploy/lightsail
sudo docker compose down                      # stops the container; the volume is kept
TAG=$(sed -n 's/^TRANSLATOR_TAG=//p' .env)
sudo docker run --rm -i --user 10001 -v translator_data:/data "translator:${TAG:-latest}" \
  sh -c 'rm -f /data/translator.db /data/translator.db-wal /data/translator.db-shm && cat > /data/translator.db' \
  < ~/translator-restore.db
rm ~/translator-restore.db
sudo docker compose up -d --no-build
for i in $(seq 30); do curl -fsS --max-time 2 http://127.0.0.1:18490/health && break; sleep 1; done; curl -fsS --max-time 5 http://127.0.0.1:18490/health
```

The restored database's provider keys are encrypted with the `APP_SECRET_KEY` in effect when they were saved, so
`translator.env` must still hold that same key.

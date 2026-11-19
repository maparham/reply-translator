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
API) to stdout; the box holds only the public key. Manual setup on the box:

```sh
sudo install -o root -g root -m 755 ~/translator/deploy/lightsail/translator-backup /usr/local/bin/
# age must be installed (see claude-gateway's install-backup-key.sh; the box already has it if that was run)
# on your Mac:   age-keygen -o translator-age.key   (keep it in the password manager)
echo 'age1...public key...' | sudo tee /usr/local/etc/translator-backup.age.pub
```

Take a copy from anywhere that can SSH in: `ssh ec2-user@<server-ip> /usr/local/bin/translator-backup > t.db.gz.age`
(or add a restricted `command="/usr/local/bin/translator-backup",restrict <key>` line to `authorized_keys` for an
automated job). Restore: `age -d -i translator-age.key t.db.gz.age | gunzip > translator.db`, then copy it into
the `translator_data` volume as `/data/translator.db` with the container stopped.

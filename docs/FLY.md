# Deploying Pit Box to Fly.io

For when there is no machine you can realistically leave on. Fly runs the
container, a Fly volume holds the database and the uploaded files, and Cloudflare
Access still decides who gets in.

Read [CLOUDFLARE.md](CLOUDFLARE.md) first if you have not — this document assumes
you know what an Access application is.

---

## What changes, and why

Running on your own machine, the app was safe because it was **unreachable**. It
bound `127.0.0.1`, no port was open, and cloudflared was the only way in. That is
what made it fine to trust a header saying who you were: nobody else could set it.

A normal Fly app breaks that assumption completely. Fly gives you
`yourapp.fly.dev`, and it is public. Anyone could then run:

```bash
curl -H 'Cf-Access-Authenticated-User-Email: whoever@wherever' \
     https://yourapp.fly.dev/api/projects
```

and walk straight past Access with your entire BOM in the response. So two things
changed:

**1. The app now verifies Cloudflare's signature.** The email header is ignored
outright. Instead, `Cf-Access-Jwt-Assertion` carries a JWT that Cloudflare signed
with a private key only they hold, and `app/access_jwt.py` checks it against
their published public keys — plus the audience, the issuer, and the expiry. A
forged header has no signature and gets a 403 no matter where it came from.

**2. This deployment publishes no port at all.** cloudflared moved *into* the
container. It dials out to Cloudflare from inside the Fly machine, so Fly never
allocates a public IP and `yourapp.fly.dev` resolves to nothing.

Either one of those would be enough. Both is the point: the tunnel means there is
no door, and the signature means the door would be locked anyway.

### "So do we drop cloudflared?"

No — it moves. Your assumption was that with no local machine there is nowhere to
run it, but the Fly container is a machine, and running it there keeps the
property that made the original design safe. You do get a choice:

| | **Tunnel in the container** (recommended, and what `fly.toml` does) | **Public Fly service** |
|---|---|---|
| Public origin URL | none — no IP is allocated | `yourapp.fly.dev`, permanently |
| DNS | the tunnel creates the record | proxied CNAME to `yourapp.fly.dev` |
| What stops a bypass | there is nothing to bypass | JWT verification + host allowlist |
| Moving parts | a second process, one secret | fewer |

The second column is a legitimate choice and the app is safe in it. The first is
better, and costs one `fly secrets set`.

---

## Answering the direct question: can you block the .fly.dev URL?

**You cannot delete the hostname.** Fly assigns `<app>.fly.dev` to every app and
there is no setting that removes it.

**You can make it resolve to nothing**, which is better. The hostname only routes
anywhere if the app has a public IP, and an app is only given one if `fly.toml`
publishes a service. The config here publishes none, so:

```bash
fly ips list        # should print no rows
```

If a row appears — `fly launch` allocates them by default — release it:

```bash
fly ips release <address>
```

If you take the public-service route instead, the .fly.dev name stays live, and
`PITBOX_ALLOWED_HOSTS` is what shuts it: set it to your real hostname and any
request addressed to the .fly.dev name is refused with a 400 before it reaches a
route. That is defence in depth — JWT verification is what actually protects the
data — but it means a curious person poking at the origin sees nothing at all.

---

## Setup

### 1. Cloudflare: create the tunnel

In <https://one.dash.cloudflare.com>: **Networks → Tunnels → Create a tunnel →
Cloudflared**. Name it `pitbox`.

Skip the install instructions — the container already has cloudflared. On the
connector page, copy the **token** (a long string in the sample command, after
`--token`).

Then add a **Public Hostname**:

| Field | Value |
|---|---|
| Subdomain | `pitbox` |
| Domain | `yourteam.org` |
| Service type | `HTTP` |
| URL | `localhost:8000` |

This creates the DNS record. Nothing is listening yet, and that is fine.

> A **remotely-managed** tunnel is what you want here — the config lives in the
> dashboard, so there is no config file to keep alive in the image, and whoever
> inherits this can change where it points without a deploy.

### 2. Cloudflare: create the Access application

Exactly as in [CLOUDFLARE.md](CLOUDFLARE.md) Part 2 — **Access → Applications →
Add an application → Self-hosted**, hostname `pitbox.yourteam.org`, one Allow
policy with **Emails ending in** `@youruniversity.edu`.

Then open the application's **Overview** tab and copy the **Application Audience
(AUD) Tag** — 64 hex characters. The app needs it to reject tokens Cloudflare
minted for some *other* application on your team.

Doing this before the first deploy means there is never a window where the
hostname is live without a policy.

### 3. Fly: create the app and the volume

```bash
fly auth login
fly apps create pitbox
```

Use `fly apps create`, not `fly launch` — `fly launch` overwrites `fly.toml` and
`Dockerfile` with its own guesses. Set `app = "pitbox"` in `fly.toml` to whatever
name you got.

```bash
fly volumes create pitbox_data --size 3 --region dfw
```

3 GB is plenty for a BOM plus CAD files; volumes can be extended, never shrunk.
The region must match `primary_region` in `fly.toml`.

### 4. Fly: set the secrets

```bash
fly secrets set TUNNEL_TOKEN="<the token from step 1>"
fly secrets set PITBOX_ACCESS_TEAM_DOMAIN="yourteam.cloudflareaccess.com"
fly secrets set PITBOX_ACCESS_AUD="<the AUD tag from step 2>"
```

Only the first is really a secret; the other two are identifiers and could live
in `fly.toml` instead. Keeping them together is simply easier to remember.

### 5. Deploy

```bash
fly deploy
fly logs
```

You are looking for two lines: `Cloudflare Access enabled: issuer=... aud=...`
and cloudflared registering a connection. Then open
`https://pitbox.yourteam.org` — you should get a Cloudflare login, not Pit Box.

If it crash-loops on `AccessConfigError`, one of the two `PITBOX_ACCESS_*`
secrets is missing. That is deliberate: the app will not start in Cloudflare mode
without the means to verify a signature, because the alternative is starting up
and trusting anything.

### 6. Check the bypass is actually closed

```bash
fly ips list
curl -i https://pitbox.fly.dev/api/health
curl -i -H 'Cf-Access-Authenticated-User-Email: attacker@evil.com' \
     https://pitbox.yourteam.org/api/projects
```

Expected: no IPs, the .fly.dev request fails to connect at all, and the forged
header gets **403**. Do all three — the third is the one that would have handed
over the BOM before this change.

---

## Moving your existing data across

The first deploy seeds a fresh demo car. If you have real work in the local
database, move it before sharing the link.

```powershell
# 1. WAL-safe snapshot. Do NOT just copy pitbox.db -- most of your recent work
#    is in pitbox.db-wal and a plain copy silently leaves it behind.
.\.venv\Scripts\python.exe scripts\backup.py

# 2. Uploaded files, as one archive (sftp cannot put a directory).
tar -czf storage.tgz storage
```

```bash
# 3. Upload both.
fly sftp shell
  put backups/pitbox-2026-08-30_1400/pitbox.db /data/pitbox.db
  put storage.tgz /data/storage.tgz
  exit

# 4. Unpack, drop the stale sidecars, restart onto the imported file.
fly ssh console -C "sh -c 'cd /data && rm -f pitbox.db-wal pitbox.db-shm && tar xzf storage.tgz --strip-components=1 -C storage && rm storage.tgz'"
fly apps restart pitbox
```

Then load the app and check the node count matches what you had. Do this while
nobody is using it — you are replacing a database file underneath a running
process, which is safe when there are no writers and nothing you want to repeat
mid-season.

---

## Running it

```bash
fly logs                  # live
fly status                # is the machine up
fly ssh console           # a shell in the container
fly apps restart pitbox
```

**Backups.** Fly snapshots the volume daily and keeps five days, which covers the
machine dying. It does not cover someone deleting a subsystem, so keep taking
real backups:

```bash
fly ssh console -C "python scripts/backup.py --out /data/backups --keep 5"
fly sftp get /data/backups/pitbox-<stamp>/pitbox.db ./pitbox-backup.db
```

That runs the same WAL-safe script as on Windows, and prints row counts so you
can see the backup has your parts in it rather than assuming.

**Cost.** One `shared-cpu-1x` 512 MB machine plus a 3 GB volume is a few dollars
a month, and the Cloudflare side stays free.

**Deploys are brief downtime, on purpose.** `strategy = "immediate"` stops the old
machine before starting the new one. SQLite tolerates exactly one writer, and two
machines sharing one database file is the failure mode that eats data. Keep
`fly scale count 1`.

---

## If it breaks

| Symptom | Cause |
|---|---|
| Deploy crash-loops, logs say `AccessConfigError` | `PITBOX_ACCESS_TEAM_DOMAIN` or `PITBOX_ACCESS_AUD` is not set |
| Cloudflare login works, then 403 "different Access application" | `PITBOX_ACCESS_AUD` belongs to another Access app |
| Cloudflare login works, then 403 "different Cloudflare team" | `PITBOX_ACCESS_TEAM_DOMAIN` is wrong |
| 502 from Cloudflare | cloudflared is up, uvicorn is not — check `fly logs` |
| Cloudflare says the tunnel is down | `TUNNEL_TOKEN` is wrong, or the machine is stopped |
| 503 "Cannot reach Cloudflare to verify sign-in" | the container cannot reach `cloudflareaccess.com`; keys could not be fetched |
| Everything is empty after a deploy | the volume is not mounted, or `PITBOX_DATABASE_URL` lost a slash — it needs **four** |

That last one is worth staring at. `sqlite:///data/pitbox.db` is a *relative*
path inside the container and works perfectly right up until the deploy that
throws the container away. `sqlite:////data/pitbox.db` is the absolute one.

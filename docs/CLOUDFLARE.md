# Running Pit Box behind Cloudflare Access

This is the deployment the app is built for. Cloudflare checks who you are;
Pit Box trusts the answer. There are no passwords, no accounts to create, and
nothing to hand over at the end of the year except the Cloudflare login.

**How access works once this is set up:** a new member with a school email opens
the URL, Cloudflare emails them a one-time code, and they are in. Pit Box sees
their email, creates their member record on the spot, and they appear in the
assignee list. Nobody runs a script. When they graduate and the school disables
their email, they stop being able to get a code.

---

## The security model

Read this before changing anything about how the app is started.

Cloudflare Access proves identity twice over, and the app relies on the half that
cannot be faked:

* **`Cf-Access-Jwt-Assertion`** carries a token Cloudflare signed with a private
  key only they hold. Pit Box verifies that signature against their published
  public keys, plus the audience (this application specifically), the issuer
  (your team) and the expiry. Forging one is not a matter of sending the right
  header — it means forging a signature.
* **`Cf-Access-Authenticated-User-Email`** is a plain header. Anyone who can
  reach the app can set it. **Pit Box ignores it entirely.**

The second point is the one worth dwelling on. Trusting the email header is a
common shortcut — Cloudflare's own quickstarts show it — and it is safe only
while the app is genuinely unreachable except through the tunnel. That condition
is easy to break by accident: binding `0.0.0.0`, forwarding a port, or moving to
a host that hands out a public URL of its own. When it breaks it breaks silently
and completely, and the app carries on looking fine.

Verifying the signature removes the assumption instead of documenting it.
Binding to loopback is still the right default and the tunnel still means no port
is ever opened — that is defence in depth. It is just no longer the only thing
standing between the parts list and a one-line `curl`.

**This needs two settings.** `PITBOX_ACCESS_TEAM_DOMAIN` and `PITBOX_ACCESS_AUD`,
below. Without them the app refuses to start rather than falling back to trusting
a header.

---

## What you need

- A domain on Cloudflare. Around $10/yr at cost from Cloudflare Registrar; a
  subdomain like `pitbox.yourteam.org` is fine.
- A machine that stays on, with Pit Box running. If you do not have one,
  [FLY.md](FLY.md) runs the same setup on Fly.io instead — same Access
  application, same policy, no machine of your own.
- A free Cloudflare Zero Trust plan — covers 50 users.

---

## Part 1 — on the machine

**1. Build the UI.**

```powershell
cd frontend; npm run build; cd ..
```

Do not start the app yet — it needs two values that Part 2 produces. Come back
here after the Access application exists.

**1b. Once you have them,** put them in `.env` (see `.env.example`):

```
PITBOX_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com
PITBOX_ACCESS_AUD=<the 64-character Application Audience tag>
```

then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`PITBOX_AUTH_MODE` defaults to `cloudflare`, so there is nothing else to set.
Confirm:

```powershell
curl.exe http://127.0.0.1:8000/api/health
# {"status":"ok","team":"Your Team Name","auth_mode":"cloudflare"}
```

If it exits immediately complaining about `PITBOX_ACCESS_TEAM_DOMAIN`, those two
values are missing. The app will not start in this mode without the means to
verify a signature — the alternative would be starting up and trusting anything.

Hitting it directly now returns **403**. That is correct: no Cloudflare token,
no entry, and no email header will change that.

**2. Install cloudflared and sign in.**

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel login
```

**3. Create the tunnel and point a hostname at it.**

```bash
cloudflared tunnel create pitbox
cloudflared tunnel route dns pitbox pitbox.yourteam.org
```

`create` prints a tunnel ID and the path to a credentials JSON — you need both next.

**4. Write the config.** Copy `deploy/cloudflared-config.example.yml` to
`%USERPROFILE%\.cloudflared\config.yml` and fill in the tunnel name, the
credentials path, and your hostname.

**5. Run it.**

```bash
cloudflared tunnel run pitbox
```

> At this point the URL is **live and unprotected**. Do Part 2 now, before
> sharing it with anyone.

---

## Part 2 — on the Cloudflare dashboard

This is the part that actually gates access.

**1.** Go to <https://one.dash.cloudflare.com> and pick your account. This is
**Zero Trust**, a different dashboard from the main Cloudflare one.

**2.** In the sidebar: **Access → Applications → Add an application**.

**3.** Choose **Self-hosted**.

**4.** Fill in the application:

| Field | Value |
|---|---|
| Application name | `Pit Box` |
| Session duration | `1 month` — how long before members re-authenticate |
| Subdomain | `pitbox` |
| Domain | `yourteam.org` |

**5.** Continue to policies and **add a policy**:

| Field | Value |
|---|---|
| Policy name | `Team members` |
| Action | **Allow** |
| Selector | **Emails ending in** |
| Value | `@youruniversity.edu` |

That single rule is the whole access-control system: anyone with a school email
gets in, everyone else does not. If your school's addresses are inconsistent,
use the **Emails** selector and list people instead — more precise, but then you
are back to maintaining a list, which is the thing this design avoids.

**6.** Login methods: **One-time PIN** is on by default and needs no setup —
Cloudflare emails a code. That is enough. If your school uses Google Workspace
or Microsoft 365, adding it under **Settings → Authentication** gives one-click
sign-in instead of a code.

**7.** Save the application, then open its **Overview** tab and copy the
**Application Audience (AUD) Tag** — 64 hex characters. That is the
`PITBOX_ACCESS_AUD` from Part 1b, and it is what stops a token Cloudflare minted
for some *other* application on your team from being accepted here.

Your team domain is on **Settings → Custom Pages**, or in the URL of the login
page: `yourteam.cloudflareaccess.com`.

**8. Verify it actually blocks.** Open the URL in a private window. You should
get a Cloudflare login prompt, *not* Pit Box. Try a personal email — it must be
refused. Only then share the link.

---

## Part 3 — make it survive a reboot

```powershell
cloudflared service install
```

And install the app's own boot task, from an **elevated** PowerShell:

```powershell
.\deploy\install-tasks.ps1
```

Then reboot the machine and load the URL from your phone on cellular. If it
comes up without you touching anything, all three pieces work together.

---

## Day-to-day

**Removing someone before they graduate:** add a Block policy above the Allow
policy with their email. Cloudflare evaluates in order.

**Signing out** clears the Cloudflare session at `/cdn-cgi/access/logout` — the
app's Sign out button already points there in this mode.

**Uptime monitoring:** `/api/health` is behind Access like everything else, so an
external monitor gets the login page. If you want one, add a **Bypass** policy
scoped to the path `/api/health`. It reveals only that the service is up.

**Local development** has no tunnel, so `dev.ps1` sets `PITBOX_AUTH_MODE=none`
and runs with no auth at all. That is fine on your own machine and nowhere else.

**No machine to leave running?** [FLY.md](FLY.md) puts the same thing on Fly.io,
with cloudflared inside the container and a volume for the database.

---

## If it breaks

| Symptom | Cause |
|---|---|
| The app exits at startup with `AccessConfigError` | `PITBOX_ACCESS_TEAM_DOMAIN` or `PITBOX_ACCESS_AUD` is not set |
| 403 "No verified Cloudflare Access token" | Reached the app without going through the tunnel, or no Access policy is attached to the hostname |
| 403 "issued for a different Access application" | `PITBOX_ACCESS_AUD` belongs to another Access app |
| 403 "issued by a different Cloudflare team" | `PITBOX_ACCESS_TEAM_DOMAIN` is wrong |
| 503 "Cannot reach Cloudflare to verify sign-in" | The machine cannot fetch Cloudflare's public keys |
| Cloudflare login appears, then 502 | Tunnel is up, app is not — start uvicorn |
| Login prompt loops | Session duration too short, or the browser is blocking third-party cookies |
| Everyone gets in, including outsiders | The application in Part 2 was never created, or its domain does not exactly match the hostname |

The last one is worth checking deliberately: a tunnel with no Access
application in front is a public URL.

---

## If you ever leave Cloudflare

The app still has a built-in login — scrypt passwords and revocable sessions —
switched off by default. Set `PITBOX_AUTH_MODE=password`, create an admin with
`python scripts/create_user.py --email you@school.edu --name "You" --admin`, and
`/login` starts working. Nothing else changes.

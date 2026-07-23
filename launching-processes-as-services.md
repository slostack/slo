# Launching a Process as a Service (Linux & macOS)

## The concept

A **service** (or **daemon**) is a long-running background process that the OS
starts, supervises, restarts on failure, and starts at boot — decoupled from any
login shell. Each OS has a **service manager** (an init system) that owns this:

| OS | Service manager | Config unit | CLI |
|---|---|---|---|
| Linux (modern) | **systemd** | `.service` unit file | `systemctl` |
| macOS | **launchd** | `.plist` file | `launchctl` |

---

## Linux — systemd

### 1. Write a unit file

**System-wide service** (runs at boot, as root or a specified user)
→ `/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=My App
After=network.target          # start after networking is up

[Service]
Type=simple                   # process stays in foreground; systemd tracks it
ExecStart=/usr/bin/python3 /opt/myapp/main.py
WorkingDirectory=/opt/myapp
User=myapp                    # drop privileges to this user
Restart=on-failure            # auto-restart if it crashes
RestartSec=5
Environment=ENV=production
EnvironmentFile=/opt/myapp/.env   # optional: load env vars from a file

[Install]
WantedBy=multi-user.target    # "enable" hooks it here for boot startup
```

### 2. Manage it

```bash
sudo systemctl daemon-reload          # re-read unit files after editing
sudo systemctl enable myapp           # start at boot
sudo systemctl start myapp            # start now
sudo systemctl status myapp           # check state
sudo systemctl restart myapp
sudo systemctl stop myapp
journalctl -u myapp -f                # tail its logs (stdout/stderr captured)
```

### User service (no root, runs under your login)

Put the same file in `~/.config/systemd/user/myapp.service`, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now myapp
loginctl enable-linger $USER          # keep it running after you log out
```

**Common `Type=` values:** `simple` (default, foreground process), `exec`,
`forking` (traditional daemons that fork), `oneshot` (run-once scripts),
`notify` (app signals readiness via sd_notify).

---

## macOS — launchd

launchd uses XML **`.plist`** files. Location determines scope:

- `~/Library/LaunchAgents/` — per-user agent (runs when you log in)
- `/Library/LaunchAgents/` — all users, on login
- `/Library/LaunchDaemons/` — system daemon, runs at boot before login

Example `~/Library/LaunchAgents/com.me.myapp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.me.myapp</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/opt/myapp/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/opt/myapp</string>

    <key>RunAtLoad</key>
    <true/>                          <!-- start on load/boot -->

    <key>KeepAlive</key>
    <true/>                          <!-- restart if it exits (≈ Restart=always) -->

    <key>StandardOutPath</key>
    <string>/tmp/myapp.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/myapp.err.log</string>
</dict>
</plist>
```

Manage it with the modern `launchctl` syntax:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.me.myapp.plist   # load
launchctl kickstart -k gui/$(id -u)/com.me.myapp                             # (re)start
launchctl print gui/$(id -u)/com.me.myapp                                    # status
launchctl bootout gui/$(id -u)/com.me.myapp                                  # unload
```

Older, still-common syntax:

```bash
launchctl load -w ~/Library/LaunchAgents/com.me.myapp.plist    # load + enable
launchctl unload ~/Library/LaunchAgents/com.me.myapp.plist     # unload
```

For system daemons in `/Library/LaunchDaemons/`, use `system/` instead of
`gui/$(id -u)` and run with `sudo`.

---

## Mapping between the two

| Intent | systemd | launchd |
|---|---|---|
| Start at boot | `WantedBy=multi-user.target` + `enable` | `RunAtLoad` + `LaunchDaemons` |
| Auto-restart | `Restart=always/on-failure` | `KeepAlive` |
| Command | `ExecStart=` | `ProgramArguments` |
| Run as user | `User=` | `UserName` (daemons) / agent location |
| Logs | journald (`journalctl`) | `StandardOutPath` / `StandardErrorPath` |
| Reload after edit | `systemctl daemon-reload` | `bootout` then `bootstrap` |

**Quick heuristic:** if the process must survive logout and start at boot without
anyone logging in → system service (`/etc/systemd/system` or
`/Library/LaunchDaemons`). If it only needs to run while *you're* logged in →
user service / LaunchAgent.

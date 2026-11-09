# mc-sync

Move a Minecraft world between your Windows PC and a VPS with a double-click, and start/stop
servers on the VPS from Discord.

```
windows/   double-click scripts: pack + upload / download + unpack (thin PowerShell)
vps/       Ansible playbooks that do the real work on the VPS (run locally there)
bot/       Discord bot: /mc status, /mc start, /mc stop -> calls vps/server.yml
```

Everything that changes the server lives in `vps/` as Ansible, so it reads top to bottom and you
can run any of it by hand:

| Playbook | What it does |
|---|---|
| `world-push.yml` | stop server if running → unpack upload to staging → sort out player data → back up current world → swap in → start again if it was running |
| `world-pull.yml` | stop server if running → pack world with you as the singleplayer player → start again if it was running |
| `server.yml` | start (stopping the others first, if `exclusive`) or stop a server |

Player data is handled by `vps/scripts/players.py` (see [Player data](#player-data) below).

Old server worlds are kept in `backup_dir` (newest 5 by default). Pulling never deletes your
local world either: it's moved to `%APPDATA%\.minecraft\world-backups` first.

## Assumed VPS layout

```
/opt/minecraft/survival/compose.yml       one folder per server
/opt/minecraft/survival/data/world/       the world (itzg/minecraft-server default)
/opt/minecraft/creative/compose.yml
/opt/minecraft-backups/                   created automatically
/opt/mc-sync/                             this project
```

Change paths in `vps/group_vars/all.yml`. The folder name (`survival`) is the server name everywhere.

## Setup

### VPS

1. Copy this project to `/opt/mc-sync` (git clone, scp, whatever).
2. Install Ansible with the `community.docker` collection (needs v3.6+ for `docker_compose_v2`):
   ```
   pipx install --include-deps ansible      # or: pip install ansible  — both include community.docker
   ```
   The distro `ansible` package is fine on Ubuntu 24.04; on older distros run
   `ansible-galaxy collection install community.docker`.
   You also need Python 3.10+ with venv support (`sudo apt install python3-venv` on Debian/Ubuntu);
   the playbooks create `vps/.venv` with `nbtlib` on first run.
3. Your SSH user must be in the `docker` group and own `/opt/minecraft` (or at least be able to write it).
4. Test by hand: `cd /opt/mc-sync/vps && ansible-playbook server.yml -e server=survival -e action=start`

### Windows

1. Put the `windows/` folder somewhere permanent, e.g. `Documents\mc-sync`.
2. Edit `config.ps1`: your SSH host alias, world name, server name.
3. Right-click `Push world to VPS.bat` → Send to → Desktop (create shortcut). Same for Pull.

Needs Windows 10/11's built-in `ssh`, `scp` and `tar` (all there by default). For a second
world/server pair, copy a `.bat` and add `-World "Other" -Server creative` to its command line.

### Discord bot

1. https://discord.com/developers/applications → New Application → Bot → copy the token.
   No privileged intents needed.
2. OAuth2 → URL Generator → scopes `bot` + `applications.commands` → open the URL to invite it.
3. Create a role called `Minecraft Admin` (or set `ALLOWED_ROLE`) for people allowed to start/stop.
   `/mc status` works for everyone.
4. On the VPS:
   ```
   cd /opt/mc-sync/bot
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env && chmod 600 .env   # fill in token + server (guild) ID
   # edit User= in mc-bot.service, then:
   sudo cp mc-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now mc-bot
   ```
   Guild ID: Discord settings → Advanced → Developer Mode, then right-click your server → Copy Server ID.

## Player data

Singleplayer stores the host player differently from everyone else, and a server ignores that:

| | Up to 1.21.x | 26.1 and later |
|---|---|---|
| Per-player files (server players, LAN guests) | `playerdata/`, `advancements/`, `stats/` | `players/data/`, `players/advancements/`, `players/stats/` |
| Singleplayer host | `level.dat` → `Data.Player` (overrides their own file) | `level.dat` → `Data.singleplayer_uuid` points at their file |

`players.py` detects the format and does this:

**Push** (singleplayer → server)
- **You** (the singleplayer host, identified from the world itself): your singleplayer inventory,
  position, advancements and stats replace your server copy.
- **Everyone else**: per player, the newer copy wins. Players who are only on the server are kept,
  and LAN guests who aren't on the server yet are added. Nobody is deleted.
- The playbook prints what it decided for each player.

**Pull** (server → singleplayer)
- **You** (your UUID comes from the launcher, or `$PlayerUuid` in `config.ps1`) become the
  singleplayer host with your server inventory. If you've never joined the server, you start fresh at spawn.
- **Everyone else**: their server files come along, so opening to LAN gives them their own inventories.
- The server's own copy of everyone's data wins on pull. Your previous local world is moved to
  `world-backups`, so nothing is lost if you had unpushed LAN progress.

Limits: UUIDs must match, so the server needs `online-mode=true` (the default; the script warns
otherwise). Requires 1.16+ worlds (UUIDs stored as int arrays). Both sides should run the same version.

## Things to know

- **Close the world in Minecraft first.** The scripts check and refuse to run if the world is open.
- **Paper/Spigot before 26.1** keeps the Nether and End in separate `world_nether` / `world_the_end`
  folders, while singleplayer and vanilla keep them inside `world/`. These scripts only move `world/`,
  which is right for vanilla/Fabric/Forge (and for any server on 26.1+, where dimensions live in `world/dimensions/`).
- **File ownership.** Unpacked files belong to your SSH user. With itzg/minecraft-server, set the
  container's `UID`/`GID` environment variables to that user's IDs (`id -u`, `id -g`) so the server can write them.
- **Ansible not found over SSH?** Non-interactive SSH may not load `~/.local/bin` into PATH. Put
  the full path in `$AnsiblePlaybook` in `config.ps1` (and `ANSIBLE_PLAYBOOK` in the bot's `.env`).

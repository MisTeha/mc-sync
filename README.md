# mc-sync

Move a Minecraft world between your Windows PC and a VPS with a double-click, and start/stop
servers on the VPS from Discord (with a tap-friendly button panel, so it's easy from a phone).

```
windows/   double-click scripts: sync a world up / down with rclone (thin PowerShell)
vps/       Ansible playbooks that do the real work on the VPS (run locally there)
bot/       Discord bot: button panel + /mc commands -> calls vps/server.yml
```

Everything that changes the server lives in `vps/` as Ansible, so it reads top to bottom and you
can run any of it by hand:

| Playbook | What it does |
|---|---|
| `world-push.yml` | stop server if running → copy the upload to staging → sort out player data → move current world to backups → swap in → start again if it was running |
| `world-pull.yml` | stop server if running → copy world for download → start again if it was running → make you the singleplayer player in the copy |
| `server.yml` | start (stopping the others first, if `exclusive`) or stop a server |

Player data is handled by `vps/scripts/players.py` (see [Player data](#player-data) below).

Worlds travel with [rclone](https://rclone.org), which only transfers files that changed. Each
server folder on the VPS has a `.sync-world` copy of the world as your PC last had it, so after the
first push or pull, playing for an evening usually means tens of MB, not the whole world.

Old server worlds are kept in `backup_dir` as plain folders (newest 5 by default). Pulling never
deletes your local world either: it's moved to `%APPDATA%\.minecraft\world-backups` first.

## Assumed VPS layout

```
/opt/minecraft/survival/compose.yml       one folder per server
/opt/minecraft/survival/data/world/       the world (itzg/minecraft-server default)
/opt/minecraft/survival/.sync-world/      the world as your PC last had it (created by push/pull)
/opt/minecraft/creative/compose.yml
/opt/minecraft-backups/survival-<date>/   old worlds (create the folder, owned by your SSH user)
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
3. Your SSH user must be in the `docker` group and own `/opt/minecraft` and `/opt/minecraft-backups`.
4. Test by hand: `cd /opt/mc-sync/vps && ansible-playbook server.yml -e server=survival -e action=start`

### Windows

1. Put the `windows/` folder somewhere permanent, e.g. `Documents\mc-sync`.
2. Install rclone: `winget install Rclone.Rclone` (then open a new terminal so it's on PATH).
   No rclone setup needed: it connects through your normal `ssh` and its config.
3. Edit `config.ps1`: your SSH host alias, world name, server name.
4. Right-click `Push world to VPS.bat` → Send to → Desktop (create shortcut). Same for Pull.

Also needs Windows 10/11's built-in `ssh` (there by default). For a second
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
5. In the channel you want it in, run `/mc panel` and pin the message it posts. That's the control
   panel: a Start/Stop button per server that updates itself (it re-checks every minute, so changes
   made by the world push/pull scripts show up too). Stop asks for confirmation first. Running
   `/mc panel` again moves it; the old one is deleted. The bot needs Send Messages in that channel.

   The panel shows up to 10 servers (a Discord limit on message size); the slash commands
   `/mc status`, `/mc start` and `/mc stop` work for all of them and for anyone who prefers typing.

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
- **The first push or pull sends the whole world**; after that only changes. Opening the world in a
  new Minecraft version or using "Optimize World" rewrites every region file, so that one is big too.
- **Pull downloads into `%APPDATA%\.minecraft\mc-sync-staging` first**, starting from a copy of your
  local world. If the download fails, your world is untouched and the next pull carries on from there.
- **Disk space on the VPS**: per server, the world, its `.sync-world` copy and up to `keep_backups`
  old worlds. Local backups in `world-backups` are never deleted automatically; clear old ones yourself.
- **File ownership.** Synced files belong to your SSH user. With itzg/minecraft-server, set the
  container's `UID`/`GID` environment variables to that user's IDs (`id -u`, `id -g`) so the server can write them.
- **Ansible not found over SSH?** Non-interactive SSH may not load `~/.local/bin` into PATH. Put
  the full path in `$AnsiblePlaybook` in `config.ps1` (and `ANSIBLE_PLAYBOOK` in the bot's `.env`).

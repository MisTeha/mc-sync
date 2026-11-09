# ---- Edit these to match your setup ----

# Host alias from your ~/.ssh/config (or user@your.vps.ip)
$VpsHost = "vps"

# Your local Minecraft folder, and the world folder name inside its saves folder
$MinecraftDir = "$env:APPDATA\.minecraft"
$SavesDir     = "$MinecraftDir\saves"
$DefaultWorld = "My World"

# The server folder name under mc_root on the VPS (e.g. /opt/minecraft/survival -> "survival")
$DefaultServer = "survival"

# Your Minecraft account's UUID, used when pulling so you get your own inventory.
# Leave empty to read it from the official launcher's account file automatically.
# Set it by hand if you use another launcher (Prism etc.) or have several accounts.
$PlayerUuid = ""

# Where the vps/ folder of this project lives on the VPS
$PlaybookDir = "/opt/mc-sync/vps"

# Command to run ansible-playbook over SSH. If it's installed with pipx into ~/.local/bin,
# use the full path, e.g. "~/.local/bin/ansible-playbook" (non-interactive SSH may not load your PATH)
$AnsiblePlaybook = "ansible-playbook"

# Where pull-world.ps1 moves your old local copy before replacing it
$LocalBackupDir = "$MinecraftDir\world-backups"

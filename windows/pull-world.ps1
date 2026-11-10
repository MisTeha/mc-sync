<#
  Download a server's world from the VPS into your local saves folder, with you as the
  singleplayer player (your server inventory). Other players' data comes along too, so
  opening the world to LAN works for them.
  Only files that differ from your local copy are downloaded (rclone).
  The VPS side (copy the world, make you the host) is vps/world-pull.yml.
  Your current local copy is moved to $LocalBackupDir first, never deleted.

  Usage:  pull-world.ps1                                  (uses defaults from config.ps1)
          pull-world.ps1 -World "Other World" -Server creative
#>
param(
    [string]$World,
    [string]$Server
)

. "$PSScriptRoot\config.ps1"
. "$PSScriptRoot\common.ps1"
if (-not $World)  { $World  = $DefaultWorld }
if (-not $Server) { $Server = $DefaultServer }

$worldPath = Join-Path $SavesDir $World
$staging   = Join-Path $StagingDir $World

# Fail early, before touching the server, if something is missing or the world is in use
Assert-SyncSetup
if (Test-Path $worldPath) { Assert-WorldClosed $worldPath }
$player = Get-PlayerUuid

Write-Step "Preparing '$Server' on the VPS"
ssh $VpsHost "cd $PlaybookDir && $AnsiblePlaybook world-pull.yml -e server=$Server -e player=$player"
Assert-Ok "The server-side playbook"

Write-Step "Downloading changes"
# Download into a separate folder that starts as a copy of your local world: only the
# differences travel, and your world stays untouched if the download fails. A folder left
# over from a failed pull is simply reused.
if (-not (Test-Path $staging) -and (Test-Path $worldPath)) {
    New-Item -ItemType Directory -Force $StagingDir | Out-Null
    Copy-Item -LiteralPath $worldPath -Destination $staging -Recurse
}
Sync-World (Get-RemoteWorld $Server) $staging
Assert-Ok "Download"

Write-Step "Swapping it in as '$World'"
if (Test-Path $worldPath) {
    Assert-WorldClosed $worldPath
    New-Item -ItemType Directory -Force $LocalBackupDir | Out-Null
    $backup = Join-Path $LocalBackupDir "$World $(Get-Date -Format 'yyyy-MM-dd HHmmss')"
    Move-Item -LiteralPath $worldPath $backup
    Write-Host "    Old local copy moved to $backup"
}
Move-Item -LiteralPath $staging $worldPath

Write-Done "'$Server' is now in your saves as '$World'."

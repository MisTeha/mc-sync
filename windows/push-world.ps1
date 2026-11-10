<#
  Upload a local Minecraft world to the VPS and make it the server's world.
  Only files that changed since the last push or pull are uploaded (rclone).
  The VPS side (stop server if running, back up, replace, restart) is vps/world-push.yml.

  Usage:  push-world.ps1                                  (uses defaults from config.ps1)
          push-world.ps1 -World "Other World" -Server creative
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

Write-Step "Uploading changes in '$World'"
if (-not (Test-Path $worldPath)) { throw "World folder not found: $worldPath" }
Assert-SyncSetup
Assert-WorldClosed $worldPath
Sync-World $worldPath (Get-RemoteWorld $Server)
Assert-Ok "Upload"
Assert-WorldClosed $worldPath   # opened during the upload? Then the copy may be half-saved

Write-Step "Swapping the world in on '$Server'"
ssh $VpsHost "cd $PlaybookDir && $AnsiblePlaybook world-push.yml -e server=$Server"
Assert-Ok "The server-side playbook"

Write-Done "'$World' is now the world on '$Server'."

<#
  Pack a local Minecraft world, upload it to the VPS, and make it the server's world.
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

$worldPath   = Join-Path $SavesDir $World
$archiveName = "mc-world-$Server.tar.gz"
$remoteFile  = "/tmp/$archiveName"

Push-Location $env:TEMP   # work in TEMP with relative names, so scp doesn't read "C:" as a host name
try {
    Write-Step "Packing '$World'"
    if (-not (Test-Path $worldPath)) { throw "World folder not found: $worldPath" }
    Assert-WorldClosed $worldPath
    tar.exe -czf $archiveName -C $worldPath .
    Assert-Ok "Packing the world"

    Write-Step "Uploading to $VpsHost"
    scp $archiveName "${VpsHost}:$remoteFile"
    Assert-Ok "Upload"

    Write-Step "Swapping the world in on '$Server'"
    ssh $VpsHost "cd $PlaybookDir && $AnsiblePlaybook world-push.yml -e server=$Server -e archive=$remoteFile"
    Assert-Ok "The server-side playbook"

    Remove-Item $archiveName
    Write-Done "'$World' is now the world on '$Server'."
}
finally {
    Pop-Location
}

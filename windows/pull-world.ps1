<#
  Download a server's world from the VPS into your local saves folder, with you as the
  singleplayer player (your server inventory). Other players' data comes along too, so
  opening the world to LAN works for them.
  The VPS side (stop server if running, pack, restart) is vps/world-pull.yml.
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

$worldPath   = Join-Path $SavesDir $World
$archiveName = "mc-world-$Server.tar.gz"
$remoteFile  = "/tmp/$archiveName"

# Fail early, before touching the server, if the local world is in use
if (Test-Path $worldPath) { Assert-WorldClosed $worldPath }
$player = Get-PlayerUuid

Push-Location $env:TEMP   # work in TEMP with relative names, so scp doesn't read "C:" as a host name
try {
    Write-Step "Packing '$Server' on the VPS"
    ssh $VpsHost "cd $PlaybookDir && $AnsiblePlaybook world-pull.yml -e server=$Server -e archive=$remoteFile -e player=$player"
    Assert-Ok "The server-side playbook"

    Write-Step "Downloading"
    scp "${VpsHost}:$remoteFile" $archiveName
    Assert-Ok "Download"
    ssh $VpsHost "rm -f $remoteFile"

    Write-Step "Unpacking into '$World'"
    if (Test-Path $worldPath) {
        New-Item -ItemType Directory -Force $LocalBackupDir | Out-Null
        $backup = Join-Path $LocalBackupDir "$World $(Get-Date -Format 'yyyy-MM-dd HHmmss')"
        Move-Item $worldPath $backup
        Write-Host "    Old local copy moved to $backup"
    }
    New-Item -ItemType Directory $worldPath | Out-Null
    tar.exe -xzf $archiveName -C $worldPath
    Assert-Ok "Unpacking the world"

    Remove-Item $archiveName
    Write-Done "'$Server' is now in your saves as '$World'."
}
finally {
    Pop-Location
}

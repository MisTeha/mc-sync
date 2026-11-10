# Small helpers shared by push-world.ps1 and pull-world.ps1

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Done([string]$Message) {
    Write-Host "OK  $Message" -ForegroundColor Green
}

# External programs (tar, scp, ssh) don't throw on failure, so check their exit code.
function Assert-Ok([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

# Minecraft keeps session.lock open while a world is loaded. If we can't open it
# exclusively, the world is in use and copying it now would give a broken snapshot.
function Assert-WorldClosed([string]$WorldPath) {
    $lock = Join-Path $WorldPath "session.lock"
    if (-not (Test-Path $lock)) { return }
    try {
        [System.IO.File]::Open($lock, 'Open', 'ReadWrite', 'None').Close()
    } catch {
        throw "The world '$WorldPath' is open in Minecraft. Go back to the title screen (or quit) and try again."
    }
}

# Your Minecraft UUID: from config.ps1 if set, otherwise from the account that is
# active in the official launcher. Only the profile id is read from that file.
function Get-PlayerUuid {
    if ($PlayerUuid) { return $PlayerUuid }
    foreach ($name in "launcher_accounts_microsoft_store.json", "launcher_accounts.json") {
        $file = Join-Path $MinecraftDir $name
        if (-not (Test-Path $file)) { continue }
        $launcher = Get-Content $file -Raw | ConvertFrom-Json
        $account  = $launcher.accounts.($launcher.activeAccountLocalId)
        if ($account.minecraftProfile.id) {
            Write-Host "    Using launcher account '$($account.minecraftProfile.name)'"
            return $account.minecraftProfile.id
        }
    }
    throw "Couldn't find your Minecraft account in the launcher files. Set `$PlayerUuid in config.ps1."
}

function Assert-SyncSetup {
    if (-not (Get-Command $Rclone -ErrorAction SilentlyContinue)) {
        throw "rclone not found. Install it with 'winget install Rclone.Rclone', then open a new window."
    }
    # These must be set: with an empty $SyncSubdir the sync would target the whole server folder,
    # and a sync makes its target an exact copy, deleting everything else in it.
    foreach ($name in "McRoot", "SyncSubdir", "StagingDir") {
        if (-not (Get-Variable $name -ValueOnly -ErrorAction SilentlyContinue)) {
            throw "`$$name is not set. Copy the rclone settings from the repo's config.ps1 into yours."
        }
    }
}

# rclone's name for a server's sync folder on the VPS
function Get-RemoteWorld([string]$Server) {
    return ":sftp:$McRoot/$Server/$SyncSubdir"
}

# Make $To an exact copy of $From, transferring only files that differ (by size and modification
# time), several at once. rclone connects through your normal ssh, so the $VpsHost alias, keys
# and ~/.ssh/config all apply. session.lock is Minecraft's "world is open" marker: never synced.
#
# The --sftp-*sum-command none flags stop rclone from running commands on the VPS (it only uses
# SFTP). Windows' ssh.exe never tells a remote command that input has ended, so rclone's
# "md5sum" check would wait forever and the sync would hang at 0 bytes. SSH already protects the
# data in transit, and rclone still checks every file's size.
function Sync-World([string]$From, [string]$To) {
    & $Rclone sync $From $To `
        --sftp-ssh "ssh $VpsHost" --sftp-shell-type unix `
        --sftp-md5sum-command none --sftp-sha1sum-command none `
        --exclude session.lock `
        --transfers $RcloneTransfers `
        --progress --log-level ERROR
}

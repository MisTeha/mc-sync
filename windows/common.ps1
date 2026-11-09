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

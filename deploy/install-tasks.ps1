<#
  Registers the CarHub scheduled tasks.

      .\deploy\install-tasks.ps1              # both (needs an elevated shell)
      .\deploy\install-tasks.ps1 -BackupOnly  # just the weekly backup, no admin
      .\deploy\install-tasks.ps1 -Host 0.0.0.0 -Port 8000

  Two tasks:
    "CarHub Backup"  weekly, runs as you, no admin needed
    "CarHub Server"  at boot, runs as SYSTEM so it survives a reboot with
                      nobody logged in -- which is why it needs admin

  The XML files next to this script are the source of truth; this only fills in
  the machine-specific paths and hands them to Task Scheduler.
#>
[CmdletBinding()]
param(
    [switch]$BackupOnly,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectDir ".venv\Scripts\python.exe"
$deployDir = Join-Path $projectDir "deploy"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- preflight: fail loudly here rather than silently at 3am -----------------
if (-not (Test-Path $python)) {
    Write-Host "No virtual environment found at:" -ForegroundColor Red
    Write-Host "  $python"
    Write-Host "Run .\run.ps1 once first to create it." -ForegroundColor Yellow
    exit 1
}
foreach ($f in @("scripts\backup.py", "deploy\serve.py")) {
    if (-not (Test-Path (Join-Path $projectDir $f))) {
        Write-Host "Missing $f - is this the right folder?" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Project : $projectDir" -ForegroundColor DarkGray
Write-Host "Python  : $python" -ForegroundColor DarkGray

function Install-FromXml {
    param([string]$XmlFile, [string]$TaskName, [hashtable]$Tokens)

    $xml = Get-Content -Raw (Join-Path $deployDir $XmlFile)
    foreach ($key in $Tokens.Keys) {
        $xml = $xml.Replace("{{$key}}", $Tokens[$key])
    }

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Write-Host "Replacing existing task '$TaskName'..." -ForegroundColor DarkGray
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    # -Xml takes the definition as a string, which sidesteps the UTF-16 encoding
    # that schtasks.exe /XML insists on.
    $null = Register-ScheduledTask -TaskName $TaskName -Xml $xml
    Write-Host "  registered '$TaskName'" -ForegroundColor Green
}

$tokens = @{
    PROJECT_DIR = $projectDir
    PYTHON      = $python
    USER        = "$env:USERDOMAIN\$env:USERNAME"
}

# --- 1. weekly backup (no admin required) ------------------------------------
Write-Host ""
Write-Host "Installing weekly backup..." -ForegroundColor Cyan
Install-FromXml -XmlFile "CarHub-Backup.xml" -TaskName "CarHub Backup" -Tokens $tokens

# --- 2. server at boot (admin required) --------------------------------------
if (-not $BackupOnly) {
    if (-not (Test-Admin)) {
        Write-Host ""
        Write-Host "Skipping the server task: it runs as SYSTEM, which needs admin." -ForegroundColor Yellow
        Write-Host "Re-run this from an elevated PowerShell to install it:" -ForegroundColor Yellow
        Write-Host "  Start-Process powershell -Verb RunAs -ArgumentList '-File','$PSCommandPath'" -ForegroundColor DarkGray
    } else {
        Write-Host ""
        Write-Host "Installing server task (boot, SYSTEM)..." -ForegroundColor Cyan

        # The bind address lives in the machine environment because the task runs
        # as SYSTEM and never sees your user variables.
        [Environment]::SetEnvironmentVariable("PITBOX_HOST", $BindHost, "Machine")
        [Environment]::SetEnvironmentVariable("PITBOX_PORT", "$Port", "Machine")
        Write-Host "  PITBOX_HOST=$BindHost  PITBOX_PORT=$Port (machine-wide)" -ForegroundColor DarkGray

        Install-FromXml -XmlFile "CarHub-App.xml" -TaskName "CarHub Server" -Tokens $tokens

        if ($BindHost -eq "127.0.0.1") {
            Write-Host "  bound to localhost only - correct for Cloudflare Tunnel." -ForegroundColor DarkGray
            Write-Host "  For LAN/Tailscale re-run with -BindHost 0.0.0.0" -ForegroundColor DarkGray
        }
    }
}

Write-Host ""
Write-Host "Done. Useful commands:" -ForegroundColor Green
Write-Host "  Start-ScheduledTask -TaskName 'CarHub Backup'      # test the backup now"
Write-Host "  Start-ScheduledTask -TaskName 'CarHub Server'      # start without rebooting"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'CarHub Server'    # last run + result"
Write-Host "  Get-Content deploy\logs\pitbox.log -Tail 30 -Wait   # follow the log"
Write-Host "  .\deploy\uninstall-tasks.ps1                        # remove both"

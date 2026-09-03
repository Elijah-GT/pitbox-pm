<#
  Removes the CarHub scheduled tasks. Leaves your database, files and backups
  completely alone -- this only unregisters the schedule.

      .\deploy\uninstall-tasks.ps1
#>
$ErrorActionPreference = "Stop"

$removed = 0

# The "Pit Box" pair is the app's former name. Anyone who installed the tasks
# before the rename still has them registered under it, and a task nobody can
# find is a task that quietly keeps running -- so clean up both.
foreach ($name in @("CarHub Server", "CarHub Backup", "Pit Box Server", "Pit Box Backup")) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        continue
    }
    try {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "removed: $name" -ForegroundColor Green
        $removed++
    } catch {
        Write-Host "could not remove '$name' - try an elevated PowerShell." -ForegroundColor Yellow
        Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($removed -eq 0) {
    Write-Host "Nothing to remove -- no CarHub tasks were registered." -ForegroundColor DarkGray
}
# pitbox.db is the real filename and has not been renamed: the app is called
# CarHub now, but the database, the Fly app and the PITBOX_* settings keep
# their old identifiers so existing deployments keep working.
Write-Host "Your data is untouched: pitbox.db, storage\ and backups\ all remain." -ForegroundColor DarkGray

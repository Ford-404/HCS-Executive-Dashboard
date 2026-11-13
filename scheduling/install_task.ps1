# Registers the weekly Windows scheduled task (default Friday 7:00 AM, PC local time).
#   powershell -ExecutionPolicy Bypass -File scheduling\install_task.ps1 [-Day Friday] [-Time 07:00]
# Runs as the signed-in user (OneDrive sync needs the user session). Keep the user signed in
# (lock the screen rather than signing out) on the always-on PC.
param([string]$Day = "Friday", [string]$Time = "07:00", [string]$TaskName = "HCS National Active Project Summary")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction -Execute (Join-Path $root "scheduling\run_weekly.bat") -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Scheduled '$TaskName' every $Day at $Time. Run it now with:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Green

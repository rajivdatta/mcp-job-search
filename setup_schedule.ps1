<#
.SYNOPSIS
  Register a Windows Scheduled Task that runs the daily job search.

.DESCRIPTION
  Creates a task that runs run_daily_hidden.vbs (which calls run_daily.py via the
  project's venv, with no console window) once a day. Paths are taken from this
  script's own folder, so just run it from the repo directory after you've created
  the .venv and installed requirements.

.EXAMPLE
  .\setup_schedule.ps1                 # daily at 16:00 (4 PM)
  .\setup_schedule.ps1 -At "08:30"     # custom time
  .\setup_schedule.ps1 -TaskName "Job Search AM" -At "07:45"
#>
param(
  [string]$At = "16:00",
  [string]$TaskName = "MCP Job Search Daily"
)

$here = $PSScriptRoot
$vbs  = Join-Path $here "run_daily_hidden.vbs"
if (-not (Test-Path $vbs)) { throw "run_daily_hidden.vbs not found in $here" }
if (-not (Test-Path (Join-Path $here ".venv\Scripts\python.exe"))) {
  Write-Warning "No .venv found here. Create it and 'pip install -r requirements.txt' before the task will work."
}

$action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`"" -WorkingDirectory $here
$trigger  = New-ScheduledTaskTrigger -Daily -At ([DateTime]$At)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "Daily job search + resume match (mcp-job-search)" -Force | Out-Null

Write-Host "Registered '$TaskName' to run daily at $At."
Write-Host ("Next run: " + (Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)
Write-Host "Remove with: Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"

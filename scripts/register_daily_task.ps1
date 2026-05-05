param(
    [string]$TaskName = "StockDailyResearch",
    [string]$Time = "08:00",
    [string]$PythonExe = "",
    [switch]$NotifyTelegram
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunDailyScript = Join-Path $ProjectRoot "run_daily.py"

if (-not (Test-Path -LiteralPath $RunDailyScript)) {
    throw "run_daily.py was not found at $RunDailyScript"
}

if (-not $PythonExe) {
    $PythonExe = (& python -c "import sys; print(sys.executable)").Trim()
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable was not found at $PythonExe"
}

$null = [datetime]::ParseExact($Time, "HH:mm", $null)
$Arguments = "`"$RunDailyScript`""
if ($NotifyTelegram) {
    $Arguments = "$Arguments --notify-telegram"
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $Arguments `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Generate Stock Daily Research reports every morning." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath

param([string]$Model = 'sonnet', [string]$Role = 'review', [switch]$NewTask)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$runnerArgs = @((Join-Path $PSScriptRoot 'claude_runner.py'), '--model', $Model, '--role', $Role)
if ($NewTask) { $runnerArgs += '--new-task' }
Push-Location -LiteralPath $taskRoot
try { & python @runnerArgs; exit $LASTEXITCODE }
finally { Pop-Location }

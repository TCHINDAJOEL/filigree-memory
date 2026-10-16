<#
.SYNOPSIS
  OPTIONAL: start the Filigree capture monitor hidden at each Windows login (current user, no admin).

.DESCRIPTION
  Creates ONE shortcut in your per-user Startup folder. It runs
      pythonw.exe -m filigree --data-dir <DataDir> capture run
  with no console window. The monitor reads claude-tap traces and, unless disabled with
  "filigree capture fallback off", the local transcripts of directly launched Claude Code / Codex
  sessions; it must be running for either to be captured. Nothing is installed unless you answer
  yes (or pass -Yes).
  Remove it with uninstall-capture-startup.ps1. Filigree never edits agent configuration.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-capture-startup.ps1 -DataDir E:\MesMemoires
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$DataDir,
  [string]$Python = "",
  [switch]$Yes
)
$ErrorActionPreference = "Stop"
$dataPath = (Resolve-Path -LiteralPath $DataDir).Path
if (-not $Python) {
  $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
  if (-not $found) { throw "pythonw.exe introuvable dans PATH. Indiquez -Python avec le chemin complet de pythonw.exe." }
  $Python = $found.Source
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "Filigree capture.lnk"
# Every path is wrapped in double quotes so spaces cannot split an argument.
$arguments = '-m filigree --data-dir "' + $dataPath + '" capture run'
Write-Host "Un raccourci de démarrage va être créé pour l'utilisateur courant :"
Write-Host "  Fichier   : $shortcut"
Write-Host "  Commande  : `"$pythonPath`" $arguments"
Write-Host "  Effet     : le moniteur de capture s'exécute en arrière-plan à l'ouverture de session."
if (-not $Yes) {
  $answer = Read-Host "Installer ? (oui/non)"
  if ($answer -notin @("oui", "o", "yes", "y")) { Write-Host "Annulé. Rien n'a été installé."; exit 0 }
}
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $pythonPath
$link.Arguments = $arguments
$link.WorkingDirectory = $dataPath
$link.WindowStyle = 7
$link.Description = "Filigree - capture automatique (moniteur local)"
$link.Save()
Write-Host "Installé. Pour retirer : scripts\uninstall-capture-startup.ps1"

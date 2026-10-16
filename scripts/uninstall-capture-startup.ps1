<#
.SYNOPSIS
  Remove the optional Filigree capture startup shortcut created by install-capture-startup.ps1.
  It does not stop a running monitor: use `python -m filigree --data-dir <DataDir> capture stop`.
#>
[CmdletBinding()]
param([switch]$Yes)
$ErrorActionPreference = "Stop"
$shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "Filigree capture.lnk"
if (-not (Test-Path -LiteralPath $shortcut)) { Write-Host "Aucun raccourci Filigree dans le dossier de démarrage."; exit 0 }
Write-Host "Le raccourci suivant va être supprimé : $shortcut"
if (-not $Yes) {
  $answer = Read-Host "Supprimer ? (oui/non)"
  if ($answer -notin @("oui", "o", "yes", "y")) { Write-Host "Annulé."; exit 0 }
}
Remove-Item -LiteralPath $shortcut
Write-Host "Supprimé. Le moniteur en cours d'exécution, s'il existe, continue jusqu'à la commande capture stop."

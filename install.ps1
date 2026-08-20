# EEF node installer — runs the single-file bootstrap via PowerShell.
# One-liner on a fresh node:
#   powershell -nop -c "irm http://26.234.244.3:8081/api/node/install.ps1 | iex"
param(
    [string]$From = "http://26.234.244.3:8081",
    [string]$Name = $env:COMPUTERNAME,
    [string]$Psk = "",
    [string]$Dir = "C:\eefn"
)
$ErrorActionPreference = "Stop"
Write-Host "== EEF node installer =="
Write-Host "Downloading bootstrap from $From ..."
$boot = Join-Path $env:TEMP "bootstrap_eef.py"
Invoke-WebRequest -UseBasicParsing "$From/api/node/bootstrap.py" -OutFile $boot
if (-not $Psk) {
    $Psk = Read-Host "Enter coordinator PSK (node.psk)"
}
python $boot --from $From --name $Name --psk $Psk --dir $Dir
Write-Host "Node installed. Start it with:  python $Dir\run_node.py"

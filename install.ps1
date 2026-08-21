# EEF node installer — one-liner that provisions a brand-new node from GitHub.
#
#   powershell -nop -c "irm https://raw.githubusercontent.com/eepyfishy/eefn/main/install.ps1 | iex"
param(
    [string]$Psk = "",
    [string]$Dir = "C:\eefn"
)
$ErrorActionPreference = "Stop"
Write-Host "== EEF node installer (from GitHub) =="
$boot = Join-Path $env:TEMP "bootstrap_eef.py"
$rawBase = "https://raw.githubusercontent.com/eepyfishy/eefn/main"
Write-Host "Downloading bootstrap from $rawBase/tools/bootstrap_eef.py ..."
Invoke-WebRequest -UseBasicParsing "$rawBase/tools/bootstrap_eef.py" -OutFile $boot
if (-not $Psk) {
    $Psk = Read-Host "Enter coordinator PSK (node.psk)"
}
python $boot --psk $Psk --dir $Dir
Write-Host "Node installed. Start it with:  python $Dir\run_node.py  (or double-click start.cmd)"
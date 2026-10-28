# End-to-end check on Windows with Power BI Desktop installed:
#   rebuild the project -> open it in Power BI Desktop -> full refresh -> run the parity DAX queries
#   inside Power BI's engine -> compare every cell with the pandas reference.
# Writes parity/dax_results.json and parity/report.txt. Exit code 0 only when nothing differs.
param([int]$TimeoutSeconds = 240, [switch]$KeepOpen)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$cli = Join-Path $root ".venv\Scripts\recovery-bi.exe"
$runner = Join-Path $root "tools\DaxRunner\bin\Release\net9.0\DaxRunner.dll"

dotnet build tools\DaxRunner -c Release -v quiet -nologo | Out-Null
& $cli build --local
& $cli queries

Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$opened = Get-Date
Start-Process -FilePath (Join-Path $root "out\powerbi\RecoveryBI.pbip")

# Wait for the report window and for an engine started after we opened the file.
$port = $null
while (-not $port) {
    if (((Get-Date) - $opened).TotalSeconds -gt $TimeoutSeconds) { throw "Power BI Desktop did not load the project" }
    Start-Sleep -Seconds 2
    $win = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "RecoveryBI" }
    $file = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces",
                          "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces" `
                -Recurse -Filter msmdsrv.port.txt -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt $opened } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($win -and $file) { $port = (Get-Content $file.FullName -Encoding Unicode).Trim() }
}
Write-Output "Power BI Desktop engine on port $port"

dotnet $runner refresh $port
dotnet $runner query $port parity\queries.json parity\dax_results.json
& $cli parity | Tee-Object -FilePath parity\report.txt
$code = $LASTEXITCODE
if (-not $KeepOpen) { Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force }
exit $code

# Aktualizacja: pobiera najnowszą wersję (gałąź main) z GitHuba i nadpisuje pliki programu.
# Zachowuje: .venv (biblioteki, model językowy) oraz config\settings.json (Twoje ustawienia).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$zipUrl = 'https://github.com/MaciejKlepacki/mama_anonimizacja/archive/refs/heads/main.zip'

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Fail($t) {
    Write-Host ""; Write-Host "BŁĄD: $t" -ForegroundColor Red
    Read-Host "Naciśnij Enter, aby zamknąć"; exit 1
}

Write-Host "Anonimizacja dokumentów – aktualizacja" -ForegroundColor Green
Write-Host "Folder programu: $root"

Step "Zamykam uruchomioną aplikację (jeśli działa)"
try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 | Out-Null
      Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.launcher*' -or $_.CommandLine -like '*app.main*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } catch {}

Step "Pobieram najnowszą wersję"
$tmp = Join-Path $env:TEMP ("anonimizacja_update_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp 'main.zip'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
      Invoke-WebRequest -UseBasicParsing -Uri $zipUrl -OutFile $zip } catch { Fail "Nie udało się pobrać aktualizacji. Sprawdź połączenie z internetem." }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem -Path $tmp -Directory | Where-Object { $_.Name -like 'mama_anonimizacja-*' } | Select-Object -First 1
if (-not $src) { Fail "Pobrane archiwum ma nieoczekiwaną zawartość." }

Step "Nadpisuję pliki programu (ustawienia i środowisko zostają)"
Get-ChildItem -Path $src.FullName -Force | ForEach-Object {
    if ($_.Name -in @('.venv', '.git')) { return }
    $dest = Join-Path $root $_.Name
    if ($_.PSIsContainer) {
        if ($_.Name -eq 'config') {
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
            Copy-Item -Path (Join-Path $_.FullName 'default_settings.json') -Destination $dest -Force
        } else {
            if (Test-Path $dest) { Remove-Item -Path $dest -Recurse -Force }
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
        }
    } else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}
Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue

Step "Doinstalowuję brakujące biblioteki i odświeżam skrót"
& (Join-Path $PSScriptRoot 'install.ps1')

# Instalator: Python (jeśli brak) + biblioteki + model językowy + skrót na pulpicie.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Fail($t) {
    Write-Host ""; Write-Host "BŁĄD: $t" -ForegroundColor Red
    Read-Host "Naciśnij Enter, aby zamknąć"; exit 1
}

function Find-Python {
    foreach ($v in '3.12', '3.13', '3.11', '3.10') {
        try {
            $p = & py "-$v" -c "import sys;print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
        } catch {}
    }
    foreach ($d in 'Python312', 'Python313', 'Python311', 'Python310') {
        $c = Join-Path $env:LOCALAPPDATA "Programs\Python\$d\python.exe"
        if (Test-Path $c) { return $c }
    }
    return $null
}

Write-Host "Anonimizacja dokumentów – instalacja" -ForegroundColor Green
Write-Host "Wszystko zostanie zainstalowane w tym folderze: $root"

$py = Find-Python
if (-not $py) {
    Step "Instaluję Pythona (jednorazowo, ok. minuty)"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        $py = Find-Python
    }
    if (-not $py) {
        Start-Process "https://www.python.org/downloads/release/python-3128/"
        Fail "Nie udało się zainstalować Pythona automatycznie. Pobierz Python 3.12 ze strony, która się otworzyła, zainstaluj go i uruchom instalator ponownie."
    }
}
Write-Host "Python: $py"

Step "Przygotowuję środowisko"
$venv = Join-Path $root ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
$venvPyw = Join-Path $venv "Scripts\pythonw.exe"
if (-not (Test-Path $venvPy)) {
    & $py -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fail "Nie udało się utworzyć środowiska Pythona." }
}

Step "Instaluję biblioteki (kilka minut)"
& $venvPy -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Instalacja bibliotek nie powiodła się. Sprawdź połączenie z internetem i spróbuj ponownie." }

Step "Pobieram model językowy (ok. 500 MB, jednorazowo)"
& $venvPy -c "import spacy,sys; sys.exit(0 if spacy.util.is_package('pl_core_news_lg') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $venvPy -m spacy download pl_core_news_lg
    if ($LASTEXITCODE -ne 0) { Fail "Nie udało się pobrać modelu językowego. Sprawdź połączenie z internetem i spróbuj ponownie." }
}

Step "Tworzę skrót na pulpicie"
$ws = New-Object -ComObject WScript.Shell
function New-Link($path) {
    $l = $ws.CreateShortcut($path)
    $l.TargetPath = $venvPyw
    $l.Arguments = "-m app.launcher"
    $l.WorkingDirectory = $root
    $l.IconLocation = (Join-Path $root "windows\ikona.ico")
    $l.Description = "Anonimizacja dokumentów sądowych"
    $l.Save()
}
$name = "Anonimizacja dokumentów.lnk"
New-Link (Join-Path ([Environment]::GetFolderPath('Desktop')) $name)
New-Link (Join-Path ([Environment]::GetFolderPath('Programs')) $name)

Write-Host ""
Write-Host "Gotowe! Na pulpicie jest ikona „Anonimizacja dokumentów”." -ForegroundColor Green
Write-Host "Pierwsze uruchomienie może potrwać kilkanaście sekund (ładuje się model językowy)."
Start-Process -FilePath $venvPyw -ArgumentList "-m", "app.launcher" -WorkingDirectory $root
Start-Sleep -Seconds 4

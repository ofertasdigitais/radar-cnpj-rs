[CmdletBinding()]
param(
    [switch]$RedefinirAcesso
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectDir = $PSScriptRoot
$dataDir = Join-Path $projectDir "data"
$credentialFile = Join-Path $dataDir ".radar-credential.xml"
$sessionSecretFile = Join-Path $dataDir ".radar-session-secret"
$pidFile = Join-Path $dataDir ".radar-launcher-pids.json"
$serverOutLog = Join-Path $dataDir "radar-server.log"
$serverErrorLog = Join-Path $dataDir "radar-server-error.log"
$tunnelOutLog = Join-Path $dataDir "cloudflared.log"
$tunnelErrorLog = Join-Path $dataDir "cloudflared-error.log"
$localUrl = "http://127.0.0.1:8000"


function Get-RadarPython {
    $radarPythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $radarPythonPath -PathType Leaf) { return [pscustomobject]@{ Source = $radarPythonPath } }
    return Get-Command python -ErrorAction SilentlyContinue
}

function Write-Step([string]$Message) {
    Write-Host "`n>> $Message" -ForegroundColor Cyan
}

function Stop-RecordedProcesses {
    if (-not (Test-Path -LiteralPath $pidFile)) { return }

    try {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        foreach ($item in @(
            @{ Id = $record.tunnelPid; Name = "cloudflared" },
            @{ Id = $record.serverPid; Name = "python" }
        )) {
            if (-not $item.Id) { continue }
            $process = Get-Process -Id ([int]$item.Id) -ErrorAction SilentlyContinue
            if ($process -and $process.ProcessName -like "$($item.Name)*") {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    catch {
        Write-Warning "Nao foi possivel limpar uma execucao anterior: $($_.Exception.Message)"
    }
    finally {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-RadarCredential {
    if ($RedefinirAcesso -and (Test-Path -LiteralPath $credentialFile)) {
        Remove-Item -LiteralPath $credentialFile -Force
    }

    if (Test-Path -LiteralPath $credentialFile) {
        try {
            return Import-Clixml -LiteralPath $credentialFile
        }
        catch {
            Remove-Item -LiteralPath $credentialFile -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "`nPRIMEIRO ACESSO" -ForegroundColor Magenta
    Write-Host "Crie o acesso administrativo. A senha sera criptografada para este usuario do Windows."
    $username = Read-Host "Usuario (pressione Enter para usar admin)"
    if ([string]::IsNullOrWhiteSpace($username)) { $username = "admin" }

    $passwordConfirmed = $false
    do {
        $securePassword = Read-Host "Nova senha (minimo 10 caracteres)" -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try { $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }

        if ($plainPassword.Length -lt 10) {
            Write-Host "Use pelo menos 10 caracteres." -ForegroundColor Yellow
            continue
        }

        $secureConfirmation = Read-Host "Confirme a nova senha" -AsSecureString
        $confirmationPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureConfirmation)
        try { $plainConfirmation = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($confirmationPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($confirmationPointer) }

        if ($plainPassword -ne $plainConfirmation) {
            Write-Host "As senhas nao conferem. Digite novamente." -ForegroundColor Yellow
            continue
        }

        $passwordConfirmed = $true
    } while (-not $passwordConfirmed)

    $credential = New-Object System.Management.Automation.PSCredential($username, $securePassword)
    $credential | Export-Clixml -LiteralPath $credentialFile
    Write-Host "Acesso salvo para o usuario: $username" -ForegroundColor Green
    return $credential
}

function Get-PlainPassword([System.Management.Automation.PSCredential]$Credential) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Wait-ForLocalServer([System.Diagnostics.Process]$Process) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($Process.HasExited) {
            $details = if (Test-Path -LiteralPath $serverErrorLog) {
                Get-Content -LiteralPath $serverErrorLog -Raw
            } else { "sem detalhes" }
            throw "O Radar encerrou durante a inicializacao. $details"
        }

        try {
            Invoke-WebRequest -Uri "$localUrl/login" -UseBasicParsing -TimeoutSec 2 | Out-Null
            return
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "O Radar nao respondeu em $localUrl dentro do tempo esperado."
}

function Wait-ForTunnelUrl([System.Diagnostics.Process]$Process) {
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($Process.HasExited) {
            $details = if (Test-Path -LiteralPath $tunnelErrorLog) {
                Get-Content -LiteralPath $tunnelErrorLog -Raw
            } else { "sem detalhes" }
            throw "O Cloudflare Tunnel encerrou durante a inicializacao. $details"
        }

        foreach ($logPath in @($tunnelOutLog, $tunnelErrorLog)) {
            if (-not (Test-Path -LiteralPath $logPath)) { continue }
            $content = Get-Content -LiteralPath $logPath -Raw -ErrorAction SilentlyContinue
            if ([string]::IsNullOrWhiteSpace($content)) { continue }
            $match = [regex]::Match($content, "https://[a-z0-9-]+\.trycloudflare\.com")
            if ($match.Success) { return $match.Value }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "O Cloudflare nao informou o endereco publico dentro do tempo esperado."
}

$serverProcess = $null
$tunnelProcess = $null

try {
    Set-Location -LiteralPath $projectDir
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

    Write-Host "============================================" -ForegroundColor DarkRed
    Write-Host "       RADAR CNPJ RS - INICIALIZADOR" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor DarkRed

    $python = Get-RadarPython
    if (-not $python) { throw "Python nao foi encontrado no PATH do Windows." }
    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflared) { throw "cloudflared nao foi encontrado no PATH do Windows." }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir "app.py"))) {
        throw "app.py nao foi encontrado em $projectDir."
    }

    Stop-RecordedProcesses

    $portOwner = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($portOwner) {
        throw "A porta 8000 ja esta sendo usada pelo processo $($portOwner.OwningProcess). Feche a execucao antiga do Radar e tente novamente."
    }

    $credential = Get-RadarCredential
    $plainPassword = Get-PlainPassword $credential

    $env:RADAR_ADMIN_USER = $credential.UserName
    $env:RADAR_ADMIN_PASSWORD = $plainPassword
    # Reset revokes persisted sessions too; all launch paths now use this key.
    if ($RedefinirAcesso -or -not (Test-Path -LiteralPath $sessionSecretFile)) {
        [System.IO.File]::WriteAllText($sessionSecretFile, ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")))
    }
    $env:RADAR_SESSION_SECRET = (Get-Content -LiteralPath $sessionSecretFile -Raw).Trim()
    $env:RADAR_SECURE_COOKIES = "1"
    # Este inicializador abre um túnel público: não herdar o modo de desenvolvimento.
    $env:RADAR_ENV = 'production'
    $env:RADAR_ALLOW_REGISTRATION = '0'
    $env:RADAR_HOST = "127.0.0.1"
    $env:RADAR_PORT = "8000"
    $env:PYTHONUNBUFFERED = "1"

    foreach ($logPath in @($serverOutLog, $serverErrorLog, $tunnelOutLog, $tunnelErrorLog)) {
        Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
    }

    Write-Step "Iniciando o Radar em $localUrl"
    $serverProcess = Start-Process -FilePath $python.Source `
        -ArgumentList @("app.py") `
        -WorkingDirectory $projectDir `
        -RedirectStandardOutput $serverOutLog `
        -RedirectStandardError $serverErrorLog `
        -WindowStyle Hidden `
        -PassThru
    Wait-ForLocalServer $serverProcess
    Write-Host "Radar iniciado." -ForegroundColor Green

    Write-Step "Criando o endereco publico pelo Cloudflare"
    $tunnelProcess = Start-Process -FilePath $cloudflared.Source `
        -ArgumentList @("tunnel", "--url", $localUrl, "--no-autoupdate") `
        -WorkingDirectory $projectDir `
        -RedirectStandardOutput $tunnelOutLog `
        -RedirectStandardError $tunnelErrorLog `
        -WindowStyle Hidden `
        -PassThru

    @{ serverPid = $serverProcess.Id; tunnelPid = $tunnelProcess.Id } |
        ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

    $publicUrl = Wait-ForTunnelUrl $tunnelProcess

    Write-Host "`n============================================" -ForegroundColor DarkRed
    Write-Host "RADAR DISPONIVEL" -ForegroundColor White
    Write-Host "Local:   $localUrl" -ForegroundColor Gray
    Write-Host "Publico: $publicUrl" -ForegroundColor Cyan
    Write-Host "Usuario: $($credential.UserName)" -ForegroundColor Gray
    Write-Host "============================================" -ForegroundColor DarkRed
    Write-Host "`nO endereco publico e temporario. Mantenha esta janela aberta."
    Write-Host "Pressione Enter para desligar o Radar e o tunel."

    Start-Process $publicUrl
    Read-Host | Out-Null
}
catch {
    Write-Host "`nERRO: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Consulte os arquivos de log na pasta data, se necessario." -ForegroundColor Yellow
    Read-Host "Pressione Enter para fechar" | Out-Null
}
finally {
    Write-Host "`nEncerrando Radar e Cloudflare..." -ForegroundColor Yellow
    foreach ($process in @($tunnelProcess, $serverProcess)) {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $env:RADAR_ADMIN_PASSWORD = $null
    $env:RADAR_SESSION_SECRET = $null
}

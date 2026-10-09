[CmdletBinding()]
param(
    [switch]$ComCloudflare,
    [switch]$Instalar,
    [switch]$Desinstalar,
    [switch]$Parar,
    [switch]$RecarregarServidor
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectDir = $PSScriptRoot
$dataDir = Join-Path $projectDir "data"
$pidFile = Join-Path $dataDir ".radar-auto-pids.json"
$statusFile = Join-Path $dataDir ".radar-auto-status.json"
$publicUrlFile = Join-Path $dataDir "public-url.txt"
$credentialFile = Join-Path $dataDir ".radar-credential.xml"
$sessionSecretFile = Join-Path $dataDir ".radar-session-secret"
$serverOutLog = Join-Path $dataDir "radar-server.log"
$serverErrorLog = Join-Path $dataDir "radar-server-error.log"
$tunnelOutLog = Join-Path $dataDir "cloudflared.log"
$tunnelErrorLog = Join-Path $dataDir "cloudflared-error.log"
$localUrl = "http://127.0.0.1:8000"
$taskName = "Radar CNPJ RS - Inicio automatico"
$runValueName = "Radar CNPJ RS"

function Write-Status([string]$Status, [string]$Message, [string]$PublicUrl = "") {
    $payload = [ordered]@{
        status = $Status
        message = $Message
        localUrl = $localUrl
        publicUrl = $PublicUrl
        updatedAt = (Get-Date).ToString("o")
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
    if ($PublicUrl) {
        "$PublicUrl`r`nAtualizado em $($payload.updatedAt)" | Set-Content -LiteralPath $publicUrlFile -Encoding UTF8
    }
    elseif (Test-Path -LiteralPath $publicUrlFile) {
        Remove-Item -LiteralPath $publicUrlFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-PlainPassword([System.Management.Automation.PSCredential]$Credential) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Stop-RecordedProcesses {
    if (-not (Test-Path -LiteralPath $pidFile)) { return }
    try {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        foreach ($item in @(
            @{ Id = $record.tunnelPid; Pattern = "cloudflared" },
            @{ Id = $record.serverPid; Pattern = "app.py" }
        )) {
            if (-not $item.Id) { continue }
            $process = Get-Process -Id ([int]$item.Id) -ErrorAction SilentlyContinue
            if (-not $process) { continue }
            $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($process.ProcessName -like "$($item.Pattern)*" -or $commandLine -match [regex]::Escape($item.Pattern)) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForLocalServer([System.Diagnostics.Process]$Process) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($Process.HasExited) {
            $details = if (Test-Path -LiteralPath $serverErrorLog) { Get-Content -LiteralPath $serverErrorLog -Raw } else { "sem detalhes" }
            throw "O Radar encerrou durante a inicializacao. $details"
        }
        try {
            Invoke-WebRequest -Uri "$localUrl/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null
            return
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    throw "O Radar nao respondeu em $localUrl dentro do tempo esperado."
}

function Wait-ForTunnelUrl([System.Diagnostics.Process]$Process) {
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($Process.HasExited) {
            $details = if (Test-Path -LiteralPath $tunnelErrorLog) { Get-Content -LiteralPath $tunnelErrorLog -Raw } else { "sem detalhes" }
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

function Install-AutoStart {
    $scriptPath = Join-Path $projectDir "Radar-AutoStart.ps1"
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    if ($ComCloudflare) { $arguments += " -ComCloudflare" }
    $method = "Agendador de Tarefas"
    try {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description "Inicia o Radar CNPJ RS automaticamente ao entrar no Windows." -Force | Out-Null
    }
    catch {
        # Alguns Windows bloqueiam a criacao de tarefas sem elevacao. O Run do
        # usuario e uma alternativa equivalente, sem pedir senha de administrador.
        $method = "Inicializacao do usuario"
        $runCommand = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
        if ($ComCloudflare) { $runCommand += " -ComCloudflare" }
        New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
        New-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $runValueName -Value $runCommand -PropertyType String -Force | Out-Null
    }
    Write-Host "Inicializacao automatica instalada para este usuario do Windows ($method)." -ForegroundColor Green
    if ($ComCloudflare) {
        Write-Host "Modo Cloudflare ativado. O endereco publico pode mudar a cada reinicio." -ForegroundColor Yellow
    }
}

try {
    Set-Location -LiteralPath $projectDir
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

    if ($Desinstalar) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $runValueName -ErrorAction SilentlyContinue
        Stop-RecordedProcesses
        Write-Status "stopped" "Inicializacao automatica removida."
        Write-Host "Inicializacao automatica removida." -ForegroundColor Yellow
        exit 0
    }

    if ($Instalar) {
        Install-AutoStart
        # No Windows PowerShell, uma lista de strings com "-ComCloudflare"
        # pode ser interpretada como argumento posicional ao chamar o proprio
        # script. Passe a chave de forma explicita para preservar o switch.
        if ($ComCloudflare) {
            & $PSCommandPath -ComCloudflare
        }
        else {
            & $PSCommandPath
        }
        exit $LASTEXITCODE
    }

    if ($Parar) {
        Stop-RecordedProcesses
        Write-Status "stopped" "Radar encerrado pelo usuario."
        Write-Host "Radar encerrado." -ForegroundColor Yellow
        exit 0
    }

    if ($RecarregarServidor) {
        if (-not (Test-Path -LiteralPath $pidFile)) { throw "O registro dos processos do Radar nao foi encontrado." }
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $serverProcess = Get-Process -Id ([int]$record.serverPid) -ErrorAction SilentlyContinue
        # O inicializador interativo usa outro registro. Só adote o processo
        # que também possui a porta local do Radar; não mate um PID antigo.
        if (-not $serverProcess) {
            $launcherRecordPath = Join-Path $dataDir '.radar-launcher-pids.json'
            if (Test-Path -LiteralPath $launcherRecordPath) {
                $launcherRecord = Get-Content -LiteralPath $launcherRecordPath -Raw | ConvertFrom-Json
                $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($listener -and $listener.OwningProcess -eq [int]$launcherRecord.serverPid) {
                    $record = $launcherRecord
                    $record | Add-Member -NotePropertyName publicUrl -NotePropertyValue '' -Force
                    $serverProcess = Get-Process -Id ([int]$record.serverPid) -ErrorAction SilentlyContinue
                }
            }
        }
        if (-not $serverProcess) { throw "O processo atual do Radar nao foi encontrado." }
        $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($serverProcess.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($commandLine -notmatch "app\.py") { throw "O processo registrado nao corresponde ao Radar; recarga cancelada." }

        $tunnelPid = [int]$record.tunnelPid
        $tunnelProcess = if ($tunnelPid) { Get-Process -Id $tunnelPid -ErrorAction SilentlyContinue } else { $null }
        if ($tunnelProcess -and -not $record.publicUrl) {
            foreach ($existingLog in @($tunnelOutLog,$tunnelErrorLog)) {
                if (Test-Path -LiteralPath $existingLog) {
                    $existingContent = Get-Content -LiteralPath $existingLog -Raw
                    if ([string]::IsNullOrEmpty($existingContent)) { continue }
                    $existingMatches = [regex]::Matches($existingContent,'https://[a-z0-9-]+\.trycloudflare\.com')
                    if ($existingMatches.Count) { $record.publicUrl = $existingMatches[$existingMatches.Count-1].Value }
                }
            }
        }
        Stop-Process -Id $serverProcess.Id -Force
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }

        $credential = Import-Clixml -LiteralPath $credentialFile
        $env:RADAR_ADMIN_USER = $credential.UserName
        $env:RADAR_ADMIN_PASSWORD = Get-PlainPassword $credential
        $env:RADAR_SESSION_SECRET = (Get-Content -LiteralPath $sessionSecretFile -Raw).Trim()
        $env:RADAR_SECURE_COOKIES = if ($tunnelProcess) { "1" } else { "0" }
        $env:RADAR_ENV = if ($tunnelProcess) { 'production' } else { 'development' }
        # Ate o estado comercial estar isolado e validado por conta, o endereco
        # publico deve aceitar somente usuarios ja provisionados.
        $env:RADAR_ALLOW_REGISTRATION = "0"
        $env:RADAR_HOST = "127.0.0.1"
        $env:RADAR_PORT = "8000"
        $env:RADAR_AUTO_SYNC = "1"
        $env:RADAR_SERPRO_AUTO_MONITOR = "1"
        $env:RADAR_DATA_DIR = $dataDir
        $env:PYTHONUNBUFFERED = "1"

        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { throw "Python nao foi encontrado no PATH do Windows." }
        $newServer = Start-Process -FilePath $python.Source -ArgumentList @("app.py") -WorkingDirectory $projectDir -RedirectStandardOutput $serverOutLog -RedirectStandardError $serverErrorLog -WindowStyle Hidden -PassThru
        $record.serverPid = $newServer.Id
        $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
        Wait-ForLocalServer $newServer
        Write-Status "running" "Radar atualizado sem reiniciar o tunel." $record.publicUrl
        Write-Host "Radar atualizado. Cloudflare mantido no processo $tunnelPid." -ForegroundColor Green
        exit 0
    }

    Stop-RecordedProcesses
    $portOwner = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($portOwner) {
        try {
            Invoke-WebRequest -Uri "$localUrl/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Status "already-running" "O Radar ja estava em execucao."
            exit 0
        }
        catch {
            throw "A porta 8000 ja esta sendo usada pelo processo $($portOwner.OwningProcess)."
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw "Python nao foi encontrado no PATH do Windows." }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir "app.py"))) { throw "app.py nao foi encontrado em $projectDir." }
    if (-not (Test-Path -LiteralPath $credentialFile)) { throw "Execute INICIAR RADAR.cmd uma vez para criar o acesso administrativo." }

    $credential = Import-Clixml -LiteralPath $credentialFile
    $plainPassword = Get-PlainPassword $credential
    if (-not (Test-Path -LiteralPath $sessionSecretFile)) {
        ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")) | Set-Content -LiteralPath $sessionSecretFile -Encoding ASCII
    }

    $env:RADAR_ADMIN_USER = $credential.UserName
    $env:RADAR_ADMIN_PASSWORD = $plainPassword
    $env:RADAR_SESSION_SECRET = (Get-Content -LiteralPath $sessionSecretFile -Raw).Trim()
    $env:RADAR_SECURE_COOKIES = if ($ComCloudflare) { "1" } else { "0" }
    $env:RADAR_ENV = if ($ComCloudflare) { 'production' } else { 'development' }
    $env:RADAR_HOST = "127.0.0.1"
    $env:RADAR_PORT = "8000"
    $env:RADAR_AUTO_SYNC = "1"
    $env:RADAR_SERPRO_AUTO_MONITOR = "1"
    # Evita que um visitante do endereco publico crie uma conta apontando para
    # o mesmo espaco comercial das contas existentes.
    $env:RADAR_ALLOW_REGISTRATION = "0"
    $env:RADAR_DATA_DIR = $dataDir
    $env:PYTHONUNBUFFERED = "1"

    $serverProcess = Start-Process -FilePath $python.Source -ArgumentList @("app.py") -WorkingDirectory $projectDir -RedirectStandardOutput $serverOutLog -RedirectStandardError $serverErrorLog -WindowStyle Hidden -PassThru
    $tunnelProcess = $null
    $record = [ordered]@{ serverPid = $serverProcess.Id; tunnelPid = 0; publicUrl = ""; startedAt = (Get-Date).ToString("o") }
    $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
    Wait-ForLocalServer $serverProcess

    $publicUrl = ""
    if ($ComCloudflare) {
        $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
        if (-not $cloudflared) { throw "cloudflared nao foi encontrado no PATH do Windows." }
        # Os logs sao reutilizados entre inicializacoes. Limpe-os antes de
        # procurar a URL para nao reaproveitar um endereco de Quick Tunnel que
        # ja expirou em uma execucao anterior.
        foreach ($logPath in @($tunnelOutLog, $tunnelErrorLog)) {
            if (Test-Path -LiteralPath $logPath) {
                Clear-Content -LiteralPath $logPath -ErrorAction SilentlyContinue
            }
        }
        # Nesta rede o pre-check do cloudflared confirma HTTP/2 e aponta QUIC
        # degradado na porta 7844. Fixar HTTP/2 evita reconexoes por timeout.
        $tunnelProcess = Start-Process -FilePath $cloudflared.Source -ArgumentList @("tunnel", "--protocol", "http2", "--url", $localUrl, "--no-autoupdate") -WorkingDirectory $projectDir -RedirectStandardOutput $tunnelOutLog -RedirectStandardError $tunnelErrorLog -WindowStyle Hidden -PassThru
        $record.tunnelPid = $tunnelProcess.Id
        $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
        $publicUrl = Wait-ForTunnelUrl $tunnelProcess
        $record.publicUrl = $publicUrl
        $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
    }

    Write-Status "running" "Radar em execucao." $publicUrl
    Write-Host "Radar iniciado em $localUrl" -ForegroundColor Green
    if ($publicUrl) { Write-Host "Endereco Cloudflare: $publicUrl" -ForegroundColor Cyan }
}
catch {
    Write-Status "error" $_.Exception.Message
    Write-Error $_.Exception.Message
    exit 1
}
finally {
    $env:RADAR_ADMIN_PASSWORD = $null
    $env:RADAR_SESSION_SECRET = $null
}

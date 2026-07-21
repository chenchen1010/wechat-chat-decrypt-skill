$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptDir
$runtimeRoot = if ($env:WECHAT_CHAT_DECRYPT_RUNTIME) { $env:WECHAT_CHAT_DECRYPT_RUNTIME } else { Join-Path $env:LOCALAPPDATA 'wechat-chat-decrypt' }
$venv = Join-Path $runtimeRoot 'venv'
$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) { $pythonArgs = @('-3') } else { $python = Get-Command python -ErrorAction SilentlyContinue; $pythonArgs = @() }
if (-not $python) { throw 'Python 3.10 or newer is required. Install Python and rerun scripts\bootstrap.ps1.' }
& $python.Source @pythonArgs -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) { & $python.Source @pythonArgs -m venv $venv }
$venvPython = Join-Path $venv 'Scripts\python.exe'
& $venvPython -m pip install --disable-pip-version-check --quiet (Join-Path $skillRoot 'vendor\wechat-cli')
& $venvPython -c 'from Crypto.Cipher import AES; import zstandard, wechat_cli; assert AES.block_size == 16'
Write-Output ('{"ok":true,"runtime":"' + $runtimeRoot + '","wechat_cli":"' + (Join-Path $venv 'Scripts\wechat-cli.exe') + '"}')

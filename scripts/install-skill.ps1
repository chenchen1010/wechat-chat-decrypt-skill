$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Split-Path -Parent $scriptDir
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$destination = Join-Path $codexHome 'skills\wechat-chat-decrypt'
New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
if ((Resolve-Path $source).Path -ne $destination) {
  if (Test-Path -LiteralPath $destination) { Move-Item -LiteralPath $destination -Destination ($destination + '.backup.' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
  Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}
& (Join-Path $destination 'scripts\bootstrap.ps1')
Write-Output ('{"ok":true,"skill":"' + $destination + '"}')

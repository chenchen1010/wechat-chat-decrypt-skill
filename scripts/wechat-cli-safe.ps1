$ErrorActionPreference = 'Stop'
$runtimeRoot = if ($env:WECHAT_CHAT_DECRYPT_RUNTIME) { $env:WECHAT_CHAT_DECRYPT_RUNTIME } else { Join-Path $env:LOCALAPPDATA 'wechat-chat-decrypt' }
$cli = Join-Path $runtimeRoot 'venv\Scripts\wechat-cli.exe'
if (-not (Test-Path -LiteralPath $cli)) { throw 'Skill runtime is not installed. Run scripts\bootstrap.ps1 first.' }
$session = Join-Path ([IO.Path]::GetTempPath()) ('wechat-cli-safe.' + [IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $session -Force | Out-Null
try {
  $env:TMP = $session
  $env:TEMP = $session
  $env:WECHAT_CLI_CACHE_DIR = Join-Path $session 'cache'
  New-Item -ItemType Directory -Path $env:WECHAT_CLI_CACHE_DIR -Force | Out-Null
  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & $cli @args
  $cliExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorAction
  if ($cliExitCode -ne 0) { exit $cliExitCode }
} finally {
  if (Test-Path -LiteralPath $session) { Remove-Item -LiteralPath $session -Recurse -Force -ErrorAction SilentlyContinue }
}

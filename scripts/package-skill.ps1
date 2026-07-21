$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Split-Path -Parent $scriptDir
$output = if ($args.Count -gt 0) { [IO.Path]::GetFullPath($args[0]) } else { Join-Path (Split-Path -Parent $source) 'wechat-chat-decrypt-skill.zip' }
if ($output.StartsWith((Resolve-Path $source).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Output zip must be outside the skill directory.' }
$stage = Join-Path ([IO.Path]::GetTempPath()) ('wechat-chat-decrypt-package.' + [IO.Path]::GetRandomFileName())
$stageRoot = Join-Path $stage (Split-Path -Leaf $source)
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
  Copy-Item -LiteralPath $source -Destination $stageRoot -Recurse -Force
  Get-ChildItem -LiteralPath $stageRoot -Recurse -Force | Where-Object { $_.FullName -match '\\(\.git|__pycache__|build)(\\|$)' -or $_.Extension -in '.pyc','.zip' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Compress-Archive -Path $stageRoot -DestinationPath $output -Force
  Write-Output ('{"ok":true,"package":"' + $output + '"}')
} finally { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }

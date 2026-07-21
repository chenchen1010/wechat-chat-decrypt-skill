# WeChat Chat Decrypt Skill

让 Codex 在用户自己的电脑上本地解密并查询微信聊天数据库。数据、密钥和导出内容不会上传。

## 平台

- Windows 10/11：使用仓库内置的 Python 内存扫描器。已验证 Weixin 4.1.8.101（`xwechat_files\<wxid>\db_storage`，SQLCipher v4），并在提取前强制检查版本与登录状态。
- Apple Silicon macOS：保留已验证的 WeChat 4.1.8 build 37261 流程。
- Linux、Intel macOS 和 iPhone 备份不在当前支持范围内。

注意：较新的 Windows Weixin 版本可能已经改变进程内存中的密钥表示。Skill 会报告检测到的版本并停止，不会猜测密钥；请安装并使用已验证的 4.1.8.101。Skill 还可以用 Windows 防火墙精确阻断 `WeixinUpdate.exe` 的出站更新连接，避免降级后自动升级。

## Windows 安装

在 PowerShell 中运行：

```powershell
git clone https://github.com/chenchen1010/wechat-chat-decrypt-skill.git
& .\wechat-chat-decrypt-skill\scripts\install-skill.ps1
```

安装后重启 Codex。首次使用时：

```powershell
$SkillDir = Join-Path $env:USERPROFILE '.codex\skills\wechat-chat-decrypt'
$Py = Join-Path $env:LOCALAPPDATA 'wechat-chat-decrypt\venv\Scripts\python.exe'
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') preflight
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') prepare-probe
# 使用上一步 JSON 返回的 manifest 路径
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') extract-keys --manifest '<manifest path>'
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') verify
```

保持微信处于已登录状态。若出现 `OpenProcess`/`ReadProcessMemory` 权限错误，让 Codex、PowerShell 和微信处于相同权限级别；仅在 Windows 明确拒绝访问时使用管理员 PowerShell。不要关闭 Defender 或内核保护。

查询必须使用安全包装器，它会为每次命令创建临时解密缓存并在退出时删除：

```powershell
& (Join-Path $SkillDir 'scripts\wechat-cli-safe.ps1') sessions --limit 20 --format text
& (Join-Path $SkillDir 'scripts\wechat-cli-safe.ps1') history '联系人' --limit 50 --format text
```

## 安全边界

仅处理当前用户拥有或明确获授权的数据；不打印 `all_keys.json`，不把聊天原文、密钥或凭据提交到 Git。运行 `cleanup --include-probes` 可清理残留临时目录。

详细流程见 [SKILL.md](SKILL.md)，平台差异见 [references/compatibility.md](references/compatibility.md)。

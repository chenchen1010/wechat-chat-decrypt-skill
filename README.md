# WeChat Chat Decrypt Skill

让 Codex 在你的 Windows 或 Apple Silicon Mac 上，直接处理你自己电脑里的微信聊天记录：解密、验证、查询和导出都在本机完成，聊天数据库和密钥不会上传。

## 给 Claude Code / Codex 的一键提示词

这个仓库是给 AI 编程助手执行的。下面这段提示词可以直接复制；具体平台、版本、降级、更新防护和验证步骤都已经写在仓库的 `SKILL.md` 里，不需要在提示词中重复。

```text
请帮我安装并使用这个仓库的 WeChat Chat Decrypt Skill：
https://github.com/chenchen1010/wechat-chat-decrypt-skill.git

请按仓库 SKILL.md 的流程完成安装、bootstrap、preflight、版本兼容处理、必要的更新防护、密钥提取和验证。只处理我本人拥有或明确授权的本机微信数据，保持本地处理，不要上传或打印密钥、all_keys.json、聊天数据库和完整聊天原文。先完成安装和验证，暂时不要查询聊天内容；完成后告诉我版本、兼容性、验证结果和下一步用法。
```

完整的分步骤版本见 [INSTALL_PROMPT.md](INSTALL_PROMPT.md)。

CTA：**把你的本地微信记录交给 Codex，变成可检索、可整理的个人资料库；不上传原始聊天，不需要你手动研究密钥和数据库。**

## 你能得到什么

- **Windows**：支持已验证的 Weixin `4.1.8.101`，可查询本机聊天、联系人和群聊记录。
- **Apple Silicon Mac**：支持已验证的 WeChat `4.1.8 build 37261`。
- **安全流程**：先检查版本和登录状态，再提取密钥；解密结果会做 HMAC 和 SQLite 完整性验证。
- **防止反复升级**：Windows 可以只阻断 `WeixinUpdate.exe`，不影响微信正常聊天网络。
- **适合交给 Codex**：安装一次后，直接用自然语言说“查某个联系人上周的聊天”即可。

## 适合谁

这是给希望让 Codex 帮忙整理自己微信记录的人使用的 Skill，例如：

- 查找某个联系人或群聊在指定日期的消息；
- 从本地聊天记录中寻找关键词、待办和承诺；
- 将指定范围的聊天导出为 Markdown，继续交给 Codex 总结；
- 在不上传原始聊天数据的前提下，建立个人知识资料。

## 先看清楚：当前支持范围

| 电脑 | 已验证微信版本 | 数据位置 | 结论 |
| --- | --- | --- | --- |
| Windows 10/11 | Weixin `4.1.8.101` | `xwechat_files\<wxid>\db_storage` | 可解密、验证、查询 |
| Apple Silicon Mac | WeChat `4.1.8 build 37261` | 微信沙盒目录 | 可解密、验证、查询 |
| 其他版本 | 未验证 | — | Skill 会停止，不猜测密钥 |

经典 WeChat `3.9.x` 已不在支持范围内；Windows 只走现代 Weixin `4.1.8.101` 路径。

## Apple Silicon Mac：从安装到第一次查询

### 1. 安装 Skill

在终端中运行：

```bash
git clone https://github.com/chenchen1010/wechat-chat-decrypt-skill.git
bash ./wechat-chat-decrypt-skill/scripts/install-skill.sh
```

安装后重启 Codex。Skill 会创建独立的本地运行环境，不会安装全局 `wechat-cli`。

### 2. 使用已验证的 WeChat 版本

当前 Mac 已验证版本是 **WeChat 4.1.8 build 37261**。如果检测到更新版本，先备份微信数据目录，再退出微信：

```text
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files
```

从腾讯 CDN 下载已验证的 DMG：

- [下载 WeChat 4.1.8 build 37261](https://dldir1v6.qq.com/weixin/Universal/Mac/xWeChatMac_universal_4.1.8.100_37261.dmg)

下载只是入口，安装前仍要验证文件是否为腾讯签名的正确版本。

### 3. 验证并安装 DMG

```bash
SKILL_DIR="$HOME/.codex/skills/wechat-chat-decrypt"
PY="$HOME/.local/share/wechat-chat-decrypt/venv/bin/python"

"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" inspect-dmg \
  --dmg "/absolute/path/to/xWeChatMac_universal_4.1.8.100_37261.dmg"
```

只有当返回结果中的 `accepted` 为 `true`，并且版本、Tencent Team ID、签名和 arm64 检查全部通过，才继续安装：

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" install-dmg \
  --dmg "/absolute/path/to/xWeChatMac_universal_4.1.8.100_37261.dmg" \
  --confirm-data-backup \
  --confirm-wechat-closed
```

安装后重新打开 WeChat、登录，然后执行本机签名步骤，让 Codex 可以读取已登录进程：

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" resign
```

### 4. 运行预检、提取并验证

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" preflight
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" prepare-probe \
  --db-dir "/absolute/path/from/preflight/db_storage"
```

把 JSON 输出里的 `manifest` 路径填入：

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" extract-keys \
  --manifest "/private/tmp/wechat-chat-decrypt-probe-.../manifest.json"
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" verify
```

### 5. 防止 Mac 自动升级并开始查询

如需保持已验证版本，在明确确认后运行：

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard block
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard status
```

然后通过安全包装器查询：

```bash
"$SKILL_DIR/scripts/wechat-cli-safe" sessions --limit 20 --format text
"$SKILL_DIR/scripts/wechat-cli-safe" history "联系人姓名" --limit 50 --format text
"$SKILL_DIR/scripts/wechat-cli-safe" search "关键词" --chat "群聊名称" --format text
```

## Windows：从安装到第一次查询

### 1. 安装 Skill

在 PowerShell 中运行：

```powershell
git clone https://github.com/chenchen1010/wechat-chat-decrypt-skill.git
& .\wechat-chat-decrypt-skill\scripts\install-skill.ps1
```

安装脚本会把 Skill 放到 `%USERPROFILE%\.codex\skills\wechat-chat-decrypt`，并创建独立运行环境，不会安装全局 `wechat-cli`。安装后重启 Codex。

### 2. 使用已验证的微信版本

如果 `preflight` 显示版本高于 `4.1.8.101`，先退出微信并备份：

```text
%USERPROFILE%\xwechat_files
```

官方安装包：

- [腾讯 CDN 下载 Weixin 4.1.8.101](https://dldir1v6.qq.com/weixin/Universal/Windows/WeChatWin_4.1.8.exe)
- SHA-256：`0c4091f5480231f0805c18c845715e36a404f7447ea61fa7c8c33fbfd5707e9b`
- [版本归档与校验信息](https://github.com/cscnk52/wechat-windows-versions/releases/tag/v4.1.8.101)

这里的真实版本号是 `4.1.8.101`；安装文件名中的 `4.1.8` 是腾讯 CDN 的命名方式。

### 3. 阻止微信自动升级

降级安装并登录后，在 PowerShell 中运行：

```powershell
$SkillDir = Join-Path $env:USERPROFILE '.codex\skills\wechat-chat-decrypt'
$Py = Join-Path $env:LOCALAPPDATA 'wechat-chat-decrypt\venv\Scripts\python.exe'
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') update-guard status
```

然后用**管理员 PowerShell**运行：

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') update-guard block
```

这个规则只拦截当前安装目录下的 `WeixinUpdate.exe`。如果以后重新安装或升级了微信，再运行一次 `update-guard block`，让规则重新指向新的更新器路径。

### 4. 运行预检、提取并验证

保持微信已登录，然后运行：

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') preflight
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') prepare-probe
```

把 JSON 输出里的 `manifest` 路径填入下一条命令：

```powershell
$manifest = '<上一步返回的 manifest 路径>'
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') extract-keys --manifest $manifest
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') verify
```

只有看到版本为 `verified_modern`、密钥匹配、HMAC 验证通过和 SQLite `quick_check=ok`，才算完成。

### 5. 直接让 Codex 查询

查询必须使用仓库提供的安全包装器：

```powershell
& (Join-Path $SkillDir 'scripts\wechat-cli-safe.ps1') sessions --limit 20 --format text
& (Join-Path $SkillDir 'scripts\wechat-cli-safe.ps1') history '联系人姓名' --limit 50 --format text
& (Join-Path $SkillDir 'scripts\wechat-cli-safe.ps1') search '关键词' --chat '群聊名称' --format text
```

也可以直接对 Codex 说：

> 查找“联系人姓名”上周的聊天，按日期整理出待办事项，只引用本机记录。

## 这些技术词是什么意思

| 技术词 | 对使用者意味着什么 | 实际价值 |
| --- | --- | --- |
| 内存扫描 | 在已登录的微信进程里找出本机数据库的解锁信息 | 不需要上传聊天数据库 |
| SQLCipher | 微信使用的本地加密数据库格式 | 只有通过校验才能继续读取 |
| Update Guard | Windows 防火墙中的更新器阻断规则 | 降级后不会被自动升级覆盖 |
| 安全包装器 | 每次查询使用临时解密副本，结束后清理 | 减少明文残留 |

## 安全边界

只处理当前用户拥有或明确获授权的数据。不打印 `all_keys.json`，不把密钥、聊天原文或凭据提交到 Git，也不会把聊天内容上传到第三方。查询结束后可运行：

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') cleanup --include-probes
```

## 常见问题

**为什么不能直接支持最新版微信？**

因为新版可能改变密钥在进程内的表示。Skill 会安全停止，而不是猜测密钥或输出一个看似成功的空结果。当前 Windows 验证版本是 `4.1.8.101`。

**更新防护会不会影响正常聊天？**

不会。它只阻断 `WeixinUpdate.exe` 的出站连接，不阻断 `Weixin.exe` 的聊天连接。

**如何恢复正常自动更新？**

在管理员 PowerShell 中运行：

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') update-guard unblock
```

然后安装腾讯当前官方版本，并重新执行 `preflight`。

## 进一步阅读

- [完整 Skill 流程](SKILL.md)
- [兼容性与版本矩阵](references/compatibility.md)
- [Windows 实机验证记录](references/windows-run.md)
- [故障排查](references/troubleshooting.md)

## 想继续交流？

这套微信聊天解密 Skill 的开源代码和安装提示词就是全部，照着提示词交给 Claude Code 或 Codex 就能用，没有隐藏步骤。

**如果你安装完后，针对更多的玩法想要有人一起交流，我组了一个付费交流群，Hermes ai共学社**（¥199一年）：我会持续分享新的 workflows / skills；如果你在过程中卡住了，也可以来群里询问。懒得自己动手的，我也可以帮你装。

有意可加微信 **BurningChen1010**，备注「**共学社**」。

如果你要让 Codex 在另一台电脑上安装，直接把本仓库地址交给 Codex，并说明“安装并配置微信聊天解密 Skill”即可。

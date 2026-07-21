# 一键安装与使用提示词

把下面整段直接复制给 Claude Code、Codex 或其他能执行本机命令的 AI 编程助手，不需要提前填写查询目标。先让 AI 安装、验证和配置好 Skill，完成后再告诉它你要查询什么。

```text
请帮我在这台电脑上安装并使用
https://github.com/chenchen1010/wechat-chat-decrypt-skill.git
这个 WeChat Chat Decrypt Skill。

请严格按以下流程执行：

1. 先判断我的操作系统和架构：Windows 10/11，或 Apple Silicon macOS。
2. 克隆仓库并运行对应的安装脚本：
   - Windows：scripts\install-skill.ps1
   - macOS：scripts/install-skill.sh
3. 运行 bootstrap，确认独立 Python 运行环境和依赖可用。
4. 运行 preflight，检查当前微信版本、登录状态、账号目录和加密数据库数量。
5. 如果是 Windows：
   - 只使用已验证的 Weixin 4.1.8.101；
   - 如果版本更高，先提示我备份 xwechat_files 并退出微信；
   - 使用 README 中的腾讯官方安装包链接和 SHA-256 校验，不要使用来源不明的安装包；
   - 安装并登录后，在管理员 PowerShell 中运行 update-guard block；
   - 确认防火墙规则只指向当前版本的 WeixinUpdate.exe，不要阻断 Weixin.exe。
6. 如果是 Apple Silicon macOS：
   - 只使用已验证的 WeChat 4.1.8 build 37261；
   - 如果版本更高，先提示我备份 xwechat_files 并退出微信；
   - 使用 README 中的腾讯 DMG 链接，先运行 inspect-dmg 验证版本、签名、Tencent Team ID 和 arm64；
   - 只有验证通过并得到我的确认后，才运行 install-dmg；
   - 重新登录后运行 resign，让 Codex 能读取当前登录进程。
7. 让我选择当前登录的账号（如果发现多个账号），然后运行 prepare-probe、extract-keys 和 verify。
8. 只有在版本兼容、密钥匹配、HMAC 验证通过、SQLite quick_check=ok 后，才开始查询。
9. 查询必须使用仓库的安全包装器，不要调用全局 wechat-cli；临时明文文件在命令结束后清理。
10. 完成后只向我报告：版本、兼容性、匹配数据库数量、HMAC/SQLite 验证结果和更新防护状态。先不要查询聊天内容。

安全要求：
- 只处理我本人拥有或明确授权的数据；
- 不打印、复制或上传 all_keys.json、密钥、聊天数据库和完整聊天原文；
- 不猜测密钥，不暴力破解，不绕过版本校验；
- 不要在没有备份和确认的情况下执行降级安装；
- 如果版本不支持或校验失败，停止并说明下一步，不要把失败说成成功。

每一步完成后报告实际结果；需要我登录、备份、确认安装或选择账号时，明确告诉我该做什么。
```

## 日常使用示例

安装完成后，直接告诉 AI 你的目标即可，例如：

```text
请使用已经验证通过的本机微信数据，查找“项目群”过去 30 天提到“合同”的消息，按日期整理出事项和负责人，不要上传原始聊天内容。
```

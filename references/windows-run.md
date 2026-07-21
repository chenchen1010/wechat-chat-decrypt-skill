# Windows 本机验证记录

本机先验证了新版 `Weixin 4.1.11.55` 会被安全阻断，随后降级到已验证的 `Weixin 4.1.8.101` 并完成登录、密钥提取和自动更新防护。

## 已验证

- `preflight` 能识别 Windows 平台、微信版本、运行中的 `Weixin.exe` 进程、账号目录和加密数据库。
- `prepare-probe` 能从真实 `db_storage` 复制完整的 4096 字节数据库首页到私有临时目录，并生成归属校验清单。
- Windows 内存扫描器会检查所有 `Weixin.exe` 进程（也支持 `--pid` 指定单个进程），只接受通过数据库 HMAC 校验的候选密钥。
- `wechat-cli-safe.ps1` 能在每次命令结束后清理临时目录；失败时不会改写原始数据库。
- `cleanup --include-probes` 能清理探针和扫描输出，已实测清理 7 个残留探针目录。

## 新版阻断记录

在本机 5 个 `Weixin.exe` 进程中扫描 21 个数据库首页，没有找到可通过 HMAC 校验的密钥。当前版本没有公开旧版扫描器所依赖的 ASCII `x'<64hex key><32hex salt>'` 运行时模式；因此 `extract-keys` 会安全失败并保留加密数据不变。这个结果与扫描器是否能访问进程无关：进程可读，失败点是候选密钥不存在或格式已经变化。

不要把这次结果写成“已成功解密”。要继续支持该版本，需要针对 `Weixin 4.1.11.55` 的新密钥表示/提取位置做版本化适配，或在用户明确授权后接入经过审计的兼容提取器。不能用猜测密钥、暴力破解或未经审计的第三方可执行文件替代 HMAC 和数据库完整性验证。
## Verified Windows paths (2026-07-21)

Weixin 4.1.8.101 uses `xwechat_files\<wxid>\db_storage` and SQLCipher v4. The logged-in run produced 20 matched keys, 20 HMAC-verified databases, and SQLite `quick_check=ok`; plaintext was removed and keys were never printed.

## 当前机器状态

- 当前进程版本：`4.1.8.101`
- 登录状态：已进入主界面
- 更新防护：`hard_blocked: true`
- 防火墙目标：`D:\Program Files\Tencent\Weixin\4.1.8.101\WeixinUpdate.exe`
- 主程序 `Weixin.exe`：不在阻断范围内

每次重新安装或升级微信后，都要再次运行管理员 PowerShell 命令：

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') update-guard block
```

## Windows packaging note

Install with `scripts\install-skill.ps1`, run `scripts\bootstrap.ps1`, then follow `SKILL.md`. The packaged workflow performs only first-page probes and removes temporary plaintext after verification.

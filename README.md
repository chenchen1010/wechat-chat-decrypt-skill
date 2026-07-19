# WeChat Chat Decrypt Skill

让 Codex 在用户自己的 Mac 上完成微信聊天数据库取钥、校验和本地查询。数据不上传，查询产生的明文数据库默认随命令退出清理。

## 已验证范围

- Apple Silicon Mac
- macOS 26.3.1 或更高（沿用上游要求）
- 微信 Mac 版 4.1.8，构建号 37261（安装包常见名称为 `4.1.8.100_37261`）
- 上游：`huohuoer/wechat-cli`，固定提交 `a3789232d4f79bf0b30634d9dadbce71e4acd601`

4.1.8.100 build 37261 DMG：

<https://dldir1v6.qq.com/weixin/Universal/Mac/xWeChatMac_universal_4.1.8.100_37261.dmg>

这是腾讯 CDN 的历史版本直链。下载后仍必须通过本 Skill 的 bundle ID、版本、构建号、Tencent Team ID、代码签名和 arm64 校验。

新版微信通常需要先降到已验证版本。出于安全和版权考虑，本 Skill **不内置、不自动下载微信安装包**；用户可以使用上面的腾讯 CDN 直链下载，脚本会校验腾讯签名后才允许安装。

## 安装

解压后运行：

```bash
bash /absolute/path/wechat-chat-decrypt/scripts/install-skill.sh
```

安装位置：

```text
~/.codex/skills/wechat-chat-decrypt
```

如果要分享给别人，先在本目录的上一级生成一个干净压缩包：

```bash
bash /absolute/path/to/wechat-chat-decrypt/scripts/package-skill.sh
```

对方解压后运行压缩包内的 `scripts/install-skill.sh`，安装完成后重启 Codex。

重启 Codex 后可以直接说：

```text
请使用 wechat-chat-decrypt，解密我当前登录的本机微信聊天记录。先做只读预检，任何降级、重签名和禁止更新操作都先告诉我。
```

## 不可避免的人工步骤

1. 在 macOS 设置里为 Codex/终端开启“完全磁盘访问权限”。
2. 需要管理员权限时，由用户本人在 `sudo` 提示中输入密码，密码不会交给 Codex。
3. 重签名或降级后，用户需要重新打开微信并登录。
4. 如果当前微信过新，用户需要自行提供可信的 4.1.8 DMG，并在降级前确认已有数据备份。

## 安全设计

- 仅允许当前 macOS 用户的本地微信容器。
- 取钥脚本捕获并丢弃会暴露密钥的原始扫描输出。
- `~/.wechat-cli` 使用私有权限，旧配置自动本地备份。
- 查询使用独立临时目录，退出时删除解密数据库。
- 不会自动上传、发送或修改微信消息。
- 安装包必须通过 bundle ID、版本、构建号、腾讯 Team ID、签名和 arm64 校验。

## 目录

```text
wechat-chat-decrypt/
├── SKILL.md
├── README.md
├── scripts/
│   ├── bootstrap.sh
│   ├── install-skill.sh
│   ├── package-skill.sh
│   ├── wechat-cli-safe
│   └── wechat_decrypt.py
├── references/
├── tests/
└── vendor/wechat-cli/
```

## 许可与来源

本包装层采用 Apache-2.0。内置的 `wechat-cli` 快照同样为 Apache-2.0，来源与固定提交见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。微信客户端属于腾讯，本项目不分发微信安装包。

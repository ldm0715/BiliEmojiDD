# biliEmojiDD 文档

B 站表情包 / 收藏集（装扮）下载器 GUI：PySide6 + QFluentWidgets 界面，`biliemoji==2.0.0` 提供 B 站接口能力。

## 文档导航

| 文档 | 说明 |
|---|---|
| [usage.md](usage.md) | **使用指南**：安装运行、页面功能、Cookie 获取、缓存、常见问题 |
| [architecture.md](architecture.md) | **架构设计**：技术栈、模块分层、线程模型、数据流、配置与缓存 |
| [development.md](development.md) | **开发与维护**：环境准备、命令、代码约定、关键坑点、修改指南 |

## 快速上手

```bash
uv sync
uv run python main.py
```

首次使用请到「设置」页填写 B 站 Cookie（`SESSDATA=...; bili_jct=...`），否则登录类功能（全部表情包、收藏集下载）不可用。

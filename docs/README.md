# biliEmojiDD 文档

B 站表情包 / 收藏集（装扮）下载器 GUI：PySide6 + QFluentWidgets 界面，`biliemoji==2.0.0` 提供 B 站接口能力。

## 文档导航

| 文档 | 说明 |
|---|---|
| [usage.md](usage.md) | **使用指南**：安装运行、页面功能、Cookie 获取、缓存、常见问题 |
| [architecture.md](architecture.md) | **架构设计**：技术栈、模块分层、线程模型、数据流、配置与缓存 |
| [development.md](development.md) | **开发与维护**：环境准备、命令、代码约定、关键坑点、修改指南 |
| [download_queue.md](download_queue.md) | **下载队列与下载设置**：下载队列工作流、设置项、踩坑记录 |
| [collection_page.md](collection_page.md) | **收藏集页 + 混合下载队列**：收藏集页改造、类别判别、混合队列、踩坑记录 |
| [image_viewer.md](image_viewer.md) | **详情页图片查看器**：遮罩 lightbox + 左右翻页、letterbox 方案、qfluentwidgets 上游坑 |
| [ui_polish.md](ui_polish.md) | **UI 改进**：暗色主题补全（全局调色板 + 主题化 Label）、网格响应式填充、下载双列 + 去阴影、侧栏主题切换 |
| [theme_grid_fixes.md](theme_grid_fixes.md) | **主题跟随 + 网格铺满 + 已下载徽标**：主题切换三处失效、详情网格右侧空白、卡片徽标与目录命名统一 |
| [setting_page_redesign.md](setting_page_redesign.md) | **设置页改版**：Fluent 设置卡片版式（分组 + 窄卡片 + 可展开行）、只改界面不改功能的落实方式、上游坑 |
| [page_card_layout.md](page_card_layout.md) | **三页卡片版式**：表情包 / 收藏集 / 下载页的大标题 + 命令卡 + 内容卡、`page_scaffold` 共用底座、踩坑 |
| [download_page_improvements.md](download_page_improvements.md) | **下载体验优化**：GIF 选项按需显隐、队列内容数量懒加载、全部成功自动出队、缩略图加载环、收藏集去重键修复 |

## 快速上手

```bash
uv sync
uv run python main.py
```

首次使用请到「设置」页填写 B 站 Cookie（`SESSDATA=...; bili_jct=...`），否则登录类功能（全部表情包、收藏集下载）不可用。

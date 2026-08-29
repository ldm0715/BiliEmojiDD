# biliEmojiDD

B 站表情包 / 收藏集（装扮）下载器 GUI，基于 PySide6 + QFluentWidgets，功能由
[biliemoji](https://pypi.org/project/biliemoji/) 2.0.0 SDK 提供。

## 功能

- **表情包**
  - 按包 ID 查询单个表情包，缩略图预览，下载（可开关 GIF 动图）
  - 登录后拉取全部表情包，按关键词本地过滤（回车 / 放大镜触发）
- **收藏集（装扮）**
  - 关键词搜索，封面 / 价格 / 收藏集标记展示
  - 点击查看详情，内容分「静态图片 / 动态视频」两个标签
  - 动态视频**直接在页面里播放**：左播放器 + 右视频网格切换，支持上一个 / 下一个、全屏
  - 选择「图片 / 视频 / 图片+视频」下载
- **搜索历史**：点搜索框下拉浮层面板，胶囊形记录最多 10 条，可单条删除或一键清空
- **图片查看器**：两个详情页均可点图全屏查看，左右箭头 / 方向键 / 滚轮翻页
- **下载队列**：会话级队列，混合表情包 + 收藏集，全选 / 删除 / 清空 / 批量下载
- **缓存**：缩略图与接口响应落盘复用，重启后仍命中；容量上限可在设置页调整并随时清除
- **设置**：B 站 Cookie、下载目录、代理、下载线程数、缓存上限、主题（浅色 / 深色 / 跟随系统）

## 运行

```bash
uv sync
uv run python main.py
```

## 文档

- [使用指南](docs/usage.md) — 页面功能、Cookie 获取、缓存、常见问题
- [架构设计](docs/architecture.md) — 技术栈、模块分层、线程模型
- [开发与维护](docs/development.md) — 环境、命令、代码约定、坑点
- [下载队列与下载设置](docs/download_queue.md) — 队列工作流、代理与线程数设置
- [收藏集页 + 混合下载队列](docs/collection_page.md) — 收藏集页改造、类别判别、混合队列
- [详情页图片查看器](docs/image_viewer.md) — 遮罩 lightbox、letterbox 方案、上游坑
- [UI 改进](docs/ui_polish.md) — 暗色主题补全、网格响应式填充、下载双列 + 去阴影、侧栏主题切换
- [主题跟随 + 网格铺满 + 已下载徽标](docs/theme_grid_fixes.md) — 主题切换三处失效、详情网格右侧空白、卡片徽标
- [设置页改版](docs/setting_page_redesign.md) — Fluent 设置卡片版式、可展开行、只改界面不改功能
- [三页卡片版式](docs/page_card_layout.md) — 表情包 / 收藏集 / 下载页的大标题 + 命令卡 + 内容卡
- [下载体验优化](docs/download_page_improvements.md) — GIF 选项按需显隐、队列内容数量、全部成功自动出队、加载环、去重键修复
- [收藏集视频预览](docs/collection_video.md) — 内容分页 Pivot、内嵌播放器 + 缩略图选择条、临时缓存与黑背景坑
- [搜索历史 + 磁盘缓存 + 应用标识](docs/search_and_cache.md) — 浮层历史面板、图片/接口落盘缓存与容量设置、窗口图标与版本号

## Cookie

部分功能（全部表情包、收藏集下载）需要登录。Cookie 在「设置」页填写，仅保存在本机
`%APPDATA%/biliEmojiDD/config.json`，不会上传。建议使用 `SESSDATA=...; bili_jct=...` 格式。

## 说明

- 所有接口来自 B 站公开 API，可能随官方更新失效
- 下载内容保存到 `下载目录/<表情包名>/` 或 `下载目录/<收藏集名>/`
- 仅供学习交流，请勿滥用，后果自负

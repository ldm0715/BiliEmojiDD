# biliEmojiDD

B 站表情包 / 收藏集（装扮）下载器 GUI，基于 PySide6 + QFluentWidgets，功能由
[biliemoji](https://pypi.org/project/biliemoji/) 2.0.0 SDK 提供。

## 功能

- **开屏面板**：启动那几秒先亮出图标 / 名称 / 版本号与加载进度，不再是一片黑
- **主页**（启动默认页）
  - 应用简介 + 状态概览（Cookie 是否有效、队列数量、下载目录）
  - Cookie 状态灯真的反映能不能用：进主页按需检测一次，失效变红；检测结论有 7 天信任期，
    期内不再重复请求
  - 三张功能入口卡，表情包 / 收藏集自带真实展示图，下载卡实时显示队列前 4 项封面
  - 快速上手三步、关于（版本 / 依赖 / 链接）
- **表情包**
  - 登录后拉取全部表情包（默认标签），按关键词本地过滤（回车 / 放大镜触发）——
    Cookie 确认有效后进主页会自动预拉取一次，进这页时列表已就绪
  - 按包 ID 查询单个表情包，缩略图预览，下载（可开关 GIF 动图）
  - **直播间专属表情**：输入直播间 room_id 拉取该房间的主播专属表情，网格预览 +
    点开看大图，整个房间作为一个下载项加入队列（目录按「主播名 [room_id]」命名）
- **收藏集（装扮）**
  - 关键词搜索，封面 / 价格 / 收藏集标记展示
  - 点击查看详情，内容分「静态图片 / 动态视频」两个标签
  - 动态视频**直接在页面里播放**：左播放器 + 右视频网格切换，支持上一个 / 下一个、全屏
  - 选择「图片 / 视频 / 图片+视频」下载
- **搜索历史**：点搜索框下拉浮层面板，胶囊形记录最多 10 条，可单条删除或一键清空
- **图片查看器**：两个详情页均可点图全屏查看，左右箭头 / 方向键 / 滚轮翻页
- **下载队列**：会话级队列，混合表情包 + 收藏集 + 直播间表情，全选 / 删除 / 清空 / 批量下载
- **缓存**：缩略图与接口响应落盘复用，重启后仍命中；容量上限可在设置页调整并随时清除
- **登录**：手机 B 站客户端扫码即可拿到 Cookie，自动保存并显示昵称头像；也可手动粘贴。设置页一张卡按登录状态变样（未登录给两个入口，已登录显示头像 + 昵称 + 退出登录）
- **设置**：B 站账号（扫码登录 / 手动填写 / 退出登录）、下载目录、代理（开关 + 地址）、下载线程数、缓存上限、主题（浅色 / 深色 / 跟随系统）、字体渲染
- **检查更新**：设置页「关于」组可查看仓库地址、手动或开机自动检查新版本；有新版时弹窗渲染更新说明，一键下载并安装。直连 GitHub 慢时可用下载加速源（内置三家，也能自己添加），支持测速分档与拖动排序，安装包一律做 SHA-256 校验

## 安装

到 [Releases](https://github.com/ldm0715/BiliEmojiDD/releases) 下载：

- `BiliEmojiDD-Setup-<版本>.exe` —— 安装包（装到当前用户目录，不需要管理员权限）
- `BiliEmojiDD-<版本>-win64.zip` —— 便携版，解压即用
- `SHA256SUMS.txt` —— 上面两个文件的校验和

## 从源码运行

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
- [主页（欢迎页）](docs/home_page.md) — 英雄卡 + 功能入口卡 + 快速上手 / 关于、静态展示图方案、性能与布局坑
- [代理](docs/proxy_diagnostics.md) — 开关 + 单地址框（**一律默认关**）、`trust_env=False` 断开系统代理、`net.py` 联网工厂、ProxyError 成因表与「测试」按钮
- [应用外壳](docs/app_shell.md) — 全局字体 LXGW 文楷等宽、FreeType 渲染后端、消息提示统一挂内容区、切页去掉位移动画
- [检查更新与打包发布](docs/update_and_packaging.md) — 版本号单点维护、更新弹窗、下载加速镜像与校验、`CHANGES.md` 发版流程、Nuitka + NSIS 与工作流
- [重新加载](docs/reload_media.md) — 图片 / 视频加载失败后的右键菜单与可点击失败态、缓存作废顺序
- [GIF 标识与动图预览](docs/gif_preview.md) — 卡片左下角 GIF 角标、表情详情悬浮播放、查看器打开即播
- [扫码登录](docs/login.md) — web 端二维码接口与状态机、Cookie 提取双路径、轮询竞态、`segno` 二维码绘制
- [Cookie 有效性检测与状态灯](docs/cookie_status.md) — 五态状态机、7 天 / 30 分钟信任期、状态灯配色、有效即静默预拉取
- [直播间专属表情](docs/live_emoji.md) — 三个直播间接口、`room_<id>_` 过滤口径、队列第三类、GIF 判据只看 URL 后缀

更新日志见 [CHANGES.md](CHANGES.md)。

## Cookie

部分功能（全部表情包、收藏集下载）需要登录。「设置 → 账号 → B 站账号」里点「扫码登录」，
用手机 B 站客户端扫二维码即可；扫不成也可点「手动填写」粘贴。Cookie 仅保存在本机
`%APPDATA%/biliEmojiDD/config.json`，不会上传。

## 说明

- 所有接口来自 B 站公开 API，可能随官方更新失效
- 下载内容保存到 `下载目录/<表情包名>/` 或 `下载目录/<收藏集名>/`
- 仅供学习交流，请勿滥用，后果自负

## 许可

本项目以 **[GPL-3.0-or-later](LICENSE)** 发布，Copyright (C) 2026 gcnanmu。

依赖的许可：

| 依赖 | 许可 |
|---|---|
| [PySide6](https://doc.qt.io/qtforpython/) | LGPLv3（允许被 GPLv3 作品吸收） |
| [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | GPLv3，**仅限非商业用途** |
| [biliemoji](https://pypi.org/project/biliemoji/) | MIT |
| [LXGW WenKai Mono GB](https://github.com/lxgw/LxgwWenKai)（内置字体） | SIL OFL 1.1 |

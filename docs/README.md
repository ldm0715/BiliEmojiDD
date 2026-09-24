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
| [collection_video.md](collection_video.md) | **收藏集视频预览**：内容分页 Pivot、内嵌播放器 + 缩略图选择条、先下到临时目录再本地播放、`VideoWidget` 黑背景坑 |
| [search_and_cache.md](search_and_cache.md) | **搜索历史 + 磁盘缓存 + 应用标识**：浮层历史面板、图片/接口落盘缓存与容量设置、窗口图标与设置页身份头 |
| [home_page.md](home_page.md) | **主页（欢迎页）**：英雄卡 + 功能入口卡 + 快速上手 / 关于、`static/showcase` 静态素材、`ImageLabel` 每帧缩放 + 圆角裁剪、一格滚轮 24 帧的滚动性能 |
| [proxy_diagnostics.md](proxy_diagnostics.md) | **代理**：只认设置页里那一个地址（开关 + 地址框）、**一律默认关**（「老配置有地址就自动置开」的迁移已删）、`trust_env=False` 断开系统代理、`net.py` 联网工厂、ProxyError 成因表与「测试」按钮 |
| [app_shell.md](app_shell.md) | **应用外壳**：全局字体 LXGW 文楷等宽（首选族名 + qfluentwidgets `getFont` 补丁）、FreeType 渲染后端、消息提示统一挂内容区、切页滑一张快照、主题切换的两处提速与天花板 |
| [update_and_packaging.md](update_and_packaging.md) | **检查更新与打包发布**：版本号单点维护、GitHub Release 检查与更新弹窗、下载加速镜像与 SHA-256 校验、`CHANGES.md` 发版流程、Nuitka + NSIS 打包与工作流 |
| [reload_media.md](reload_media.md) | **重新加载**：图片 / 视频加载失败后的右键菜单与可点击失败态、三层缓存作废的顺序、`forget` 不能误删下载产物 |
| [gif_preview.md](gif_preview.md) | **GIF 标识与动图预览**：角标判定口径、原始字节只在 `image_cache` 里、悬浮播放与查看器自动播放、`QMovie(None)` 段错误 |
| [login.md](login.md) | **扫码登录**：web 端二维码接口与状态机、Cookie 提取的双路径、专用会话工厂的浏览器 UA、轮询线程模型与关窗竞态、`segno` 二维码绘制、账号信息展示 |
| [cookie_status.md](cookie_status.md) | **Cookie 有效性检测与状态灯**：五态状态机、有效 7 天 / 失效 30 分钟的信任期、主页状态灯配色、Cookie 有效时静默预拉取全部表情包 |
| [live_emoji.md](live_emoji.md) | **直播间专属表情**：三个接口的实测结论（`getInfoByRoom` 被风控故不用）、`room_<id>_` 过滤口径、队列第三类要同步的五个位置、GIF 判据只看 URL 后缀（`is_dynamic` 实测不可信）、目录命名一致性 |
| [clipboard_copy.md](clipboard_copy.md) | **右键复制表情**：CF_DIB 装不下动画、动图落文件走 CF_HDROP、`image_cache` 取原始字节的三层降级、范围只到表情网格、失败静默 |
| [performance.md](performance.md) | **帧率与滚动性能**：加载环空转 / IconMode 整块重绘 / 可视区间全量遍历三个真凶的实测数字、`QT_SCALE_FACTOR=1.25` 的基准口径、试过并回退的几种做法 |
| [fps_testing.md](fps_testing.md) | **帧率测试怎么做**：真机帧率脚本的完整命令、看哪三行、达标判据、结果怎么解读（等图窗口期 / p99 尖峰）、跑不动时先查什么 |

## 快速上手

```bash
uv sync
uv run python main.py
```

首次使用请到「设置」页填写 B 站 Cookie（`SESSDATA=...; bili_jct=...`），否则登录类功能（全部表情包、收藏集下载）不可用。

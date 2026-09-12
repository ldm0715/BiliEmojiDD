# 三页改版：Fluent 卡片版式（表情包 / 收藏集 / 下载）

设置页改完之后（[setting_page_redesign.md](setting_page_redesign.md)），另外三个 Tab 也按同一套
Fluent 卡片规范重做：**大标题 → 命令卡（工具栏）→ 内容**。本文记录版式规则、共用底座与踩坑。

## 一、背景

三页原本都是 `QVBoxLayout` + 16px 页边距 + 控件直接摊在页面底色上：没有页面标题、
工具栏没有承载面、边距与新设置页（36px）不一致，四页放在一起风格割裂。

沿用上一批的硬约束：**只改界面，不动功能**——槽函数（`_on_query` / `_on_fetch` / `_repopulate` /
`_open_detail` / `_show_detail` / `_sync_queue_btn` / `_on_download*` …）与控件属性名、类型全部保留，
三个页面仍是 `QWidget`（`notify_*(parent=...)` 的 InfoBar 定位不变）。改动只在「控件装在什么容器里」。

## 二、修改文件

| 文件 | 改动 |
|---|---|
| `app/components/page_scaffold.py`（新） | 四页共用版式底座：`PAGE_MARGIN` / `page_title` / `title_row` / `CommandCard` / `SectionCard` |
| `app/components/package_detail.py` | 头部卡（信息 + 操作 + 进度）+ `SectionCard("表情预览")` 包网格；新增 `add_leading_widget()` |
| `app/view/emoji_page.py` | 大标题 + Pivot；两个 Tab 各自的命令卡；详情页「返回列表」挪进头部卡 |
| `app/view/dress_page.py` | 大标题 + 搜索命令卡；详情头部卡 + `SectionCard("内容预览")` + 视频卡 |
| `app/view/download_page.py` | 大标题 + 命令卡（计数 + 4 按钮 + 状态 + 进度条） |
| `app/view/setting_page.py` | `_PAGE_MARGIN` 改为共用 `PAGE_MARGIN`（值不变） |
| `scripts/check_pages_layout.py`（新） | 三页 + `PackageDetailView` 的回归断言 |
| `scripts/screenshot_pages.py` | 三页整页亮/暗截图；`scripts/check_grid_click.py` 补 `QPixmapCache` 预置 |

## 三、版式规则

```
<页面大标题>                       TitleLabel，(36, 20, 36, 12)
[Pivot]                           仅表情包页
┌ CommandCard ────────────────────────────────┐
│ 搜索 / 过滤 / 多选 / 主操作按钮                 │
│ 已选 N 个                        [加入下载]    │  ← 仅多选态显示
└─────────────────────────────────────────┘
  网格（页面底色上）
  分页 / 提示
```

三条取舍：

1. **列表网格不套卡**：`PackageCard` / `DressCard` / `QueueCard` 本身就是卡片项，
   再套一层是「卡中卡」；它们直接铺在页面底色上。
2. **详情预览网格套卡**：`EmojiGrid` / `DressDetailGrid` 的项是纯图片按钮、没有自己的承载面，
   放进 `SectionCard`（`HeaderCardWidget` 的薄封装）正好补上标题栏与背景，
   顺带替掉原来那句裸 `BodyLabel("表情预览")`。
3. **详情页信息 + 操作合成一张头部卡**：返回按钮 + 名称 + 元信息 + 已下载徽标 + 选项 + 按钮 + 进度条
   全在一张卡里，比「信息卡 + 底部操作卡」省一行，图片网格能占满剩余空间。

页边距四页统一 `PAGE_MARGIN = 36`，大标题与命令卡左边缘对齐。

## 四、共用底座 `app/components/page_scaffold.py`

- `PAGE_MARGIN / PAGE_TOP / PAGE_BOTTOM / SECTION_SPACING`：版式常量；
- `page_title(text, parent)` + `title_row(label)`：大标题与它的缩进行
  （**缩进必须走布局边距**，Label 有组件库 QSS，`setContentsMargins` 会被 `QStyleSheetStyle` 覆盖）；
- `CommandCard(SimpleCardWidget)`：`add_row()` 加一行控件、`add_row_widget()` 返回
  `(整行容器, 布局)` 便于整行显隐、`add_widget()` 整行放一个控件（进度条等）；
- `SectionCard(HeaderCardWidget)`：带标题栏的内容卡，内容区边距从库默认 24 收紧到 `(12, 4, 12, 12)`。

两个卡片基类都继承 `BackgroundAnimationWidget`（构造里连 `qconfig.themeChanged`）并
`FluentStyleSheet.CARD_WIDGET.apply(self)`，**主题切换自动重绘**，不需要自己写 QSS。

## 五、各页要点

- **表情包页**：`EmojiPage` 根布局零边距，标题行 + Pivot 行 + `stackedWidget`；两个 Tab 内部
  `(36, 0, 36, 24)` 与标题对齐。**Pivot 顺序是「全部表情包 → 按 ID 查询」，且默认停在
  全部表情包**（它才是主体，按 ID 查询没输入 ID 时是片空白；默认项正好是 index 0，
  指示条初始位置天然正确——见 [cookie_status.md](cookie_status.md) 第六节）。
  「全部表情包」命令卡两行：拉取/刷新/多选/过滤/计数，
  多选行（已选 N 个 + 加入下载）只在多选态显示。详情子页去掉了单独的返回行，
  `backBtn` 换成 `TransparentPushButton(LEFT_ARROW)` 由 `detail.add_leading_widget()` 放进头部卡。
- **收藏集页**：搜索命令卡（关键词 + 仅看收藏集 + 多选 + 搜索）+ 多选行；详情头部卡
  （返回 + 名称/信息 + 徽标 + 加入下载/下载到本地 + 下载内容下拉 + 进度条）、`SectionCard("内容预览")`、
  视频卡（`videoToggle` 当卡头 + `videoList`，无视频时整卡隐藏）。
  > 视频卡后来被「内容预览」卡头的 `Pivot`（静态图片 / 动态视频）取代，
  > 见 [collection_video.md](collection_video.md)。
- **下载页**：命令卡里放计数 + 全选/删除/清空/下载 + `statusLabel` + `bar`；
  后两者由 `start_download` 控制显隐，隐藏时不占位，命令卡自动收缩。

## 六、踩坑记录

1. **`SettingCard` 那套是设置页专用**：内容页要的是「承载面」而不是「设置行」，
   用 `SimpleCardWidget` / `HeaderCardWidget`；两者都自带主题重绘，别自己画背景。
2. **不换行的 QLabel 会把整页最小宽度顶起来**：详情头部卡里名称 / 元信息一旦是长文本，
   `minimumSizeHint` 就是整串文字宽度，页面缩不到最小窗口（实测收藏集详情一度要 734px，
   而最小窗口 820 − 侧栏 150 − 页边距 72 只有 598）。给 `nameLabel` / `detailLabel` /
   `detailName` / `detailInfo` / `hintLabel` 都开 `setWordWrap(True)` 后回到 600 以内。
3. **隐藏的子页不会重新布局**：`QStackedWidget` 里非当前页、以及未 `show()` 的 Tab，
   几何停留在上次可见时的尺寸。写几何断言前必须先切到该页 —— 否则量到的是过期数字，
   断言会「假通过」（本批次的窄窗口断言第一版就栽在这里，故脚本里补了一条
   `page.width() == 600` 的自检）。
4. **假 URL 会拖住脚本退出**：网格拿到 `https://x.invalid/...` 就会排一个 15s 超时的下载任务，
   脚本跑完要等全局线程池收工。断言脚本一律先 `QPixmapCache.insert(url, 假图)` 预置，
   `thumb_manager.request` 会同步命中不走网络。
5. **`ruff` 默认尊重 `.gitignore`**：`scripts/` 一度被写进 `.gitignore`，于是所有脚本
   从未被 lint 过（去掉那行后立刻冒出一条陈旧 `noqa`）。

## 七、验证

```bash
uv run ruff check .
uv run python -c "import app.MainWindow"

QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py    # 本批次新增
QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py
QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py
QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py      # 三页亮/暗整页截图
```

`check_pages_layout.py` 覆盖 7 组：功能控件仍在（三页 + `PackageDetailView` 共 50 个属性、
`modeCombo` 的 image/video/both 仍在）、大标题与命令卡左对齐 36、多选行显隐 + 命令卡高度随之变化、
详情头部卡（返回按钮在名称左侧、`set_package` 后按钮可用、预览网格填充）、
内容分页 Pivot 随视频有无启停、600px 窄窗口不越界 + 下载页 980 宽仍两列、切主题后卡片背景重算。

六个脚本均 ALL PASSED。真实交互（网络拉取、下载、队列）依赖 Cookie，需人工
`uv run python main.py` 验证。

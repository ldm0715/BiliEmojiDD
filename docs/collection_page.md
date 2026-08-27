# 收藏集页改造 + 混合下载队列（新增功能说明）

本次改动把「收藏集」页从单列横版卡片重做为**四列竖版海报卡片**，打通「搜索 → 多选加入下载队列 → 详情预览 → 下载」完整链路，并把下载队列从「仅表情包」扩展为**表情包 + 收藏集混合**。本文记录改动内容、关键实现与踩坑点，便于后续维护。

## 一、背景

原收藏集页存在多个问题：

1. **类别无法区分**：搜索结果是「收藏集」与「装扮」混合的，但 biliemoji 的 `DressCollectionSummary.is_collection` 恒为 `False`（解析 bug），界面无法正确分类。
2. **卡片布局差**：海报被压进 72×72 方块（`setScaledContents` 拉伸变形）；单列横版卡片又宽又占空间。
3. **点击进详情是坏的**：`DressCard.clicked = Signal(object)` 与基类 `CardWidget` 的 0 参数 `clicked` 冲突，点卡片 `TypeError` 被 PySide 吞掉，详情页完全点不进去。
4. **无多选**：无法批量挑选收藏集加入下载。
5. **下载队列仅支持表情包**：收藏集只能单包即时下载，无法进队列统一管理。

## 二、新交互流程

```
搜索关键词 → 四列竖版海报卡片（海报 + 名称 + 类别徽标）
  ├─ 点卡片（非多选态）→ 详情页：动态尺寸图片网格 + 视频折叠列表 + 模式选择下载
  └─ 勾选「多选」→ 勾选框 + 选中高亮 →「加入下载」→ 下载队列
下载页（下载队列）：混合展示表情包 + 收藏集，统一横向卡片，全选/删除/清空/批量下载
```

## 三、关键实现

### 1. 类别判别（`app/components/dress_helpers.py`，新）

biliemoji 的 typed 字段有解析 bug：API 把 `dlc_act_id` / `dlc_lottery_id` 以**字符串**返回，`_optional_int` 拒收字符串 → 模型字段恒 `None`，`is_collection` 恒 `False`，`id` 也恒 `None`（真实键是 `item_id`）。

因此判别与取 id 一律从 `summary.raw` 读取：

- `props(summary)["type"]`：`"dlc_act"` = 收藏集、`"ip"` = 装扮（已用真实数据验证）。
- `dlc_ids(summary)`：返回字符串形式的 `(dlc_act_id, dlc_lottery_id)`，可直接传 `certain_lottery_typed`。
- `is_collection(summary)` / `category_name(summary)`：供卡片徽标、详情入口、批量下载共用。

### 2. 卡片网格重构（`app/components/widgets.py`）

- 抽出 `_CardGridBase(QListWidget)`：通用网格基类，内置**懒加载缩略图 + 多选 API + 动态单元格**（`set_cards` / `_cell_size` / `checked_items` / `set_all_checked` / `selectionChanged`）。
- `PackageGrid` / `PackageCard`：迁移到基类，公开 API（`packageClicked` / `set_packages` / `checked_packages`）保持不变。
- `DressCard`（重写）：**纯 QWidget**（弃用 `CardWidget`，修复点击 0 参信号冲突）；竖版海报（`QPushButton` 设 `Expanding` 尺寸策略撑满）+ 名称 + 类别徽标 + 右上角勾选框。
- `DressGrid(_CardGridBase)`：恰好 4 列，单元格宽 = `(视口宽 - 3×间距) // 4`，海报 3:4。
- `DetailCard` + `DressDetailGrid(_CardGridBase)`：收藏集详情网格，卡片尺寸**动态计算**（视口 + 项目数量），项目少时放大撑满、多时缩小滚动。
- `QueueCard` + `QueueList(_CardGridBase)`：下载页统一横向卡片（固定封面框 + 名称 + 类别 + ID/价格），横/竖封面都等比适配，宽度铺满视口。

### 3. 下载队列混合化（`app/components/download_queue.py`）

- 从「仅 `EmotePackage`、按 `pkg.id` 去重」改为「混合存储、按 `(类型, ID)` 去重」。
- `item_kind(item)`：`"package"` / `"collection"`（按有无 `emote` 字段判别）。
- `item_key(item)`：表情包 `("pkg", id)`；收藏集 `("coll", raw["item_id"])`（summary.id 恒 None）。
- `items()` 替代原 `packages()`；`remove` 接受 `item_key` 键。

### 4. 批量下载（`app/components/download_runner.py`）

- `download_collection_batch(collections, dest, *, mode, max_workers, on_progress)`：单 `Downloader` + 单进度条；**显式 `proxies`**（biliemoji 的 `download_collection` 不转发代理给内部 `Downloader`）；逐项 `certain_lottery_typed`，单个失败合成 FAILED 继续；目录 `dest/<收藏集名>/`。
- `download_mixed_batch(items, dest, *, gif, mode, ...)`：下载页「下载选中」入口，按 `item_kind` 拆分、先表情包后收藏集顺序执行两子批并合并 `DownloadBatchResult`（进度条在两子批间重新定程）。

### 5. 详情页（`app/view/dress_page.py`）

- 点击卡片（非多选态）→ 详情：`dlc_ids` 取 id → `run_task(certain_lottery_typed)` → 动态图片网格 + 视频折叠列表。
- 视频区为**可折叠**（`QToolButton` 箭头，默认收起），不再占固定高度。
- 下载模式 ComboBox（图片 / 视频 / 图片+视频）。

### 6. 收藏集页多选

- 「多选」勾选 → `DressGrid.set_selectable` + 选中计数 + 「加入下载」按钮 → `download_queue.add_many`，与表情包页行为一致。

## 四、踩坑记录

1. **`QPushButton` 垂直 size policy 默认 `Fixed`**：在 `QVBoxLayout` 里加 `stretch=1` 也拉不撑它，海报被压成 12px 高、多余空间全给文字 label。必须 `setSizePolicy(Expanding, Expanding)`。
2. **qfluentwidgets `ComboBox.addItem(text, icon, userData)`**：第二位置参数是 **icon**，不是 userData！`addItem("静态图片", "image")` 会把 `"image"` 当图标，`currentData()` 恒 `None` → `download_collection` 里 `mode.lower()` 抛 `AttributeError`。必须 `addItem("...", userData="image")`。（`setting_page.py` 的代理协议、主题 ComboBox 也有同样坑，已一并修。）
3. **`CardWidget` 点击 0 参信号**：基类 `mouseReleaseEvent` 只发 `clicked.emit()`（0 参数）；子类重声明 `clicked = Signal(object)` 会在运行时抛 `TypeError` 且被 PySide 静默吞掉（点卡片无反应）。卡片改用纯 `QWidget` + 自写 `mousePressEvent`。
4. **biliemoji 收藏集 typed 字段不可信**：`is_collection` / `dlc_act_id` / `dlc_lottery_id` / `id` 因 API 字符串被 `_optional_int` 拒收而恒 `None`。一律用 `dress_helpers` 从 `raw` 读。

## 五、涉及文件

| 文件 | 说明 |
|---|---|
| `app/components/dress_helpers.py`（新） | 类别判别 + dlc id 读取 |
| `app/components/download_queue.py` | 队列混合化 |
| `app/components/download_runner.py` | `download_collection_batch` / `download_mixed_batch` |
| `app/components/widgets.py` | `_CardGridBase` 重构；DressCard / DressGrid / DressDetailGrid / QueueCard / QueueList |
| `app/view/dress_page.py` | 四列网格 + 多选加入队列 + 详情（动态网格 + 视频折叠 + 下载） |
| `app/view/download_page.py` | 下载页改用 `QueueList` 混合展示 + `download_mixed_batch` |

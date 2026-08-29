# 应用外壳：全局字体 / 消息提示位置 / 切页无动画

三件跨页面的「壳」层改动，都不属于任何单个功能页。

---

## 一、全局字体 AlibabaPuHuiTi

### woff2 加载不了

`static/font/` 里原本只有 `AlibabaPuHuiTi-3-55-Regular.woff2`。
**Qt 的 `QFontDatabase.addApplicationFont()` 只认 TrueType / TrueType Collection /
OpenType**，woff / woff2 一律返回 -1。

解法是离线转一次：`scripts/convert_font.py` 用
`fontTools.ttLib.woff2.decompress` 把目录下每个 `.woff2` 解成同名 `.ttf`
（5.2 MB → 7.1 MB），产物入库，运行时零依赖。`fonttools` / `brotli` 只在 dev 组里。

```bash
uv run python scripts/convert_font.py --dry-run   # 先看要生成什么
uv run python scripts/convert_font.py             # 真的写
uv run python scripts/convert_font.py --force     # 覆盖已有 ttf
```

### 光 `QApplication.setFont` 改不动 qfluentwidgets

组件库在 `qfluentwidgets/common/font.py::getFont()` 里**硬编码**字体族：

```python
font.setFamilies(['Segoe UI', 'Microsoft YaHei', 'PingFang SC'])
```

而每个 Label / Button / ComboBox / SettingCard 构造时都 `setFont(getFont(...))`，
所以应用默认字体对它们完全无效。必须打补丁。

补丁的坑：库里 **21 个模块**写的是 `from ...common.font import setFont, getFont`
——导入那一刻就把函数对象绑到了自己模块的全局名上，事后替换
`qfluentwidgets.common.font.getFont` 对它们无效。所以 `app/common/font.py`：

1. 换掉 `qfluentwidgets.common.font.getFont`（新版把内置字体插到族名最前，去重）；
2. 再扫一遍 `sys.modules`，把仍指向原函数的模块级 `getFont` 重绑一次。

`setFont` **不用重绑**：它的函数体在自己模块的 globals 里查 `getFont`，天然吃到补丁。

### 调用时机

`main.py` 里 `QApplication` 建好之后、`import app.MainWindow` **之前**调
`apply_app_font(app)`：

- `addApplicationFont` 需要 QGuiApplication 实例；
- `sys.modules` 重绑必须赶在页面控件构造之前（`app.common.config` 在模块顶层就把
  qfluentwidgets 拉进来了，所以那批模块此时已经导入完了）。

### 字重

只装了 Regular，`TitleLabel` / `StrongBodyLabel` 要的 DemiBold / Bold 由 Qt 合成
伪粗体。想要真字重，把 `AlibabaPuHuiTi-3-85-Bold.ttf` 之类丢进 `static/font/`
即可——`app_font_files()` 扫整个目录，同族不同字重 Qt 会自己挑，**无需改代码**。

字体缺失 / 加载失败一律静默返回 `None`，不影响启动（与 `resource.py`
「任何缺失都静默降级」的既有约定一致）。

---

## 二、消息提示统一落在内容区右上角

改动前各页面各传各的 parent（`self` / `self.searchPage` / `self.detailPage`），
而上游 `InfoBarManager` 是按 `infoBar.parent()` 的矩形算位置的
（TOP_RIGHT = 父级右上角内缩 24px）。后果有两个：

- 消息浮在命令卡中间，位置随页面结构飘；
- **挂在子页上，页面一切走消息就跟着被 `QStackedWidget` 藏掉了**。

`FluentWindowBase` 把 `widgetLayout` 的上边距设成 48 再放 `stackedWidget`
（`window/fluent_window.py:162`），所以 `stackedWidget` 恰好就是
「标题栏以下、侧栏以右」的内容区。`app/common/notify.py` 新增 `_resolve_parent()`：
从传入 widget 的 `window()` 上取 `stackedWidget`，取不到就原样退回
（屏幕外脚本单独构页时不抛）。建完 `bar.raise_()`——InfoBar 不进
`QStackedLayout`，只是 `stackedWidget` 的普通子控件。

**调用点一行都不用改**，仍然传自己的页面 widget，由 `notify.py` 归一。

---

## 三、切页不做位移动画

上游 `PopUpAniStackedWidget.setCurrentIndex` 每次切页跑 **300 ms 的整页 `pos`
动画**（`deltaY=76`），这 300 ms 里整页被重绘十几帧。实测单帧重绘成本
（`page.grab()`，1100x760）：

| 页面 | 单帧 |
|---|---|
| 主页 | 12.2 ms |
| 设置 | 11.3 ms |
| 表情包 | 5.1 ms |
| 收藏集 | 3.7 ms |
| 下载 | 2.6 ms |

主页 / 设置页 ≈ 25 fps 的滑动，肉眼就是卡。页面内容本身够重（滚动区 + 几十张卡片），
为一次导航付这个代价不值。

`MainWindow._set_current_interface()` 跳过动画，直接
`QStackedWidget.setCurrentIndex(view, index)`。两个细节：

- **换的是 `stackedWidget` 实例上的 `setCurrentWidget` 方法**，不只是覆写
  `switchTo`——切页有三个入口：侧栏点击（`onClick` → `switchTo`）、程序化
  `switchTo`、标题栏返回按钮（`qrouter.pop()` 直接调 `stacked.setCurrentWidget`）。
  换实例方法一次盖全。
- 切之前若有动画在跑要 `stop()`，切完 `interface.move(x, 0)` 把页放回原位——
  动画中途被打断时页可能停在 +76px 上。

切完实测：一轮事件循环内到位，整次切页 6–45 ms（含一次完整布局 + 重绘）。

### 已知未优化

建卡片本身很贵：`PackageGrid.set_packages` 建 300 张卡约 4 s。开销分布是
每张卡 10 次 `signal.connect`（0.8 s）、9 次 `setStyleSheet`（0.78 s）、
`addItem` + `setItemWidget`（1.2 s，其中 `TableItemDelegate.updateEditorGeometry`
是 **O(n²)**：300 项触发 45150 次）。表情包页有分页（`_PAGE_SIZE = 20`，
约 180 ms/页）所以还能忍，收藏集搜索 30 条约 280 ms。真要优化得动卡片结构
（少建组件库控件 / 复用卡片），本次未做。

---

## 回归断言

`scripts/check_shell.py`（`QT_QPA_PLATFORM=offscreen`）覆盖三件事：
字体加载 + `getFont` 补丁生效（含 `label.py` 的重绑）、InfoBar 挂在
`stackedWidget` 且位置在内容区右上角 / 切页后仍可见、切页一轮事件循环内到位
且无残留动画。

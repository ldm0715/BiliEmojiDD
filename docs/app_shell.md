# 应用外壳：全局字体 / 字体渲染 / 消息提示位置 / 切页无动画 / 开屏面板

四件跨页面的「壳」层改动，都不属于任何单个功能页。

---

## 一、全局字体 LXGW 文楷等宽 GB

### 目录里放什么、用哪个

`static/font/` 下只有 `LXGWWenKaiMonoGB-Regular.ttf`（族名 **`LXGW WenKai Mono GB`**）。
**Qt 的 `QFontDatabase.addApplicationFont()` 只认 TrueType / TrueType Collection /
OpenType**，woff / woff2 一律返回 -1——想用只在 Web 包里发 woff2 的字体（阿里普惠体就是
这样），得先离线解成 ttf 再入库。

`load_app_fonts()` 把目录下所有字体都注册进去，然后**优先返回 `PREFERRED_FAMILY`**
（`app/common/font.py` 里的常量，就是上面那个族名），目录里没有它才退回第一个成功加载的。
这样「用哪个字体」是代码里的显式事实，而不是文件名排序的副产品——以前目录里同时躺着
阿里普惠体和文楷时，生效的是排序靠前的阿里普惠体，看起来像是新字体没装上。

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

### 光打 `getFont` 补丁还不够：QSS 赢过 `setFont`

改完 `getFont` 之后仍然有一半控件是 Segoe UI——按钮、勾选框、InfoBar、设置卡，
而输入框和下拉却是对的。根因是**上游 23 个 QSS 把字体族写死了**：

```css
/* BUTTON / CHECK_BOX / INFO_BAR / EXPAND_SETTING_CARD / DIALOG ... */
font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
```

**QSS 的优先级高于 `QWidget.setFont()`**，`QStyleSheetStyle` 在 polish 时会用 QSS 里的
族名重算控件字体，把 `getFont` 补丁的结果整个盖掉。`LINE_EDIT` / `COMBO_BOX` 里那两行
恰好是**注释掉**的（`/* font: ... */`），所以输入框和下拉一直正常——这个「有的对有的不对」
正是判断依据。

这些 qss **编在 Qt 资源里**（`:/qfluentwidgets/qss/...`），磁盘上 `grep` 不到，
只能在读出来的那一刻替换。所有库内 qss 都经 `getStyleSheetFromFile` 出口，
`_patch_stylesheet_font()` 包一层，用正则把那串族名换成内置字体：

```python
_QSS_FAMILIES_RE = re.compile(
    r'''['"]Segoe UI['"]\s*,\s*['"]Microsoft YaHei['"]'''
    r'''(?:\s*,\s*['"]PingFang SC['"])?'''
)
```

单双引号都出现过、`PingFang SC` 有时没有，所以两处都写成可选。库内没有别的模块直接
import 这个函数，不用像 `getFont` 那样扫 `sys.modules` 重绑。回归断言在
`scripts/check_shell.py` 第 2c 节：关键 qss 里不再有硬编码族名，且 `PushButton` /
`CheckBox` **`ensurePolished()` 之后**仍是内置字体（不 polish 量不出这个 bug）。

### 调用时机

`main.py` 里 `QApplication` 建好之后、`import app.MainWindow` **之前**调
`apply_app_font(app)`：

- `addApplicationFont` 需要 QGuiApplication 实例；
- `sys.modules` 重绑必须赶在页面控件构造之前（`app.common.config` 在模块顶层就把
  qfluentwidgets 拉进来了，所以那批模块此时已经导入完了）。

### 字重

只装了 Regular，`TitleLabel` / `StrongBodyLabel` 要的 DemiBold / Bold 由 Qt 合成
伪粗体。想要真字重，把 `LXGWWenKaiMonoGB-Medium.ttf` 之类丢进 `static/font/`
即可——`app_font_files()` 扫整个目录，同族不同字重 Qt 会自己挑，**无需改代码**。

字体缺失 / 加载失败一律静默返回 `None`，不影响启动（与 `resource.py`
「任何缺失都静默降级」的既有约定一致）。

---

## 二、字体渲染后端（DirectWrite / FreeType）

Qt 在 Windows 上默认用 DirectWrite 光栅化。文楷这类手写风字体笔画细、又不带 TT hinting
指令，14px 下容易显得发糊，ClearType 的次像素抗锯齿还会在细笔画上留彩边（看起来就是
「颗粒感」）。换 FreeType 渲染通常笔画更实、没有彩边。

切换只能靠**平台插件启动参数**，且必须在 `QApplication` 构造之前设：

```python
os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"
```

所以 `main.py` 的第一句是 `apply_font_engine()`（读 `cfg.font_engine`），
之后才 `QApplication(sys.argv)`。设置页「外观 → 字体渲染」改的就是这个配置项，
**重启应用后生效**。`QT_QPA_PLATFORM` 已被外部指定时（屏幕外脚本的 `offscreen`）
直接让路，不覆盖。

配套还给应用字体和补丁后的 `getFont` 都设了
`QFont.HintingPreference.PreferFullHinting`——DirectWrite 会忽略它，FreeType 下它决定
字形是否对齐像素网格。

**实测（PySide6 6.4.2，Windows）**：把同一段文字画进 QImage 比 md5，

| `QT_QPA_PLATFORM` | 结果 |
|---|---|
| 未设（DirectWrite） | `b38eda02…` |
| `windows:fontengine=freetype` | `932e03b3…`（**不同** → 引擎真的换了） |
| `windows:fontengine=gdi` | `b38eda02…`（与默认一致 → **不支持**） |
| `windows:fontengine=bogus` | `b38eda02…`（乱写也不报错，Qt 静默忽略） |

**Qt 对不认识的 `fontengine` 值不报警告**，只能靠比对渲染结果判断有没有生效。
所以 `FONT_ENGINES` 只给 `("default", "freetype")` 两项，没有 GDI。

---

## 三、消息提示统一落在内容区右上角

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

## 四、切页不做位移动画

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

## 五、开屏面板（启动前几秒不再是黑屏）

### 为什么要有

冷启动实测（本机，`uv run python main.py` 的各阶段计时）：

| 阶段 | 耗时 |
|---|---|
| `import PySide6.QtWidgets` | ~370 ms |
| `QApplication()` | ~70 ms |
| `import qfluentwidgets` | ~520 ms |
| `apply_app_font()` | ~150 ms |
| **`import app.MainWindow`** | **~2100 ms** |
| **`MainWindow()`（五个页面同步构造）** | **~2700 ms** |

后两项占八成。这几秒里屏幕上什么都没有，用户会以为程序没起来（真实反馈）。

### 为什么不用上游的 `SplashScreen`

`qfluentwidgets.window.splash_screen.SplashScreen` **不合用**：

- 它必须挂在一个**已经存在的** `FluentWindow` 上（构造里 `parent.installEventFilter`，
  `eventFilter` 跟着父窗口 resize）——而我们要遮的恰恰是「MainWindow 还没造出来」那一段；
- 它只画一个居中图标 + 一条 `TitleBar`，没有应用名与版本号。

所以自己写了 `app/components/splash.py::SplashWindow`：独立顶层窗口
（`Qt.SplashScreen | FramelessWindowHint | WindowStaysOnTopHint` + `WA_TranslucentBackground`
+ 自绘圆角卡片底），内容是 图标 / `BiliEmojiDD` / 版本胶囊 / 进度文案。
版本号走 `APP_VERSION`（`pyproject.toml` 那个唯一来源），**发版不用改这里**。

### 时序（`main.py`）

```python
apply_font_engine()            # 必须最早：平台插件启动参数
app = QApplication(sys.argv)
apply_app_font(app)            # 必须早于 import MainWindow：getFont 补丁
app.setWindowIcon(app_icon())
setTheme(cfg.theme.value)      # 提到 splash 之前，开屏才跟随亮/暗主题
splash = SplashWindow(); splash.start()
splash.set_message("正在加载界面组件…")
from app.MainWindow import MainWindow          # ← 大头之一
window = MainWindow(on_progress=splash.set_message)   # ← 大头之二，逐页报进度
window.show(); splash.finish(window)
```

三条硬约束：

- **splash 只能 import `config` / `resource` / `theme` / `page_scaffold`**，
  绝不碰 `app.view.*` 或 `app.MainWindow`——否则等于把要遮的开销提到了开屏之前。
  `check_splash.py` 用 `ast` 解析 import 语句做回归断言（不能用「源码里有没有这个词」判，
  docstring 里就会提到 MainWindow）。
- **进度更新走 `repaint()` 不走 `processEvents()`**。构造 `MainWindow` 期间没有事件循环，
  `processEvents()` 会在页面半构造好的时候重入事件派发。只有 `start()` 里那一次
  `processEvents` 是安全的——那时 MainWindow 还不存在。
- **不做动画**。没有事件循环，转圈会僵在某一帧，看着更像卡死；分阶段换文案已经够了。

### 进度文案被挤成一条（踩过）

`QVBoxLayout.setAlignment(Qt.AlignHCenter)` 会让**每个子项只拿到自己的 sizeHint 宽度**，
而 `wordWrap` 的 `QLabel` 的 sizeHint 宽度很窄 → 文案被压成细长一条、折了好几行还看不清。

修法：整个布局**不设**对齐，居中交给每个子项自己的对齐标志；需要铺满整行的
`messageLabel` 则 `addWidget(label)` **不带**对齐标志。另外把它
`setFixedHeight(两行)`，否则每换一次文案整块布局都要重排、面板会抖。
（与「有 QSS 的控件 `setContentsMargins` 会被忽略」是同一类问题：
**带对齐标志的布局项不会被拉伸**，设置页的代理地址框也踩过，见 `setting_page_redesign.md`。）

---

## 回归断言

`scripts/check_splash.py` 覆盖：面板内容（图标 / 品牌名 / 版本号 / 进度文案）与居中位置、
`set_message` 可反复更新、**进度文案铺满可用宽度且最长文案单行放得下**、`finish()` 后不可见、
亮暗两主题各构造一次不崩、**splash 不 import 页面 / 主窗口 / biliemoji**、
`MainWindow.__init__` 收 `on_progress` 且构造五页时真的逐次回调。

`scripts/check_shell.py`（`QT_QPA_PLATFORM=offscreen`）覆盖五件事：
字体加载（含「首选族名而不是文件名排序第一个」）、`getFont` 补丁生效（含 `label.py`
的重绑）、**qss 里硬编码的字体族也被替换**（`PushButton`/`CheckBox` polish 后仍是内置字体）、
`apply_font_engine()` 的三种取值与「不覆盖外部 `QT_QPA_PLATFORM`」、
InfoBar 挂在 `stackedWidget` 且位置在内容区右上角 / 切页后仍可见、
切页一轮事件循环内到位且无残留动画。

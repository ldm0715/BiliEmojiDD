# 设置页改版：Fluent 设置卡片版式

把设置页从「三张大卡片 + 自己拼的表单」改成 Win11 / QFluentWidgets Gallery 那套
**大标题 → 分组标题 → 每行一张「图标 + 标题 / 灰色副标题 + 右侧控件」窄卡片**（参考图
`设置页面重新设计.png`）。

前置阅读：[ui_polish.md](ui_polish.md)、[theme_grid_fixes.md](theme_grid_fixes.md)（主题机制与背景绘制的来龙去脉）。

## 一、背景

改版前 `app/view/setting_page.py` 是三张 `CardWidget`，每张卡内部 `QVBoxLayout` 堆
「标题 + 说明 + 一排控件」，是手工表单：分组感靠卡片边框、说明文字散落在控件之间、
控件宽度各行不齐，和参考图（也就是组件库自带的设置页范式）差得远。

**硬约束（用户要求）：只改界面代码，不动功能代码。** 落实为三条：

1. 所有槽函数 `_on_save` / `_on_verify` / `_on_verify_ok` / `_on_browse` / `_on_open_dir` /
   `_on_save_download` / `_on_theme_changed` / `_sync_theme_combo` / `_sync_theme_icon` **逐字未改**；
2. 槽函数引用的控件**属性名与类型全部保留**（`cookieEdit` / `saveBtn` / `verifyBtn` / `dirEdit` /
   `browseBtn` / `openDirBtn` / `protoCombo` / `hostEdit` / `portSpin` / `threadSpin` /
   `downloadSaveBtn` / `themeCombo`）；
3. `SettingPage` **仍是 `QWidget`**（没改成 `ScrollArea` 子类）——槽里 `notify_*(parent=self, ...)`
   的 InfoBar 定位行为保持不变。

变的只有「控件怎么摆」，以及三处纯展示改动：路径改由卡片副标题显示、按钮文案精简、
未配置 Cookie 时该行默认展开。

## 二、修改文件

| 文件 | 改动 |
|---|---|
| `app/view/setting_page.py` | UI 层重写：`SettingCardGroup` + `SettingCard` / `ExpandGroupSettingCard` + `ScrollArea`；槽函数原样保留 |
| `scripts/check_setting_page.py`（新） | 改版回归断言（功能控件仍在 / 版式 / 展开 / 窄窗口 / 主题 / 透明背景） |
| `scripts/screenshot_pages.py` | 设置页补一张亮色截图，尺寸放大到 900×900 |

## 三、版式与实现

### 1. 页面骨架

```
SettingPage(QWidget)
└── QVBoxLayout(0,0,0,0)
    ├── QHBoxLayout(36, 20, 36, 12) → TitleLabel("设置")
    └── ScrollArea                     透明 + 无边框 + 横向滚动条关
        └── scrollWidget(QWidget, objectName="settingScrollWidget")
            └── ExpandLayout(36, 0, 36, 24), spacing 28
                ├── SettingCardGroup("账号")  3 张卡
                ├── SettingCardGroup("下载")  4 张卡
                └── SettingCardGroup("外观")  1 张卡
```

大标题、分组标题、卡片左边缘三者都落在 x=36（脚本里有断言）。

### 2. 卡片清单与控件归位

| 分组 | 卡片 | 类型 | 右侧控件 |
|---|---|---|---|
| 账号 | B 站 Cookie | `ExpandGroupSettingCard` | 展开区：`cookieEdit` + `saveBtn`「保存」 |
| 账号 | 访问权限 | `_WidgetSettingCard` | `verifyBtn`「验证」 |
| 账号 | 配置文件 | `SettingCard` | 无（副标题就是 config.json 路径） |
| 下载 | 下载目录 | `ExpandGroupSettingCard` | 标题行：`browseBtn`「选择文件夹」+ `openDirBtn`「打开下载文件夹」；展开区：`dirEdit` |
| 下载 | 代理 | `_WidgetSettingCard` | `protoCombo` + `hostEdit` + `portSpin` |
| 下载 | 下载线程数 | `_WidgetSettingCard` | `threadSpin` |
| 下载 | 保存下载设置 | `_WidgetSettingCard` | `downloadSaveBtn`「保存」 |
| 外观 | 应用主题 | `_WidgetSettingCard` | `themeCombo` |

图标：Cookie=`VPN`、访问权限=`CERTIFICATE`、配置文件=`DOCUMENT`、下载目录=`DOWNLOAD`、
代理=`GLOBE`、线程=`SPEED_HIGH`、保存=`SAVE`、主题=`BRUSH`。

### 3. 两个本地 helper

- `_WidgetSettingCard(icon, title, content, widgets, parent)`：库里只有 `PushSettingCard`
  （单个原生 `QPushButton`），而本页要挂 ComboBox / SpinBox / 组件库按钮。做法和上游一样——
  `SettingCard.hBoxLayout` 末尾是 `addStretch(1)`，**之后 `addWidget` 自然靠右排**。
  用组件库控件（`PushButton` / `ComboBox` / `SpinBox`）而不是 `PushSettingCard.button`
  那个裸 `QPushButton`，主题重刷才有保障。
- `_expand_row(widgets)`：`ExpandGroupSettingCard` 展开区的一行，`QHBoxLayout(48, 12, 24, 12)`
  左缩进对齐标题列，**必须 `setFixedHeight`**（展开高度按 `viewLayout.sizeHint()` 算）。

### 4. 为什么 Cookie / 下载目录用可展开卡片

两者的输入框都很宽，行内摆会在最小窗口下把右侧控件挤爆（最小窗口 820 − 侧栏展开 150 −
页边距 72 ≈ 598px 可用）。收起态正好复刻参考图第一行「按钮 + ⌄」的形态：

- Cookie：副标题说明用途，展开填 `cookieEdit` + 保存；**未配置 Cookie 时构造即展开**，
  首次使用不用先找那个 ⌄；
- 下载目录：副标题显示当前路径（`dirEdit.textChanged → card.setContent` 同步），
  标题行挂两颗按钮，展开区仍留可编辑 `dirEdit` —— 只显示路径会丢掉「粘贴路径」这个已有能力，
  属于功能退化，不做。

### 5. 宽度收敛（窄窗口不裁控件）

`protoCombo` 105 / `hostEdit` 150 / `portSpin` 130 / `threadSpin` 110 / `themeCombo` ≥140；
代理副标题精简为「留空不使用代理」，原来那句长提示（socks / 端口范围）挪到卡片 `setToolTip`。
`check_setting_page.py` 在 600px 宽下断言「控件右边缘 ≤ 卡片宽」且「副标题与右侧控件不重叠」。

## 四、踩坑记录

1. **`HeaderSettingCard.addWidget` 只能调一次**（`expand_setting_card.py:128-135`）：它每次都会
   `removeItem(最后一项)` 再重新 `addWidget(self.expandButton)`，调第二次就是把已在布局里的
   `expandButton` 再加一遍。多个控件要先包进一个无边距容器（`_button_box`）再挂。
2. **`ExpandSettingCard` 没有 `setContent`**：它是 `QScrollArea` 子类，标题行在 `.card` 上，
   要写 `card.card.setContent(...)`（本页的 `dirEdit.textChanged` 就是连到这里）。
3. **`ExpandLayout.count()` 数不到卡片**：`addWidget` 进的是内部 `__widgets` 列表，
   `count()` 只数 `addItem` 进来的 QLayoutItem（`expand_layout.py:15-32`），恒为 0。
   要数卡片得遍历子控件（脚本里的 `_cards_of`）。
4. **给 Label 设 `setContentsMargins` 没用**：`TitleLabel` 构造时 `FluentStyleSheet.LABEL.apply(self)`，
   有 QSS 的控件由 `QStyleSheetStyle` 按 QSS 盒模型重算 contentsMargins，手动设的被忽略——
   大标题第一版就因此贴在 x≈2 而不是 36。缩进要走**布局边距**。
5. **`QScrollArea` 必须显式透明**：页面在 `FluentWindow` 的 `stackedWidget` 子树里，靠「自己不画背景」
   透出窗口底色；`QScrollArea` 是原生控件，不透明的话暗色下会露出 palette 的 Base 色块。
   用 Gallery 同款写法：`QScrollArea{border:none;background:transparent}` +
   `.QWidget{background:transparent}`——`.QWidget` 是**类选择器**，只命中 viewport / scrollWidget
   这类纯 QWidget，不会级联到卡片。
6. **`SpinBox` 宽度给少了数字会被裁没**：右侧上下按钮占掉约 64px，第一版给 90px，端口 7890
   一个数字都看不见。端口 130 / 线程 110。
7. **展开动画要等真实时间**：`setExpand` 是 200ms `QPropertyAnimation`，光 `processEvents()`
   不推进时间，测试里第一版「循环 40 次 processEvents」量到的还是收起态高度（假失败）。
   脚本用 `wait_until(cond, timeout)`（processEvents + `time.sleep(0.01)` 轮询）。

## 五、验证

```bash
uv run ruff check .
uv run python -c "import app.MainWindow"

QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py    # 本批次新增
QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py    # 回归：主题下拉 / 侧栏同步
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py    # 回归：第 8 组断言本页按钮
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py      # 出图，与参考图比对
```

`check_setting_page.py` 覆盖 7 组：

1. 12 个功能控件仍在、类型未变、取值正常（`openDirBtn` 文案、`protoCombo.currentData()`、
   `themeCombo.count()==3` 等）；
2. 三个分组 + 每组卡片数 3/4/1 + 大标题 / 分组标题 / 卡片左对齐（36/36/36）；
3. `dirEdit` 改路径 → 下载目录卡副标题同步；
4. Cookie / 下载目录卡展开到位（70 → 148）并能收起复原；未配置 Cookie 时默认展开；
5. 600px 窄窗口下右侧控件不越界、副标题与控件不重叠；
6. 切主题后卡片 QSS 重刷、下拉闭合态图标重新取色；
7. 滚动区显式透明 + 无边框。

四个既有脚本（`check_theme_switch` / `check_improvements` / `check_grid_click` /
`check_image_viewer`）均无回归，全部 **ALL PASSED**。

截图 `screenshots/setting_page_light.png` / `setting_page_dark.png` 与参考图逐行比对；
真实交互（保存 Cookie、验证权限、选择 / 打开目录、保存下载设置、切主题）需人工
`uv run python main.py` 跑一遍。

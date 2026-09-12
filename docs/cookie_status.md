# Cookie 有效性检测与状态灯

主页英雄卡的状态行原本只看「Cookie 填没填」：填过就是「● Cookie 已配置」。Cookie 被
B 站吊销（`SESSDATA` 过期、在别处退出登录、风控）之后主页仍然显示一切正常，用户要等真的
点了「拉取全部表情包」吃到 `AuthRequired` 报错才知道。本文记录这次的修法与两条硬约束。

| 位置 | 职责 |
|---|---|
| `app/components/cookie_status.py` | **状态机 + 信任期 + 探针**。不 import 任何视图 |
| `app/common/config.py` | 三个记录项 `cookieCheckedAt` / `cookieCheckedHash` / `cookieCheckedState` |
| `app/common/theme.py` | 状态灯的 `SUCCESS_TEXT` / `DANGER_TEXT` 两对色 |
| `app/view/home_page.py` | 英雄卡五态状态灯 + `showEvent` 里触发检测 |
| `app/MainWindow.py` | 订阅状态信号 → 有效时静默预拉取全部表情包 |
| `app/view/emoji_page.py` | 标签顺序（全部表情包在前）+ 静默预拉取入口 |
| `app/view/setting_page.py` | 保存 Cookie / 验证 / 退出登录三条路的汇合 |
| `scripts/check_cookie_status.py` | 屏幕外断言 |

## 一、状态机

```python
NO_COOKIE  # 配置里没填 Cookie
CHECKING   # 正在联网检测（只在内存，不落盘）
VALID      # 有效
INVALID    # 失效
UNKNOWN    # 没验过 / 记录过了信任期 / 上次检测网络失败
```

对内有两个读法，**别混**：

- `known_state()` —— 从配置推出来的**结论**（读记录 + 算指纹 + 比信任期），零网络。
  `ensure_checked()` 用它决定「要不要联网」。
- `current_state()` —— **界面该显示的状态**：探针在飞时恒为 `CHECKING`，否则等于
  `known_state()`。英雄卡读它。读 `known_state()` 的话，「正在检测…」会被任何一次
  `refresh()`（配置变更、队列变化、主题切换）立刻盖成「未验证」。

## 二、「每次进主页都检测」与「不要一直检测」怎么调和

用户的两条要求看着矛盾，落点是：**检测逻辑每次都跑，网络探测受信任期约束**。

```python
HomePage.showEvent → cookie_status.ensure_checked()
    ├─ 记录新鲜（下面那张表） → 只广播一次结论，零请求
    └─ 记录过期 / 换过号     → 广播 CHECKING，起一次 nav 探针
```

`ensure_checked()` 开头那个「不是 UNKNOWN 就直接 return」**不是 bug**，别删。

| 结论 | 信任期 | 为什么不对称 |
|---|---|---|
| `VALID` | **7 天** | 服务器确认过的强事实；这就是需求里说的「Cookie 有效期 7 天」 |
| `INVALID` | **30 分钟** | **弱事实**：`nav` 在风控下返回 HTTP 200 + 空 `data`，看起来就是「没登录」（`_payload` 刻意不看业务 code，见 `bili_login.py`）。7 天红灯一旦误判就再也纠正不过来 |
| 网络失败 | **不写记录** | 网络不通不该把灯变红；下次进主页再试 |

失效那一档还有个副作用是好的：真失效时灯每半小时自愈一次，用户重新登录或者修好网络之后
不需要等 7 天。

## 三、探针为什么用 `nav` 而不是 `all_packages`

`bili_login.fetch_account(cookie, proxies=...)`（打 `x/web-interface/nav`）是全项目最轻的
「Cookie 还有效吗」，也是设置页本来就在用的账号信息来源。三种结果映射得干干净净：

| 探针返回 | 状态 | 写记录 |
|---|---|---|
| `Account` | `VALID` | 是 |
| `None`（`isLogin` 为假） | `INVALID` | 是 |
| 抛异常（`LoginFailed` / `LoginDisabled`） | `UNKNOWN` | **否** |

设置页的「验证」仍在用 `all_packages()` —— 它要证明的是「表情包访问权限」，本来就比
「登录还有效吗」更严格。两者汇合到同一份记录，**且有方向**：

- `all_packages` 成功 → `note(VALID)`（**只提升**）；
- 失败遇 `AuthRequired` → `invalidate()`（作废记录，让下次 `nav` 重新判），**不直接判红**
  ——那次失败也可能是网络或风控。

`nav` 是唯一能写出 `INVALID` 的地方。任何一条需要登录的操作吃到 `AuthRequired`
（表情包页拉全量）都会 `invalidate()`，所以「记录里挂着 7 天的旧绿灯、Cookie 其实已经
被吊销」这种情况最多撑到用户下一次动手。

## 四、状态灯

英雄卡的状态行还是那个 `CaptionLabel` + `●` 字符，只是文案与颜色跟着状态走：

| 状态 | 文案 | 颜色 |
|---|---|---|
| `NO_COOKIE` | `● 未配置 Cookie` | `ORANGE_TEXT` |
| `CHECKING` | `● 正在检测 Cookie…` | `SECONDARY_TEXT` |
| `VALID` | `● Cookie 有效` | `SUCCESS_TEXT` |
| `INVALID` | `● Cookie 已失效` | `DANGER_TEXT` |
| `UNKNOWN` | `● Cookie 已配置（未验证）` | `SECONDARY_TEXT` |

- 映射是 `home_page.cookie_light(state)` 这个**纯函数**（模块级 `_COOKIE_LIGHT` 字典），
  断言脚本直接读它，不从 `QLabel` 回读像素。
- `UNKNOWN` 的文案**刻意保留「已配置」**：改动前只要填过就显示「已配置」，改成「状态未知」
  对「离线 + 有 Cookie」的用户是信息退化。
- **主按钮一个字没改**：只看「填没填」（失效时仍是「开始使用」→ 表情包页），状态灯才反映
  「有没有用」。这是刻意的取舍 —— 不把用户挡在主页。

## 五、Cookie 有效 → 后台静默预拉取全部表情包

```python
cookie_status.emit(VALID) → MainWindow._on_cookie_state
    ├─ 二次核对 known_state()（防迟到回调：探针在飞时用户可能已登出）
    └─ QTimer.singleShot(0, emojiPage.ensure_all_packages)
```

- **不切页**：用户留在主页，等他进表情包页时列表已经就绪。延到事件循环第一拍是为了
  不把「读缓存 + 建 20 张卡片」的开销塞进窗口构造。
- `_AllPackagesTab.ensure_loaded()` 幂等：有数据 / 正在拉 / 没 Cookie 都直接返回。
  每次进主页都会广播一次状态，这条路径被反复叫到很正常。
- 静默路径**不弹**那条「已使用本地缓存」InfoBar —— 不然每次启动都糊用户一脸，而他此刻
  还在主页上、压根没点过任何东西。
- 命中 24 小时缓存时零请求（`cache.py` 的口径没动）。

## 六、标签顺序：全部表情包在前

`「全部表情包」` 现在是第一个标签**且是默认页**，`「按 ID 查询」` 退到第二位。
「按 ID 查询」在没输入 ID 时是片空白，不该是这页的门面。

- 默认项正好是 index 0，`Pivot` 指示条的初始位置天然正确 —— 这也是不在 `resizeEvent` /
  未显示时程序化定位的理由（未实现的控件量不到几何）。**别把默认项改成第二项。**
- `setCurrentItem` 不触发 `onClick`、`onClick` 也不移动指示条，初始化两句都要写。
- 顺带把 `filter_by` 的行为说清楚了：Cookie 有效时全量已被预拉取，所以主页带关键词跳过来
  通常**真的会立刻过滤**（以前多半只是回填关键词）。

## 七、踩坑

- **带参信号不能直接接无参槽**：`signal_bus.cookieStateChanged` 载着一个 `str`，
  `connect(self.refresh)` 会 `TypeError`，必须包一层 `_on_cookie_state`（或 lambda）。
- **`_inflight` / `_loading` 必须在 `on_finished` 里清**：`run_task` 的成功与两条异常路
  都会发 `finished`，只挂 `on_success` 的话失败一次就永久卡死，探针和预拉取都不再重试。
  断言脚本里的 `run_task` 桩同理，**必须回调 `on_finished`**。
- **`current_state()` 不能退化成 `known_state()`**：见第一节。
- **指纹是防「写错人」的**：`note(state, cookie)` 收的是**发起请求时的 Cookie 快照**，
  worker 回来时配置可能已经变了（用户在这期间登出 / 换号）。快照与当前 Cookie 不一致就
  不写记录 —— 否则会把上一个账号的结论写到新账号头上。
- **重填同一个 Cookie 也要 `invalidate()`**：`_apply_cookie` 里这次作废**不看值有没有变**。
  「我又填了一遍」的意图就是「重新验证」，不能因为指纹恰好没变就把上一盏红灯继续摆下去。
- **`qconfig.set` 值没变时不落盘**：`cookieCheckedAt` 每次都不同所以没问题，但别在
  `known_state()` 的非 UNKNOWN 路径上调 `note()`，否则每次进主页都写一次盘。
- **失效信任期不能给 7 天**：见第二节，`nav` 在风控下会假报「没登录」。
- **`refreshBtn` 以前失败后不恢复**（顺手修掉的）：它在 `_request_all` 里被 disable，而
  只有成功路径会重新 enable，一次失败就永久禁用。现在统一在 `on_finished` 里按
  「有没有数据」给。
- **状态灯的颜色不是照抄 `mirror_card` 的胶囊底色**：那两档是给白字压的深底，当小字号
  文字色时暗色一侧对比度不够，所以 `SUCCESS_TEXT` / `DANGER_TEXT` 的暗色一侧提亮了。
- **屏幕外脚本要关联网**：凡是会显示主页（`HomePage.showEvent`）或构造 `MainWindow`
  的脚本都要 `cookie_status.set_enabled(False)`，与 `updater.set_enabled(False)` 同一套
  理由。`set_enabled(False)` 是**一个任务都不提交**，不是「提交了再抛异常」。

## 八、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_cookie_status.py
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_home_page.py
```

`check_cookie_status.py` 全程零网络（`run_task` 换同步桩、`fetch_account` 换假函数，
「有没有发请求」就是桩被叫了几次），覆盖：五态映射（含网络失败不写记录）、
两条信任期的边界、指纹作废与迟到回调、不叠任务与失败后不卡死、`set_enabled(False)`、
预拉取的幂等与缓存命中零请求、`MainWindow` 接线（有效 → 拉一次且不切页）、标签顺序。

`check_home_page.py` 覆盖状态灯的五态文案与配色，以及写入记录后灯真的跟着变色。

**需要人工确认的部分**：真机 `uv run python main.py` 看灯在亮 / 暗两个主题下是否好认
（暗色一侧的对比度只有人眼能判），以及启动后预拉取那一下在主页上有没有可见卡顿。
真失效场景（把 `SESSDATA` 改坏）没法自动化 —— 那要真实网络。

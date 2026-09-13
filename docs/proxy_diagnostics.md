# 代理：只认设置页里的那一个地址

## 背景

「设置里的代理」= 往 requests 里填 `proxies=` 参数，**不是**接管一个全局代理软件。
但此前的实现是按后者的思路做的，留下三个问题：

1. **系统代理仍在偷偷生效（真 bug）。** 上一轮已经删掉了 `ProxyEnvManager`
   （不再写 `HTTP_PROXY` 环境变量），但 requests 自己那条读环境的路一直开着：

   ```python
   # requests/sessions.py:845
   if self.trust_env:                                   # 默认 True
       env_proxies = get_environ_proxies(url, ...)      # -> urllib.request.getproxies()
       for k, v in env_proxies.items():
           proxies.setdefault(k, v)                     # 塞进「请求级」proxies
   # requests/sessions.py:863
   proxies = merge_setting(proxies, self.proxies)       # 请求级覆盖会话级
   ```

   `urllib.request.getproxies()` 在 Windows 上先读环境变量，读不到就**读注册表里的
   IE / 系统代理**——Clash、v2ray 开「系统代理」写的正是那里。拿到的值被塞进请求级
   proxies，再由 `merge_setting` **覆盖**我们显式传的 `session.proxies`。结果：
   设置页留空时应用会偷偷走系统代理，填了也可能被系统代理顶掉。

2. **UI 是按「配代理软件」做的**：协议下拉 + 主机 + 端口 + 测试 + 用户名 + 密码，
   六个控件；`app/common/proxy.py` 里八个函数只为拼装 / 拆解这六个控件的值而存在。

3. **没有总开关**，「不用代理」只能靠「主机名留空」间接表达。

## 改动

### 1. `trust_env = False`：新增 `app/common/net.py`

所有 `Emoji` / `Dress` / `BiliClient` / `Downloader` 都从这个模块建，工厂保证两件事：
**代理只来自设置页**、**Session 不读环境变量与系统代理**。

| 工厂 | 说明 |
|---|---|
| `current_proxies()` | 当前该用的代理；开关关闭或地址为空 → `None` |
| `make_client(cookie, proxies)` | `BiliClient` + `session.trust_env = False` |
| `make_emoji(cookie, proxies)` | 走 `Emoji(client=...)`（上游支持预构建客户端） |
| `make_dress(cookie, proxies)` | 走 `Dress(client=...)` |
| `make_downloader(max_workers, on_progress, proxies)` | `_NoEnvDownloader` 覆写 `_build_session()`，复用上游的 retry / adapter 配置 |

`proxies` 的默认值是**哨兵 `_FROM_CFG` 而不是 `None`**：漏传就自动读配置，
不会像以前那样静默变成直连。`thumb` / `video_cache` 这类 worker 仍在主线程读好
`current_proxies()` 再显式传进去（worker 不碰 `cfg`）。

联网入口一共十处，全部改走工厂：

| 入口 | 位置 |
|---|---|
| 搜索 / 表情包详情 / 收藏集详情 | `app/components/api_cache.py` |
| 批量下载（元数据 + 文件） | `app/components/download_runner.py` |
| 缩略图 | `app/components/thumb.py` |
| 收藏集视频缓存 | `app/components/video_cache.py` |
| 代理连通性自检 | `app/components/proxy_probe.py` |
| Cookie 验证 / 账号信息 / 全部表情包 | `app/view/setting_page.py`、`app/view/emoji_page.py` |
| 扫码登录（二维码申请 / 轮询 / `nav`） | `app/components/bili_login.py` |
| Cookie 有效性检测（进主页按信任期探一次） | `app/components/cookie_status.py` |
| 直播间表情（表情 / 房间信息 / 主播信息） | `app/components/live_emoji.py` |

**新增联网代码一律走这些工厂**，别再直接 new 上游对象——`scripts/check_proxy_hint.py`
第 3 节会检查每个工厂产出的 session `trust_env is False`。

> ⚠️ 行为变化：**关掉代理开关就是真直连**，哪怕 Windows 开着系统代理。
> 原本靠系统代理才能访问 B 站的环境，现在必须把地址填进设置页。

### 2. 代理开关 + 单地址框

配置项 `proxy_enabled`（`ConfigItem("Download", "proxyEnabled", False, _StrictBoolValidator(False))`），
**一律默认关**，没有任何「老配置里有地址就自动置开」的迁移（为什么删掉见下）。

#### 代理开关为什么不再自动置开（真实报障）

用户反馈「装新版本后，代理开关默认是打开的」。两次排查的结论：

- **真·全新安装（家目录没有 `config.json`）一直是关的** —— 把文件读取打桩成
  `FileNotFoundError` 之后构造设置页实测：开关 `isChecked()=False`、地址框与「测试」disabled、
  副标题「已关闭：所有请求直连」。界面侧也没有取反、没有读错配置项。
- 变开的唯一来源是那段**迁移**：老配置有 `Download.proxy` + 没有 `proxyEnabled` 键
  + 没有 `App.schema` → 首次启动置开并落盘。它的前提是「文件里有地址 ⇒ 用户正在用代理」，
  这个前提只在 0.1.0 成立（那一版没有开关，有地址就通过环境变量走代理）。
  之后就只剩「用户以前填过、后来关掉了」——而**关开关不清空地址**，残留地址会长期
  留在文件里；再加 `packaging/installer.nsi` 卸载**默认保留** `%APPDATA%\biliEmojiDD`，
  用户口中的「全新安装」其实带着老配置。
- 手动保存那套让情况更糟：老版本要按「保存下载设置」才写盘，用户在框里清空了地址却
  没点保存，**文件里那个旧值一直留着而界面看着是干净的** —— 等到装新版本，迁移读到的
  正是这个残留地址。

现在**迁移已删除**（`config.py::_migrate()` 里只剩 `schema_version` 那套熄火机制），
设置页那一组也没有「保存」按钮了：开关 / 地址框 / 下载目录 / 线程数全部改完即落库，
界面和文件不会再有机会不一致。

代价与恢复：真在代理环境里的 0.1.x 老用户升级后变直连、可能连不上 B 站 ——
但**地址还在地址框里**（关开关不清空地址），拨一下开关就恢复，报错文案里也有
「当前未使用代理（代理开关已关闭）」的提示（`app/common/exception.py::_proxy_suffix`）。

> 顺带一条上游坑：**别用 `BoolValidator`**。它是 `OptionsValidator([True, False])`，而
> `OptionsValidator.correct()` 把非法值兜成 `options[0]` —— **恒为 `True`**，与这一项自己的
> 默认值无关。配置文件里出现 `"proxyEnabled": "false"` / `null` 这类非布尔值时，
> 开关会被读成「开」并被 `_ensure_persisted()` 固化成 `true`。本项目改用
> `config.py::_StrictBoolValidator(默认值)`：非布尔值回落**这一项自己的默认值**。

#### 迁移必须靠显式 schema 标记熄火（同一类坑的历史记录）

`schema_version`（`ConfigItem("App", "schema", 0)`）+ `CONFIG_SCHEMA` 是迁移的熄火标记，
`_migrate()` 只在 `schema < CONFIG_SCHEMA` 时跑且**只改内存**，落盘统一交给
`_ensure_persisted()`。**不能靠「写完盘那个键就存在了」自我熄火**：
`qconfig.set` 在值没变化时直接 return、根本不落盘（上游 `config.py:299`），
旧写法因此会永久武装，把用户明确关掉的开关反复翻回「开」（真实报障）。
`_ensure_persisted()` 比一次「文件原文 vs `qconfig.toDict()`」，不一致就补写
（首次运行 / 新增字段 / 文件被改坏之后各写一次，之后自然收敛）。

回归断言在 `scripts/check_proxy_hint.py` 第 7 节（开子进程按不同初始 `config.json` 各起一次
配置模块）：完全没有配置文件 → 关；老配置里有地址 → **仍然是关**；用户关掉的开关重启仍是关；
`proxyEnabled` 写成 `"false"` / `null` / `0` 都读成关；默认 True 的项（`autoCheck` / `gif`）
非法值仍回落它们各自的默认值。

设置页代理行三个控件：`SwitchButton` + `LineEdit` + 「测试」。
**开关关着时地址框与测试按钮都 disable**（`_sync_proxy_enabled`）——「没开代理」这件事
在界面上就是确定的，不用去猜「留空算不算不用」。

`_current_proxy()` 是唯一的取值 / 校验入口（「测试」用；以前「保存」也共用，那个按钮已删）：

| 情况 | 返回 |
|---|---|
| 开关关 | `""`（不使用代理） |
| 开着、地址为空 | `None` + 提示（不会静默存成直连） |
| 开着、地址含空格 | `None` + 提示 |
| 其余 | `normalize_proxy(text)`（无协议前缀补 `http://`） |

**代理即时生效：下载组根本没有「保存」按钮**（2026-09 删掉了那张 `saveDownloadCard`）。
开关一拨就 `qconfig.set`，地址框 `editingFinished`（回车 / 焦点移开）就落库，
下载目录与线程数也是同一套。这条是踩出来的：

> 在框里把代理换成新 IP、按了「测试」，然后去用应用——其它请求全是
> `ProxyError`，报错里的「当前代理」还是**旧 IP**。看起来像「代理没接进请求」，
> 实际上代理接得好好的，只是那一栏改完没点保存，`cfg.proxy` 还是旧值。

手动保存那套还有更阴的一面：**界面和配置文件可以不一致** —— 用户在框里清空了地址
却没点保存，文件里那个旧值会一直留着（这就是下面「开关被自动打开」的源头）。删掉按钮、
全部改成即时生效后，这个不一致窗口就没了。

自动保存是静默的：地址含空格就不写也不弹提示（切个焦点弹一次太吵），报错留给显式的
「测试」。空地址照写——`current_proxies()` 本来就把「开着但地址为空」当直连，
写进去才能让界面与实际行为一致。

**卡片副标题显示当前生效的代理**（读 `cfg`，不是读输入框，密码打码）：

| 状态 | 副标题 |
|---|---|
| 开关关 | 已关闭：所有请求直连，不读系统代理 |
| 开着、有地址 | 当前生效：`http://u:***@1.2.3.4:8080` |
| 开着、地址为空 | 已开启但地址为空，仍是直连 |

输入框里是「正在编辑的值」，副标题是「其它请求真正在用的值」——把后者摆出来，
省得对着报错猜。
**关开关不清空地址**，下次打开还在。

### 3. `proxy.py` 砍成纯字符串工具

只剩 `PROXY_PLACEHOLDER` / `normalize_proxy` / `parse_proxy` / `redact_proxy`（141 → 60 行）。
删掉的：`ProxyParts`、`PROXY_SCHEMES`、`build_proxy`、`split_proxy`、`split_proxy_auth`、
`proxy_scheme`、`is_socks`、`pysocks_available`——它们全是为那六个控件服务的。

地址就是 requests 认的那种 URL：`scheme://[user:pass@]host[:port]`。
scheme 指**代理自身说什么协议**（`http` / `https` / `socks5` / `socks5h`），
不是被代理流量的协议——绝大多数本地代理软件是 `http`。
`redact_proxy` 保留「认证段按**最后一个 `@`** 切」这条：`@` 是合法密码字符，
按第一个切会切错（`urlsplit` 就是这么切的，所以不用它）。

**`PySocks` 依赖保留**：地址框里写 `socks5://127.0.0.1:7891` 就靠它，删了会变成一个
看不懂的 `InvalidSchema`。它不是为旧 UI 存在的。

### 4. `cause_hint` 精简

`biliemoji.client` 把所有 requests 异常压成 `NetworkError(f"网络错误：{类型名}")`，
真正的原因只留在 `__cause__` 里。`cause_hint` 沿 `__cause__` / `__context__` 最多走 6 层
收集 (类名, 消息)，按关键字翻成可行动的中文，拼进提示正文并附上当前代理（密码打码）。

| 底层特征 | 提示 |
|---|---|
| `ProxyError` + `407` / `Proxy Authentication Required` | 代理要求认证，把 `user:pass@` 写进地址 |
| `ProxyError` + refused / 10061 / unreachable | 连不上代理，ping 通不代表该端口上有代理 |
| `ProxyError` + timeout | 连接代理超时 |
| `ProxyError` 兜底 | 地址 / 端口不对，或那个端口上根本不是代理（并提一句 B 站全是 HTTPS、代理得支持 CONNECT） |
| `InvalidSchema` / `InvalidProxyURL` | 地址格式不对 |
| `SSLError` / `ConnectTimeout` / `ConnectionError` | 对应中文 |

407 必须**排在其它 ProxyError 判断之前**：`Tunnel connection failed: 407 ...`
两个特征会同时出现。删掉的是为旧 UI 写的三条（「把协议下拉改成 HTTP」「缺 PySocks」
「CONNECT 单列一条」）。

`_proxy_suffix()` 跟着开关走：关 → 「当前未使用代理（代理开关已关闭）」。

### 5. 「测试」按钮

`app/components/proxy_probe.py::probe_proxy(proxy_text)` 用**当前控件里的值**
（不是已保存值）打一次不需要 Cookie 的收藏集搜索接口，`DressNotFound` 也算通
（请求确实打通了）。只在 worker 线程调用（`run_task`）。

```
PROBE_URL  = https://api.bilibili.com/x/garb/v2/mall/home/search
PROBE_NAME = 收藏集搜索接口
```

`PROBE_URL` 刻意抄一份常量而不是 import `biliemoji.dress._SEARCH_URL`：提示文案要展示它，
上游改私有常量时这里最多是文案过时，不会 `ImportError` 把测试整个崩掉。

**失败不走通用的 `show_bili_error`。** 通用提示报的是「网络错误 + `cfg.proxy`」，
可两者在测试场景下都不对：标题看不出是测试失败，地址报的还是**配置里那个**
（用户可能刚改了输入框还没保存，测的和报的是两个值）。所以设置页有自己的
`_on_proxy_failed`（按下「测试」时先 `_autosave_proxy()`，保证测的就是生效的）：

```
代理测试失败
  <cause_hint 翻出来的因果>
  测试地址：http://u:***@18.162.158.218:80      ← _probed_proxy，按下「测试」时记下的
  测试接口：GET https://api.bilibili.com/x/garb/v2/mall/home/search
```

`duration=NEVER_DISMISS`（带诊断信息，让用户自己读完关掉）。成功提示同样写明接口。
卡片 tooltip 里也列了 `PROBE_URL`——按之前只写「发一次真实请求」，看不出发去了哪。

> **`duration=0` 不是「不消失」而是「立刻消失」。** 上游
> `InfoBar.showEvent` 里是 `if self.duration >= 0: QTimer.singleShot(self.duration, fadeOut)`
> ——0 表示 0 毫秒后淡出，**负数**才永不消失。第一版写成 `duration=0`，表现就是
> 诊断提示一闪而过、根本读不到。`notify.py` 现在导出具名常量 `NEVER_DISMISS = -1`，
> `exception.py` 里未知异常那条（同样写的 0）一并修了。

**ping 通的地址为什么可能用不了**：B 站接口全是 HTTPS，走 HTTP 代理时 requests 必须先发
`CONNECT api.bilibili.com:443` 建隧道。只会转发明文 `http://` 绝对 URI 的代理会拒掉
CONNECT，报 `Tunnel connection failed: 4xx`。ping 只验证主机在线，既不验证端口上有代理，
也不验证它支持 CONNECT。判断能不能用，就按「测试」。

### 6. 「测试中」的加载环

按下「测试」到出结果之间要发一次真实请求（超时 15s），没有反馈会以为按钮没响应。
`_BusyPushButton`（`setting_page.py`）在按钮里嵌一个 `IndeterminateProgressRing`：
忙碌时文案变「测试中」、环转在文字左边，同时 disable 防重复点。三个细节：

- **空格数按空格实际宽度现算**，不写死。文字前面用空格给环腾位置，而空格宽度随字体变
  （Segoe UI 7px、LXGW 等宽 10px），写死几个空格换字体就会让环压在文字上。
- **宽度按忙碌态预留**（`reserve_busy`），否则一转圈按钮变宽、整行跟着跳。
- 收环后 `_sync_proxy_enabled(开关状态)` 重新对齐可用性——测试期间开关可能已被拨掉，
  `set_busy(False)` 无条件 `setEnabled(True)` 会让关着代理的按钮变成可点。

不覆写 `PushButton.__init__`（库里是 `singledispatchmethod`，`(text, parent)` 重载内部会
再调一次 `__init__`），初始化走 `_postInit()` 钩子。


## 布局上的一个坑

代理行的地址框一开始写的是 `setFixedWidth(240)`，窄窗口（600px 视口）下整行被顶出卡片
右边缘、测试按钮还和输入框重叠。根因是 `_WidgetSettingCard` 用
`addWidget(w, 0, Qt.AlignRight)` 挂控件——**带对齐标志的布局项拿的是 sizeHint 宽度、
不会被压缩**。改法：横向 `Expanding` 的控件改用 `addWidget(w, 1)` 按 stretch 加，
地址框 `setMinimumWidth(150)` + `setMaximumWidth(320)`，窄窗口能缩、宽窗口能长。

> 旧版其实也溢出，只是 `check_setting_page.py` 的断言量的是 `portSpin`（四个控件里的
> 第三个）而不是最右边的测试按钮，一直没被发现。新断言量的是能代表整行的控件。

## 相关

- 回归断言：`scripts/check_proxy_hint.py`（不联网，九节 81 条）。第 3 节检查每个工厂产出的
  session `trust_env is False`；第 5b 节验证下载组即时生效（没有保存按钮）与副标题三态、
  以及「清空地址框会真的把地址从配置里清掉」；第 5c 节打桩 `notify_error` 确认失败提示报的是
  被测地址、写明接口、且 `duration` 为负；**第 7 节按不同的初始 `config.json` 各起一次配置
  模块**，验代理一律默认关、布尔项的非法值不会回落成「开」。
  下载组即时生效的断言在 `scripts/check_setting_page.py` 第 3b 节，加载环在同文件第 1b 节。
- `app/common/proxy.py` / `app/common/net.py` 的模块注释里记了同样的要点。

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

联网入口一共七处，全部改走工厂：

| 入口 | 位置 |
|---|---|
| 搜索 / 表情包详情 / 收藏集详情 | `app/components/api_cache.py` |
| 批量下载（元数据 + 文件） | `app/components/download_runner.py` |
| 缩略图 | `app/components/thumb.py` |
| 收藏集视频缓存 | `app/components/video_cache.py` |
| 代理连通性自检 | `app/components/proxy_probe.py` |
| Cookie 验证 / 全部表情包 | `app/view/setting_page.py`、`app/view/emoji_page.py` |

**新增联网代码一律走这些工厂**，别再直接 new 上游对象——`scripts/check_proxy_hint.py`
第 3 节会检查每个工厂产出的 session `trust_env is False`。

> ⚠️ 行为变化：**关掉代理开关就是真直连**，哪怕 Windows 开着系统代理。
> 原本靠系统代理才能访问 B 站的环境，现在必须把地址填进设置页。

### 2. 代理开关 + 单地址框

配置项 `proxy_enabled`（`ConfigItem("Download", "proxyEnabled", False, BoolValidator())`），
**默认关**。老配置迁移：`config.py::_migrate_proxy_enabled()` 在 `qconfig.load` 之后读一次
JSON，若 `Download` 段里**没有** `proxyEnabled` 键而 `proxy` 非空，则置 True——
以前填过代理的人升级后不会突然断网。只认「键不存在」这一种情况，用户自己关掉开关后
键就存在了，不会被地址非空翻回来。

设置页代理行三个控件：`SwitchButton` + `LineEdit` + 「测试」。
**开关关着时地址框与测试按钮都 disable**（`_sync_proxy_enabled`）——「没开代理」这件事
在界面上就是确定的，不用去猜「留空算不算不用」。

`_current_proxy()` 是唯一的取值 / 校验入口（保存与测试共用）：

| 情况 | 返回 |
|---|---|
| 开关关 | `""`（不使用代理） |
| 开着、地址为空 | `None` + 提示（不会静默存成直连） |
| 开着、地址含空格 | `None` + 提示 |
| 其余 | `normalize_proxy(text)`（无协议前缀补 `http://`） |

**代理即时生效，不进「保存下载设置」那套。** 开关一拨就 `qconfig.set`，地址框
`editingFinished`（回车 / 焦点移开）就落库。这条是踩出来的：

> 在框里把代理换成新 IP、按了「测试」，然后去用应用——其它请求全是
> `ProxyError`，报错里的「当前代理」还是**旧 IP**。看起来像「代理没接进请求」，
> 实际上代理接得好好的，只是那一栏改完没点保存，`cfg.proxy` 还是旧值。

自动保存是静默的：地址含空格就不写也不弹提示（切个焦点弹一次太吵），报错留给显式的
「保存」与「测试」。空地址照写——`current_proxies()` 本来就把「开着但地址为空」当直连，
写进去才能让界面与实际行为一致。

**卡片副标题显示当前生效的代理**（读 `cfg`，不是读输入框，密码打码）：

| 状态 | 副标题 |
|---|---|
| 开关关 | 已关闭：所有请求直连，不读系统代理 |
| 开着、有地址 | 当前生效：`http://u:***@1.2.3.4:8080` |
| 开着、地址为空 | 已开启但地址为空，仍是直连 |

输入框里是「正在编辑的值」，副标题是「其它请求真正在用的值」——把后者摆出来，
省得对着报错猜。「保存下载设置」现在只管下载目录与线程数。
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

- 回归断言：`scripts/check_proxy_hint.py`（不联网，八节 60 条）。第 3 节检查每个工厂产出的
  session `trust_env is False`；第 5b 节验证「改完不点保存也生效」与副标题三态；
  第 5c 节打桩 `notify_error` 确认失败提示报的是被测地址、写明接口、且 `duration` 为负。
  加载环的断言在 `scripts/check_setting_page.py` 第 1b 节。
- `app/common/proxy.py` / `app/common/net.py` 的模块注释里记了同样的要点。

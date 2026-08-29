# 代理：只走 `proxies=` 参数 + 可行动的失败诊断

## 背景

用户填了一个远程 HTTP 代理服务器，报 `网络错误：ProxyError
(url=https://api.bilibili.com/x/vas/dlc_act/lottery_home_detail)`，无从下手。
排查下来有三个独立问题：

1. **应用在偷偷设全局代理。** `ProxyEnvManager` 会把配置写进 `HTTP_PROXY` /
   `HTTPS_PROXY` / `ALL_PROXY` 环境变量。这不只是「多余」——requests 的
   `Session.merge_environment_settings` 会把环境变量塞进**请求级** proxies，
   再由 `merge_setting(请求级, 会话级)` 让请求级**覆盖** `session.proxies`，
   等于显式传进去的值被环境变量顶掉。而且是进程级副作用，影响同进程里所有库。
2. **有一个联网入口漏传了 proxies。** `thumb.py` 的缩略图 worker
   `BiliClient(cookie=...)` 没带 `proxies`，一直靠上面那套环境变量兜底。
3. **失败原因被吞掉了。** `biliemoji.client` 把所有 requests 异常压成
   `NetworkError(f"网络错误：{类型名}")`，真正的原因留在 `__cause__` 里没人看。

## 改动

### 1. 删掉全局代理，全部走 `proxies=`

`app/common/proxy.py` 移除 `ProxyEnvManager` / `proxy_env`，`main.py` 与
`setting_page._on_save_download` 里的 `remember()` / `apply()` 一并删除。
代理只以 `proxies=` 参数显式传给 requests，联网入口一共七处：

| 入口 | 位置 |
|---|---|
| 搜索 / 表情包详情 / 收藏集详情 | `app/components/api_cache.py` |
| 批量下载（元数据 + 文件） | `app/components/download_runner.py`（`Emoji`/`Dress` + `Downloader`） |
| 缩略图 | `app/components/thumb.py`（**本次补上**） |
| 收藏集视频缓存 | `app/components/video_cache.py` |
| 代理连通性自检 | `app/components/proxy_probe.py` |
| Cookie 验证 / 全部表情包 | `app/view/setting_page.py`、`app/view/emoji_page.py` |

`thumb.py` 的 cookie 与 proxies 都在**主线程** `request()` 里读一次再交给 worker，
worker 不碰 `cfg`。回归断言在 `scripts/check_proxy_hint.py` 第 3、4 节：
保存代理不写任何代理环境变量；打桩 `BiliClient.__init__` 确认三个入口都带了 proxies。

### 2. 代理认证（用户名 / 密码）

远程代理常要认证，缺凭据时代理回 407，requests 同样抛 ProxyError。设置页「下载」
分组新增「代理认证」一行（`用户名` + `PasswordLineEdit` 密码），拼进地址：
`scheme://user:pass@host:port`。

- `build_proxy(scheme, host, port, username="", password="")` 对用户名 / 密码做
  `quote(safe="")` 百分号转义——`:@/` 都是合法密码字符，不转义 requests 会切错。
- `split_proxy_auth(text) -> ProxyParts(scheme, username, password, host, port)`
  按**最后一个 `@`** 切认证段（密码里可以有 `@`），与 requests / urllib3 一致；
  刻意不用 `urlsplit`，它按第一个 `@` 切。
- `split_proxy()` 保留旧签名（只给 scheme/host/port），认证段不会混进 host。
- `redact_proxy()` 把密码换成 `***` 供提示展示——**不能复用 `build_proxy`**，
  否则 `***` 也被转义成 `%2A%2A%2A`。

### 3. SOCKS

`PySocks>=1.7.1` 进 `dependencies`（此前没装，socks 地址直接 `InvalidSchema`）。
协议下拉从 HTTP/HTTPS 扩到 `PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")`
（`socks5h` = 域名解析也交给代理）。保存前若选了 socks 而 `pysocks_available()`
为假，拒绝保存并提示。

### 4. 失败原因翻译

`app/common/exception.py` 新增 `cause_hint(exc)`：沿 `__cause__` / `__context__`
最多走 6 层收集 (类名, 消息)，按类名 + 关键字匹配出可行动的中文，
拼在 `NetworkError` / `DownloadError` 的提示正文里，并附上当前代理
（`redact_proxy`，密码打码）。

| 底层特征 | 提示 |
|---|---|
| `ProxyError` + `407` / `Proxy Authentication Required` | 代理要求认证，去设置页填用户名密码 |
| `ProxyError` + `Tunnel connection failed` | 代理拒绝建立 HTTPS 隧道（CONNECT），这类代理用不了 |
| `ProxyError` + `only use HTTP` | 代理只讲明文 HTTP，把协议改成 HTTP |
| `InvalidSchema` + `SOCKS` | 需要 PySocks |
| `ProxyError` + refused / 10061 / unreachable | 连不上代理，ping 通不代表该端口上有代理 |
| `SSLError` / `ConnectTimeout` / `ConnectionError` | 对应中文 |

407 必须**排在隧道判断之前**：`Tunnel connection failed: 407 ...` 两个特征同时出现。

### 5. 「测试」按钮

代理卡右侧加「测试」，走 `app/components/proxy_probe.py::probe_proxy(proxy_text)`：
用**当前控件里的值**（不是已保存值）打一次不需要 Cookie 的 `search_dress_typed`，
`DressNotFound` 也算通（请求确实打通了）。失败交给 `show_bili_error`，
上面那张表会给出确切原因。只在 worker 线程调用（`run_task`）。

## 关于「ping 得通的代理为什么用不了」

**B 站接口全是 HTTPS。** 走 HTTP 代理访问 HTTPS 目标时，requests 必须先向代理发
`CONNECT api.bilibili.com:443` 建隧道。只会转发明文 `http://` 绝对 URI 的代理
（或者压根不是代理、只是个网站）会拒掉 CONNECT，报
`Tunnel connection failed: 4xx`。ping 只验证主机在线，既不验证端口上有代理，
也不验证它支持 CONNECT。判断一个地址能不能用，用设置页的「测试」按钮。

实测 `18.163.99.118:80`：`CONNECT` 返回 `400 Bad Request`；用它代理明文
`http://` 目标时，返回的是它自己 nginx 的内容（`{"code":1001,"msg":"Unauthorized"}`
或站点首页），并没有转发到目标站——即它不是一个可用的转发代理。

## 相关

- `app/common/proxy.py` 模块注释里记了三条易错点（scheme 语义 / CONNECT / 认证）。
- 回归断言：`scripts/check_proxy_hint.py`（不联网）。

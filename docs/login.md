# 扫码登录

B 站 Cookie 的自动化获取路径：**二维码扫码 → 拿到 Cookie → 立即落盘生效 → 显示账号**。
手动粘贴保留为退路 —— 扫码接口是社区逆向记录下来的，B 站随时可能改。

| 位置 | 职责 |
|---|---|
| `app/components/bili_login.py` | 网络层：申请二维码 / 轮询状态 / 查账号信息。纯逻辑，不 import 任何 Qt 控件 |
| `app/components/login_dialog.py` | `LoginDialog`（二维码 + 轮询状态机）、`_QrCodeView`、`AccountAvatar` |
| `app/view/setting_page.py` | 「账号」组的「B 站账号」卡：按登录态切换按钮、账号展示、Cookie 落盘与退出登录 |
| `app/common/net.py` | `make_bili_session()` —— 扫码请求专用的会话工厂 |
| `pyproject.toml` | 新依赖 `segno`（纯 Python、零依赖），只用来算二维码编码矩阵 |

## 一、接口与状态机

用的是 B 站 **web 端**扫码登录（TV 端那套返回的是 `access_token`，不是我们要的 Cookie）：

```
GET https://passport.bilibili.com/x/passport-login/web/qrcode/generate
    → data.url（二维码内容）、data.qrcode_key（32 字符密钥）
GET https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=...
    → data.code 即状态
```

密钥 **180 秒**过期（`QRCODE_TTL_SECONDS`）。`data.code` 到 `LoginState` 的映射：

| code | 状态 | 界面 |
|---|---|---|
| `86101` | `WAITING` | 请使用 B 站手机客户端扫码 |
| `86090` | `SCANNED` | 已扫码，请在手机上确认登录 |
| `0` | `CONFIRMED` | 收尾关窗，把 Cookie 交给调用方 |
| `86038` | `EXPIRED` | 二维码已失效，点「刷新二维码」重来 |

**认不出的码一律当失效**（`_state_from_payload`）。卡在「等待扫码」里转圈是最难排查的
表现，而判失效是可恢复的 —— 对话框上有刷新按钮。字段缺失（`data` 里没有 `code`）同理。

确认成功后服务端在响应头里写 `SESSDATA` / `bili_jct` / `DedeUserID` / `DedeUserID__ckMd5` / `sid`。

> **`data.url` 的形态会变**：2026-09 实测是
> `https://account.bilibili.com/h5/account-h5/auth/scan-web?navhide=1&...`，
> 而早前的记录是 `passport.bilibili.com/h5-app/passport/login/scan?...`。
> 我们**只把它当二维码内容原样编码，从不解析它**，所以换域名 / 换路径都影响不到这里。
> 会解析的只有**登录成功响应**里的 `data.url`（那个 crossDomain 地址），是另一回事。

## 二、Cookie 提取走两条路径

`_cookie_from_headers` 优先（响应头是权威来源），`_cookie_from_cross_domain` 兜底：
成功响应的 `data.url` 是个 crossDomain 跳转地址，几个 cookie 以 query 参数挂在上面。
两条路互为备份 —— `Set-Cookie` 要靠 cookie jar 解析，遇到 Domain 属性、重定向或
jar 被清过时未必留得下；而这个 URL 就在同一个响应体里。

**回退路径刻意不做 URL 解码**：cookie 值在 URL 里就是编码形式（`SESSDATA` 里含 `%2C`
这类转义），解码后反而与 `Set-Cookie` 那条路的取值对不上，拼出来的 Cookie 登不上去。

最后按固定顺序 `SESSDATA → bili_jct → DedeUserID → DedeUserID__ckMd5 → sid` 拼成
`"k=v; k=v"`（`_COOKIE_FIELDS` / `_join_cookie`），只收已知且非空的键。
`SESSDATA` 排最前是为了人工排查时一眼能看到。

## 三、为什么必须新开一个 `make_bili_session`

扫码要读 **`Set-Cookie` 响应头**，而 `BiliClient.get_json()` 只返回 `resp.json()`，
够不着响应头 —— 所以不能用 biliemoji 现成的客户端。

但它仍然走 `net.py` 这个唯一工厂（项目硬规矩：所有联网都走工厂，代理只来自设置页、
`trust_env = False`）。`make_bili_session` 与 `make_session` 的区别是 UA：

- `make_session` 用的是 `BiliEmojiDD/0.1.2`（GitHub 检查更新用，那个接口不带 UA 会 403）
- `make_bili_session` 用**浏览器 UA + `Referer: https://www.bilibili.com/`**

**别把这两个 UA 合并**：拿 `BiliEmojiDD/0.1.2` 打 passport 接口大概率被风控挡掉。
UA 版本档位与 biliemoji 内部的 UA 池保持一致，免得同一账号在服务端看来是两套客户端。

## 四、轮询的线程模型与关窗竞态

一个 `QTimer(1000ms)` 同时管两件事：刷新倒计时文案、按 2 秒间隔发一次 poll。
每次 poll 是独立的 `run_task`，结果经信号回主线程 —— 与全应用一致，worker 不碰控件。

三条守卫，缺一不可：

1. **`_polling` 标志防堆任务**：上一次 poll 还没回来就跳过这次 tick。网络慢时不然会
   每 2 秒叠一个任务上去。
2. **`_closed` 标志防迟到回调**：`run_task` 起来了就取消不掉，关窗那一刻在飞的那次
   请求还会回来。`_on_poll` / `_on_qr_ready` / `_on_poll_failed` 都要先判它。
   `_shutdown()` 挂在**四个出口**上（幂等，重复调用无害）：

   | 出口 | 为什么不能少 |
   |---|---|
   | `reject` / `accept` | 正常关闭。**必须同步收**——上游 `done()` 给 dialog 挂了淡出动画，`hide()` 是动画之后才发生的，等 `hideEvent` 会晚一拍 |
   | `closeEvent` | `close()` 这条路 |
   | `hideEvent` | **父窗口关闭时 Qt 只是把子窗口隐藏掉**，`closeEvent` / `accept` / `reject` 一个都不走（实测 `_closed` 仍为 False）。少了它就会留下一个看不见、却还在每 2 秒轮询 B 站的定时器 |
3. **失败不弹全局提示**：网络抖一下就弹一条 `show_bili_error` 的 InfoBar 太吵，而且会
   盖住对话框。改成在对话框里显示「网络不稳，正在重试…」，下一次 tick 自然重试。

`proxies` 由调用方在**主线程**读好 `current_proxies()` 再传给对话框（`_refresh_account`
里也是先读后传）—— worker 线程不碰 `cfg`，与 `thumb` / `video_cache` 同一条规矩。

## 五、二维码绘制

`segno` 只负责编码：`qr_matrix()` 拿 `matrix_iter(scale=1, border=4)` 的 0/1 矩阵。
绘制是 `_QrCodeView` 自己用 `QPainter` 画小方块 —— 不引 Pillow、不做 PNG 解码、
按整数倍像素画方块所以缩放不糊。

- **`border=4` 的 quiet zone 不能省**：手机靠它把码区和背景分开，贴边画的码经常扫不出来。
- **配色恒为白底黑块，不跟主题**：扫码靠固定对比度，深色主题下把底也调暗有扫不出来的
  风险。别"顺手"接上主题化。
- 矩阵先**预渲染进一张 `QPixmap`**（按 `devicePixelRatio` 放大），`paintEvent` 只剩一次
  blit —— 否则一帧要画上千个小方块。

> 组件库没有二维码控件。`FluentIcon.QRCODE` 只是图标字体里的一个字形，画出来是个二维码
> 图案，不能编码数据。也试过用 `PixmapLabel` 承载，但它的 `setPixmap` 用
> `setFixedSize(pixmap.size())`（物理尺寸）配 `drawPixmap` 平滑拉伸，高 DPI 下尺寸和缩放
> 都不受控 —— 二维码糊一个模块就扫不出来。所以这里是**自绘**，不是没找组件库。

## 六、界面：一张卡两种形态

「账号」组里只有一张 **「B 站账号」** 卡，按登录状态切换 —— **不并排放「Cookie 卡 + 账号卡」
两张**：都登录了还摆着「手动填写」，看着就多余。

| 状态 | 卡片长什么样 |
|---|---|
| 未登录 | 副标题「未登录 — 部分功能需要登录」＋ 右侧 `[手动填写] [扫码登录]` |
| 已登录、账号信息还没到 | 副标题「已登录」＋ 头像 ＋ `[退出登录]` |
| 已登录、账号信息已到 | 副标题「昵称 · UID xxx」＋ 头像 ＋ `[退出登录]` |

- **三个按钮各自连自己的槽，靠显隐切换**，不做「一个按钮换文案换行为」那种状态耦合
  （那种写法迟早出双触发）。
- **`_apply_cookie()` 是扫码 / 手动填写 / 退出登录三条路的唯一汇合点**：落盘 + 刷卡片 +
  发 `configChanged` + 异步取账号。三个入口各自只负责弹窗与提示语。
- 「手动填写」是 `CookieDialog`：一个输入框（预填当前 Cookie）+ 一行「去哪儿复制」的提示。
  组件库的 `LineEdit` **没有 `setError`**，做不了红框错误态，所以空输入用「保存」禁用表达。
- 「退出登录」走组件库 `MessageBox` 二次确认，**只清 `cookie` 与 `account_*`**；
  下载目录、图片缓存、已下载的文件都不动（缓存本来就按 cookie 指纹隔离，不会串号）。
- 「验证」验的是 **`cfg.cookie`（生效值）**，不再读某个输入框 —— 它就是配置里那一个值。

## 七、账号信息（昵称 / 头像）

`fetch_account()` 打 `https://api.bilibili.com/x/web-interface/nav`，读
`data.isLogin` / `uname` / `mid` / `face`。存进配置的 `account_name` / `account_mid` /
`account_face` 三项。

- **启动时不联网刷新**：设置页只显示上一次登录留下的缓存信息（`_sync_account_card`）。
  省一次请求，也免得屏幕外脚本被拖住。
- 取到的时机：扫码登录成功、点「保存」、点「验证」。都走 `_refresh_account`。
- **拿不到就静默**（`on_error=lambda _e: None`）—— 昵称头像只是展示，不该因为它失败
  弹错误提示。`_on_account(None)` 也不覆盖已有昵称。
- **换账号先清旧的**：`_apply_cookie` 在 Cookie 值变了的时候先清掉 `account_*` 三项。
  否则新的 nav 请求回来之前会继续显示**上一个账号**的昵称，比显示「已配置 Cookie」
  更容易误导。

头像用组件库的 `AvatarWidget`（圆形裁剪 + 中心裁切），外面套一层「**没图就整个藏起来**」：
未登录时 `setVisible(False)` —— 没有账号就没有头像位，卡片上只剩「未登录」和扫码按钮
（「有 Cookie 但还没拿到头像 URL」的中间态同样隐藏，等 `nav` 回来才显形）。
不做灰色占位图：那是块假信息，用户看到的应该是「这儿没有东西」。

⚠️ 喂图必须**把控件尺寸钉回去**，见下面坑点清单第一条 —— 这是本项目里最容易漏的一处。

## 八、登录之后：这个 Cookie 还有效吗

扫码成功只说明「那一刻」可用。`SESSDATA` 会自己过期，也可能在别处退出登录后被吊销。
「现在还灵不灵」这件事由 `app/components/cookie_status.py` 统一管，本文件只负责**拿到** Cookie：

- 探针就是这里的 `fetch_account()`（打 `nav`）—— 返回 `Account` = 有效、返回 `None` =
  失效、抛异常 = 不知道（**网络不通不判失效**）；
- 主页英雄卡的状态灯读它（有效绿 / 失效红 / 未配置橙），进主页时按需检测一次；
- 结论有信任期（有效 7 天、失效 30 分钟），期内进主页一个请求都不发；
- 设置页三条路都并进同一份记录：`_apply_cookie`（保存 / 扫码 / 退出）**无条件作废**，
  `_on_account`（那次 nav 的结果）给出结论，「验证」成功只提升为有效。

完整推导、配色与踩坑见 [cookie_status.md](cookie_status.md)。

## 九、坑点清单

- **`ImageLabel.setImage` 会把控件尺寸改成图片尺寸**（上游 `label.py:300` 无条件
  `setFixedSize(self.image.size())`），而 `AvatarWidget` 的整套绘制都建立在
  「控件边长 = 2*radius」上。所以 `AccountAvatar._adopt()` 喂完图必须
  `setFixedSize(SIZE, SIZE)` 钉回去 —— 否则一张 500x320 的头像会把控件**撑成
  500x320**，圆形裁剪与等比缩放全部失效，头像变成一块长方形的原图。

  > 这个坑很阴：早先喂的是 40x40 的占位图，尺寸恰好等于目标值，所以一直没暴露；
  > 换成真头像（非正方形大图）立刻现形。断言要喂**非正方形的大图**并**真的渲染一次**
  > （`grab()` 后量像素），只断言 `avatar.image.size()` 是抓不到的。
  >
  > 顺带一条：`grab()` 出来的四角**不是透明的**（控件有自己的 QSS 背景色），
  > 圆形裁剪的判据是「圆外没被头像染上」，不是 `alpha == 0`。

- **`MessageBoxBase.yesButton` 默认连到 `accept()`**：这里改成「刷新二维码」，
  必须先 `clicked.disconnect()`，否则点一下弹窗当场消失。
- **收摊不能只挂 `closeEvent`**：父窗口关闭时 Qt 走的是「隐藏子窗口」，那几个回调
  都不发。查这个的教训是——写断言时**先 `show()` 再 `hide()`**，`hide()` 对没显示过的
  控件是 no-op，不 show 就测了个寂寞（`check_login.py` 第 5 节最后一条）。
- **`MaskDialogBase.__init__` 直接读 `parent.width()`** 来铺遮罩，`parent=None` 会在
  构造里 `AttributeError`。所以 `LoginDialog` 的 `parent` 是**必填位置参数**，
  传 `page.window()`。
- **对话框要留引用**（`self._loginDialog`）：只 `show()` 不持有的话 Python 包装器会被
  回收，对话框在轮询到一半时凭空消失。
- **别覆写 `AvatarWidget.__init__`**：`ImageLabel.__init__` 是库自实现的
  `singledispatchmethod`，子类加必填参数会在它内部第二次调用时 `TypeError`。
  用 `_postInit()` 钩子，它在 `self.image` 初始化之后、`setBorderRadius` 之后执行。
- **`_WidgetSettingCard` 的副标题文案要短**：这一行在窄窗口（约 600px）下要和头像、
  按钮并排，太长会把行顶出卡片。`scripts/check_setting_page.py` 第 5 节有几何断言。
- **`qconfig.set` 的值没变时不落盘**（上游行为）：`_apply_cookie` 里"值变了才清账号信息"
  的判断就是靠这个语义 —— 值没变说明还是同一个号，不该把昵称清掉。

## 十、验证

```bash
QT_QPA_PLATFORM=offscreen uv run python scripts/check_login.py       # 扫码登录专项
QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py # 设置页版式（新增账号卡）
QT_QPA_PLATFORM=offscreen uv run python scripts/check_cookie_status.py # 登录之后的 Cookie 状态
```

`check_login.py` 覆盖：状态码映射、Cookie 双路径拼装（含「不解码」）、
`set_enabled(False)` 后零请求、二维码 quiet zone 与像素采样、对话框四个状态的迁移与
关窗竞态、账号卡三态显隐与退出登录、手动填写对话框、头像控件（含非正方形大图的圆形渲染）。

**真机扫码没法自动化** —— 手机扫屏幕那一步得人工跑一次 `uv run python main.py`，
确认能扫出来、文案按「未扫码 → 已扫码 → 成功」走、昵称头像显示正确。

## 十一、接口失效了怎么办

这套接口**不是 B 站官方公开 API**，是社区逆向记录（bilibili-API-collect）。B 站改动后
表现通常是：`generate` 直接返回错误、`poll` 一直 `86101`、或者能登录但 Cookie 不认。

所以**手动粘贴 Cookie 的入口必须一直留着**（`setting_page.py` 的 Cookie 卡）。
真失效时的处理顺序：先确认 Cookie 卡手动粘贴仍然可用 → 再去对接口。

`bili_login.py` 里三个 URL 是模块常量，改动只动那一处。

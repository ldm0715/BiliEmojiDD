"""代理连通性自检：拿一次真实的 B 站请求验证代理是否真的能用。

「ping 得通」只能说明主机在线，说明不了那个端口上有没有代理、代理讲不讲得了 HTTPS。
所以设置页的「测试」按钮走这里：用**当前控件里的代理值**（不是已保存值）打一次
不需要 Cookie 的收藏集搜索接口，成功与否直接反映代理可用性。

失败时原样把 `BiliError` 抛出去，由设置页的 `_on_proxy_failed` 组装提示——那边会带上
**被测的那个地址**（不是配置里的）与这里的接口地址，`cause_hint` 再沿 `__cause__`
翻出「连不上代理」「代理要求认证」之类的确切原因。

**只在 worker 线程调用**（走 `run_task`）。
"""
from __future__ import annotations

from biliemoji import DressNotFound

from app.common.net import make_dress
from app.common.proxy import parse_proxy

# 与 biliemoji.dress._SEARCH_URL 一致。刻意抄一份常量而不是 import 私有名：
# 提示文案要展示它，上游改私有常量时这里最多是文案过时，不会 ImportError 崩掉测试。
PROBE_URL = "https://api.bilibili.com/x/garb/v2/mall/home/search"
PROBE_NAME = "收藏集搜索接口"
_PROBE_KEYWORD = "2233"  # 随便一个必有结果的关键词，接口不需要 Cookie


def probe_proxy(proxy_text: str) -> str:
    """用给定代理打一次真实请求；通了返回描述文字，不通抛 BiliError。

    proxies 显式传入而不是读配置：测的是**输入框里还没保存的那个值**。
    """
    proxies = parse_proxy(proxy_text)
    try:
        make_dress(proxies=proxies).search_dress_typed(1, keyword=_PROBE_KEYWORD)
    except DressNotFound:
        pass  # 请求本身通了，只是没搜到结果——对连通性而言算成功
    channel = "通过代理" if proxies else "直连"
    return f"已{channel}访问 {PROBE_NAME}\nGET {PROBE_URL}"

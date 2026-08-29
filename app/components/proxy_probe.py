"""代理连通性自检：拿一次真实的 B 站请求验证代理是否真的能用。

「ping 得通」只能说明主机在线，说明不了那个端口上有没有代理、代理讲的是不是选中的
协议。所以设置页的「测试」按钮走这里：用**当前控件里的代理值**（不是已保存值）打一次
不需要 Cookie 的搜索接口，成功与否直接反映代理可用性。

失败时原样把 `BiliError` 抛出去交给 `show_bili_error`——那边会沿 `__cause__` 翻出
「代理只讲 HTTP」「连不上代理」之类的确切原因。

**只在 worker 线程调用**（走 `run_task`）。
"""
from __future__ import annotations

from biliemoji import Dress, DressNotFound

from app.common.proxy import parse_proxy

_PROBE_KEYWORD = "2233"  # 随便一个必有结果的关键词，接口不需要 Cookie


def probe_proxy(proxy_text: str) -> str:
    """用给定代理打一次真实请求；通了返回描述文字，不通抛 BiliError。"""
    proxies = parse_proxy(proxy_text)
    try:
        Dress(proxies=proxies).search_dress_typed(1, keyword=_PROBE_KEYWORD)
    except DressNotFound:
        pass  # 请求本身通了，只是没搜到结果——对连通性而言算成功
    return "已通过代理成功访问 B 站接口" if proxies else "已直连访问 B 站接口（未使用代理）"

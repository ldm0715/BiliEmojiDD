"""收藏集 / 装扮判别与 dlc id 读取（绕开 biliemoji 的 broken typed 字段）。

`DressCollectionSummary` 的 `dlc_act_id` / `dlc_lottery_id` / `id` 因 API 返回字符串、
被 `_optional_int` 拒收而恒为 None，`is_collection` 恒为 False。判别一律从 `raw` 读取：

- `raw["properties"]["type"]`：`"dlc_act"` = 收藏集、`"ip"` = 装扮（已用真实数据验证）。
- `raw["part_id"]`：0 = 收藏集、6 = 装扮（兜底用）。
"""
from __future__ import annotations


def props(summary) -> dict:
    """summary.raw['properties']，缺失 / 非 dict 返回 {}。"""
    raw = getattr(summary, "raw", None) or {}
    p = raw.get("properties")
    return p if isinstance(p, dict) else {}


def part_id(summary) -> int | None:
    """top-level part_id，优先 raw；兼容模型字段。"""
    raw = getattr(summary, "raw", None) or {}
    v = raw.get("part_id")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return getattr(summary, "part_id", None)


def item_type(summary) -> str | None:
    """type：'dlc_act'=收藏集 / 'ip'=装扮；缺失返回 None。"""
    return props(summary).get("type")


def dlc_ids(summary) -> tuple[str | None, str | None]:
    """(dlc_act_id, dlc_lottery_id)，字符串原样返回，可直接传 certain_lottery_typed。"""
    p = props(summary)
    act = p.get("dlc_act_id")
    lot = p.get("dlc_lottery_id")
    return (
        str(act) if act not in (None, "") else None,
        str(lot) if lot not in (None, "") else None,
    )


def is_collection(summary) -> bool:
    """可下载收藏集：type=='dlc_act' 且带 act/lottery id；无 type 时兜底旧逻辑。"""
    p = props(summary)
    t = p.get("type")
    has_ids = bool(p.get("dlc_act_id")) and bool(p.get("dlc_lottery_id"))
    if t == "dlc_act":
        return has_ids
    if t == "ip":
        return False
    # 兜底：没有 type 字段时按 part_id==0 且带 id 判断
    return part_id(summary) == 0 and has_ids


def category_name(summary) -> str:
    """卡片类别徽标文字。"""
    return "收藏集" if is_collection(summary) else "装扮"

"""屏幕外验证「检查更新 + 下载加速 + 版本胶囊」（不联网）。

1. 版本号从 `pyproject.toml` 读，`is_newer` 的各种边界；
2. `pick_asset` 只认安装包 exe；2b `parse_digest` 只认 sha256（别的算法宁可当没有）；
3. **镜像**：前缀拼接、`download_urls` 三种配置下的候选顺序、校验和不走镜像；
   3b/3c/3d 自定义源的增删改与拖动排序（改完保持位置、删掉不留悬空引用）；
   3e 测速三档文案；
4. 设置页「关于」组：在最上面、五张卡、开关与下拉读写配置；
   4b 加速卡展开区的行、按钮显隐、行内编辑与拖动落库；
5. `_on_release` 分支：非新版只改副标题，新版弹 `UpdateDialog`；
6. `UpdateDialog`：markdown 渲染出内容、**yesButton 已从上游 accept() 断开**（否则一点就关窗）；
7. `changelog.extract` 取得到内容、缺版本会抛；
8. `make_session` 的 `trust_env is False`（新增的联网入口）；
9. SHA-256 校验：**优先用 Release JSON 的 asset digest（零额外请求）**、老版本才退回
   直连取清单（取不到就抛 UpdateError 而不是裸异常）、对得上放行、改一个字节就拒绝；
   9b 失败文案不被 `cause_hint` 顺异常链盖掉；
10. 版本号胶囊：三处都是 InfoBadge 且留了白。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_update.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 必须赶在 import app.* 之前隔离 APPDATA，否则会写脏真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

import requests
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import ExpandSettingCard, SettingCard, SettingCardGroup, qconfig

from app.common.config import APP_NAME, GH_MIRROR_CHAIN, cfg
from app.common.exception import cause_hint
from app.common.net import make_session
from app.common.version import is_newer, parse_version, project_version
from app.components import cookie_status, updater
from app.components.update_dialog import UpdateDialog, _failure_detail
from app.components.updater import (
    LATENCY_GOOD_MS,
    TIER_ERROR,
    TIER_FAIR,
    TIER_GOOD,
    MirrorSpeed,
    ReleaseInfo,
    UpdateError,
    add_custom_mirror,
    all_mirrors,
    download_urls,
    expected_checksum,
    is_custom,
    mirror_chain,
    mirrored,
    normalize_mirror,
    orderable_mirrors,
    parse_digest,
    parse_sums,
    remove_custom_mirror,
    set_mirror_order,
    update_custom_mirror,
)

updater.set_enabled(False)  # 本脚本不联网

sys.path.insert(0, str(ROOT / "packaging"))
from changelog import VersionNotFound
from changelog import extract as extract_changelog

from app.view.setting_page import SettingPage

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_until(cond, timeout: float = 3.0) -> None:
    """轮询等后台任务落地（光 processEvents 不推进真实时间）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
        settle(2)
        time.sleep(0.01)
    settle(2)


def _cards_of(group: SettingCardGroup) -> list:
    return [
        w for w in group.children() if isinstance(w, (SettingCard, ExpandSettingCard))
    ]


print("== 1. 版本号来源与比较 ==")
version = project_version()
check(version not in ("", "unknown"), f"版本号读自 pyproject.toml（{version}）")
check(
    project_version(ROOT / "不存在.toml") == "unknown",
    "读不到文件时返回 'unknown'——它解析不出版本号，检查更新会安静地不提示",
)
check(parse_version("v1.2.3-beta.1") == ((1, 2, 3), "beta.1"), "剥 v 前缀、切出预发布段")
cases = [
    ("v0.2.0", "0.1.0", True, "主版本段更大"),
    ("v0.1.1", "0.1.0", True, "修订段更大"),
    ("0.1.0", "0.1.0", False, "同版本不算新"),
    ("0.0.9", "0.1.0", False, "更旧不算新"),
    ("v1.2", "1.2.0", False, "位数不等时补零对齐（1.2 == 1.2.0）"),
    ("1.0.0", "1.0.0-rc.1", True, "正式版新于同号预发布"),
    ("1.0.0-rc.1", "1.0.0", False, "预发布不新于同号正式版"),
    ("garbage", "0.1.0", False, "脏 tag 一律不提示（宁可漏，不能天天弹）"),
    ("", "0.1.0", False, "空 tag 同理"),
]
for remote, local, want, why in cases:
    check(is_newer(remote, local) is want, f"is_newer({remote!r}, {local!r}) = {want} —— {why}")

print("== 2. 资产挑选 ==")
exe = {
    "name": "BiliEmojiDD-Setup-0.2.0.exe",
    "browser_download_url": "https://x/e.exe",
    "size": 1,
    # GitHub 会给每个资产算一个摘要，随 Release JSON 一起返回（大写十六进制）
    "digest": "sha256:" + "A1" * 32,
}
zipped = {"name": "BiliEmojiDD-0.2.0-win64.zip", "browser_download_url": "https://x/z.zip", "size": 2}
sums = {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/s.txt", "size": 3}
check(updater.pick_asset([zipped, exe, sums]) is exe, "优先挑安装包 exe，跳过 zip 与校验和")
check(updater.pick_asset([zipped, sums]) is None, "没有 exe 返回 None（界面退化成「打开发布页」）")
info = updater._release_info(
    {
        "tag_name": "v0.2.0",
        "body": "## 新增\n- 一条更新说明",
        "published_at": "2026-08-30T10:00:00Z",
        "html_url": "https://github.com/ldm0715/BiliEmojiDD/releases/tag/v0.2.0",
        "assets": [exe, zipped, sums],
    }
)
check(info.tag == "v0.2.0" and info.has_installer, "解析出 tag 与安装包地址")
check(info.published == "2026-08-30", f"发布日期只留 YYYY-MM-DD（{info.published}）")
check(info.sums_url == sums["browser_download_url"], "认出 SHA256SUMS.txt 资产")
check(info.asset_digest == "a1" * 32, f"取到官方 digest 并转小写（{info.asset_digest[:12]}…）")
old = updater._release_info({"tag_name": "v0.0.9", "assets": [zipped, sums]})
check(old.asset_digest == "" and old.sums_url, "老 Release 没有 digest 字段时留空，退回清单文件")

print("== 2b. digest 解析：只认 sha256 ==")
hex64 = "ab" * 32
for raw, want, why in [
    (f"sha256:{hex64}", hex64, "标准形态"),
    (f"SHA256:{hex64.upper()}", hex64, "大小写都认（GitHub 回的是大写）"),
    ("sha512:" + "ab" * 64, "", "**别的算法拒收**——与 _stream_to 算的 sha256 对不上，放过去会变成永远校验失败"),
    ("sha256:", "", "只有算法头没有值"),
    ("sha256:xyz", "", "值里混了非十六进制字符"),
    (hex64, "", "没有算法头——不知道是什么算法，不收"),
    ("", "", "空串"),
    (None, "", "字段是 null（GitHub 对没算过的老资产会给 null）"),
]:
    got = parse_digest(raw)
    check(got == want, f"parse_digest({str(raw)[:24]!r}…) = {want!r} —— {why}")

print("== 3. 下载加速镜像 ==")
url = "https://github.com/ldm0715/BiliEmojiDD/releases/download/v0.2.0/setup.exe"
check(
    mirrored(url, "https://gh-proxy.com/") == "https://gh-proxy.com/" + url,
    "前缀式拼接：镜像 + 完整原始 URL",
)
check(mirrored(url, "https://gh-proxy.com") == "https://gh-proxy.com/" + url, "镜像末尾有无斜杠都不会拼出 //")
check(mirrored(url, "") == url, "不使用镜像时原样返回")
qconfig.set(cfg.gh_mirror, "")
check(download_urls(url) == [url], "直连：候选只有原始地址")
qconfig.set(cfg.gh_mirror, "https://ghfast.top/")
picked = download_urls(url)
check(
    picked == ["https://ghfast.top/" + url],
    f"选了具体镜像就只走它——失败要能看出是镜像的问题（{len(picked)} 个候选）",
)
qconfig.set(cfg.gh_mirror, "auto")
auto = download_urls(url)
check(len(auto) == 1 + len(GH_MIRROR_CHAIN), f"自动：直连 + {len(GH_MIRROR_CHAIN)} 个镜像（实际 {len(auto)}）")
check(auto[0] == url, "自动模式直连优先")
check(all(u.endswith(url) for u in auto[1:]), "其余候选都是同一个原始地址加不同前缀")
qconfig.set(cfg.gh_mirror, "")

print("== 3b. 自定义加速源：地址规范化 / 增删改 ==")
cases = [
    ("gh-proxy.com", "https://gh-proxy.com/", "无协议补 https://"),
    ("https://x.io", "https://x.io/", "结尾补斜杠"),
    ("  https://y.io/  ", "https://y.io/", "去空白且不重复补斜杠"),
    ("http://z.cc/a/", "http://z.cc/a/", "带路径的前缀原样保留"),
    ("ftp://n.o", "", "非 http(s) 拒收——前缀式反代就是拿 URL 拼的"),
    ("a b", "", "含空格拒收"),
    ("https://", "", "只有协议头拒收"),
    ("", "", "空串拒收"),
]
for raw, want, why in cases:
    got = normalize_mirror(raw)
    check(got == want, f"normalize_mirror({raw!r}) = {want!r} —— {why}（实际 {got!r}）")

added = add_custom_mirror("mine.example")
check(added == "https://mine.example/", f"添加时顺手规范化（{added}）")
check(added in [v for _, v in all_mirrors()], "新源进了下拉列表")
check(is_custom(added), "被认作自定义源（可改可删）")
check(not is_custom("https://gh-proxy.com/"), "内置源不算自定义（不可改不可删，但可排序）")
for bad, why in [("mine.example", "同一个源"), ("https://gh-proxy.com/", "内置源")]:
    try:
        add_custom_mirror(bad)
    except ValueError:
        check(True, f"重复添加被拒（{why}）")
    else:
        check(False, f"重复添加竟然成功了（{why}）")
try:
    add_custom_mirror("ftp://nope")
except ValueError:
    check(True, "非法地址被拒")
else:
    check(False, "非法地址竟然加进去了")

print("== 3c. 顺序：可拖动，且 auto 就按这个顺序试 ==")
default_order = orderable_mirrors()
check(default_order[-1] == added, f"新加的排在末尾（{default_order}）")
set_mirror_order([added, *[m for m in default_order if m != added]])
check(orderable_mirrors()[0] == added, "重排后落库并生效")
check(mirror_chain() == orderable_mirrors(), "auto 的尝试顺序 == 用户排的顺序")
qconfig.set(cfg.gh_mirror, "auto")
check(download_urls(url)[1] == added + url, "auto 第一个镜像候选就是排在最前的那个")
qconfig.set(cfg.gh_mirror, "")
# 顺序表只记顺序不记成员：塞进不存在的源要被过滤掉，否则删掉的源会复活
set_mirror_order([added, "https://ghost.example/", "https://gh-proxy.com/"])
check(
    "https://ghost.example/" not in orderable_mirrors(),
    f"顺序表里不存在的源被过滤（{orderable_mirrors()}）",
)
check(
    set(orderable_mirrors()) == set(default_order),
    "没在顺序表里的源自动补在后面，不会凭空消失",
)

print("== 3d. 编辑与删除 ==")
qconfig.set(cfg.gh_mirror, added)
edited = update_custom_mirror(added, "better.example")
check(edited == "https://better.example/", f"改地址返回规范化结果（{edited}）")
check(orderable_mirrors()[0] == edited, "**改完位置不变**（先算顺序再改成员，否则会被排到末尾）")
check(cfg.gh_mirror.value == edited, "正在使用的那个跟着改过去，不会指向已不存在的地址")
try:
    update_custom_mirror(edited, "https://gh-proxy.com/")
except ValueError:
    check(True, "改成已存在的源被拒")
else:
    check(False, "改成已存在的源竟然成功了")
remove_custom_mirror(edited)
check(edited not in orderable_mirrors(), "删除后从列表消失")
check(cfg.gh_mirror.value == "", "删掉正在用的源会退回直连，不留悬空引用")

print("== 3e. 测速分档 ==")
check(
    MirrorSpeed("m", 100, TIER_GOOD).text.startswith("良好"),
    f"良好档文案（{MirrorSpeed('m', 100, TIER_GOOD).text}）",
)
check(
    MirrorSpeed("m", 2000, TIER_FAIR).text.startswith("一般"),
    f"一般档文案（{MirrorSpeed('m', 2000, TIER_FAIR).text}）",
)
fail = MirrorSpeed("m", -1, TIER_ERROR, "超时")
check(fail.text == "错误 · 超时", f"错误档显示原因而不是 -1 ms（{fail.text}）")
check(LATENCY_GOOD_MS > 0, f"良好档阈值是个正数毫秒（{LATENCY_GOOD_MS}）")

print("== 4. 设置页「关于」组 ==")
page = SettingPage()
page.resize(900, 760)
page.show()
settle()
groups = [w for w in page.scrollWidget.children() if isinstance(w, SettingCardGroup)]
titles = [g.titleLabel.text() for g in groups]
check(titles[:1] == ["关于"], f"「关于」排在最上面（实际 {titles}）")
check(
    titles == ["关于", "账号", "下载", "缓存", "外观"],
    f"五个分组依次为 关于/账号/下载/缓存/外观（实际 {titles}）",
)
check(len(_cards_of(groups[0])) == 5, f"「关于」组五张卡（实际 {len(_cards_of(groups[0]))}）")
for name in ("repoCard", "updateCard", "autoUpdateCard", "mirrorCard", "licenseCard"):
    check(hasattr(page, name), f"卡片属性 {name} 在（断言脚本与槽函数按名取用）")
check("ldm0715/BiliEmojiDD" in page.repoCard.contentLabel.text(), "代码仓库卡显示 owner/repo")
check(version in page.updateCard.contentLabel.text(), f"检查更新卡显示当前版本（{page.updateCard.contentLabel.text()!r}）")

page.autoUpdateSwitch.setChecked(False)
settle()
check(cfg.auto_check_update.value is False, "自动检查开关一拨即落库")
page.autoUpdateSwitch.setChecked(True)
settle()
check(cfg.auto_check_update.value is True, "拨回来也即时生效")

# 上游 addItem 的第二个位置参数是 icon 不是 userData，写错 currentData() 恒为 None
datas = [page.mirrorCombo.itemData(i) for i in range(page.mirrorCombo.count())]
check(all(d is not None for d in datas), f"镜像下拉每一项都有 userData（{datas}）")
page.mirrorCombo.setCurrentIndex(2)
settle()
check(
    cfg.gh_mirror.value == datas[2] and cfg.gh_mirror.value.startswith("http"),
    f"选中镜像即时写配置（{cfg.gh_mirror.value!r}）",
)
page.mirrorCombo.setCurrentIndex(0)
settle()
check(cfg.gh_mirror.value == "", "选回「不使用」恢复直连")
# ExpandSettingCard 是 QScrollArea 子类，没有 setContent，副标题在 .card 上（写错直接崩）
check(
    "直接从 GitHub 下载" in page.mirrorCard.card.contentLabel.text(),
    f"加速卡副标题显示生效值（{page.mirrorCard.card.contentLabel.text()!r}）",
)

print("== 4b. 加速卡展开区：行、按钮、拖动 ==")
card = page.mirrorCard
card.setExpand(True)
settle()
custom = add_custom_mirror("row-test.example")
card.reload()
settle()
values = [r.value for r in card._rows]
check(values[0] == "", f"直连排第一（{values}）")
check(values[1:] == orderable_mirrors(), "其余行 == 排好序的加速源，一一对应")
check(custom in values, "自定义源出现在展开区")
direct, first_builtin = card._rows[0], card._rows[1]
custom_row = next(r for r in card._rows if r.value == custom)
check(not direct.draggable and direct.handle.isHidden(), "直连行没有拖动手柄（它谈不上顺序）")
check(first_builtin.draggable, "内置源可以拖")
check(first_builtin.editBtn.isHidden() and first_builtin.removeBtn.isHidden(), "内置源没有编辑 / 删除")
check(
    not custom_row.editBtn.isHidden() and not custom_row.removeBtn.isHidden(),
    "自定义源有编辑与删除按钮",
)
# 原地编辑：行内换成输入框，确认后保持位置
custom_row.begin_edit()
settle()
check(custom_row.is_editing(), "点编辑后进入行内编辑态")
check(custom_row.edit.text() == custom, "输入框预填当前地址，不用重打一遍")
check(not custom_row.okBtn.isHidden() and custom_row.badgeHolder.isHidden(), "编辑态换成确定 / 取消按钮")
custom_row.cancel_edit()
settle()
check(not custom_row.is_editing() and custom_row.editBtn.isHidden() is False, "取消后回到常态")

before = [r.value for r in card._rows]
last = card._rows[-1]
card._on_drag_start(last, QPoint(10, 20))
card._on_drag_move(QPoint(10, 1 * 56 + 20))  # 拖到直连之下
card._on_drag_finish()
settle()
after = [r.value for r in card._rows]
check(after[0] == "", "拖动后直连仍钉在最前（不能被越过）")
check(after[1] == before[-1], f"被拖的行落到了目标位置（{before} -> {after}）")
check(orderable_mirrors() == after[1:], "拖完的顺序已落库")
remove_custom_mirror(custom)
card.reload()
settle()

print("== 4c. 加速卡展开后收得回去 ==")
# 上游 ExpandSettingCard 收起动画的终值取自 verticalScrollBar().maximum()，而它覆写
# resizeEvent 时没调 super() → range 停在构造期的陈旧值，实测收起后高度卡在 292 而不是 70


def settle_ani(ani, timeout: float = 2.0) -> None:
    """等属性动画真正跑完：光 processEvents 不推进真实时间，必须带 sleep 轮询。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if ani.state() != ani.State.Running:
            return
        time.sleep(0.01)


card.setExpand(False)
settle_ani(card.expandAni)
check(
    card.height() == card.card.height(),
    f"初始收起态高度 == 标题行（{card.height()}）",
)
for round_no in (1, 2):  # 连开两轮，确认不是一次性的
    card.card.expandButton.click()
    settle_ani(card.expandAni)
    check(card.isExpand, f"第 {round_no} 轮：点下拉按钮后展开")
    check(
        card.height() > card.card.height(),
        f"第 {round_no} 轮：展开后高度撑开（{card.height()} > {card.card.height()}）",
    )
    card.card.expandButton.click()
    settle_ani(card.expandAni)
    check(not card.isExpand, f"第 {round_no} 轮：再点一次收起")
    check(
        card.height() == card.card.height(),
        f"第 {round_no} 轮：收起后高度落回标题行（{card.height()} == {card.card.height()}）",
    )

print("== 5. 检查结果分支 ==")
same = ReleaseInfo(tag=f"v{version}", notes="x", html_url="https://example/r")
page._on_release(same)
settle()
check(
    "已是最新" in page.updateCard.contentLabel.text(),
    f"非新版只改副标题、不弹窗（{page.updateCard.contentLabel.text()!r}）",
)
check(
    not any(isinstance(w, UpdateDialog) for w in page.window().findChildren(UpdateDialog)),
    "非新版没有创建更新弹窗",
)

print("== 6. 更新弹窗 ==")
notes = "## 新增\n\n- 第一条\n- 第二条\n\n## 修复\n\n- 修了个 bug\n"
dialog = UpdateDialog(
    ReleaseInfo(
        tag="v9.9.9",
        notes=notes,
        published="2026-08-30",
        html_url="https://example/r",
        asset_name="BiliEmojiDD-Setup-9.9.9.exe",
        asset_url="https://example/setup.exe",
        asset_size=83 * 1024 * 1024,
    ),
    page,
)
dialog.show()  # offscreen 下 exec() 会阻塞脚本
settle()
rendered = dialog.notesEdit.toPlainText()
check("第一条" in rendered and "修了个 bug" in rendered, "markdown 渲染出了正文")
check("##" not in rendered, "标题被渲染成样式而不是留着井号")
check("9.9.9" in dialog.titleLabel.text(), f"标题写明新版本号（{dialog.titleLabel.text()!r}）")
check("83.0 MB" in dialog.metaLabel.text(), f"元信息带安装包大小（{dialog.metaLabel.text()!r}）")
check(dialog.yesButton.text() == "下载并安装", f"主按钮文案（{dialog.yesButton.text()!r}）")
check(dialog.progressBar.isHidden(), "进度条默认藏着")
# 上游 MessageBoxBase 把 yesButton 连到了 accept()，不断开的话点一下弹窗当场关闭，
# 进度条根本没机会出现。这里 updater 已被 set_enabled(False)，下载会立刻失败，
# 正好顺带验证失败路径：弹窗不关、按钮恢复、状态行说明失败。
dialog.yesButton.click()
settle()
check(dialog.isVisible(), "点「下载并安装」后弹窗仍在（上游 accept 已断开）")
wait_until(lambda: not dialog.yesButton.isEnabled() or "失败" in dialog.statusLabel.text())
wait_until(lambda: "失败" in dialog.statusLabel.text())
check(
    "失败" in dialog.statusLabel.text(),
    f"下载失败后状态行说明情况（{dialog.statusLabel.text()!r}）",
)
check(dialog.yesButton.isEnabled(), "失败后主按钮恢复可用，能重试")
check(dialog.isVisible(), "失败也不关弹窗（用户可以换镜像重来）")
dialog.close()

no_exe = UpdateDialog(ReleaseInfo(tag="v9.9.9", notes="x", html_url="https://example/r"), page)
check(
    no_exe.yesButton.text() == "打开发布页",
    f"没有安装包资产时退化成「打开发布页」（{no_exe.yesButton.text()!r}）",
)
no_exe.close()
page.close()

print("== 7. CHANGES.md 抽取 ==")
body = extract_changelog(project_version())
check(bool(body.strip()), f"当前版本能抽到非空更新说明（{len(body)} 字符）")
check(
    not body.lstrip().startswith("## ") and f"[{project_version()}]" not in body,
    "抽出的是小节正文，版本标题行已剥掉（三级标题 ### 照常保留）",
)
try:
    extract_changelog("99.99.99")
except VersionNotFound:
    check(True, "缺版本小节时抛 VersionNotFound（构建会失败，不会发空说明的 Release）")
else:
    check(False, "缺版本小节竟然没抛异常")

print("== 8. 新联网入口也不吃系统代理 ==")
check(make_session().trust_env is False, "make_session 的 session 关掉了 trust_env")
probe = {"http": "http://1.2.3.4:9", "https": "http://1.2.3.4:9"}
check(dict(make_session(proxies=probe).proxies) == probe, "显式 proxies 落到 session 上")
check(
    APP_NAME in make_session().headers.get("User-Agent", ""),
    f"带 UA（GitHub API 不带 UA 会 403）：{make_session().headers.get('User-Agent')!r}",
)

print("== 9. 安装包校验和 ==")
payload = b"pretend this is an installer"
digest = hashlib.sha256(payload).hexdigest()
sums_text = f"{digest}  BiliEmojiDD-Setup-0.2.0.exe\ndeadbeef  BiliEmojiDD-0.2.0-win64.zip\n"
check(
    parse_sums(sums_text, "BiliEmojiDD-Setup-0.2.0.exe") == digest,
    "按文件名取到对应那一行的摘要",
)
check(parse_sums(sums_text, "不在里面.exe") == "", "文件名不在清单里返回空串（视为未校验）")
tampered = hashlib.sha256(payload + b"!").hexdigest()
check(tampered != digest, "改一个字节摘要就变——下载完的比对据此拒绝运行")


class _NoNet:
    """一被调用就炸的假 session：用来证明「有官方 digest 时压根没发请求」。"""

    def get(self, *args, **kwargs):
        raise AssertionError("这一步不该发任何请求")


class _DeadNet:
    """取清单文件时连不上——模拟 github.com 直连超时（加速源用户最常见的情形）。"""

    def get(self, *args, **kwargs):
        raise requests.ConnectionError("github.com 连不上")


SUMS_URL = "https://github.com/ldm0715/BiliEmojiDD/releases/download/v0.2.0/SHA256SUMS.txt"
with_digest = ReleaseInfo(
    tag="v0.2.0",
    asset_name="BiliEmojiDD-Setup-0.2.0.exe",
    asset_digest=digest,
    sums_url=SUMS_URL,
)
check(
    expected_checksum(with_digest, _NoNet()) == digest,
    "**有官方 digest 就一个请求都不发**——取清单要直连 github.com，而它排在镜像候选"
    "循环之前，一超时整个下载就没了，镜像连出场机会都没有",
)
check(
    expected_checksum(ReleaseInfo(asset_digest="", sums_url=""), _NoNet()) == "",
    "两样都没有时返回空串（视为不校验），同样不发请求",
)
legacy = ReleaseInfo(
    tag="v0.1.0", asset_name="BiliEmojiDD-Setup-0.2.0.exe", sums_url=SUMS_URL
)
try:
    expected_checksum(legacy, _DeadNet())
except UpdateError as exc:
    check(
        "SHA256SUMS" in str(exc) and "校验不了就不会安装" in str(exc),
        f"老 Release 又直连不上时抛 UpdateError 且说明「不下」而不是裸抛 requests 异常（{exc}）",
    )
except Exception as exc:  # noqa: BLE001
    check(False, f"抛的是 {type(exc).__name__}，应当是 UpdateError")
else:
    check(False, "清单取不到竟然没抛异常——那会带着空摘要继续下载")

print("== 9b. 失败文案不被 cause_hint 盖掉 ==")
# updater 的异常消息带 from exc 的链，cause_hint 会顺链翻到底层的 ConnectTimeout
chained = UpdateError("这个版本没有官方校验和摘要，校验不了就不会安装")
chained.__cause__ = requests.ConnectTimeout("github.com 超时")
check(
    _failure_detail(chained).startswith("这个版本没有官方校验和摘要"),
    "updater 自己的异常：原样展示它的消息",
)
check(
    cause_hint(chained).startswith("连接超时"),
    "（对照）cause_hint 顺链翻出来的是「连接超时，请检查网络 / 代理」——正是要避免盖上去的那句",
)
plain = requests.ConnectTimeout("boom")
check(
    _failure_detail(plain).startswith("连接超时"),
    "非 updater 的异常照旧走 cause_hint（biliemoji 那类真因埋在 __cause__ 里的靠它）",
)

print("== 10. 版本号胶囊 ==")
from qfluentwidgets import InfoBadge

from app.view.home_page import HomePage

cookie_status.set_enabled(False)  # 主页 showEvent 会触发一次 Cookie 检测

home = HomePage()
home.resize(900, 700)
home.show()
settle()
badges = {
    "设置页身份行": SettingPage().versionLabel,
    "主页英雄卡": home.heroCard.versionLabel,
}
for where, badge in badges.items():
    check(isinstance(badge, InfoBadge), f"{where}的版本号是胶囊（InfoBadge，实际 {type(badge).__name__}）")
    check(badge.text() == f"v{version}", f"{where}显示 v{version}（实际 {badge.text()!r}）")
    # 上游 qss 只给 padding 1px 3px，不补留白文字会贴着圆角边
    plain = badge.fontMetrics().horizontalAdvance(badge.text())
    check(
        badge.sizeHint().width() >= plain + 16,
        f"{where}的胶囊两侧留了白（文字 {plain}px / 控件 {badge.sizeHint().width()}px）",
    )
home.close()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")

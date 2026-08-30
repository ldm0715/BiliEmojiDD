"""打包：Nuitka 编译 → NSIS 安装包 + 便携 zip + 校验和 + 发布说明。

本地与 CI 跑的是**同一条命令**，编译参数只此一处，不会漂移：

    uv run python packaging/build.py                     # 只编译，本地先试这一步
    uv run python packaging/build.py --installer         # 编译 + 安装包 + 便携 zip
    uv run python packaging/build.py --installer --version v0.2.0   # CI 用 tag 覆盖版本

产物都在 `dist/`：

    BiliEmojiDD/                     编译结果（便携目录，可直接跑）
    BiliEmojiDD-Setup-<ver>.exe      NSIS 安装包
    BiliEmojiDD-<ver>-win64.zip      便携版压缩包
    SHA256SUMS.txt                   上面两个文件的校验和（更新器直连取它校验）
    release_notes.md                 从 CHANGES.md 抽出的本版更新说明

版本号来自 `pyproject.toml`，用 tomllib 读而**不 import 应用模块**——构建脚本不该
为了取个版本号把整个 Qt 拉起来。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from changelog import extract as extract_changelog


def _force_utf8_output() -> None:
    """把自己的 stdout / stderr 钉成 UTF-8。

    GitHub runner 上 Python 的标准流按系统区域设置走 **cp1252**，而本脚本要打印的
    Nuitka 命令里带中文（`--file-description=B站表情包/收藏集下载器`），后面几条
    进度信息也是中文 —— 直接 `UnicodeEncodeError` 把构建打断在 `print` 上，
    看起来像编译失败，实际连 Nuitka 都还没启动（v0.1.1 第一次发布就栽在这）。
    本地中文 Windows 的 GBK 能编码中文，所以只在 CI 上暴露。

    `errors="replace"` 是第二道保险：万一某个流不支持 UTF-8，也只是显示成问号，
    不该让一次打印毁掉整个构建。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "BiliEmojiDD"
NSI_PATH = Path(__file__).resolve().parent / "installer.nsi"

EXE_NAME = "BiliEmojiDD.exe"
SUMS_NAME = "SHA256SUMS.txt"
NOTES_NAME = "release_notes.md"
PUBLISHER = "gcnanmu"


def project_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as fp:
        return tomllib.load(fp)["project"]["version"]


def _is_ascii(*parts: str) -> bool:
    return all(part.isascii() for part in parts)


def ascii_workarounds() -> tuple[list[str], dict[str, str]]:
    """用户名含非 ASCII 字符时，绕开 Nuitka 里两处按字节处理路径的地方。

    在中文 Windows 上，`C:\\Users\\某某某` 会让 Nuitka 挂在两个地方：

    1. **DLL 依赖扫描**：默认的 `depends.exe` 输出被 `_parseDependsExeOutput2` 按
       **latin1** 解码（`DllDependenciesWin32DependsExe.py:151`），中文用户名被拆成
       `\\x04` 之类的字节，接着 `assert os.path.isfile(dll_filename)` 直接崩。
       换成纯 Python 的 pefile 扫描器绕开。
    2. **工具链缓存**：Nuitka 要下载 MinGW 时会把它解压进
       `%LOCALAPPDATA%\\Nuitka\\...`，同样的路径问题让 Scons 后端起不来。
       把缓存目录挪到全 ASCII 的路径即可。

    CI（windows-latest，路径全 ASCII）走默认路径，不受影响。返回 (额外参数, 额外环境变量)。
    """
    home = str(Path.home())
    cache = os.environ.get("LOCALAPPDATA", home)
    if _is_ascii(home, cache, sys.executable):
        return [], {}
    fallback = Path(os.environ.get("SystemDrive", "C:") + "/") / "nuitka-cache"
    fallback.mkdir(parents=True, exist_ok=True)
    print(
        f"检测到非 ASCII 用户目录（{home}）：改用 pefile 依赖扫描并把 Nuitka 缓存挪到 {fallback}"
    )
    return (
        ["--experimental=force-dependencies-pefile"],
        {"NUITKA_CACHE_DIR": str(fallback)},
    )


def run(command: list[str], env_extra: dict[str, str] | None = None, **kwargs) -> None:
    print("+", " ".join(str(c) for c in command), flush=True)
    env = {**os.environ, **env_extra} if env_extra else None
    subprocess.run(command, check=True, cwd=ROOT, env=env, **kwargs)


def nuitka_command(version: str) -> list[str]:
    """编译参数。每一条为什么在这里，见注释——别随手删。"""
    # Windows 的 VERSIONINFO 要四段
    file_version = ".".join((version.split("-")[0].split(".") + ["0", "0", "0"])[:4])
    extra, _ = ascii_workarounds()
    return [
        sys.executable, "-m", "nuitka", "main.py",
        "--standalone",
        "--assume-yes-for-downloads",       # CI 无人值守，别卡在「是否下载 ccache」
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",   # GUI 应用，别弹黑框（2.x 起的写法）
        f"--windows-icon-from-ico={ROOT / 'static' / 'logo.ico'}",
        # static/ 是运行时资源（图标、字体、主页展示图），资源根解析见
        # app/common/resource.py::_project_root——编译后按 exe 所在目录找
        "--include-data-dir=static=static",
        # 版本号唯一来源，app/common/version.py::project_version 运行时要读它
        "--include-data-files=pyproject.toml=pyproject.toml",
        # 页面是在 main() 里延迟 import 的，显式带上整个包更稳妥
        "--include-package=app",
        # PySocks 由 urllib3 在「代理地址写 socks5://」时才懒加载，静态分析看不见
        "--include-module=socks",
        # QtMultimedia 插件：收藏集详情页的视频播放要用，pyside6 插件默认不一定带
        "--include-qt-plugins=multimedia",
        "--nofollow-import-to=tkinter",
        # 关掉链接期优化：MinGW 后端的 lto-wrapper 在 Windows 上很脆（实测
        # 「could not open symbol resolution file」直接断在链接阶段），而这个应用
        # 一百多 MB 里绝大部分是 Qt 的 DLL，LTO 能省的那点体积和速度不值得冒险。
        "--lto=no",
        "--company-name=" + PUBLISHER,
        "--product-name=BiliEmojiDD",
        f"--file-version={file_version}",
        f"--product-version={file_version}",
        "--file-description=B站表情包/收藏集下载器",
        "--copyright=Copyright (C) 2026 gcnanmu - GPL-3.0-or-later",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={EXE_NAME}",
        "--remove-output",                  # 编完删中间产物，CI 磁盘不富裕
        *extra,                             # 非 ASCII 用户目录下的绕行参数
    ]


def compile_app(version: str) -> None:
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    _, env_extra = ascii_workarounds()
    run(nuitka_command(version), env_extra=env_extra)
    produced = BUILD_DIR / "main.dist"
    if not produced.is_dir():
        raise SystemExit(f"Nuitka 没有产出 {produced}")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(APP_DIR))
    print(f"编译完成: {APP_DIR}")


def find_makensis() -> str:
    """PATH 优先，其次 NSIS 默认安装位置。"""
    found = shutil.which("makensis")
    if found:
        return found
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if not base:
            continue
        candidate = Path(base) / "NSIS" / "makensis.exe"
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(
        "找不到 makensis。请安装 NSIS（https://nsis.sourceforge.io）后重试，"
        "或把它的目录加进 PATH。"
    )


def build_installer(version: str) -> Path:
    output = DIST_DIR / f"BiliEmojiDD-Setup-{version}.exe"
    run([
        find_makensis(),
        f"/DVERSION={version}",
        f"/DSRCDIR={APP_DIR}",
        f"/DOUTFILE={output}",
        f"/DLICENSE={ROOT / 'LICENSE'}",
        f"/DPUBLISHER={PUBLISHER}",
        str(NSI_PATH),
    ])
    return output


def build_portable(version: str) -> Path:
    output = DIST_DIR / f"BiliEmojiDD-{version}-win64.zip"
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, Path("BiliEmojiDD") / path.relative_to(APP_DIR))
    return output


def write_sums(paths: list[Path]) -> Path:
    """`sha256sum` 格式：`<hex>  <文件名>`。更新器按文件名取行（见 updater.parse_sums）。"""
    lines = []
    for path in paths:
        digest = hashlib.sha256()
        with open(path, "rb") as fp:
            for chunk in iter(lambda: fp.read(1 << 20), b""):
                digest.update(chunk)
        lines.append(f"{digest.hexdigest()}  {path.name}")
        print(f"  {lines[-1]}")
    output = DIST_DIR / SUMS_NAME
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def write_notes(version: str) -> Path:
    """抽 CHANGES.md 对应小节。缺这一节就让构建失败——见 changelog.extract 的说明。"""
    output = DIST_DIR / NOTES_NAME
    output.write_text(extract_changelog(version), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="编译并打包 BiliEmojiDD")
    parser.add_argument(
        "--version",
        default=None,
        help="版本号（可带前导 v）。默认读 pyproject.toml",
    )
    parser.add_argument(
        "--installer",
        action="store_true",
        help="额外产出 NSIS 安装包、便携 zip、校验和与发布说明",
    )
    parser.add_argument("--skip-compile", action="store_true", help="复用已有的 dist 目录")
    args = parser.parse_args()

    version = (args.version or project_version()).lstrip("vV")
    print(f"== BiliEmojiDD {version} ==")

    if args.installer:
        # 先验更新说明再花十几分钟编译：CHANGES.md 缺这一节的话，现在失败比编译完再失败好
        extract_changelog(version)

    if not args.skip_compile:
        compile_app(version)
    elif not APP_DIR.is_dir():
        raise SystemExit(f"--skip-compile 需要已有的 {APP_DIR}")

    if not args.installer:
        print("完成（只编译）。加 --installer 可产出安装包。")
        return 0

    notes = write_notes(version)
    installer = build_installer(version)
    portable = build_portable(version)
    sums = write_sums([installer, portable])
    print("\n产物：")
    for path in (APP_DIR, installer, portable, sums, notes):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""季度股池数据侧统一路径解析：本机 Windows 与云端 Linux 共用一份代码。

环境变量优先，其次按平台给默认值：
  Windows 本机  —— 沿用既有 WorkBuddy 目录，保证改造后本机行为不变
  Linux 云端    —— 由 bootstrap 克隆到 /workspace 下的兄弟目录

可用变量：POOL_DATA_DIR（本工程根）、POOL_BASE（主项目 pool-core）、
          PROF_DIR、AFGI_DIR、WESTOCK_BIN、WB_LIBRARY_SKILL、POOL_PY
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 本工程根目录（scripts/paths.py 的上级）
BASE = Path(os.environ.get("POOL_DATA_DIR") or Path(__file__).resolve().parent.parent)

_WIN = {
    "POOL_BASE": r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30",
    "PROF_DIR": r"C:\Users\12066\WorkBuddy\2026-10-07-14-39-28\work",
    "AFGI_DIR": r"C:\Users\12066\WorkBuddy\2026-10-05-14-50-58\afgi_tdx",
}
_LINUX = {"POOL_BASE": "pool-core", "PROF_DIR": "prof-model", "AFGI_DIR": "afgi_tdx"}


def _ref(env_var: str) -> Path:
    v = os.environ.get(env_var)
    if v:
        return Path(v)
    if os.name == "nt":
        return Path(_WIN[env_var])
    return BASE.parent / _LINUX[env_var]


MAIN = _ref("POOL_BASE")          # 主项目 pool-core
PROF = _ref("PROF_DIR")           # PROF 盈利能力模型
AFGI = _ref("AFGI_DIR")           # AFGI 情绪指数工程

SCRIPTS = BASE / "scripts"
DATA = BASE / "data"

PY = os.environ.get("POOL_PY") or sys.executable

# westock CLI：跨平台 Go 二进制，Windows 为 westock.exe，Linux 为 westock
WESTOCK = (os.environ.get("WESTOCK_BIN")
           or (str(Path.home() / ".local" / "bin" / "westock.exe") if os.name == "nt" else "westock"))


def library_skill() -> Path:
    """定位资料库 library skill（含 page/import_html.py）。"""
    env = os.environ.get("WB_LIBRARY_SKILL")
    cands: list[Path] = []
    if env:
        cands.append(Path(env))
    if os.name == "nt":
        cands.append(Path(os.path.expandvars(
            r"%USERPROFILE%\.workbuddy\plugins\cache\workbuddy-builtin\skill-library")))
        # 本机该 skill 带版本号子目录，做一次 glob 兜底
        p = cands[-1]
        if p.is_dir():
            subs = sorted([d for d in p.iterdir() if (d / "page" / "import_html.py").exists()],
                          key=lambda d: d.name, reverse=True)
            if subs:
                return subs[0]
    else:
        cands += [
            Path("/root/.codebuddy/skills/library"),
            Path("/root/.workbuddy/skills/library"),
            Path.home() / ".codebuddy/skills/library",
            Path.home() / ".workbuddy/skills/library",
        ]
    for c in cands:
        if (c / "page" / "import_html.py").exists():
            return c
    raise FileNotFoundError(
        "找不到资料库 library skill（page/import_html.py），"
        f"可用 WB_LIBRARY_SKILL 指定。已尝试：{[str(c) for c in cands]}"
    )


if __name__ == "__main__":
    print(f"BASE    = {BASE}")
    print(f"MAIN    = {MAIN}")
    print(f"PROF    = {PROF}")
    print(f"AFGI    = {AFGI}")
    print(f"SCRIPTS = {SCRIPTS}")
    print(f"PY      = {PY}")
    print(f"WESTOCK = {WESTOCK}")

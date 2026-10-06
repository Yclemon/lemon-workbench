# -*- coding: utf-8 -*-
"""
steam_local.py —— 只读本机 Steam 目录，汇总「游戏库 / 游玩时长 / 磁盘占用 / 账号」。
纯本地、不联网、只读，不会修改任何 Steam 文件。

数据来源：
  1. steamapps/libraryfolders.vdf            库文件夹列表（可能有多个盘）
  2. <库>/steamapps/appmanifest_*.acf        已安装游戏：名称、大小、上次运行
  3. config/loginusers.vdf                   账号昵称
  4. userdata/<id>/config/localconfig.vdf    游玩时长（分钟）、最后运行时间
  5. cache/appinfo.json                      可选：一次联网补全「已卸载但玩过」的游戏名（可删）
"""
from __future__ import annotations

import os
import glob
import json
import time

COMMON_STEAM_PATHS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    r"E:\Steam",
    r"D:\Program Files (x86)\Steam",
    r"F:\Steam",
)


def _looks_like_steam_root(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "steamapps", "libraryfolders.vdf"))


def detect_steam_root() -> str:
    """自己去把 Steam 装哪儿找出来，别写死在某台电脑的路径上。

    顺序：注册表（HKCU\\Software\\Valve\\Steam 的 SteamPath / InstallPath）→ 常见安装位置。
    找不到就返回第一个候选路径，由调用方报错提示用户用 --steam-root 指定。
    """
    cands: list = []
    try:
        import winreg  # 只有 Windows 有
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        )
        for hive, subkey in locations:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if value:
                            cands.append(str(value).replace("/", os.sep))
            except OSError:
                continue
    except ImportError:
        pass

    cands.extend(COMMON_STEAM_PATHS)
    for path in cands:
        if _looks_like_steam_root(path):
            return os.path.normpath(path)
    for path in cands:
        if path and os.path.isfile(os.path.join(path, "config", "loginusers.vdf")):
            return os.path.normpath(path)
    return os.path.normpath(cands[0])


DEFAULT_STEAM_ROOT = detect_steam_root()

# 不是游戏、默认从列表里隐藏的 appid / 名称关键字
NON_GAME_IDS = {7, 760, 228980, 431960, 993090, 1905180, 250820, 1070560}
NON_GAME_HINTS = (
    "Redistributables",
    "Steam Linux Runtime",
    "Proton",
    "SteamVR",
    "Wallpaper Engine",
    "OBS Studio",
    "Lossless Scaling",
    "Steam Client",
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
APPINFO_CACHE = os.path.join(CACHE_DIR, "appinfo.json")

# --------------------------------------------------------------------------
# KeyValues (VDF / ACF) 解析
# --------------------------------------------------------------------------

_ESCAPE = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


def read_text(path: str) -> str:
    """Steam 的 vdf 基本都是 UTF-8（可能有 BOM），个别旧文件是本地编码，做兜底。"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            out.append(_ESCAPE.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _tokens(text: str):
    """把 VDF 切成 ('str', 值) / ('{', None) / ('}', None)。"""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n\ufeff":
            i += 1
            continue
        if c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "{":
            yield ("{", None)
            i += 1
            continue
        if c == "}":
            yield ("}", None)
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j])
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            yield ("str", _unescape("".join(buf)))
            i = j + 1
            continue
        # 没加引号的裸值（少见，但容错）
        j = i
        while j < n and text[j] not in ' \t\r\n"{}':
            j += 1
        yield ("str", text[i:j])
        i = j


def parse_vdf(text: str) -> dict:
    toks = list(_tokens(text))
    pos = 0
    total = len(toks)

    def _set(d, key, val):
        if key in d and isinstance(d[key], dict) and isinstance(val, dict):
            _merge(d[key], val)
        else:
            d[key] = val

    def _merge(dst, src):
        for k, v in src.items():
            _set(dst, k, v)

    def parse_obj():
        nonlocal pos
        d = {}
        while pos < total:
            kind, val = toks[pos]
            if kind == "}":
                pos += 1
                return d
            if kind != "str":
                pos += 1
                continue
            key = val
            pos += 1
            if pos >= total:
                break
            k2, v2 = toks[pos]
            if k2 == "{":
                pos += 1
                _set(d, key, parse_obj())
            elif k2 == "str":
                pos += 1
                _set(d, key, v2)
            else:  # 多余的 }
                pos += 1
        return d

    root = {}
    while pos < total:
        kind, val = toks[pos]
        if kind != "str":
            pos += 1
            continue
        key = val
        pos += 1
        if pos < total and toks[pos][0] == "{":
            pos += 1
            _set(root, key, parse_obj())
        elif pos < total and toks[pos][0] == "str":
            _set(root, key, toks[pos][1])
            pos += 1
        else:
            break
    return root


def ci_get(d, *names):
    """大小写不敏感地按层取值（Steam 里 'Apps' / 'apps' 都出现过）。"""
    cur = d
    for nm in names:
        if not isinstance(cur, dict):
            return None
        nxt = None
        if nm in cur:
            nxt = cur[nm]
        else:
            low = nm.lower()
            for k, v in cur.items():
                if isinstance(k, str) and k.lower() == low:
                    nxt = v
                    break
        cur = nxt
    return cur


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default


# --------------------------------------------------------------------------
# 各个数据源
# --------------------------------------------------------------------------

def find_library_folders(steam_root: str):
    """返回库根目录列表（形如 D:\\Steam、V:\\SteamLibrary）。"""
    paths = []
    lf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(lf):
        data = parse_vdf(read_text(lf))
        sec = ci_get(data, "libraryfolders") or data
        if isinstance(sec, dict):
            for _, v in sec.items():
                if isinstance(v, dict):
                    p = ci_get(v, "path")
                    if p:
                        paths.append(p)
                elif isinstance(v, str) and len(v) > 1 and v[1] == ":":
                    paths.append(v)  # 老格式： "1"  "D:\\Games"

    norm = [os.path.normpath(p) for p in paths]
    root_norm = os.path.normpath(steam_root)
    if root_norm not in norm:
        norm.insert(0, root_norm)

    seen, out = set(), []
    for p in norm:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"path": p, "exists": os.path.isdir(p)})
    return out


def account_id_candidates(folder: str):
    """userdata 目录名 → 可能的 32 位 account id（新客户端会多一个前导 1）。"""
    if not folder.isdigit():
        return []
    n = int(folder)
    cands = []
    if len(folder) == 10 and folder[0] == "1":
        cands.append(n - 10 ** 9)
    cands.append(n)
    if n > 10 ** 9:
        cands.append(n - 10 ** 9)
    out = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def read_accounts(steam_root: str):
    """合并 config/loginusers.vdf 与 userdata/ 目录，返回账号列表（最近使用的在前）。"""
    users = {}
    lu = os.path.join(steam_root, "config", "loginusers.vdf")
    if os.path.isfile(lu):
        sec = ci_get(parse_vdf(read_text(lu)), "users") or {}
        if isinstance(sec, dict):
            for sid, v in sec.items():
                if not isinstance(v, dict):
                    continue
                users[str(sid)] = {
                    "persona_name": ci_get(v, "PersonaName") or "",
                    "account_name": ci_get(v, "AccountName") or "",
                    "timestamp": _int(ci_get(v, "Timestamp")),
                    "auto_login": str(ci_get(v, "AutoLogin") or "") == "1",
                }

    out = []
    ud = os.path.join(steam_root, "userdata")
    if os.path.isdir(ud):
        for name in sorted(os.listdir(ud)):
            lc = os.path.join(ud, name, "config", "localconfig.vdf")
            if not (name.isdigit() and os.path.isfile(lc)):
                continue
            sid64, info = "", None
            for aid in account_id_candidates(name):
                cand = str(76561197960265728 + aid)
                if cand in users:
                    sid64, info = cand, users[cand]
                    break
            if not info:
                aid = account_id_candidates(name)
                sid64 = str(76561197960265728 + (aid[0] if aid else 0))
                info = {}
            out.append({
                "folder": name,
                "steamid64": sid64,
                "persona_name": info.get("persona_name") or ("账号 " + name),
                "account_name": info.get("account_name") or "",
                "localconfig": lc,
                "mtime": os.path.getmtime(lc),
                "matched": bool(info),
            })
    out.sort(key=lambda a: a["mtime"], reverse=True)
    return out


def read_manifests(library_path: str, lib_exists=True):
    """读一个库里的所有 appmanifest_*.acf。"""
    out = {}
    sap = os.path.join(library_path, "steamapps")
    for acf in glob.glob(os.path.join(sap, "appmanifest_*.acf")):
        try:
            st = ci_get(parse_vdf(read_text(acf)), "AppState")
        except Exception:
            continue
        if not isinstance(st, dict):
            continue
        aid = _int(ci_get(st, "appid"))
        if not aid:
            continue
        out[aid] = {
            "appid": aid,
            "name": ci_get(st, "name") or ("App %d" % aid),
            "installdir": ci_get(st, "installdir") or "",
            "size_bytes": _int(ci_get(st, "SizeOnDisk")),
            "last_updated": _int(ci_get(st, "LastUpdated")),
            "manifest_last_played": _int(ci_get(st, "LastPlayed")),
            "buildid": _int(ci_get(st, "buildid")),
            "state_flags": _int(ci_get(st, "StateFlags")),
            "library": library_path,
            "library_exists": lib_exists,
            "installed": state_flags_installed(_int(ci_get(st, "StateFlags"))),
        }
    return out


def state_flags_installed(flags: int) -> bool:
    """StateFlags 第 4 位(0x4) = 已完整安装。0 表示未知，当作已安装。"""
    if flags == 0:
        return True
    return bool(flags & 0x4)


def find_apps_section(root: dict):
    """在 localconfig.vdf 里找 apps 段：先按标准路径，再递归兜底。"""
    for path in (
        ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"),
        ("UserLocalConfigStore", "Software", "Valve", "Steam", "Apps"),
        ("Software", "Valve", "Steam", "apps"),
    ):
        sec = ci_get(root, *path)
        if isinstance(sec, dict) and sec:
            return sec

    stack = [root]
    while stack:
        cur = stack.pop()
        if not isinstance(cur, dict):
            continue
        for k, v in cur.items():
            if isinstance(k, str) and k.lower() == "apps" and isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and (
                        ci_get(vv, "Playtime") is not None or ci_get(vv, "LastPlayed") is not None
                    ):
                        return v
        for v in cur.values():
            if isinstance(v, dict):
                stack.append(v)
    return None


def read_playtime(localconfig_path: str):
    """→ {appid: {playtime_min, last_played, playtime_disconnected_min}}"""
    try:
        root = parse_vdf(read_text(localconfig_path))
    except Exception:
        return {}
    apps = find_apps_section(root)
    out = {}
    if not isinstance(apps, dict):
        return out
    for k, v in apps.items():
        if not isinstance(k, str) or not k.isdigit() or not isinstance(v, dict):
            continue
        pt = _int(ci_get(v, "Playtime"))
        lp = _int(ci_get(v, "LastPlayed"))
        ac = ci_get(v, "autocloud")
        le = _int(ci_get(ac, "lastexit")) if isinstance(ac, dict) else 0
        pd = _int(ci_get(v, "PlaytimeDisconnected"))
        if pt or lp or le or pd:
            out[int(k)] = {
                "playtime_min": pt,
                "last_played": max(lp, le),
                "playtime_disconnected_min": pd,
            }
    return out


# --------------------------------------------------------------------------
# 名称补全缓存（可选联网，一次性写入 cache/appinfo.json，之后完全离线）
# --------------------------------------------------------------------------

def load_appinfo_cache():
    if os.path.isfile(APPINFO_CACHE):
        try:
            with open(APPINFO_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_appinfo_cache(d):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(APPINFO_CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)


def fetch_app_names(appids, timeout=8):
    """用 Steam 商店接口补全名称。失败就返回已拿到的部分，不抛异常。"""
    import urllib.request
    import urllib.parse

    got = {}
    for aid in appids:
        try:
            url = "https://store.steampowered.com/api/appdetails?appids=%d&l=schinese" % aid
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                js = json.loads(r.read().decode("utf-8", "replace"))
            node = js.get(str(aid)) or {}
            if node.get("success"):
                d = node.get("data") or {}
                got[str(aid)] = {"name": d.get("name") or "", "type": d.get("type") or ""}
        except Exception:
            continue
        time.sleep(0.12)  # 对商店接口客气一点
    return got


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def is_non_game(appid: int, name: str) -> bool:
    if appid in NON_GAME_IDS:
        return True
    n = name or ""
    return any(h.lower() in n.lower() for h in NON_GAME_HINTS)


def collect(steam_root: str = DEFAULT_STEAM_ROOT, account_folder: str | None = None,
            enrich: bool = False):
    t0 = time.time()
    libraries = find_library_folders(steam_root)
    accounts = read_accounts(steam_root)

    account = None
    if accounts:
        if account_folder:
            account = next((a for a in accounts if a["folder"] == account_folder), None)
        account = account or accounts[0]

    playtime = read_playtime(account["localconfig"]) if account and os.path.isfile(account["localconfig"]) else {}

    installed = {}
    for lib in libraries:
        if lib["exists"]:
            installed.update(read_manifests(lib["path"], True))
        else:
            installed.update(read_manifests(lib["path"], False))

    cache = load_appinfo_cache()
    if enrich:
        missing = [aid for aid in playtime if aid not in installed and str(aid) not in cache]
        if missing:
            got = fetch_app_names(missing)
            if got:
                cache.update(got)
                save_appinfo_cache(cache)

    games = {}

    def slot(aid: int):
        if aid not in games:
            games[aid] = {
                "appid": aid,
                "name": "",
                "installed": False,
                "library": "",
                "library_exists": True,
                "installdir": "",
                "size_bytes": 0,
                "last_updated": 0,
                "manifest_last_played": 0,
                "playtime_min": 0,
                "last_played": 0,
                "playtime_disconnected_min": 0,
                "state_flags": 0,
                "buildid": 0,
                "source": "localconfig",
            }
        return games[aid]

    for aid, m in installed.items():
        g = slot(aid)
        g.update({
            "name": m["name"],
            "installed": m["installed"],
            "library": m["library"],
            "library_exists": m["library_exists"],
            "installdir": m["installdir"],
            "size_bytes": m["size_bytes"],
            "last_updated": m["last_updated"],
            "manifest_last_played": m["manifest_last_played"],
            "state_flags": m["state_flags"],
            "buildid": m["buildid"],
            "source": "appmanifest",
        })

    for aid, p in playtime.items():
        g = slot(aid)
        g["playtime_min"] = p["playtime_min"]
        g["playtime_disconnected_min"] = p["playtime_disconnected_min"]
        g["last_played"] = max(p["last_played"], g["manifest_last_played"])
        if not g["name"]:
            c = cache.get(str(aid)) or {}
            g["name"] = c.get("name") or ("App %d" % aid)
            g.setdefault("type", c.get("type", ""))

    for aid, g in games.items():
        if not g["name"]:
            c = cache.get(str(aid)) or {}
            g["name"] = c.get("name") or ("App %d" % aid)
        g["is_tool"] = is_non_game(aid, g["name"])
        g["last_played"] = max(g["last_played"], g["manifest_last_played"])
        # 已安装但清单里没有 last_played 时，用游玩记录
        if g["installed"] and not g["manifest_last_played"]:
            g["manifest_last_played"] = g["last_played"]

    out_games = sorted(games.values(), key=lambda g: (-g["playtime_min"], -g["last_played"], g["name"]))
    unnamed = sum(1 for g in out_games if g["name"].startswith("App ") and g["name"][4:].isdigit())

    return {
        "generated_at": int(time.time()),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "steam_root": steam_root,
        "libraries": libraries,
        "accounts": [
            {k: v for k, v in a.items() if k != "localconfig"} for a in accounts
        ],
        "account": ({k: v for k, v in account.items() if k != "localconfig"} if account else None),
        "names_cached": len(cache),
        "unnamed_count": unnamed,
        "games": out_games,
    }


def main():
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Steam 本地游玩数据抓取")
    ap.add_argument("--steam-root", default=DEFAULT_STEAM_ROOT)
    ap.add_argument("--account", default=None, help="userdata 目录名，默认最近使用的账号")
    ap.add_argument("--enrich", action="store_true", help="联网补全已卸载游戏的名称并写入缓存")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = ap.parse_args()

    data = collect(args.steam_root, args.account, enrich=args.enrich)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print("Steam 根目录 : %s" % data["steam_root"])
    print("库文件夹     : %s" % ", ".join(
        "%s%s" % (l["path"], "" if l["exists"] else "(不存在)") for l in data["libraries"]))
    acct = data["account"]
    print("当前账号     : %s%s" % (
        acct["persona_name"] if acct else "-",
        ("  [%s]" % acct["folder"]) if acct else ""))
    print("扫描耗时     : %d ms" % data["elapsed_ms"])
    print("记录条数     : %d" % len(data["games"]))
    print("-" * 72)
    inst = [g for g in data["games"] if g["installed"]]
    played = [g for g in data["games"] if g["playtime_min"] > 0]
    total_min = sum(g["playtime_min"] for g in data["games"])
    total_gb = sum(g["size_bytes"] for g in inst) / 1024 ** 3
    print("已安装 %d 款 · 有游玩记录 %d 款 · 总时长 %.0f 小时 · 占用 %.1f GB" % (
        len(inst), len(played), total_min / 60.0, total_gb))
    print("-" * 72)
    for g in data["games"][:15]:
        print("%8.1fh  %10.1fGB  %s  %s" % (
            g["playtime_min"] / 60.0,
            g["size_bytes"] / 1024 ** 3,
            "已装" if g["installed"] else "未装",
            g["name"]))


if __name__ == "__main__":
    main()

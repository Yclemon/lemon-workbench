# -*- coding: utf-8 -*-
"""
app.py —— Steam 游玩报告的本地小服务（只监听 127.0.0.1，不对外网开放）。

用法：
    python app.py                 # 自动选端口并打开浏览器
    python app.py --port 8770     # 指定端口
    python app.py --no-browser    # 不自动打开浏览器
    python app.py --steam-root "D:\\Steam"
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import steam_local
import steam_online

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
# 用户自己给游戏加的图片就放这儿（在 web/ 下面，静态服务直接就能发出去）
IMAGES_DIR = os.path.join(WEB_DIR, "images")
IMG_MAX_BYTES = 12 * 1024 * 1024
IMG_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
           "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
           "avif": "image/avif"}

CACHE_TTL = 60.0
ONLINE_CACHE_TTL = 300.0
# 成就数据多久算「还新鲜」：这之内的重复请求直接吃本地记录，不再打 Steam 接口
ACH_TTL = 6 * 3600
_cache_lock = threading.Lock()
_cache = {"key": None, "ts": 0.0, "value": None}
_online_cache = {"key": None, "ts": 0.0, "value": None}

CONFIG = {"steam_root": steam_local.DEFAULT_STEAM_ROOT}
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


# ---------------------------------------------------------------- 配置读写

def load_config():
    """config.json 只存三样东西：API Key、SteamID64、是否默认走联网。"""
    cfg = {"api_key": "", "steamid": "", "online": False}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            cfg["api_key"] = str(raw.get("api_key") or "")
            cfg["steamid"] = str(raw.get("steamid") or "")
            cfg["online"] = bool(raw.get("online") or False)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print("!! config.json 读不了（%s），按未配置处理" % e)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def mask_key(k):
    if not k:
        return ""
    if len(k) <= 10:
        return "已设置"
    return k[:4] + "…" + k[-4:]


def config_public():
    """给前端的配置视图 —— 永远不回传完整 Key，只给一个打码提示。"""
    cfg = CONFIG["_cfg"]
    return {
        "online": bool(cfg["online"]),
        "steamid": cfg["steamid"],
        "key_set": bool(cfg["api_key"]),
        "key_hint": mask_key(cfg["api_key"]),
        "configured": bool(cfg["api_key"] and cfg["steamid"]),
    }


CONFIG["_cfg"] = load_config()


# ---------------------------------------------------------------- 手动标记
# manual.json: {"<appid>": {"done": true, "ach": 12, "ach_total": 30,
#                           "source": "steam"|"手填", "at": <ts>}}
# 这是全工具里唯一会被写入的业务数据 —— 只写在这一个文件里，不碰 Steam 的任何东西。

MANUAL_PATH = os.path.join(BASE_DIR, "manual.json")


def load_manual():
    try:
        with open(MANUAL_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print("!! manual.json 读不了（%s），按空处理" % e)
        return {}


def save_manual(m):
    tmp = MANUAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, MANUAL_PATH)


def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def update_manual(appid, payload):
    """改一款游戏的标记；返回 (新记录或 None, 错误文案)。"""
    m = load_manual()
    key = str(int(appid))

    if payload.get("clear"):
        m.pop(key, None)
        save_manual(m)
        return None, ""

    cur = dict(m.get(key) or {})
    if "done" in payload:
        cur["done"] = bool(payload.get("done"))
    if "ach" in payload:
        v = _int_or_none(payload.get("ach"))
        cur["ach"] = v
    if "ach_total" in payload:
        v = _int_or_none(payload.get("ach_total"))
        cur["ach_total"] = v
    if "noach" in payload:
        # 这个游戏 Steam 那边压根没有成就系统，记一笔，省得每次打开都白问一次
        cur["noach"] = bool(payload.get("noach"))
        if cur["noach"]:
            cur.pop("ach", None)
            cur.pop("ach_total", None)
    # 总数不能比已完成还小，直接夹一下，省得页面显示 12/8
    if cur.get("ach") is not None and cur.get("ach_total"):
        if cur["ach"] > cur["ach_total"]:
            cur["ach_total"] = cur["ach"]
    cur["at"] = int(time.time())
    if payload.get("source"):
        cur["source"] = str(payload["source"])[:12]

    if cur.get("done") or cur.get("ach") is not None or cur.get("ach_total") or cur.get("noach"):
        m[key] = cur
    else:
        m.pop(key, None)          # 全都清空了就别留个空壳
    save_manual(m)
    return m.get(key), ""


# ------------------------------------------------------------ 自己加的图片

def _img_dir(appid, create=False):
    d = os.path.join(IMAGES_DIR, str(int(appid)))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name):
    """只接受纯文件名（中文、空格都可以），挡住路径穿越和 Windows 非法字符。"""
    name = os.path.basename(str(name or "")).strip()
    if not name or name.startswith(".") or len(name) > 120:
        return ""
    if ".." in name or any(c in name for c in '/\\:*?"<>|'):
        return ""
    return name


def list_images(appid):
    d = _img_dir(appid)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if n.startswith("."):
            continue
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"file": n, "size": st.st_size, "at": int(st.st_mtime)})
    out.sort(key=lambda x: (x["at"], x["file"]))
    return out


def image_counts():
    """{appid: 张数}，给卡片墙上的小徽章用。"""
    counts = {}
    try:
        names = os.listdir(IMAGES_DIR)
    except OSError:
        return counts
    for n in names:
        if not n.isdigit():
            continue
        try:
            c = sum(1 for f in os.listdir(os.path.join(IMAGES_DIR, n)) if not f.startswith("."))
        except OSError:
            continue
        if c:
            counts[n] = c
    return counts


def save_image(appid, name, data_url):
    """把前端读出来的 data:image/...;base64,xxx 落盘，返回文件名。"""
    m = re.match(r"^data:image/([A-Za-z0-9.+-]+);base64,(.*)$", str(data_url or ""), re.S)
    if not m:
        raise ValueError("图片数据格式不认识（应该是 data:image/…;base64,…）")
    ext = m.group(1).lower()
    ext = "jpg" if ext == "jpeg" else ext
    if ext not in IMG_EXT:
        raise ValueError("先不支持 .%s 这个格式，转成 png / jpg / webp / gif 再传" % m.group(1))
    try:
        blob = base64.b64decode(m.group(2), validate=False)
    except Exception:
        raise ValueError("图片数据解不开，可能传到一半断了")
    if not blob:
        raise ValueError("这是一张空图")
    if len(blob) > IMG_MAX_BYTES:
        raise ValueError("单张图上限 12 MB，这张有 %.1f MB" % (len(blob) / 1048576.0))

    stem = _safe_name(name) or "image"
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", stem) or "image"
    d = _img_dir(appid, create=True)
    fn = "%s.%s" % (stem, ext)
    i = 1
    while os.path.exists(os.path.join(d, fn)):
        fn = "%s-%d.%s" % (stem, i, ext)
        i += 1
    with open(os.path.join(d, fn), "wb") as f:
        f.write(blob)
    return fn


def delete_image(appid, name):
    n = _safe_name(name)
    if not n:
        raise ValueError("文件名不对")
    p = os.path.join(_img_dir(appid), n)
    if not os.path.isfile(p):
        raise ValueError("找不到这张图（可能已经删过了）")
    os.remove(p)
    return n


def img_public(appid):
    """给前端的图片列表：带上可直接当 <img src> 用的相对地址。"""
    return [{
        "file": it["file"],
        "url": "images/%d/%s" % (int(appid), urllib.parse.quote(it["file"])),
        "size": it["size"],
        "at": it["at"],
    } for it in list_images(appid)]


def apply_manual(data):
    """把标记贴到 games 上（就地改，调用方保证这是要返回的那一份）。"""
    m = load_manual()
    counts = image_counts()
    marked_done = 0
    marked_ach = 0
    ach_done_total = 0
    ach_all_total = 0
    for g in data.get("games", []):
        rec = m.get(str(g.get("appid")))
        # 先无条件清空，再按记录填 —— 否则取消标记后，缓存里的旧值会赖着不走
        g["done"] = bool(rec.get("done")) if rec else False
        g["ach"] = rec.get("ach") if rec else None
        g["ach_total"] = rec.get("ach_total") if rec else None
        g["mark_source"] = (rec.get("source") or "") if rec else ""
        g["mark_at"] = rec.get("at") if rec else None
        g["ach_at"] = rec.get("at") if rec else None
        g["ach_none"] = bool(rec.get("noach")) if rec else False
        g["image_count"] = counts.get(str(g.get("appid")), 0)
        if not rec:
            continue
        if g["done"]:
            marked_done += 1
        if g["ach"] is not None:
            marked_ach += 1
            ach_done_total += int(g["ach"])
            ach_all_total += int(g["ach_total"] or 0)
    data["manual"] = {
        "done_count": marked_done,
        "ach_count": marked_ach,
        "ach_done_total": ach_done_total,
        "ach_all_total": ach_all_total,
        "saved_count": len(m),
    }
    return data


# ---------------------------------------------------------------- 数据组装

def _local_data(account=None, force=False, enrich=False):
    key = (CONFIG["steam_root"], account, bool(enrich))
    now = time.time()
    with _cache_lock:
        if (not force and not enrich and _cache["key"] == key
                and now - _cache["ts"] < CACHE_TTL and _cache["value"] is not None):
            cached = dict(_cache["value"])
            cached["cached"] = True
            return apply_manual(cached)

    data = steam_local.collect(CONFIG["steam_root"], account, enrich=enrich)
    data["cached"] = False
    if not enrich:
        with _cache_lock:
            _cache.update(key=key, ts=time.time(), value=data)
    return apply_manual(data)


def _fetch_online(cfg, force=False):
    """带缓存的官方接口调用；失败返回 (None, 中文错误)。"""
    key = (cfg["api_key"], cfg["steamid"])
    now = time.time()
    with _cache_lock:
        if (not force and _online_cache["key"] == key
                and now - _online_cache["ts"] < ONLINE_CACHE_TTL
                and _online_cache["value"] is not None):
            return _online_cache["value"], ""

    try:
        owned = steam_online.fetch_owned(cfg["api_key"], cfg["steamid"])
    except steam_online.OnlineError as e:
        return None, str(e)

    with _cache_lock:
        _online_cache.update(key=key, ts=time.time(), value=owned)

    # 顺手把官方名字补进本地缓存，以后断网扫描也能显示正确名字
    try:
        cache = steam_local.load_appinfo_cache()
        fresh = {k: v for k, v in steam_online.online_names(owned).items() if k not in cache}
        if fresh:
            cache.update(fresh)
            steam_local.save_appinfo_cache(cache)
    except Exception:
        pass
    return owned, ""


def get_data(account=None, force=False, enrich=False, online=False):
    local = _local_data(account, force, enrich)
    cfg = CONFIG["_cfg"]

    if not online:
        data = local
        data["online"] = {
            "enabled": False, "ok": False, "error": "",
            "configured": bool(cfg["api_key"] and cfg["steamid"]),
        }
        return data

    if not (cfg["api_key"] and cfg["steamid"]):
        data = local
        data["online"] = {
            "enabled": True, "ok": False, "configured": False,
            "error": "还没有填 SteamID 和 API Key。",
        }
        return data

    owned, err = _fetch_online(cfg, force=force)
    if owned is None:
        data = local
        data["online"] = {"enabled": True, "ok": False, "configured": True, "error": err}
        return data

    # 合并会改动 games 列表，所以复制一份，别污染本地缓存
    data = copy.deepcopy(local)
    persona = ""
    if data.get("account"):
        persona = data["account"].get("persona_name") or ""
    return steam_online.merge_online(data, owned, cfg["steamid"], persona)



class Handler(SimpleHTTPRequestHandler):
    server_version = "SteamReport/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    # 让日志安静一点
    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            return
        sys.stderr.write("[web] %s\n" % (fmt % args))

    # 所有响应都禁止缓存：改完前端按一下刷新就能看到，不会拿到浏览器里的旧 JS/CSS
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            return self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")

        if parsed.path == "/api/data":
            account = (q.get("account") or [None])[0] or None
            force = (q.get("force") or ["0"])[0] == "1"
            enrich = (q.get("enrich") or ["0"])[0] == "1"
            online_raw = (q.get("online") or [None])[0]
            online = CONFIG["_cfg"]["online"] if online_raw is None else online_raw == "1"
            try:
                return self._json(get_data(account, force, enrich, online))
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)

        if parsed.path == "/api/config":
            return self._json(config_public())

        if parsed.path == "/api/achievements":
            appid = (q.get("appid") or [""])[0]
            if not appid.isdigit():
                return self._json({"ok": False, "error": "appid 不对"}, 400)
            cfg = CONFIG["_cfg"]
            if not (cfg["api_key"] and cfg["steamid"]):
                return self._json({"ok": False, "error": "要先连上 Steam 账号（填 API Key + SteamID）才能读成就。"}, 400)

            force = (q.get("force") or [""])[0] in ("1", "true", "yes")
            key = str(int(appid))
            now = int(time.time())
            cur = (load_manual().get(key) or {})

            # 新鲜的话直接吃本地记录，不打 Steam 接口（页面每次打开都会来问一次）
            if not force and cur.get("at") and now - int(cur["at"]) < ACH_TTL:
                if cur.get("noach"):
                    return self._json({"ok": True, "none": True, "cached": True,
                                       "manual": cur})
                if cur.get("source") == "steam" and cur.get("ach_total"):
                    return self._json({"ok": True, "achieved": cur.get("ach") or 0,
                                       "total": cur["ach_total"], "cached": True,
                                       "manual": cur})

            try:
                r = steam_online.fetch_achievements(cfg["api_key"], cfg["steamid"], int(appid))
            except steam_online.OnlineError as e:
                msg = str(e)
                # 「这游戏没有成就系统」不是错误，记一笔就别再问了
                if "没有成就系统" in msg or "400" in msg:
                    rec, _ = update_manual(appid, {"noach": True, "source": "steam"})
                    return self._json({"ok": True, "none": True, "note": msg, "manual": rec})
                return self._json({"ok": False, "error": msg}, 400)
            rec, _ = update_manual(appid, {
                "ach": r["achieved"], "ach_total": r["total"], "source": "steam",
            })
            return self._json({"ok": True, "achieved": r["achieved"], "total": r["total"], "manual": rec})

        if parsed.path == "/api/health":
            return self._json({"ok": True, "steam_root": CONFIG["steam_root"]})

        if parsed.path == "/api/images":
            appid = (q.get("appid") or [""])[0]
            if not appid.isdigit():
                return self._json({"ok": False, "error": "appid 不对"}, 400)
            return self._json({"ok": True, "appid": int(appid),
                               "images": img_public(appid)})

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/api/config", "/api/manual", "/api/images"):
            return self.send_error(404)

        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 40 * 1024 * 1024:
                return self._json({"ok": False, "error": "这次传的东西太大了（上限 40 MB）"}, 413)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("body 必须是 JSON 对象")
        except (ValueError, UnicodeDecodeError) as e:
            return self._json({"ok": False, "error": "请求格式不对：%s" % e}, 400)

        if parsed.path == "/api/images":
            appid = str(payload.get("appid") or "")
            if not appid.isdigit():
                return self._json({"ok": False, "error": "appid 不对"}, 400)
            op = str(payload.get("op") or "add")
            try:
                if op == "del":
                    delete_image(appid, payload.get("name"))
                elif op == "add":
                    save_image(appid, payload.get("name"), payload.get("data"))
                else:
                    return self._json({"ok": False, "error": "不认识的 op：%s" % op}, 400)
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            except OSError as e:
                return self._json({"ok": False, "error": "写/删图片失败：%s" % e}, 500)
            with _cache_lock:
                _cache.update(key=None, ts=0.0, value=None)   # 让 /api/data 重算图片数
            return self._json({"ok": True, "appid": int(appid),
                               "images": img_public(appid)})

        if parsed.path == "/api/manual":
            appid = str(payload.get("appid") or "")
            if not appid.isdigit():
                return self._json({"ok": False, "error": "appid 不对"}, 400)
            try:
                rec, err = update_manual(appid, payload)
            except OSError as e:
                return self._json({"ok": False, "error": "写不进 manual.json：%s" % e}, 500)
            if err:
                return self._json({"ok": False, "error": err}, 400)
            # 汇总得在真正的 games 列表上算（空列表算出来全是 0，前端会被带偏）
            try:
                summary = _local_data().get("manual") or {}
            except Exception:
                summary = {}
            return self._json({"ok": True, "appid": int(appid), "manual": rec,
                               "summary": summary})

        cfg = dict(CONFIG["_cfg"])
        if "api_key" in payload:
            cfg["api_key"] = str(payload.get("api_key") or "").strip()
        if "steamid" in payload:
            sid = str(payload.get("steamid") or "").strip()
            # 允许填自定义网址名，顺手解析成 SteamID64
            if sid and not sid.isdigit():
                if not cfg["api_key"]:
                    return self._json({"ok": False, "error": "填自定义网址名前，得先有 API Key 才能解析。"}, 400)
                try:
                    sid = steam_online.resolve_vanity(cfg["api_key"], sid)
                except steam_online.OnlineError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            cfg["steamid"] = sid
        if "online" in payload:
            cfg["online"] = bool(payload.get("online"))

        try:
            save_config(cfg)
        except OSError as e:
            return self._json({"ok": False, "error": "写不进 config.json：%s" % e}, 500)
        CONFIG["_cfg"] = cfg
        with _cache_lock:
            _online_cache.update(key=None, ts=0.0, value=None)   # 换 Key 了，缓存作废
        return self._json({"ok": True, **config_public()})


def free_port(host, start, tries=12):
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise SystemExit("端口 %d~%d 都被占用了，用 --port 指定一个别的。" % (start, start + tries - 1))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Steam 游玩报告（本地）")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--steam-root", default=steam_local.DEFAULT_STEAM_ROOT)
    ap.add_argument("--account", default=None, help="userdata 目录名，默认最近使用的账号")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--enrich", action="store_true", help="启动时联网补全一次名称缓存")
    ap.add_argument("--online", action="store_true",
                    help="启动时就用 Steam 官方接口拉账号级数据（需要 config.json 里已有 Key）")
    args = ap.parse_args()

    CONFIG["steam_root"] = args.steam_root
    if not os.path.isdir(args.steam_root):
        print("!! 找不到 Steam 目录：%s" % args.steam_root)
        print("   用 --steam-root 指定，例如 --steam-root \"C:\\Program Files (x86)\\Steam\"")
        raise SystemExit(2)
    if not os.path.isdir(WEB_DIR):
        raise SystemExit("缺少 web 目录：%s" % WEB_DIR)

    cfg = CONFIG["_cfg"]
    use_online = args.online or cfg["online"]
    if cfg["api_key"] and cfg["steamid"]:
        print("Steam 账号：%s（API Key %s）" % (cfg["steamid"], mask_key(cfg["api_key"])))
    else:
        print("Steam 账号：未配置（页面上点「连接 Steam 账号」可加上跨设备时长）")

    print("Steam 目录：%s" % args.steam_root)
    print("首次扫描中…")
    t0 = time.time()
    data = get_data(args.account, force=True, enrich=args.enrich, online=use_online)
    inst = [g for g in data["games"] if g["installed"]]
    print("  共 %d 条记录，已安装 %d 款，耗时 %.0f ms" % (
        len(data["games"]), len(inst), (time.time() - t0) * 1000))
    on = data.get("online") or {}
    if on.get("enabled"):
        if on.get("ok"):
            print("  已合并账号数据：%d 款游戏，其中 %d 款本机没有记录" % (
                on["game_count"], on["added"]))
        else:
            print("  !! 联网取账号数据失败：%s" % on.get("error"))
    if data.get("unnamed_count"):
        print("  有 %d 款已卸载游戏还没有名字，页面右上角可一键联网补全" % data["unnamed_count"])

    port = free_port(args.host, args.port)
    if port != args.port:
        print("端口 %d 被占用，改用 %d" % (args.port, port))
    httpd = ThreadingHTTPServer((args.host, port), Handler)
    url = "http://%s:%d/" % (args.host, port)
    print("\n  ▶ 打开： %s" % url)
    print("    按 Ctrl+C 停止\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
steam_online.py —— 走 Steam 官方 Web API 拿「账号级」游玩数据（跨设备、跨年份）。

为什么需要它：本机 userdata 里的 localconfig.vdf 只记录**这台电脑**跑过的时长。
官方接口返回的是账号维度的累计时长，还包括「最近两周」和官方口径的最后运行时间。

需要一个 Steam Web API Key（免费、只读、随时可吊销）：
    https://steamcommunity.com/dev/apikey
Key 只会存进本机的 config.json，脚本不往任何第三方发东西。

用到的接口：
    IPlayerService/GetOwnedGames/v1/          全部拥有游戏：累计时长 / 近两周时长 / 最后运行
    IPlayerService/GetRecentlyPlayedGames/v1/ 最近玩过的游戏
    ISteamUser/ResolveVanityURL/v1/           自定义网址名 → SteamID64
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.steampowered.com/"
UA = "steam-play-report/1.0 (+local tool)"

# SteamID64 与 32 位 accountID 的换算基数
STEAMID64_BASE = 76561197960265728


class OnlineError(Exception):
    """给用户看的中文错误，不往上抛原始异常。

    code 是给程序看的机器可读标记（文案会变，code 不变）：
      "no_stats" = Steam 明确说这个 appid 没有统计数据（多半就是没成就系统）
      "http400"  = 其它 400；"http401"/"http403"/"http429"/"timeout"/"offline"…
    """

    def __init__(self, msg, code=""):
        super().__init__(msg)
        self.code = code


def account_id_from_steamid64(steamid64) -> int:
    return int(steamid64) - STEAMID64_BASE


def steamid64_from_account_id(account_id) -> str:
    return str(int(account_id) + STEAMID64_BASE)


def _api(path: str, params: dict, timeout: float = 25.0, code400: str = "http400") -> dict:
    url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise OnlineError("API Key 无效（Steam 返回 401）。请确认复制完整，或重新申请一个。", "http401")
        if e.code == 403:
            raise OnlineError("Steam 拒绝了这个 Key（403），可能已被吊销。", "http403")
        if e.code == 429:
            raise OnlineError("请求太频繁被 Steam 限流了（429），过几分钟再试。", "http429")
        if e.code == 400:
            # Steam 对「这个 appid 没有统计数据」也是回 400，但正文里会写清楚：
            #   {"playerstats":{"error":"Requested app has no stats","success":false}}
            # 所以这里读一下正文，只有真的写着 no stats 才敢认成 no_stats。
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:                                   # noqa: BLE001
                pass
            code = code400
            if code400 == "no_stats" and "no stats" not in body.lower():
                code = "http400"
            raise OnlineError("Steam 说这个请求不成立（400）—— 最常见的原因是这款游戏没有成就系统。",
                              code)
        raise OnlineError("Steam 返回 HTTP %d。" % e.code, "http%d" % e.code)
    except socket.timeout:
        raise OnlineError("连接 Steam 超时，检查一下网络或代理。", "timeout")
    except urllib.error.URLError as e:
        raise OnlineError("连不上 Steam：%s" % (getattr(e, "reason", e),), "offline")
    try:
        return json.loads(body)
    except ValueError:
        raise OnlineError("Steam 返回的不是 JSON，可能被网络中间层拦了。", "badjson")


def resolve_vanity(api_key: str, vanity: str) -> str:
    """把自定义网址名（steamcommunity.com/id/xxx 里的 xxx）解析成 SteamID64。"""
    data = _api("ISteamUser/ResolveVanityURL/v1/", {
        "key": api_key, "vanityurl": vanity.strip(), "format": "json",
    })
    resp = data.get("response") or {}
    if resp.get("success") == 1 and resp.get("steamid"):
        return str(resp["steamid"])
    raise OnlineError("找不到这个自定义网址名：%s" % vanity.strip())


def fetch_owned(api_key: str, steamid: str) -> dict:
    """返回 {appid: {...}}，键是 int。拿不到就抛 OnlineError。"""
    data = _api("IPlayerService/GetOwnedGames/v1/", {
        "key": api_key,
        "steamid": steamid,
        "include_appinfo": 1,
        "include_played_free_games": 1,
        "format": "json",
    })
    resp = data.get("response")
    if resp is None:
        raise OnlineError("Steam 返回里没有 response 字段，Key 可能不对。")
    raw = resp.get("games") or []
    if not raw:
        # response 为 {} 或空 games：最常见的原因是「游戏详情」没公开
        raise OnlineError(
            "拿到的游戏列表是空的。请确认 SteamID 正确，"
            "并在 Steam 隐私设置里把「游戏详情」设为公开。"
        )
    owned = {}
    for g in raw:
        aid = g.get("appid")
        if not aid:
            continue
        owned[int(aid)] = {
            "name": g.get("name") or "",
            "playtime_forever": int(g.get("playtime_forever") or 0),
            "playtime_2weeks": int(g.get("playtime_2weeks") or 0),
            "rtime_last_played": int(g.get("rtime_last_played") or 0),
            "img_icon_url": g.get("img_icon_url") or "",
        }
    return owned


def fetch_recent(api_key: str, steamid: str) -> dict:
    """最近玩过的游戏（另一个视角，接口里带近两周时长）。"""
    data = _api("IPlayerService/GetRecentlyPlayedGames/v1/", {
        "key": api_key, "steamid": steamid, "count": 20, "format": "json",
    })
    resp = data.get("response") or {}
    out = {}
    for g in resp.get("games") or []:
        aid = g.get("appid")
        if aid:
            out[int(aid)] = {
                "name": g.get("name") or "",
                "playtime_2weeks": int(g.get("playtime_2weeks") or 0),
                "playtime_forever": int(g.get("playtime_forever") or 0),
            }
    return out


# --------------------------------------------------------------------------
# 合并进本地数据
# --------------------------------------------------------------------------

def merge_online(data: dict, owned: dict, steamid: str, persona: str = "") -> dict:
    """把账号级数据合并进 collect() 的结果里。

    合并后的约定（前端只需要认这几个字段）：
      playtime_min         —— 变成「账号总计」，这样所有页面不用改
      playtime_local_min   —— 保留本机那份，供详情页对照
      playtime_total_min   —— 账号总计（和 playtime_min 相同）
      playtime_2weeks_min  —— 最近两周（官方口径，本机文件里没有）
      last_played          —— 取本地与账号两者里更晚的
      online_only          —— 本机完全没记录、只在账号里存在的游戏
    """
    games = {g["appid"]: g for g in data.get("games", [])}
    added = 0
    for aid, o in owned.items():
        g = games.get(aid)
        if g is None:
            g = {
                "appid": aid, "name": "", "installed": False, "library": "",
                "library_exists": True, "installdir": "", "size_bytes": 0,
                "last_updated": 0, "manifest_last_played": 0,
                "playtime_min": 0, "last_played": 0,
                "playtime_disconnected_min": 0, "state_flags": 0, "buildid": 0,
                "source": "online",
            }
            games[aid] = g
            added += 1

        local_min = int(g.get("playtime_min") or 0)
        total_min = int(o.get("playtime_forever") or 0)
        g["playtime_local_min"] = local_min
        g["playtime_total_min"] = total_min
        g["playtime_2weeks_min"] = int(o.get("playtime_2weeks") or 0)
        g["online_last_played"] = int(o.get("rtime_last_played") or 0)
        g["playtime_min"] = max(local_min, total_min)
        g["last_played"] = max(int(g.get("last_played") or 0), g["online_last_played"])
        g["online_only"] = (local_min == 0 and not g.get("installed"))
        # 本地只有 "App 123456" 这种占位名时，用官方名字补上
        nm = g.get("name") or ""
        if (not nm or nm.startswith("App ")) and o.get("name"):
            g["name"] = o["name"]

    data["games"] = sorted(
        games.values(), key=lambda g: (-g["playtime_min"], -g["last_played"], g["name"])
    )

    two_weeks = sum(g.get("playtime_2weeks_min", 0) for g in data["games"])
    data["online"] = {
        "enabled": True,
        "ok": True,
        "steamid": str(steamid),
        "persona": persona,
        "fetched_at": int(time.time()),
        "game_count": len(owned),
        "matched": len(owned) - added,
        "added": added,
        "total_min": sum(g["playtime_min"] for g in data["games"]),
        "two_weeks_min": two_weeks,
        "error": "",
    }
    data["unnamed_count"] = sum(
        1 for g in data["games"] if (g.get("name") or "").startswith("App ")
        and (g.get("name") or "")[4:].isdigit()
    )
    return data


def online_names(owned: dict) -> dict:
    """给 appinfo 缓存用的 {appid: {name, type}}。"""
    return {str(aid): {"name": o["name"], "type": ""}
            for aid, o in owned.items() if o.get("name")}


def fetch_achievements(api_key: str, steamid: str, appid: int) -> dict:
    """单款游戏的成就解锁情况。返回 {"achieved": n, "total": n}。

    注意：只有「带成就系统、且你玩过」的游戏才有数据，剩下的一律抛 OnlineError，
    文案直接来自 Steam（常见是 "Requested app has no stats"）。
    """
    data = _api("ISteamUserStats/GetPlayerAchievements/v1/", {
        "key": api_key, "steamid": steamid, "appid": int(appid), "l": "schinese",
    }, code400="no_stats")
    stats = data.get("playerstats")
    if not isinstance(stats, dict):
        raise OnlineError("Steam 没返回成就数据（可能是这个游戏没有成就系统）。", "no_stats")
    if not stats.get("success"):
        # Steam 自己说没有统计数据的措辞就那几种，认出来才敢记「永久没成就」
        msg = stats.get("error") or ""
        code = "no_stats" if ("no stats" in msg.lower() or "not have" in msg.lower()) else "statsfail"
        raise OnlineError("拿不到成就：%s" % (msg or "这个游戏没有成就数据。"), code)
    achs = stats.get("achievements") or []
    total = len(achs)
    achieved = sum(1 for a in achs if a.get("achieved"))
    return {"achieved": achieved, "total": total}

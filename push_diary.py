#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把日记推送到手机微信。

用法：
    python push_diary.py              # 推最新一篇
    python push_diary.py 2026-10-17   # 推指定日期
    python push_diary.py --list       # 列出所有日记
    python push_diary.py --all        # 推送全部（会分段发）

前提：最近 48 小时内你在微信里给机器人发过消息 —— 微信 bot 不允许
在没有活跃会话时主动推消息（平台限制，不是本工具的问题）。
如果报「会话已过期」，给机器人随便发一句，再跑一次即可。
"""
import sys, io, os, json, base64, random, time, urllib.request, urllib.error, re
from pathlib import Path

DIARY_DIR = Path(r"V:\Software\WorkBench\Wx-work\diary")
CRED = Path(r"C:\Users\Yellow 灿\.dsh\.credentials.yaml")
TOKEN_FILE = Path(r"C:\Users\Yellow 灿\.dsh\diary-push-token.json")
OLD_STATE = Path(r"C:\Users\Yellow 灿\.dsh\dsh-im-connect\accounts\weixin_5623017cb4e0\wechat-state.json")

BASE = "https://ilinkai.weixin.qq.com"
USER = "o9cq806ySnjh5iLjdrLsOOrjmQl0@im.wechat"
CHUNK = 1800          # 单条消息字符上限，超了就分段


# ---------- 凭据 ----------

def read_bot_token():
    """从 DSH 凭据里读微信 bot token。两个键名都试。"""
    if not CRED.exists():
        sys.exit(f"[x] 找不到凭据文件: {CRED}")
    for line in io.open(CRED, encoding="utf-8"):
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key in ("im_connect_weixin_5623017cb4e0_botToken",
                   "DSH_WEIXIN_BOT_TOKEN_1A1A5E5C56AEDB62BE5F7303"):
            return line.split(":", 1)[1].strip().strip("\"'")
    sys.exit("[x] 凭据里没找到微信 bot token")


def headers(token):
    uin = base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()
    return {
        "content-type": "application/json",
        "iLink-App-ClientVersion": "1",
        "X-WECHAT-UIN": uin,
        "Authorization": "Bearer " + token,
        "AuthorizationType": "ilink_bot_token",
    }


def post(path, body, token, timeout=25):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers(token),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------- 拿 context_token ----------
# 微信要求每条消息带 context_token，它只在「收到用户消息」时才下发。
# 所以推送前先拉一次 getupdates：有新消息就有新 token，没有就退回缓存。

def load_cached():
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cached(d):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_context_token(token):
    """拉一次更新，从用户消息里抓 context_token 和最新 sync_buf。"""
    cache = load_cached()

    buf = cache.get("syncBuf", "")
    if not buf and OLD_STATE.exists():
        try:
            buf = json.loads(OLD_STATE.read_text(encoding="utf-8")).get("syncBuf", "")
        except Exception:
            pass

    try:
        data = post("/ilink/bot/getupdates",
                    {"get_updates_buf": buf, "base_info": {"channel_version": "1.0.0"}},
                    token, timeout=30)
    except Exception as e:
        print(f"  [警告] 拉取更新失败: {e}")
        return cache.get("contextToken", "")

    if data.get("get_updates_buf"):
        cache["syncBuf"] = data["get_updates_buf"]

    for msg in data.get("msgs") or []:
        if msg.get("context_token"):
            cache["contextToken"] = msg["context_token"]
            cache["fetchedAt"] = int(time.time())
            break

    save_cached(cache)
    return cache.get("contextToken", "")


# ---------- 发送 ----------

def send_text(token, text, ctx):
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": USER,
            "client_id": "dsh-diary:%d:%d" % (int(time.time() * 1000), random.randint(0, 999999)),
            "message_type": 2,
            "message_state": 2,
            "context_token": ctx,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        },
        "base_info": {"channel_version": "1.0.0"},
    }
    return post("/ilink/bot/sendmessage", body, token)


def push(text, token, ctx):
    """分段发送。返回成功段数。"""
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [text]
    ok = 0
    for idx, part in enumerate(chunks, 1):
        prefix = f"({idx}/{len(chunks)})\n" if len(chunks) > 1 else ""
        try:
            r = send_text(token, prefix + part, ctx)
            ret = int(r.get("ret", 0) or 0)
            if ret == 0:
                ok += 1
                print(f"  第 {idx}/{len(chunks)} 段 已发送")
            else:
                print(f"  第 {idx}/{len(chunks)} 段 被拒: ret={ret} {r.get('errmsg','')}")
                if ret == -2:
                    print("  → context_token 失效，说明会话窗口已关。")
                    return ok
        except urllib.error.HTTPError as e:
            print(f"  第 {idx}/{len(chunks)} 段 HTTP {e.code}")
            return ok
        except Exception as e:
            print(f"  第 {idx}/{len(chunks)} 段 出错: {e}")
            return ok
        time.sleep(0.6)
    return ok


# ---------- 日记 ----------

def all_diaries():
    """按日期倒序返回 [(date, path)]。"""
    out = []
    for p in DIARY_DIR.rglob("*.md"):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.md", p.name)
        if m:
            out.append((m.group(1), p))
    return sorted(out, reverse=True)


def to_plain_text(path):
    """Markdown → 手机上好读的纯文本。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines:
        s = ln.rstrip()
        if s.startswith("# "):
            out.append(s[2:])
            out.append("=" * 20)
        elif s.startswith("## "):
            out.append("")
            out.append("【" + s[3:] + "】")
        elif s.startswith("### "):
            out.append("· " + s[4:])
        elif s.startswith("> "):
            out.append("  " + s[2:])       # 引用降级成缩进
        elif s.strip() in ("---", "***"):
            out.append("-" * 20)
        else:
            out.append(s)
    # 连续空行压成一个
    res, blank = [], False
    for s in out:
        if not s.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        res.append(s)
    return "\n".join(res).strip()


# ---------- 导出文件（不依赖微信，一定能用）----------

OUT_DIR = DIARY_DIR.parent / "diary-txt"


def export_txt(date, path):
    """把一篇日记导成 .txt，返回导出的路径。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"{date}.txt"
    text = to_plain_text(path)
    dst.write_text(text + "\n", encoding="utf-8-sig")   # utf-8-sig：Windows 记事本才认
    return dst


def export_all(picks):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 顺手生成一个合并版，方便一次传走
    merged, names = [], []
    for order, (date, path) in enumerate(picks, 1):
        dst = export_txt(date, path)
        names.append(dst)
        size = dst.stat().st_size
        print(f"  {date}  →  {dst.name}   {size:,} B")
        merged.append(to_plain_text(path))
        merged.append("\n" + "=" * 24 + "\n")
    if len(picks) > 1:
        total = OUT_DIR / "全部日记.txt"
        total.write_text("\n".join(merged).strip() + "\n", encoding="utf-8-sig")
        print(f"  合并版  →  {total.name}   {total.stat().st_size:,} B")
        names.append(total)
    return names


# ---------- 主流程 ----------

def main():
    args = sys.argv[1:]

    diaries = all_diaries()
    if not diaries:
        sys.exit(f"[x] 日记目录里没有 .md 文件: {DIARY_DIR}")

    if "--list" in args:
        print(f"共 {len(diaries)} 篇：")
        for d, p in diaries:
            print(f"  {d}   {p.stat().st_size:>6} B")
        return

    if "--all" in args:
        picks = diaries[::-1]          # 从旧到新
    else:
        # 过滤掉 -- 开头的开关，剩下的才是日期
        pos = [a for a in args if not a.startswith("--")]
        if pos:
            target = pos[0]
            hit = [x for x in diaries if x[0] == target]
            if not hit:
                sys.exit(f"[x] 没找到 {target}，用 --list 看看有哪些")
            picks = hit
        else:
            picks = [diaries[0]]
            print(f"最新一篇：{picks[0][0]}")

    # --- 模式一：只导出 txt，不碰微信 ---
    if "--txt" in args:
        print(f"\n导出 {len(picks)} 篇到 {OUT_DIR}")
        files = export_all(picks)
        print(f"\n完成，共 {len(files)} 个文件。")
        print(f"位置：{OUT_DIR}")
        return

    # --- 模式二：微信推送 ---
    print(f"准备推送 {len(picks)} 篇")
    token = read_bot_token()
    print("  拉取会话 token…")
    ctx = fetch_context_token(token)
    if not ctx:
        print("\n[x] 拿不到 context_token —— 微信会话窗口已关闭。")
        print("    微信规定：机器人只能在你「最近给它发过消息」的窗口内主动推送。")
        print("    你上次和它说话是 34 天前，窗口早关了。\n")
        print("    两条路：")
        print("      A. 手机微信给机器人发一句「在吗」，然后重跑本命令")
        print("      B. 改用文件导出（一定能用）：")
        print("           python push_diary.py --txt")
        print("           python push_diary.py --all --txt")
        sys.exit(1)
    print(f"  token 已就绪（{len(ctx)} 字符）")

    total_ok = 0
    for date, path in picks:
        print(f"\n推送 {date} …")
        text = to_plain_text(path)
        if not text.strip():
            print("  (空文件，跳过)")
            continue
        ok = push(text, token, ctx)
        total_ok += ok
        if ok == 0:
            print("\n[x] 发送失败。若提示 context_token 失效，给机器人发条消息再试。")
            print("    或者改用：python push_diary.py --txt")
            sys.exit(1)

    print(f"\n完成：{len(picks)} 篇，共 {total_ok} 段消息已送达")


if __name__ == "__main__":
    main()

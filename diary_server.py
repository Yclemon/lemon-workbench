#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记手机阅读服务。

电脑上跑起来，手机连同一个 WiFi，浏览器打开就能读日记。
不用传文件、不用微信、不用装 App。

用法：
    python diary_server.py

启动后终端会打印两个地址：
    http://127.0.0.1:8788        电脑上自己看
    http://<你的局域网IP>:8788   手机上用这个

只在本机 + 局域网可见，没有对外的口子。
"""
import io
import re
import sys
import html
import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

DIARY_DIR = Path(__file__).resolve().parent / "diary"
PORT = 8788


# ---------- 日记读取 ----------

def all_diaries():
    """按日期倒序返回 [(date, path)]。"""
    out = []
    for p in DIARY_DIR.rglob("*.md"):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.md", p.name)
        if m:
            out.append((m.group(1), p))
    return sorted(out, reverse=True)


WEEKDAY = "一二三四五六日"


def pretty_date(d):
    """2026-10-17 → 2026年10月17日 星期六"""
    try:
        y, m, dd = d.split("-")
        import datetime
        w = datetime.date(int(y), int(m), int(dd)).weekday()
        return f"{y}年{int(m)}月{int(dd)}日 星期{WEEKDAY[w]}"
    except Exception:
        return d


# ---------- Markdown → HTML（只认日记里会出现的几种）----------

def md_to_html(md):
    lines = md.splitlines()
    out, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        s = raw.rstrip()
        stripped = s.strip()

        if not stripped:
            close_list()
            continue

        if s.startswith("# "):
            close_list()
            out.append(f'<h1>{html.escape(s[2:])}</h1>')
        elif s.startswith("## "):
            close_list()
            out.append(f'<h2>{html.escape(s[3:])}</h2>')
        elif s.startswith("### "):
            close_list()
            out.append(f'<h3>{html.escape(s[4:])}</h3>')
        elif stripped in ("---", "***", "___"):
            close_list()
            out.append("<hr>")
        elif stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        elif stripped.startswith("> "):
            close_list()
            out.append(f'<blockquote>{inline(stripped[2:])}</blockquote>')
        else:
            close_list()
            out.append(f"<p>{inline(s)}</p>")

    close_list()
    return "\n".join(out)


def inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+?)`", r"<code>\1</code>", t)
    return t


# ---------- 页面 ----------

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1115; --card:#171a21; --line:#252a34;
  --fg:#e6e8ec; --dim:#8b93a1; --accent:#4a9eff;
}
@media (prefers-color-scheme: light){
  :root{ --bg:#f7f8fa; --card:#fff; --line:#e3e6ec; --fg:#1a1d23; --dim:#6b7280; --accent:#0066cc; }
}
body{
  background:var(--bg); color:var(--fg);
  font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  padding:16px 14px 60px; max-width:720px; margin:0 auto;
  -webkit-text-size-adjust:100%;
}
a{color:var(--accent);text-decoration:none}
header{padding:8px 0 18px;border-bottom:1px solid var(--line);margin-bottom:18px}
header h1{font-size:21px;font-weight:600;letter-spacing:.5px}
header p{color:var(--dim);font-size:13px;margin-top:6px}

.entry{
  display:block;background:var(--card);border:1px solid var(--line);
  border-radius:12px;padding:15px 17px;margin-bottom:11px;
  transition:border-color .15s;
}
.entry:active{border-color:var(--accent)}
.entry .d{font-size:17px;font-weight:600;margin-bottom:5px}
.entry .p{color:var(--dim);font-size:13px;line-height:1.5;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

.back{display:inline-block;margin-bottom:16px;font-size:14px;color:var(--dim)}
.back:active{color:var(--accent)}

article h1{font-size:24px;font-weight:650;line-height:1.35;margin-bottom:6px}
article h2{font-size:16px;font-weight:600;color:var(--accent);
  margin:26px 0 10px;letter-spacing:.3px}
article h3{font-size:15px;font-weight:600;margin:18px 0 8px}
article p{margin:9px 0;white-space:pre-wrap}
article ul{margin:10px 0 10px 22px}
article li{margin:5px 0}
article hr{border:0;border-top:1px solid var(--line);margin:24px 0}
article blockquote{border-left:3px solid var(--line);padding-left:14px;
  color:var(--dim);margin:12px 0}
article code{background:var(--card);padding:2px 6px;border-radius:4px;
  font-family:ui-monospace,Consolas,monospace;font-size:14px}
.nav{display:flex;gap:11px;margin-top:36px;padding-top:20px;border-top:1px solid var(--line)}
.nav a{flex:1;text-align:center;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:13px;font-size:14px}
.nav a:active{border-color:var(--accent)}
.copy{
  display:block;width:100%;margin:22px 0 0;padding:14px;
  background:var(--accent);color:#fff;border:0;border-radius:10px;
  font-size:15px;font-weight:600;font-family:inherit;cursor:pointer;
}
.copy:active{opacity:.8}
.copy.done{background:#2ea043}
.empty{color:var(--dim);text-align:center;padding:60px 20px;line-height:2}
"""

COPY_JS = """
function copyAll(btn){
  const el = document.querySelector('article');
  // innerText 会自动把 <p> 之间的换行还原成空行，粘到笔记 App 里才像一篇文章
  const text = el.innerText.trim();
  const done = () => {
    btn.textContent = '已复制 ✓';
    btn.classList.add('done');
    setTimeout(() => { btn.textContent = '复制全文'; btn.classList.remove('done'); }, 2000);
  };
  if (navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
  function fallback(){
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); }
    catch(e){ btn.textContent = '复制失败，请长按选中'; }
    document.body.removeChild(ta);
  }
}
"""


def page(title, body):
    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head><body>
{body}
</body></html>"""


def render_index():
    items = all_diaries()
    if not items:
        body = ('<header><h1>日记</h1></header>'
                '<div class="empty">还没有日记。<br>在电脑上说一句「写日记」就能开始。</div>')
        return page("日记", body)

    cards = []
    for d, p in items:
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            txt = ""
        preview = " ".join(
            ln.strip().lstrip("#>-* ").strip()
            for ln in txt.splitlines()
            if ln.strip() and not ln.strip().startswith(("#", "---"))
        )[:120]
        cards.append(
            f'<a class="entry" href="/d/{d}">'
            f'<div class="d">{html.escape(pretty_date(d))}</div>'
            f'<div class="p">{html.escape(preview)}</div></a>'
        )

    body = (f'<header><h1>日记</h1>'
            f'<p>共 {len(items)} 篇 · 最新在上</p></header>'
            + "".join(cards))
    return page("日记", body)


def render_entry(date):
    hit = [x for x in all_diaries() if x[0] == date]
    if not hit:
        return None
    _, path = hit[0]
    md = path.read_text(encoding="utf-8")

    items = [x[0] for x in all_diaries()]
    i = items.index(date)
    newer = items[i - 1] if i > 0 else None
    older = items[i + 1] if i + 1 < len(items) else None

    nav = ['<div class="nav">']
    nav.append(f'<a href="/d/{newer}">← 更新</a>' if newer else '<a style="opacity:.35">← 更新</a>')
    nav.append('<a href="/">全部</a>')
    nav.append(f'<a href="/d/{older}">更早 →</a>' if older else '<a style="opacity:.35">更早 →</a>')
    nav.append('</div>')

    body = (f'<a class="back" href="/">← 全部日记</a>'
            f'<article>{md_to_html(md)}</article>'
            f'<button class="copy" onclick="copyAll(this)">复制全文</button>'
            '<script>' + COPY_JS + '</script>'
            + "".join(nav))
    return page(pretty_date(date), body)


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "Diary"

    def log_message(self, fmt, *a):
        pass                                  # 静音，手机刷屏没意义

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")     # 写完日记刷新即见
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/":
            return self._send(200, render_index())

        if path.startswith("/d/"):
            date = path[3:]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self._send(400, page("出错了", "<p>日期格式不对</p>"))
            out = render_entry(date)
            if out is None:
                return self._send(404, page("找不到",
                    '<div class="empty">没有这一天的日记。<br><a href="/">← 回列表</a></div>'))
            return self._send(200, out)

        if path == "/favicon.ico":
            return self._send(204, "")

        self._send(404, page("找不到", '<div class="empty">页面不存在<br><a href="/">← 回列表</a></div>'))


def lan_ip():
    """拿到本机在局域网里的 IP（不会真发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    for a in sys.argv[1:]:
        if a.isdigit():
            globals()["PORT"] = int(a)

    if not DIARY_DIR.exists():
        sys.exit(f"[x] 找不到日记目录: {DIARY_DIR}")

    ip = lan_ip()
    print()
    print("  " + "=" * 46)
    print("      日记 —— 手机阅读")
    print("  " + "=" * 46)
    print()
    print(f"  电脑上打开:   http://127.0.0.1:{PORT}")
    print(f"  手机上打开:   http://{ip}:{PORT}")
    print()
    print("  手机要和电脑连同一个 WiFi。")
    print("  把这个地址存成手机浏览器书签，以后点开就能看。")
    print()
    print("  关掉这个窗口 = 服务停止。")
    print("  " + "-" * 46)
    print()

    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Timer(0.7, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")


if __name__ == "__main__":
    main()

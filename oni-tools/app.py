#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺氧计算查询工具 —— 本地服务

设计原则（沿用 steam-play 的调性）:
  - 只读本地 JSON 数据，不联网、不写入用户文件
  - 纯标准库，零第三方依赖
  - 只监听 127.0.0.1，不对外
"""
import json
import os
import sys
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DATA = os.path.join(HERE, "data")
PORT = 8781
HOST = "127.0.0.1"

# 允许前端读取的数据文件（白名单，防止目录穿越）
ALLOWED = {"buildings.json", "elements.json", "recipes.json", "meta.json",
           "rooms.json", "tags.json", "buildings_rooms.json"}


class Handler(SimpleHTTPRequestHandler):
    """静态文件 + /api/data/<名字> 数据接口。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        # 静音常规访问日志，只在出错时打印
        if not str(args[1] if len(args) > 1 else "").startswith("2"):
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def do_GET(self):
        if self.path.startswith("/api/data/"):
            name = self.path[len("/api/data/"):].split("?")[0]
            if name not in ALLOWED:
                self.send_error(404, "unknown dataset")
                return
            path = os.path.join(DATA, name)
            if not os.path.isfile(path):
                self.send_error(404, "not found")
                return
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except OSError as e:
                self.send_error(500, f"read failed: {e}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # 本地工具，禁掉缓存免得改了文件刷新看不到
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    if not os.path.isdir(WEB):
        print(f"错误: 找不到前端目录 {WEB}")
        return 1
    os.makedirs(DATA, exist_ok=True)

    n = 0
    bpath = os.path.join(DATA, "buildings.json")
    if os.path.isfile(bpath):
        try:
            with open(bpath, encoding="utf-8") as f:
                n = len(json.load(f))
        except (OSError, ValueError):
            n = -1

    url = f"http://{HOST}:{PORT}/"
    print("=" * 52)
    print("  缺氧计算查询工具")
    print("=" * 52)
    print(f"  建筑数据: {n} 条" if n > 0 else "  建筑数据: 尚未生成")
    print(f"  地址    : {url}")
    print("  关闭    : 按 Ctrl+C")
    print("=" * 52)

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

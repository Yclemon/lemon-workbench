#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载 ilspycmd 工具包并解压到项目本地目录（不装系统）。

用法:
    python fetch_ilspy.py 8.2.0.7535
"""
import io
import os
import ssl
import sys
import urllib.request
import zipfile

ssl._create_default_https_context = ssl._create_unverified_context

DEST_ROOT = os.path.dirname(os.path.abspath(__file__))


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "oni-tools"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        total = resp.headers.get("Content-Length")
        print(f"  HTTP {resp.status}  Content-Length={total}")
        return resp.read()


def main() -> int:
    ver = sys.argv[1] if len(sys.argv) > 1 else "8.2.0.7535"
    pkg_dir = os.path.join(DEST_ROOT, "tools", f"ilspycmd-{ver}")
    url = (
        f"https://api.nuget.org/v3-flatcontainer/ilspycmd/{ver}/"
        f"ilspycmd.{ver}.nupkg"
    )
    print(f"下载 {ver}")
    print(f"  {url}")
    data = download(url)
    print(f"  已下载 {len(data) / 1024 / 1024:.2f} MB")

    os.makedirs(pkg_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        print(f"  包内 {len(names)} 个文件")
        for n in names[:30]:
            print(f"    {n}")
        zf.extractall(pkg_dir)
    print(f"\n解压到: {pkg_dir}")

    # 找到主程序 dll 和 runtimeconfig.json
    for root, _dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.lower().endswith((".dll", ".runtimeconfig.json", ".deps.json")):
                p = os.path.join(root, f)
                print(f"  {os.path.relpath(p, pkg_dir)}  ({os.path.getsize(p) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

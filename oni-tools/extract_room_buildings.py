# -*- coding: utf-8 -*-
"""
生成 buildings_rooms.json —— 186 栋与房间判定相关的建筑。

这是一个纯组装步骤，把三份已有产物合并：
  target_room_buildings.txt         目标建筑类名清单（一行一个，带 Config 后缀）
  _decomp/<类名>.cs                 尺寸、功率、质量、建造时间
  build_names_zh.json               中文名（由 build_names.py 生成）

用法:
  python extract_room_buildings.py

前置:
  python build_names.py        先生成中文名表
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DECOMP = os.path.join(HERE, "_decomp")
TARGETS = os.path.join(HERE, "target_room_buildings.txt")
NAMES = os.path.join(HERE, "build_names_zh.json")
OUT = os.path.join(HERE, "buildings_rooms.json")


def load_targets():
    """目标清单: 一行一个建筑类名，'#' 后为注释"""
    if not os.path.isfile(TARGETS):
        return []
    out = []
    with open(TARGETS, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def read_config(cls):
    """读反编译源码，抓尺寸与运行参数"""
    for fname in (cls + ".cs", cls + "Config.cs"):
        p = os.path.join(DECOMP, fname)
        if os.path.isfile(p):
            return open(p, encoding="utf-8", errors="ignore").read()
    return None


def parse_id_decl(src, cls):
    """找 ID 变量声明: public const string ID = "Shower"; / private static readonly string ID = ..."""
    m = (re.search(r'\bID\s*=\s*"(\w+)"', src)
         or re.search(r'SetOverlaySymbol\(\s*"(\w+)"', src))
    if m:
        return m.group(1)
    # 兜底：类名去掉 Config 后缀（ShowerConfig -> Shower）
    if cls.endswith("Config") and len(cls) > 6:
        return cls[:-6]
    return None


def parse_one(cls, src):
    rec = {"class": cls}

    # 主力写法: BuildingTemplates.CreateBuildingDef("ID", width, height, "anim", time, mass, ...)
    # ID 位置也可能是变量（如 ShowerConfig 用 ID）
    m = re.search(
        r'CreateBuildingDef\(\s*("?\w+"?)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]*)"\s*,'
        r'\s*([\d.]+)f?\s*,\s*([\d.]+)f?',
        src)
    if m:
        raw = m.group(1).strip('"')
        rec["id"] = parse_id_decl(src, cls) if raw == "ID" else raw
        rec["width"] = int(m.group(2))
        rec["height"] = int(m.group(3))
        rec["build_time_s"] = float(m.group(5))
        rec["build_mass_kg"] = float(m.group(6))
    else:
        # 退化写法 1: 命名参数/乱序 —— 只抓 ID 与尺寸（裸数字对）
        m = re.search(r'CreateBuildingDef\(\s*("?\w+"?)\s*,\s*(\d+)\s*,\s*(\d+)', src)
        if m:
            raw = m.group(1).strip('"')
            rec["id"] = parse_id_decl(src, cls) if raw == "ID" else raw
            rec["width"] = int(m.group(2))
            rec["height"] = int(m.group(3))
        else:
            # 退化写法 2: 命名参数打乱顺序 —— 找成对的 width/height
            mw = re.search(r'\bwidth:\s*(\d+)', src)
            mh = re.search(r'\bheight:\s*(\d+)', src)
            if mw and mh:
                rec["width"] = int(mw.group(1))
                rec["height"] = int(mh.group(1))
            rec["id"] = parse_id_decl(src, cls)
            m2 = re.search(r'SetSize\(\s*new\s+CellOffset\(\s*(\d+)\s*,\s*(\d+)\s*\)', src)
            if m2 and "width" not in rec:
                rec["width"] = int(m2.group(1))
                rec["height"] = int(m2.group(2))

    # 建造时间（上面没抓到时兜底）
    if "build_time_s" not in rec:
        m = re.search(r'ConstructionTime\s*=\s*([\d.]+)f?', src)
        if m:
            rec["build_time_s"] = float(m.group(1))

    # 建造质量（兜底）
    if "build_mass_kg" not in rec:
        m = (re.search(r'MassForConstruction\s*=\s*([\d.]+)f?', src)
             or re.search(r'\bMass\s*=\s*([\d.]+)f?', src))
        if m:
            rec["build_mass_kg"] = float(m.group(1))

    # 耗电: EnergyConsumptionWhenActive
    m = re.search(r'EnergyConsumptionWhenActive\s*=\s*([\d.]+)f?', src)
    if m:
        rec["power_w"] = float(m.group(1))

    # 发热: SelfHeatKilowattsWhenActive / ExhaustKilowattsWhenActive
    m = re.search(r'SelfHeatKilowattsWhenActive\s*=\s*([\d.]+)f?', src)
    if m:
        rec["self_heat_kw"] = float(m.group(1))
    m = re.search(r'ExhaustKilowattsWhenActive\s*=\s*([\d.]+)f?', src)
    if m:
        rec["exhaust_heat_kw"] = float(m.group(1))

    return rec if "id" in rec else None


def main():
    targets = load_targets()
    if not targets:
        print(f"错误: 目标清单为空或不存在 -> {TARGETS}")
        return 1

    names = {}
    if os.path.isfile(NAMES):
        blob = json.load(open(NAMES, encoding="utf-8"))
        names = {k.upper(): v for k, v in blob.get("by_id", {}).items()}
    else:
        print(f"提示: 未找到 {NAMES}，中文名将留空（先跑 build_names.py）")

    out, skipped = [], []
    for cls in targets:
        src = read_config(cls)
        if src is None:
            skipped.append((cls, "找不到源码"))
            continue
        rec = parse_one(cls, src)
        if rec is None:
            skipped.append((cls, "解析不出 ID"))
            continue
        bid = (rec.get("id") or "").upper()
        rec["name_cn"] = names.get(bid) or rec["id"]
        out.append(rec)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"目标清单: {len(targets)} 栋")
    print(f"成功解析: {len(out)} 栋")
    print(f"跳过    : {len(skipped)} 栋")
    print(f"输出    : {OUT}")

    named = sum(1 for r in out if r["name_cn"] != r["id"])
    print(f"有中文名: {named} 栋")

    if skipped:
        print("\n--- 跳过明细 ---")
        for cls, why in skipped[:15]:
            print(f"  {cls:<32} {why}")

    print("\n--- 抽查 ---")
    for r in out[:5]:
        print(f"  {r['class']:<28} {r.get('name_cn',''):<8} "
              f"{r.get('width','?')}x{r.get('height','?')}  "
              f"耗电 {r.get('power_w','-')}W")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

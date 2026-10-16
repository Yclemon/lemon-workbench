#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从缺氧反编译源码中提取建筑数值。

数据来源: Assembly-CSharp.dll 反编译出的 C# 源码（_decomp/）
输出: buildings.json

提取逻辑基于缺氧的代码约定:
  - 每个建筑一个 XxxConfig 类，实现 IBuildingConfig
  - 类里有 `public const string ID = "建筑ID";`
  - CreateBuildingDef() 里有 BuildingTemplates.CreateBuildingDef(...) 调用
  - 数值写在 obj.XXX = NNNf 的赋值里
  - 输入输出写在 ElementConverter.ConsumedElement / OutputElement

设计原则: **宁可漏，不可错**。抓不准的字段就不抓，绝不算错。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DECOMP = os.path.join(HERE, "_decomp")
TARGETS = os.path.join(HERE, "target_buildings.txt")
OUT = os.path.join(HERE, "buildings.json")


def find_source(name: str) -> str | None:
    """递归查找配置类源码。

    关键: 同名有两个文件 —— <类名>.cs 是执行层组件（Electrolyzer 的
    运行逻辑），<类名>Config.cs 才是配置类（ID、尺寸、耗电、转换率）。
    必须优先 Config 版本，否则抓到组件文件会缺 ID 和转换率。
    """
    candidates = []
    if not name.endswith("Config"):
        candidates.append(name + "Config.cs")
    candidates.append(name + ".cs")

    for root, _dirs, files in os.walk(DECOMP):
        for cand in candidates:
            if cand in files:
                return os.path.join(root, cand)
    return None


def read_targets() -> list[tuple[str, str]]:
    """读目标清单，返回 [(类名, 中文注释)]。"""
    out: list[tuple[str, str]] = []
    with open(TARGETS, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("#", 1)
            cls = parts[0].strip()
            note = parts[1].strip() if len(parts) > 1 else ""
            if cls:
                out.append((cls, note))
    return out


# ---------- 数值解析 ----------

# 捕获组里只放数字部分，f 后缀放在组外，这样 group(1) 一定是纯数字。
# 注意: 用于 findall 时必须用 NONCAP（非捕获组），否则会多出分组。
NUM = r"(-?\d+(?:\.\d+)?)"
NONCAP = r"(?:-?\d+(?:\.\d+)?)"


def grab_float(src: str, pattern: str) -> float | None:
    """按 pattern 抓一个浮点数，抓不到返回 None。"""
    m = re.search(pattern, src)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (ValueError, IndexError):
        return None


def parse_building(src: str, cls: str, note: str) -> dict:
    """解析单个建筑的 Config 源码。"""
    rec: dict = {"class": cls, "name_cn": note}

    # --- 建筑 ID ---
    m = re.search(r'ID\s*=\s*"([^"]+)"', src)
    if m:
        rec["id"] = m.group(1)

    # --- 尺寸 / 建造材质质量 / 建造时间 ---
    # BuildingTemplates.CreateBuildingDef(id, width, height, anim, time, mass, ...)
    m = re.search(
        r"CreateBuildingDef\(\s*[^,]+,\s*(\d+)\s*,\s*(\d+)\s*,[^,]*,\s*(\d+)\s*,\s*(" + NUM + r")f",
        src,
    )
    if m:
        rec["width"] = int(m.group(1))
        rec["height"] = int(m.group(2))
        rec["build_time_s"] = int(m.group(3))
        rec["build_mass_kg"] = float(m.group(4))

    # --- 耗电 ---
    v = grab_float(src, r"EnergyConsumptionWhenActive\s*=\s*(" + NUM + r")f")
    if v is not None:
        rec["power_w"] = v
    # 发电机: 发电量（注意是 GeneratorWattageRating，不是 WattageRating）
    # 但变压器也用这个字段存电池容量，必须要求存在 EnergyGenerator 才算真发电机
    has_energy_gen = "EnergyGenerator" in src
    v2 = grab_float(src, r"GeneratorWattageRating\s*=\s*(" + NUM + r")f")
    if v2 is not None and has_energy_gen:
        rec["generator_w"] = v2
        rec["is_generator"] = True
    # 备用容量
    v2b = grab_float(src, r"GeneratorBaseCapacity\s*=\s*(" + NUM + r")f")
    if v2b is not None and has_energy_gen:
        rec["generator_capacity_j"] = v2b

    # --- 发电机燃料公式 ---
    # EnergyGenerator.CreateSimpleFormula(消耗Tag, 消耗率, 存储量, 输出元素, 输出率, ...)
    mf = re.search(
        r"CreateSimpleFormula\(\s*SimHashes\.(\w+)\.CreateTag\(\)\s*,\s*("
        + NONCAP + r")f\s*,\s*(" + NONCAP + r")f\s*,\s*SimHashes\.(\w+)\s*,\s*("
        + NONCAP + r")f",
        src,
    )
    if mf:
        rec["fuel_formula"] = {
            "fuel": mf.group(1),
            "fuel_rate_kg_s": float(mf.group(2)),
            "fuel_storage_kg": float(mf.group(3)),
            "exhaust_element": mf.group(4),
            "exhaust_rate_kg_s": float(mf.group(5)),
        }
        temp_m = re.search(r",\s*(" + NONCAP + r")f\s*\);", src[mf.start():mf.start() + 600])
        if temp_m:
            rec["fuel_formula"]["exhaust_temp_k"] = float(temp_m.group(1))

    # 变体: new Tag("Coal") 形式
    if "fuel_formula" not in rec:
        mf2 = re.search(
            r"CreateSimpleFormula\(\s*new Tag\(\"([^\"]+)\"\)\s*,\s*("
            + NONCAP + r")f\s*,\s*(" + NONCAP + r")f\s*,\s*SimHashes\.(\w+)\s*,\s*("
            + NONCAP + r")f",
            src,
        )
        if mf2:
            rec["fuel_formula"] = {
                "fuel": mf2.group(1),
                "fuel_rate_kg_s": float(mf2.group(2)),
                "fuel_storage_kg": float(mf2.group(3)),
                "exhaust_element": mf2.group(4),
                "exhaust_rate_kg_s": float(mf2.group(5)),
            }

    # 变体: 裸字符串 "BuildingWood" 形式（木料发电机）
    if "fuel_formula" not in rec:
        mf3 = re.search(
            r"CreateSimpleFormula\(\s*\"([^\"]+)\"\s*,\s*("
            + NONCAP + r")f\s*,\s*\w+\s*,\s*SimHashes\.(\w+)\s*,\s*("
            + NONCAP + r")f",
            src,
        )
        if mf3:
            rec["fuel_formula"] = {
                "fuel": mf3.group(1),
                "fuel_rate_kg_s": float(mf3.group(2)),
                "exhaust_element": mf3.group(3),
                "exhaust_rate_kg_s": float(mf3.group(4)),
                "note": "存储量用变量表达，未取到固定值",
            }

    # 变体: 3 参数版 CreateSimpleFormula(fuelTag, rate, storage)（氢气发电机）
    if "fuel_formula" not in rec:
        mf4 = re.search(
            r"CreateSimpleFormula\(\s*SimHashes\.(\w+)\.CreateTag\(\)\s*,\s*("
            + NONCAP + r")f\s*,\s*(" + NONCAP + r")f\s*\)",
            src,
        )
        if mf4:
            rec["fuel_formula"] = {
                "fuel": mf4.group(1),
                "fuel_rate_kg_s": float(mf4.group(2)),
                "fuel_storage_kg": float(mf4.group(3)),
                "note": "仅消耗型，尾气/产物需查执行层",
            }

    # --- 发热 ---
    v = grab_float(src, r"SelfHeatKilowattsWhenActive\s*=\s*(" + NUM + r")f")
    if v is not None:
        rec["self_heat_kw"] = v
    v = grab_float(src, r"ExhaustKilowattsWhenActive\s*=\s*(" + NUM + r")f")
    if v is not None:
        rec["exhaust_heat_kw"] = v

    # --- 管道消耗率 ---
    v = grab_float(src, r"consumptionRate\s*=\s*(" + NUM + r")f")
    if v is not None:
        rec["conduit_consumption_kg_s"] = v

    # --- 输入元素 ---
    ins = re.findall(
        r"new ElementConverter\.ConsumedElement\(\s*new Tag\(\"([^\"]+)\"\)\s*,\s*(" + NONCAP + r")f\s*\)",
        src,
    )
    if ins:
        rec["inputs"] = [{"element": e, "rate_kg_s": float(r)} for e, r in ins]

    # --- 输出元素 ---
    outs = re.findall(
        r"new ElementConverter\.OutputElement\(\s*(" + NONCAP + r")f\s*,\s*SimHashes\.(\w+)\s*,\s*(" + NONCAP + r")f",
        src,
    )
    if outs:
        rec["outputs"] = [
            {"rate_kg_s": float(r), "element": el, "temp_k": float(t)}
            for r, el, t in outs
        ]

    # --- 转换率常量（有些建筑用它而非 ElementConverter）---
    ratios = re.findall(r"float (\w*(?:RATIO|RATE)\w*)\s*=\s*(" + NONCAP + r")f", src)
    if ratios:
        rec["constants"] = {k: float(v) for k, v in ratios}

    return rec


def main() -> int:
    targets = read_targets()
    print(f"目标建筑: {len(targets)} 个")

    results: list[dict] = []
    missing: list[str] = []

    for cls, note in targets:
        path = find_source(cls)
        if path is None:
            missing.append(cls)
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        results.append(parse_building(src, cls, note))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    print(f"提取成功: {len(results)}")
    print(f"未找到  : {len(missing)}")
    if missing:
        print("  " + ", ".join(missing))
    print(f"输出    : {OUT}")

    # 预览几个关键建筑
    print("\n--- 抽查 ---")
    for key in ("Electrolyzer", "Generator", "MetalRefinery"):
        for r in results:
            if r.get("id") == key:
                print(f"  {r['id']} ({r['name_cn']}): "
                      f"power={r.get('power_w')} "
                      f"in={r.get('inputs')} out={r.get('outputs')}")
                break
    no_id = [r["class"] for r in results if "id" not in r]
    if no_id:
        print(f"\n注意: {len(no_id)} 个类没有 ID 字段: {', '.join(no_id[:10])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
提取「测算」用的游戏常量 —— 小人呼吸、饮食等。

这些是散落在 TUNING/ 目录下的调参常量，不在建筑配置里。
用法:
  python extract_constants.py     ->  constants.json
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DECOMP = os.path.join(HERE, "_decomp")
OUT = os.path.join(HERE, "constants.json")


def grab(src, pattern, cast=float):
    m = re.search(pattern, src)
    return cast(m.group(1)) if m else None


def grab_expr(src, name):
    """取常量值，支持 1f / 6f、-1000000f、0.1f 三种写法"""
    # 形式一: NAME = A f / B f
    m = re.search(
        name + r"\s*=\s*(-?[\d.]+)f\s*/\s*(-?[\d.]+)f", src)
    if m:
        return round(float(m.group(1)) / float(m.group(2)), 6)
    # 形式二: NAME => A f / B f   （表达式成员）
    m = re.search(
        name + r"\s*=>\s*(-?[\d.]+)f\s*/\s*(-?[\d.]+)f", src)
    if m:
        return round(float(m.group(1)) / float(m.group(2)), 6)
    # 形式三: 普通字面量
    m = re.search(name + r"\s*=\s*(-?[\d.]+)f", src)
    if m:
        return float(m.group(1))
    m = re.search(name + r"\s*=>\s*(-?[\d.]+)f", src)
    if m:
        return float(m.group(1))
    return None


def main():
    path = os.path.join(DECOMP, "TUNING", "DUPLICANTSTATS.cs")
    if not os.path.isfile(path):
        print(f"错误: 找不到 {path}")
        return 1
    src = open(path, encoding="utf-8").read()

    const = {}

    # --- 小人基础呼吸 ---
    const["oxygen_used_per_second"] = grab(
        src, r"OXYGEN_USED_PER_SECOND\s*=\s*([\d.]+)f")
    const["oxygen_to_co2_conversion"] = grab(
        src, r"OXYGEN_TO_CO2_CONVERSION\s*=\s*([\d.]+)f")
    const["low_oxygen_threshold"] = grab(
        src, r"LOW_OXYGEN_THRESHOLD\s*=\s*([\d.]+)f")
    const["no_oxygen_threshold"] = grab(
        src, r"NO_OXYGEN_THRESHOLD\s*=\s*([\d.]+)f")
    const["min_co2_to_emit"] = grab(
        src, r"MIN_CO2_TO_EMIT\s*=\s*([\d.]+)f")

    # --- 饮食 / 代谢 ---
    const["calories_burned_per_cycle"] = grab_expr(src, "CALORIES_BURNED_PER_CYCLE")
    const["max_calories"] = grab_expr(src, "MAX_CALORIES")
    const["bladder_increase_per_second"] = grab_expr(
        src, "BLADDER_INCREASE_PER_SECOND")
    const["stamina_used_per_second"] = grab_expr(
        src, "STAMINA_USED_PER_SECOND")

    # --- 单位换算参考 ---
    const["_units"] = {
        "oxygen_used_per_second": "kg/s（游戏内显示 100 g/s）",
        "oxygen_to_co2_conversion": "呼出 CO2 = 吸入 O2 × 此比例",
        "calories_burned_per_cycle": "千卡/周期（源码为负数，此处保留负号）",
        "bladder_increase_per_second": "每秒膀胱增量（1/6 = 约 6 秒涨满 1%）",
    }

    # --- 制氧设备（从建筑数据里挑，避免重复提取）---
    bpath = os.path.join(HERE, "buildings.json")
    makers = []
    if os.path.isfile(bpath):
        for b in json.load(open(bpath, encoding="utf-8")):
            oxy = [o for o in (b.get("outputs") or [])
                   if o.get("element") == "Oxygen"]
            if oxy:
                makers.append({
                    "id": b.get("id"),
                    "name_cn": b.get("name_cn"),
                    "oxygen_kg_s": sum(o["rate_kg_s"] for o in oxy),
                    "power_w": b.get("power_w"),
                    "inputs": b.get("inputs") or [],
                    "outputs": b.get("outputs") or [],
                })
    const["oxygen_makers"] = makers

    # --- 发电机（发电量 + 燃料）---
    gens = []
    if os.path.isfile(bpath):
        for b in json.load(open(bpath, encoding="utf-8")):
            if b.get("generator_w"):
                gens.append({
                    "id": b.get("id"),
                    "name_cn": b.get("name_cn"),
                    "wattage": b["generator_w"],
                    "fuel_formula": b.get("fuel_formula"),
                })
    const["generators"] = gens

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(const, f, ensure_ascii=False, indent=1)

    print("=== 小人常量 ===")
    for k in ("oxygen_used_per_second", "oxygen_to_co2_conversion",
              "low_oxygen_threshold", "no_oxygen_threshold",
              "calories_burned_per_cycle", "bladder_increase_per_second",
              "stamina_used_per_second"):
        print(f"  {k:<32} {const.get(k)}")
    print(f"\n制氧设备: {len(makers)} 台")
    for m in makers:
        print(f"  {m['name_cn']:<12} {m['oxygen_kg_s']*1000:>7.1f} g/s  "
              f"耗电 {m['power_w']}W")
    print(f"\n发电机: {len(gens)} 台")
    for g in gens:
        fuel = (g["fuel_formula"] or {}).get("fuel_rate_kg_s")
        print(f"  {g['name_cn']:<12} {g['wattage']:>6.0f}W  燃料 {fuel} kg/s")
    print(f"\n输出: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

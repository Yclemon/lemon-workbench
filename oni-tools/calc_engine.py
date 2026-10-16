# -*- coding: utf-8 -*-
"""
缺氧测算引擎 —— 制氧测算 + 供电测算。

数据来源: constants.json（由 extract_constants.py 从游戏源码提取）

命令行用法:
  python calc_engine.py oxy 8               # 8 个人需要几台制氧机
  python calc_engine.py oxy --machines 2 Electrolyzer   # 2 台电解器能养几个人
  python calc_engine.py power Electrolyzer:2 LiquidPump:1   # 用电汇总 + 发电机配比
  python calc_engine.py list                # 列出可用设备

网页端由 web/calc.js 调用同名逻辑。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONST = os.path.join(HERE, "constants.json")
BUILDINGS = os.path.join(HERE, "buildings.json")

# 元素中文名（与前端 ELEM_CN 保持一致的精简版）
ELEM_CN = {
    "Oxygen": "氧气", "Hydrogen": "氢气", "Water": "水", "DirtyWater": "污水",
    "CarbonDioxide": "二氧化碳", "Carbon": "煤", "Algae": "藻类",
    "Rust": "铁锈", "Salt": "盐", "IronOre": "铁矿石", "ChlorineGas": "氯气",
    "Methane": "天然气", "CombustibleLiquid": "燃油", "BuildingWood": "木材",
    "ContaminatedOxygen": "污染氧", "Clay": "黏土", "Sand": "沙子",
    "Fertilizer": "肥料", "ToxicSand": "污染沙", "Phosphorite": "磷灰石",
}


def elem_cn(e):
    return ELEM_CN.get(e, e)


def load_json(p):
    if not os.path.isfile(p):
        print(f"错误: 找不到 {p}")
        print("       请先运行 python extract_constants.py")
        return None
    return json.load(open(p, encoding="utf-8"))


# ============ 制氧测算 ============
def calc_oxygen(const, population=None, machine_id=None, machine_count=None):
    """
    正算: 人口 -> 需要几台机器
    反算: 机器 -> 能养几个人
    """
    per_minion = const["oxygen_used_per_second"]      # kg/s
    co2_ratio = const["oxygen_to_co2_conversion"]

    makers = [m for m in const.get("oxygen_makers", [])
              if m["oxygen_kg_s"] > 0]
    if not makers:
        return {"error": "constants.json 里没有制氧设备"}

    # 按单位产氧量排序，电解器通常最实用
    makers.sort(key=lambda m: -m["oxygen_kg_s"])

    if population:
        need = population * per_minion
        result = {
            "mode": "population->machines",
            "population": population,
            "oxygen_need_kg_s": need,
            "co2_output_kg_s": need * co2_ratio,
            "options": [],
        }
        for m in makers:
            import math
            n = math.ceil(need / m["oxygen_kg_s"])
            opt = {
                "id": m["id"],
                "name_cn": m["name_cn"],
                "count": n,
                "oxygen_kg_s": m["oxygen_kg_s"],
                "capacity_kg_s": round(m["oxygen_kg_s"] * n, 4),
                "power_w_each": m["power_w"],
                "power_w_total": (round(m["power_w"] * n, 1)
                                  if m["power_w"] else None),
                "inputs_total": [
                    {"element": i["element"],
                     "element_cn": elem_cn(i["element"]),
                     "rate_kg_s": round(i["rate_kg_s"] * n, 4),
                     "per_cycle_kg": round(i["rate_kg_s"] * n * 600, 1)}
                    for i in (m["inputs"] or [])
                ],
            }
            # 副产物
            opt["byproducts"] = [
                {"element": o["element"], "element_cn": elem_cn(o["element"]),
                 "rate_kg_s": round(o["rate_kg_s"] * n, 4)}
                for o in (m["outputs"] or []) if o["element"] != "Oxygen"
            ]
            opt["margin_kg_s"] = round(
                m["oxygen_kg_s"] * n - need, 4)
            result["options"].append(opt)
        return result

    # 反算: 机器 -> 人口
    if machine_id and machine_count:
        m = next((x for x in makers
                  if x["id"] == machine_id or x["name_cn"] == machine_id), None)
        if not m:
            return {"error": f"找不到制氧设备: {machine_id}"}
        supply = m["oxygen_kg_s"] * machine_count
        return {
            "mode": "machines->population",
            "machine": m["name_cn"],
            "machine_id": m["id"],
            "count": machine_count,
            "oxygen_supply_kg_s": round(supply, 4),
            "population": int(supply / per_minion),
            "population_exact": round(supply / per_minion, 2),
            "co2_output_kg_s": round(supply * co2_ratio, 4),
            "power_w_total": (round(m["power_w"] * machine_count, 1)
                              if m["power_w"] else None),
            "inputs_total": [
                {"element": i["element"], "element_cn": elem_cn(i["element"]),
                 "rate_kg_s": round(i["rate_kg_s"] * machine_count, 4),
                 "per_cycle_kg": round(i["rate_kg_s"] * machine_count * 600, 1)}
                for i in (m["inputs"] or [])
            ],
        }
    return {"error": "需要 population 或 (machine_id + machine_count)"}


# ============ 供电测算 ============
def calc_power(const, buildings, usage):
    """
    usage: [(建筑id或类名, 台数), ...]
    返回总耗电 + 各发电机所需台数 + 燃料消耗
    """
    idx = {}
    for b in buildings:
        for k in (b.get("id"), b.get("class"), b.get("name_cn")):
            if k:
                idx[k] = b

    consumers, unknown = [], []
    total_w = 0.0
    for key, n in usage:
        b = idx.get(key)
        if not b:
            unknown.append(key)
            continue
        w = b.get("power_w") or 0
        sub = w * n
        total_w += sub
        consumers.append({
            "id": b.get("id"), "name_cn": b.get("name_cn"),
            "count": n, "power_w_each": w,
            "power_w_total": round(sub, 1),
        })

    consumers.sort(key=lambda c: -c["power_w_total"])

    result = {
        "mode": "usage->generators",
        "consumers": consumers,
        "unknown": unknown,
        "total_power_w": round(total_w, 1),
        "total_power_kw": round(total_w / 1000, 3),
        "generators": [],
    }

    gens = const.get("generators", [])
    for g in gens:
        watt = g["wattage"]
        import math
        n = math.ceil(total_w / watt) if total_w > 0 else 0
        ff = g.get("fuel_formula") or {}
        rate = ff.get("fuel_rate_kg_s")
        item = {
            "id": g["id"], "name_cn": g["name_cn"], "wattage": watt,
            "count": n,
            "output_w": round(watt * n, 1),
            "margin_w": round(watt * n - total_w, 1),
            "fuel": ff.get("fuel"),
            "fuel_cn": elem_cn(ff.get("fuel")) if ff.get("fuel") else None,
            "fuel_rate_kg_s_each": rate,
        }
        if rate and n:
            item["fuel_rate_kg_s_total"] = round(rate * n, 4)
            item["fuel_per_cycle_kg"] = round(rate * n * 600, 1)
        result["generators"].append(item)

    result["generators"].sort(key=lambda g: (g["count"], g["wattage"]))
    return result


# ============ 命令行 ============
def cmd_oxy(args):
    const = load_json(CONST)
    if const is None:
        return 1
    if args.population:
        r = calc_oxygen(const, population=args.population)
    else:
        r = calc_oxygen(const, machine_id=args.machines[0],
                        machine_count=int(args.machines[1]))
    if "error" in r:
        print("错误:", r["error"])
        return 1

    print("=" * 58)
    if r["mode"] == "population->machines":
        print(f"人口 {r['population']} 人")
        print(f"氧气需求 {r['oxygen_need_kg_s']*1000:.1f} g/s "
              f"({r['oxygen_need_kg_s']} kg/s)")
        print(f"呼出二氧化碳 {r['co2_output_kg_s']*1000:.1f} g/s")
        print("=" * 58)
        for o in r["options"]:
            print(f"\n【{o['name_cn']}】{o['count']} 台"
                  f"  产能 {o['capacity_kg_s']*1000:.1f} g/s"
                  f"  余量 {o['margin_kg_s']*1000:+.1f} g/s")
            if o["power_w_total"]:
                print(f"    耗电 {o['power_w_each']:.0f}W/台 "
                      f"→ 合计 {o['power_w_total']:.0f}W")
            for i in o["inputs_total"]:
                print(f"    消耗 {i['element_cn']:<6} "
                      f"{i['rate_kg_s']:.4f} kg/s "
                      f"({i['per_cycle_kg']:.1f} kg/周期)")
            for b in o["byproducts"]:
                print(f"    副产 {b['element_cn']:<6} {b['rate_kg_s']:.4f} kg/s")
    else:
        print(f"{r['machine']} × {r['count']} 台")
        print(f"氧气产量 {r['oxygen_supply_kg_s']*1000:.1f} g/s")
        print(f"可养活 {r['population']} 人 "
              f"(精确 {r['population_exact']} 人)")
        if r["power_w_total"]:
            print(f"耗电合计 {r['power_w_total']:.0f} W")
        for i in r["inputs_total"]:
            print(f"消耗 {i['element_cn']:<6} {i['rate_kg_s']:.4f} kg/s "
                  f"({i['per_cycle_kg']:.1f} kg/周期)")
    print()
    return 0


def cmd_power(args):
    const = load_json(CONST)
    buildings = load_json(BUILDINGS)
    if const is None or buildings is None:
        return 1
    usage = []
    for tok in args.usage:
        if ":" in tok:
            k, v = tok.split(":", 1)
        else:
            k, v = tok, "1"
        usage.append((k, int(v)))

    r = calc_power(const, buildings, usage)
    print("=" * 58)
    print("用电清单")
    print("=" * 58)
    for c in r["consumers"]:
        print(f"  {c['name_cn']:<14} ×{c['count']:<3} "
              f"{c['power_w_each']:>7.0f}W/台  "
              f"小计 {c['power_w_total']:>8.0f}W")
    if r["unknown"]:
        print(f"  ⚠ 未找到: {', '.join(r['unknown'])}")
    print(f"  {'合计':<14} {r['total_power_w']:>27.0f}W "
          f"= {r['total_power_kw']:.2f} kW")

    print()
    print("=" * 58)
    print("发电机配比")
    print("=" * 58)
    for g in r["generators"]:
        line = (f"  {g['name_cn']:<12} ×{g['count']:<3} "
                f"{g['wattage']:>7.0f}W/台  合计 {g['output_w']:>8.0f}W "
                f"余 {g['margin_w']:>7.0f}W")
        print(line)
        if g.get("fuel_rate_kg_s_total"):
            print(f"      燃料 {g['fuel_cn']} "
                  f"{g['fuel_rate_kg_s_total']:.4f} kg/s "
                  f"({g['fuel_per_cycle_kg']:.1f} kg/周期)")
    print()
    return 0


def cmd_list(args):
    const = load_json(CONST)
    if const is None:
        return 1
    print("=== 制氧设备 ===")
    for m in const.get("oxygen_makers", []):
        print(f"  {m['id']:<22} {m['name_cn']:<12} "
              f"{m['oxygen_kg_s']*1000:>7.1f} g/s")
    print("\n=== 发电机 ===")
    for g in const.get("generators", []):
        ff = g.get("fuel_formula") or {}
        print(f"  {g['id']:<22} {g['name_cn']:<12} {g['wattage']:>6.0f}W  "
              f"燃料 {ff.get('fuel')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="缺氧测算引擎")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("oxy", help="制氧测算")
    p1.add_argument("population", nargs="?", type=int, help="人口数")
    p1.add_argument("--machines", nargs=2, metavar=("ID", "COUNT"),
                    help="反算: 机器 ID 与台数")
    p1.set_defaults(func=cmd_oxy)

    p2 = sub.add_parser("power", help="供电测算")
    p2.add_argument("usage", nargs="+", metavar="ID[:COUNT]",
                    help="建筑 ID 或中文名，可加 :台数")
    p2.set_defaults(func=cmd_power)

    p3 = sub.add_parser("list", help="列出可用设备")
    p3.set_defaults(func=cmd_list)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
缺氧 房间规划计算器 —— 核心引擎 v2
数据源:
  data/buildings.json        64 栋核心生产建筑（体力活动/资源转换）
  buildings_rooms.json       186 栋房间相关建筑（带尺寸 + 中文名 + 房间 tag）
  rooms.json                 19 种房间类型的约束规则
  tags.json                  186 栋建筑 -> 房间约束 tag

功能: 给定「想放哪些建筑」，算出能构成哪些房间 + 尺寸区间 + 还缺什么
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        p = os.path.join(BASE, "data", name)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


BUILDINGS = _load("buildings_rooms.json")
ROOMS = _load("rooms.json")
TAGS = _load("tags.json")

# 建筑类名 -> tag
TAGMAP = TAGS["buildings"]

# 建筑 ID(大写) -> 记录
BY_ID = {}
for b in BUILDINGS:
    bid = (b.get("id") or "").upper()
    if bid:
        BY_ID.setdefault(bid, b)

# 中文名 -> 记录
BY_CN = {}
for b in BUILDINGS:
    if b.get("name_cn"):
        BY_CN.setdefault(b["name_cn"], b)


def building_tags(b):
    return set(TAGMAP.get(b.get("class", ""), []))


# tag 名 -> 房间约束 id
TAG2CID = {
    "FlushToiletType": "FLUSH_TOILET",
    "ToiletType": "TOILET",
    "BedType": "HAS_BED",
    "LuxuryBedType": "HAS_LUXURY_BED",
    "Clinic": "CLINIC",
    "WashStation": "WASH_STATION",
    "AdvancedWashStation": "ADVANCEDWASHSTATION",
    "CookTop": "COOK_TOP",
    "SpiceStation": "SPICE_STATION",
    "KitchenRefrigerator": "KITCHENREFRIGERATOR",
    "DiningTableType": "DINING_TABLE",
    "ScienceBuilding": "SCIENCE_BUILDINGS",
    "PowerBuilding": "POWER_STATION",
    "GeneratorType": "POWER_STATION",
    "FarmStationType": "FARM_STATION",
    "RanchStationType": "RANCH_STATION",
    "Park": "PARK_BUILDING",
    "RecBuilding": "REC_BUILDING",
    "Decoration": "ORNAMENTDISPLAYED",
    "IndustrialMachinery": "NO_INDUSTRIAL_MACHINERY",
    "MachineShopType": "MACHINE_SHOP",
    "RocketInterior": "ROCKET",
    "DeStressingBuilding": "MASSAGE_TABLE",
}

# 这些约束是「数量上限」型：正好 N 个，多了不行。缺了也算不满足，但单独提示
SINGLE_CIDS = {
    "MESS_STATION_SINGLE": ("DiningTableType", "只能一张餐桌"),
    "LUXURY_BED_SINGLE": ("LuxuryBedType", "只能一张豪华床"),
}

# 这些需要「数量 ≥2」而不是 ≥1
MULTI_CIDS = {
    "SCIENCE_BUILDINGS": ("ScienceBuilding", 2, "研究设备"),
    "WILDPLANTS": (None, 2, "野生植物"),
    "DECORATIVE_ITEM_2": ("Decoration", 2, "装饰物"),
}

# 这些约束由房间本身天然满足 / 或属纯装饰，不进需求列表、也不算分母
SKIP_CIDS = {"IS_BACKWALLED", "ORIGINALTILES",
             "DECORATIVE_ITEM", "DECORATIVE_ITEM_2"}

# 语义中文
CID_CN = {
    "FLUSH_TOILET": "冲水马桶", "TOILET": "厕所", "HAS_BED": "床", "HAS_LUXURY_BED": "豪华床",
    "LUXURY_BED_SINGLE": "只能一张豪华床", "CLINIC": "医疗设备", "WASH_STATION": "洗手池",
    "ADVANCEDWASHSTATION": "洗手池/淋浴", "COOK_TOP": "灶台", "SPICE_STATION": "调味台",
    "KITCHENREFRIGERATOR": "冰箱", "DINING_TABLE": "餐桌", "MASSAGE_TABLE": "按摩床",
    "SCIENCE_BUILDINGS": "研究设备×2", "POWER_STATION": "发电站", "FARM_STATION": "农业站",
    "RANCH_STATION": "牧栏站", "PARK_BUILDING": "公园标识", "REC_BUILDING": "娱乐建筑",
    "MACHINE_SHOP": "机械车间", "ROCKET": "火箭内部", "NO_INDUSTRIAL_MACHINERY": "不要工业机械",
    "NO_OUTHOUSES": "不要旱厕", "NO_MESS_STATION": "不要餐桌", "NO_COTS": "不要简易床",
    "NO_BASIC_MESS_STATIONS": "不要普通餐桌", "MULTI_MINION_DINING_TABLE": "多人大餐桌",
    "MESS_STATION_SINGLE": "只能一张餐桌", "CEILING_HEIGHT_4": "层高≥4",
}


def resolve(names):
    """建筑名 -> 记录（精确优先，然后前缀/包含）"""
    out, miss = [], []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if n in BY_CN:
            out.append(BY_CN[n]); continue
        if n.upper() in BY_ID:
            out.append(BY_ID[n.upper()]); continue
        cand = [b for k, b in BY_CN.items() if n in k]
        if not cand:
            cand = [b for k, b in BY_CN.items() if k in n]
        if cand:
            out.append(sorted(cand, key=lambda b: len(b["name_cn"]))[0])
        else:
            miss.append(n)
    return out, miss


def eval_rooms(chosen):
    """评估能建哪些房间"""
    have_tags = set()
    for b in chosen:
        have_tags |= building_tags(b)
    have_cids = {TAG2CID[t] for t in have_tags if t in TAG2CID}

    results = []
    for r in ROOMS:
        if r["id"] == "Neutral":
            continue
        need, neg, sizes = [], [], {}
        for c in r["constraints"]:
            cid = c["id"]
            if cid.startswith("MINIMUM_SIZE_"):
                sizes["min"] = int(cid.rsplit("_", 1)[-1]); continue
            if cid.startswith("MAXIMUM_SIZE_"):
                sizes["max"] = int(cid.rsplit("_", 1)[-1]); continue
            if cid == "CEILING_HEIGHT_4":
                sizes["height"] = 4; continue
            if cid in SKIP_CIDS:
                continue
            if cid.startswith("NO_"):
                neg.append(cid); continue
            need.append(cid)

        ok = [c for c in need if c in have_cids]
        if not ok:
            continue
        missing = []
        for c in need:
            if c in have_cids:
                continue
            # 「正好 N 个」型：只有放了这类家具才算，且要另加"不能多"的提示
            if c in SINGLE_CIDS:
                tag, label = SINGLE_CIDS[c]
                if tag in have_tags:
                    missing.append(c)
                continue
            missing.append(c)
        violated = []
        for c in neg:
            if c == "NO_INDUSTRIAL_MACHINERY" and "IndustrialMachinery" in have_tags:
                violated.append(c)
            if c == "NO_OUTHOUSES" and "ToiletType" in have_tags and "FlushToiletType" not in have_tags:
                violated.append(c)
            if c in ("NO_MESS_STATION", "NO_BASIC_MESS_STATIONS") and "DiningTableType" in have_tags:
                violated.append(c)
            if c == "NO_COTS" and "BedType" in have_tags and "LuxuryBedType" not in have_tags:
                violated.append(c)   # 只有简易床时才冲突；豪华床不算简易床
            if c == "NO_OUTHOUSES" and "FlushToiletType" not in have_tags:
                violated.append(c)   # 没有冲水马桶 = 只能是旱厕，不符合

        total = len(need)
        ratio = len(ok) / total if total else 0
        results.append({
            "id": r["id"], "name_cn": r["name_cn"], "category": r.get("category", ""),
            "size_min": sizes.get("min"), "size_max": sizes.get("max"), "height": sizes.get("height"),
            "satisfied": sorted(ok, key=lambda c: CID_CN.get(c, c)),
            "missing": sorted(missing, key=lambda c: CID_CN.get(c, c)),
            "violated": sorted(set(violated), key=lambda c: CID_CN.get(c, c)),
            "ratio": round(ratio, 2),
            "complete": not missing and not violated,
        })

    results.sort(key=lambda x: (not x["complete"], -x["ratio"], -len(x["satisfied"]), x["name_cn"] or ""))
    return results


def cid_cn(c):
    return CID_CN.get(c, c)


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or ["抽水马桶", "洗手池", "床"]
    chosen, miss = resolve(names)
    print(f"选中: {[b['name_cn'] for b in chosen]}")
    if miss: print(f"未识别: {miss}")
    res = eval_rooms(chosen)
    print(f"\n可构成房间 {len(res)} 种:\n")
    for r in res[:14]:
        mark = "✅" if r["complete"] else "🔶"
        size = f"{r['size_min']}~{r['size_max']}格" if r["size_min"] else "?"
        extra = ""
        if r["height"]: extra = f" 层高≥{r['height']}"
        print(f" {mark} {r['name_cn']:<12} [{size}{extra}]")
        if r["missing"]: print(f"      还缺: {'、'.join(cid_cn(c) for c in r['missing'])}")
        if r["violated"]: print(f"      ⚠️冲突: {'、'.join(cid_cn(c) for c in r['violated'])}")

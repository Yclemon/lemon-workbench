# -*- coding: utf-8 -*-
"""从 *Config.cs 里提取每栋建筑的房间约束 tag（AddTag(RoomConstraints.ConstraintTags.X)）"""
import os, re, json, glob

DECOMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_decomp")

# ConstraintTags 字段名 -> 语义中文名（供前端展示）
TAG_CN = {
    "BedType": "床",
    "LuxuryBedType": "豪华床",
    "Clinic": "诊所设备",
    "ToiletType": "厕所",
    "FlushToiletType": "冲水马桶",
    "WashStation": "洗手池",
    "AdvancedWashStation": "高级洗手池",
    "FoodPreparation": "食物加工",
    "CookTop": "灶台",
    "SpiceStation": "调味台",
    "Refrigerator": "冰箱",
    "DiningTable": "餐桌",
    "MassageTable": "按摩台",
    "ScienceBuilding": "研究建筑",
    "PowerStation": "发电站",
    "FarmStation": "农业站",
    "RanchStation": "牧栏站",
    "Park": "公园建筑",
    "Recreation": "娱乐建筑",
    "Decoration": "装饰物",
    "IndustrialMachinery": "工业机械",
    "MachineShop": "机械车间",
    "Rocket": "火箭",
    "PowerBuilding": "发电设备",
    "GeneratorType": "发电机",
    "HeavyDutyGeneratorType": "重型发电机",
    "LightDutyGeneratorType": "轻型发电机",
    "WarmingStation": "加温设备",
    "DiningTableType": "餐桌",
    "KitchenRefrigerator": "冰箱",
    "FarmStationType": "农业站",
    "RanchStationType": "牧栏站",
    "RecBuilding": "娱乐建筑",
    "MachineShopType": "机械车间",
    "DeStressingBuilding": "减压建筑",
    "BionicUpkeepType": "仿生人维护设备",
    "RocketInterior": "火箭内部",
}

def main():
    pat_tag = re.compile(r'AddTag\s*\(\s*RoomConstraints\.ConstraintTags\.(\w+)\s*\)')
    pat_bld = re.compile(r'class\s+(\w+Config)\s*:')
    out = {}
    for path in sorted(glob.glob(os.path.join(DECOMP, "*Config.cs"))):
        try:
            src = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        tags = pat_tag.findall(src)
        if not tags:
            continue
        cls = os.path.basename(path)[:-3]
        m = pat_bld.search(src)
        if m:
            cls = m.group(1)
        out[cls] = sorted(set(tags))

    # 输出：建筑类名 -> tag 列表
    with open("tags.json", "w", encoding="utf-8") as f:
        json.dump({"tags_cn": TAG_CN, "buildings": out}, f, ensure_ascii=False, indent=2)

    print(f"带房间 tag 的建筑: {len(out)} 个")
    from collections import Counter
    c = Counter(t for ts in out.values() for t in ts)
    print("\n--- tag 使用频次 ---")
    for t, n in c.most_common():
        print(f"  {TAG_CN.get(t, '?'):<12} {t:<24} {n} 栋")
    print("\n--- 抽查 ---")
    for k in ["FlushToiletConfig", "OuthouseConfig", "BedConfig", "LuxuryBedConfig",
              "DiningTableConfig", "MassageTableConfig", "ResearchCenterConfig"]:
        if k in out:
            print(f"  {k:<26} {out[k]}")

if __name__ == "__main__":
    main()

/* 缺氧计算查询工具 —— 前端
 * 纯原生 JS，零依赖。
 */
'use strict';

// ---------- 元素中文名 ----------
// 游戏源码里是 SimHashes 枚举名，这里映射成中文
var ELEM_CN = {
  Water: '水', DirtyWater: '污水', SaltWater: '盐水', Brine: '浓盐水',
  Oxygen: '氧气', ContaminatedOxygen: '污染氧', Hydrogen: '氢气',
  CarbonDioxide: '二氧化碳', ChlorineGas: '氯气', Methane: '天然气',
  Carbon: '煤', Coal: '煤', RefinedCarbon: '精炼碳',
  Algae: '藻类', Dirt: '泥土', Rust: '铁锈', Salt: '盐',
  IronOre: '铁矿石', Clay: '黏土', Sand: '沙子', Filter: '过滤介质',
  ToxicSand: '污染沙', Fertilizer: '肥料', Phosphorite: '磷灰石',
  Petroleum: '石油', OxyRock: '氧化石', Steel: '钢', Iron: '铁',
  Lime: '石灰', BuildingWood: '木材', WoodLog: '木材',
  Copper: '铜', Gold: '金', Lead: '铅', Tungsten: '钨',
  Glass: '玻璃', Diamond: '钻石', Niobium: '铌', Fullerene: '富勒烯',
  SuperCoolant: '超强冷却液', NuclearWaste: '核废料', Ethanol: '乙醇',
  PollutedWater: '污水', Slime: '菌泥', IgneousRock: '火成岩',
  CrushedRock: '碎石', Regolith: '沙尘', BleachStone: '漂白石',
  Magma: '岩浆', Steam: '蒸汽', LiquidOxygen: '液氧', LiquidHydrogen: '液氢',
  Vacuum: '真空', Salt: '盐',
  // 发电机燃料等特殊元素名（游戏里叫 CombustibleLiquid 的是石油系燃料）
  CombustibleLiquid: '石油燃料', Methane: '天然气',
  RefinedMetal: '精炼金属', RawMetal: '原矿金属', Metal: '金属',
  CarbonFibre: '碳纤维', Ceramic: '陶瓷', TungstenGas: '钨气',
  Sulfur: '硫', SulfurGas: '硫气', LiquidSulfur: '液硫',
  UraniumOre: '铀矿', EnrichedUranium: '浓缩铀', DepletedUranium: '贫铀',
  Radium: '镭', DiamondDust: '钻石粉尘'
};

function elemCN(id) {
  return ELEM_CN[id] || id;
}

// ---------- 存档的元素名是英文，做一次反向搜索增强 ----------
function elemSearchText(id) {
  return id + ' ' + elemCN(id);
}

// ---------- 工具 ----------
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtNum(v, digits) {
  if (v == null || isNaN(v)) return null;
  var d = digits == null ? 3 : digits;
  var s = Number(v).toFixed(d);
  // 只在存在小数点时才剥尾随 0，否则 "120.000" 会被剥成 "12"
  if (s.indexOf('.') >= 0) {
    s = s.replace(/0+$/, '');      // 先剥尾随 0
    s = s.replace(/\.$/, '');      // 再剥孤立的小数点
  }
  return s;
}

function kelvinToC(k) {
  if (k == null) return null;
  return k - 273.15;
}

function fmtTemp(k) {
  // 温度 <= 0K 说明源码里没写这个参数（默认值被当成 0 存下来了），
  // 绝不能显示成绝对零度 -273.15°C，那样是假数据。直接不显示。
  if (k == null || k <= 0) return '';
  var c = kelvinToC(k);
  return Math.round(k) + 'K / ' + fmtNum(c, 1) + '°C';
}

// ---------- 状态 ----------
var state = {
  all: [],
  cat: 'all',
  q: '',
  onlyCore: false
};

// ---------- 分类推导 ----------
// 按建筑 ID 归到功能类别，用于筛选
var CATS = [
  { id: 'all', name: '全部' },
  { id: 'oxygen', name: '制氧/净气' },
  { id: 'power', name: '发电' },
  { id: 'refine', name: '精炼/加工' },
  { id: 'liquid', name: '泵/管道过滤' },
  { id: 'thermal', name: '温控' },
  { id: 'farm', name: '农业/生物' },
  { id: 'sanitation', name: '卫生' },
  { id: 'storage', name: '储物' }
];

var CAT_MAP = {
  Electrolyzer: 'oxygen', MineralDeoxidizer: 'oxygen', RustDeoxidizer: 'oxygen',
  AlgaeHabitat: 'oxygen', AirFilter: 'oxygen', CO2Scrubber: 'oxygen',
  Generator: 'power', ManualGenerator: 'power', HydrogenGenerator: 'power',
  MethaneGenerator: 'power', PetroleumGenerator: 'power', WoodGasGenerator: 'power',
  SolarPanel: 'power', SteamTurbine: 'power', NuclearReactor: 'power',
  Battery: 'power', BatteryMedium: 'power', BatterySmart: 'power',
  PowerTransformer: 'power', PowerTransformerSmall: 'power',
  Wire: 'power', WireRefined: 'power', HighWattageWire: 'power',
  MetalRefinery: 'refine', RockCrusher: 'refine', Kiln: 'refine',
  GlassForge: 'refine', OilRefinery: 'refine', SupermaterialRefinery: 'refine',
  ChemicalRefinery: 'refine', OxyliteRefinery: 'refine',
  AlgaeDistillery: 'refine', WaterPurifier: 'refine', Compost: 'refine',
  FertilizerMaker: 'refine',
  LiquidPump: 'liquid', GasPump: 'liquid', LiquidMiniPump: 'liquid',
  GasMiniPump: 'liquid', LiquidFilter: 'liquid', GasFilter: 'liquid',
  SolidFilter: 'liquid', LiquidVent: 'liquid', GasVent: 'liquid',
  GasReservoir: 'liquid', LiquidReservoir: 'liquid',
  FarmTile: 'farm', HydroponicFarm: 'farm', PlanterBox: 'farm',
  FarmStation: 'farm',
  FlushToilet: 'sanitation', Outhouse: 'sanitation', WashSink: 'sanitation',
  DecontaminationShower: 'sanitation',
  AirConditioner: 'thermal', LiquidCooledFan: 'thermal', SpaceHeater: 'thermal',
  IceMachine: 'thermal', IceCooledFan: 'thermal', WaterCooler: 'thermal',
  Refrigerator: 'thermal',
  StorageLocker: 'storage', GasReservoir: 'storage', LiquidReservoir: 'storage',
  BottleEmptier: 'storage', GasBottler: 'storage', LiquidBottler: 'storage'
};

function catOf(id) { return CAT_MAP[id] || 'other'; }

// ---------- 渲染 ----------
function matches(r) {
  if (state.onlyCore && !r.core) return false;
  if (state.cat !== 'all' && catOf(r.id) !== state.cat) return false;
  if (!state.q) return true;
  var q = state.q.toLowerCase();
  var hay = [
    r.name_cn, r.id, r.class,
    elemSearchText(r.fuel_formula ? r.fuel_formula.fuel : ''),
    (r.inputs || []).map(function (i) { return elemSearchText(i.element); }).join(' '),
    (r.outputs || []).map(function (o) { return elemSearchText(o.element); }).join(' '),
    r.description || ''
  ].join(' ').toLowerCase();
  return hay.indexOf(q) >= 0;
}

function metric(k, v, cls) {
  if (v == null || v === '') return '';
  return '<span class="metric"><span class="k">' + esc(k) + '</span>' +
    '<span class="v ' + (cls || '') + '">' + v + '</span></span>';
}

function itemHTML(el, rate, temp) {
  var s = '<span class="item"><span class="el">' + esc(elemCN(el)) + '</span>';
  if (rate != null) {
    s += '<span class="rate">' + fmtNum(rate, 4) + ' kg/s</span>';
  }
  // 只有真实温度才显示，避免出现绝对零度这种假数据
  if (temp != null && temp > 0) {
    s += '<span class="temp">@' + fmtTemp(temp) + '</span>';
  }
  return s + '</span>';
}

function flowHTML(r) {
  var left = [], right = [];

  // 燃料（发电机）
  var f = r.fuel_formula;
  if (f) {
    left.push('<span class="item fuel"><span class="el">' + esc(elemCN(f.fuel)) +
      '</span><span class="rate">' + fmtNum(f.fuel_rate_kg_s, 4) + ' kg/s</span></span>');
    if (f.exhaust_element) {
      right.push(itemHTML(f.exhaust_element, f.exhaust_rate_kg_s, f.exhaust_temp_k));
    }
  }

  (r.inputs || []).forEach(function (i) {
    left.push(itemHTML(i.element, i.rate_kg_s, null));
  });
  (r.outputs || []).forEach(function (o) {
    right.push(itemHTML(o.element, o.rate_kg_s, o.temp_k));
  });

  if (!left.length && !right.length) return '';

  var html = '<div class="flow">';
  html += '<div class="side">' + (left.length ? left.join('') : '<span class="item"><span class="el">—</span></span>') + '</div>';
  html += '<span class="arrow">→</span>';
  html += '<div class="side">' + (right.length ? right.join('') : '<span class="item"><span class="el">—</span></span>') + '</div>';
  html += '</div>';

  if (f && f.note) {
    html += '<div class="note">' + esc(f.note) + '</div>';
  }
  return html;
}

function cardHTML(r) {
  var m = [];

  // 发电 / 耗电
  if (r.generator_w != null) {
    m.push(metric('发电', fmtNum(r.generator_w, 0) + ' W', 'gen'));
  } else if (r.power_w != null) {
    m.push(metric('耗电', fmtNum(r.power_w, 0) + ' W', 'hl'));
  } else {
    m.push(metric('耗电', '无', 'na'));
  }

  // 发热
  if (r.self_heat_kw != null) {
    m.push(metric('自发热', fmtNum(r.self_heat_kw, 2) + ' kW'));
  }
  if (r.exhaust_heat_kw != null) {
    m.push(metric('废气热', fmtNum(r.exhaust_heat_kw, 2) + ' kW'));
  }

  // 尺寸
  if (r.width != null && r.height != null) {
    m.push(metric('尺寸', r.width + '×' + r.height));
  }

  // 建造质量
  if (r.build_mass_kg != null) {
    m.push(metric('建造质量', fmtNum(r.build_mass_kg, 0) + ' kg'));
  }
  if (r.build_time_s != null) {
    m.push(metric('建造时间', r.build_time_s + ' s'));
  }

  var tagline = '';
  if (r.generator_capacity_j != null) {
    tagline = '储电 ' + fmtNum(r.generator_capacity_j, 0) + ' J';
  }

  return '<div class="card">' +
    '<div class="card-head">' +
      '<span class="card-name">' + esc(r.name_cn) + '</span>' +
      (r.core ? '<span class="core-badge">常用</span>' : '') +
      '<span class="card-id">' + esc(r.id) + '</span>' +
      (tagline ? '<span class="tagline">' + esc(tagline) + '</span>' : '') +
    '</div>' +
    '<div class="metrics">' + m.join('') + '</div>' +
    flowHTML(r) +
    '</div>';
}

function render() {
  var rows = state.all.filter(matches);

  // 按是否核心排序，核心在前；再按中文名
  rows.sort(function (a, b) {
    if (a.core !== b.core) return a.core ? -1 : 1;
    return (a.name_cn || '').localeCompare(b.name_cn || '', 'zh');
  });

  document.getElementById('list').innerHTML = rows.map(cardHTML).join('');
  document.getElementById('empty').hidden = rows.length > 0;
  document.getElementById('count').textContent =
    rows.length === state.all.length
      ? state.all.length + ' 个建筑'
      : rows.length + ' / ' + state.all.length + ' 个建筑';
}

function renderFilters() {
  var counts = {};
  state.all.forEach(function (r) {
    var c = catOf(r.id);
    counts[c] = (counts[c] || 0) + 1;
  });

  var html = CATS.map(function (c) {
    var n = c.id === 'all' ? state.all.length : (counts[c.id] || 0);
    return '<button class="fbtn' + (state.cat === c.id ? ' on' : '') +
      '" data-cat="' + c.id + '">' + esc(c.name) +
      '<span class="n">' + n + '</span></button>';
  }).join('');
  document.getElementById('filters').innerHTML = html;
}

// ---------- 事件 ----------
function bind() {
  var q = document.getElementById('q');
  q.addEventListener('input', function () {
    state.q = q.value.trim();
    render();
  });

  document.getElementById('onlyCore').addEventListener('change', function (e) {
    state.onlyCore = e.target.checked;
    render();
  });

  document.getElementById('filters').addEventListener('click', function (e) {
    var b = e.target.closest('.fbtn');
    if (!b) return;
    state.cat = b.dataset.cat;
    renderFilters();
    render();
  });

  document.querySelectorAll('.tab').forEach(function (t) {
    t.addEventListener('click', function () {
      switchTab(t.dataset.tab);
    });
  });

  // 支持 #rooms / #about 直接切页，并响应浏览器前进后退
  window.addEventListener('hashchange', function () {
    var h = (location.hash || '').replace(/^#/, '');
    if (h) switchTab(h);
  });
}

// 切换到某个标签页（供点击与 hash 路由共用）
function switchTab(name) {
  var target = document.querySelector('.tab[data-tab="' + name + '"]');
  if (!target) return;
  document.querySelectorAll('.tab').forEach(function (x) { x.classList.remove('on'); });
  document.querySelectorAll('.pane').forEach(function (x) { x.classList.remove('on'); });
  target.classList.add('on');
  var pane = document.getElementById(name);
  if (pane) pane.classList.add('on');
}

// ---------- 启动 ----------
function boot() {
  bind();

  // 初始 hash 直接定位到对应标签页
  var h0 = (location.hash || '').replace(/^#/, '');
  if (h0 && document.querySelector('.tab[data-tab="' + h0 + '"]')) switchTab(h0);

  fetch('/api/data/buildings.json')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      state.all = data || [];
      var src = document.getElementById('metaSrc');
      if (src) {
        src.textContent = '反编译源码提取，共 ' + state.all.length +
          ' 个建筑；其中 ' + state.all.filter(function (r) { return r.core; }).length +
          ' 个标记为常用。';
      }
      renderFilters();
      render();
    })
    .catch(function (e) {
      document.getElementById('list').innerHTML =
        '<div class="empty">数据加载失败: ' + esc(e.message) + '</div>';
    });
}

document.addEventListener('DOMContentLoaded', boot);

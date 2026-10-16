/* ============ 房间规划 ============ */
/* 依赖: rooms-plan.js 之前需先加载 app.js（要用 esc / fmtNum） */

var tagCN = {};      // 房间约束 id -> 中文名（后端已给，这里做补漏）
var roomState = {
  buildings: [],     // 186 栋房间相关建筑
  rooms: [],         // 19 种房间
  tags: {},          // 建筑类名 -> tag 数组
  picked: [],        // 已选建筑（记录对象）
  ready: false
};

// tag 名 -> 房间约束 id（与后端 room_engine.py 保持一致）
var RTAG2CID = {
  FlushToiletType: 'FLUSH_TOILET',
  ToiletType: 'TOILET',
  BedType: 'HAS_BED',
  LuxuryBedType: 'HAS_LUXURY_BED',
  Clinic: 'CLINIC',
  WashStation: 'WASH_STATION',
  AdvancedWashStation: 'ADVANCEDWASHSTATION',
  CookTop: 'COOK_TOP',
  SpiceStation: 'SPICE_STATION',
  KitchenRefrigerator: 'KITCHENREFRIGERATOR',
  DiningTableType: 'DINING_TABLE',
  ScienceBuilding: 'SCIENCE_BUILDINGS',
  PowerBuilding: 'POWER_STATION',
  GeneratorType: 'POWER_STATION',
  FarmStationType: 'FARM_STATION',
  RanchStationType: 'RANCH_STATION',
  Park: 'PARK_BUILDING',
  RecBuilding: 'REC_BUILDING',
  Decoration: 'ORNAMENTDISPLAYED',
  IndustrialMachinery: 'NO_INDUSTRIAL_MACHINERY',
  MachineShopType: 'MACHINE_SHOP',
  RocketInterior: 'ROCKET',
  DeStressingBuilding: 'MASSAGE_TABLE'
};

var CID_CN = {
  FLUSH_TOILET: '冲水马桶', TOILET: '厕所', HAS_BED: '床', HAS_LUXURY_BED: '豪华床',
  LUXURY_BED_SINGLE: '只能一张豪华床', CLINIC: '医疗设备', WASH_STATION: '洗手池',
  ADVANCEDWASHSTATION: '洗手池/淋浴', COOK_TOP: '灶台', SPICE_STATION: '调味台',
  KITCHENREFRIGERATOR: '冰箱', DINING_TABLE: '餐桌', MASSAGE_TABLE: '按摩床',
  SCIENCE_BUILDINGS: '研究设备×2', POWER_STATION: '发电站', FARM_STATION: '农业站',
  RANCH_STATION: '牧栏站', PARK_BUILDING: '公园标识', REC_BUILDING: '娱乐建筑',
  MACHINE_SHOP: '机械车间', ROCKET: '火箭内部',
  NO_INDUSTRIAL_MACHINERY: '不要工业机械', NO_OUTHOUSES: '不要旱厕',
  NO_MESS_STATION: '不要餐桌', NO_COTS: '不要简易床',
  NO_BASIC_MESS_STATIONS: '不要普通餐桌',
  MULTI_MINION_DINING_TABLE: '多人大餐桌', MESS_STATION_SINGLE: '只能一张餐桌'
};

// 房间天然满足 / 纯装饰，不进需求也不进分母
var RSKIP = { IS_BACKWALLED: 1, ORIGINALTILES: 1, DECORATIVE_ITEM: 1, DECORATIVE_ITEM_2: 1 };

var RSINGLE = {
  MESS_STATION_SINGLE: 'DiningTableType',
  LUXURY_BED_SINGLE: 'LuxuryBedType'
};

var CAT_CN = {
  Bathroom: '卫生', Sleep: '睡眠', Food: '食物', Hospital: '医疗',
  Industrial: '工业', Agricultural: '农业', Science: '科研',
  Recreation: '娱乐', Park: '公园', Rocket: '火箭'
};

function cidCN(c) { return CID_CN[c] || c; }
function roomCatCN(c) { return CAT_CN[c] || c || '其他'; }

// 与房间判定真正相关的 tag（用于候选排序：带这些的才是家具类）
var ROOM_RELEVANT = {
  BedType: 1, LuxuryBedType: 1, Clinic: 1, ToiletType: 1, FlushToiletType: 1,
  WashStation: 1, AdvancedWashStation: 1, CookTop: 1, SpiceStation: 1,
  KitchenRefrigerator: 1, DiningTableType: 1, DeStressingBuilding: 1,
  ScienceBuilding: 1, PowerBuilding: 1, GeneratorType: 1,
  FarmStationType: 1, RanchStationType: 1, Park: 1, RecBuilding: 1,
  Decoration: 1, MachineShopType: 1
};

// 建筑带的房间 tag
function tagsOf(b) {
  return roomState.tags[b['class']] || [];
}

// 是不是"能决定房间类型"的建筑（家具类），而不是只带 NO_* 或火箭标签的
function isRoomFurniture(b) {
  return tagsOf(b).some(function (t) { return ROOM_RELEVANT[t]; });
}

// ---------- 搜索候选 ----------
function renderSuggest() {
  var q = (document.getElementById('rq').value || '').trim();
  var box = document.getElementById('rsuggest');
  var pickedIds = {};
  roomState.picked.forEach(function (b) { pickedIds[b['class']] = 1; });

  var pool = roomState.buildings.filter(function (b) {
    if (pickedIds[b['class']]) return false;
    if (!b.name_cn) return false;
    if (!q) return true;
    return (b.name_cn + ' ' + (b.id || '')).toLowerCase().indexOf(q.toLowerCase()) >= 0;
  });

  // 家具类排最前，其余（只带工业/火箭标签）排后
  pool.sort(function (a, b) {
    var fa = isRoomFurniture(a) ? 0 : 1, fb = isRoomFurniture(b) ? 0 : 1;
    if (fa !== fb) return fa - fb;
    return (a.name_cn || '').localeCompare(b.name_cn || '', 'zh');
  });

  var show = pool.slice(0, q ? 40 : 18);
  if (!show.length) {
    box.innerHTML = '<div class="rsug-none">' +
      (q ? '没有匹配的建筑' : '输入建筑名开始搜索') + '</div>';
    return;
  }

  box.innerHTML = show.map(function (b, i) {
    var sz = (b.width && b.height) ? b.width + '×' + b.height : '?';
    var tg = isRoomFurniture(b) ? '房间因素' : '其他';
    return '<button class="rsug" data-i="' + i + '">' +
      '<span>' + esc(b.name_cn) + '</span>' +
      '<span><span class="tg">' + tg + '</span> <span class="sz">' + sz + '</span></span>' +
      '</button>';
  }).join('');

  Array.prototype.forEach.call(box.querySelectorAll('.rsug'), function (el) {
    el.addEventListener('click', function () {
      var b = show[+el.dataset.i];
      if (!b) return;
      if (!roomState.picked.some(function (x) { return x['class'] === b['class']; })) {
        roomState.picked.push(b);
      }
      document.getElementById('rq').value = '';
      renderSuggest();
      renderPicked();
      computeRooms();
    });
  });
}

// ---------- 已选 ----------
function renderPicked() {
  var wrap = document.getElementById('rsel');
  var box = document.getElementById('rchips');
  if (!roomState.picked.length) { wrap.hidden = true; box.innerHTML = ''; return; }
  wrap.hidden = false;
  box.innerHTML = roomState.picked.map(function (b, i) {
    return '<span class="rchip">' + esc(b.name_cn) +
      '<button data-i="' + i + '" title="移除">×</button></span>';
  }).join('');
  Array.prototype.forEach.call(box.querySelectorAll('button'), function (el) {
    el.addEventListener('click', function () {
      roomState.picked.splice(+el.dataset.i, 1);
      renderSuggest(); renderPicked(); computeRooms();
    });
  });
}

// ---------- 核心计算 ----------
function computeRooms() {
  var out = document.getElementById('rresult');
  if (!roomState.picked.length) {
    out.innerHTML = '<div class="empty">先选几个想放进房间的建筑</div>';
    return;
  }

  // 汇总现有 tag / 约束
  var haveTags = {}, haveCids = {};
  roomState.picked.forEach(function (b) {
    tagsOf(b).forEach(function (t) {
      haveTags[t] = 1;
      if (RTAG2CID[t]) haveCids[RTAG2CID[t]] = 1;
    });
  });

  var results = [];
  roomState.rooms.forEach(function (r) {
    if (r.id === 'Neutral') return;
    var need = [], neg = [], sizes = {};
    (r.constraints || []).forEach(function (c) {
      var cid = c.id;
      if (cid.indexOf('MINIMUM_SIZE_') === 0) { sizes.min = +cid.split('_').pop(); return; }
      if (cid.indexOf('MAXIMUM_SIZE_') === 0) { sizes.max = +cid.split('_').pop(); return; }
      if (cid === 'CEILING_HEIGHT_4') { sizes.height = 4; return; }
      if (RSKIP[cid]) return;
      if (cid.indexOf('NO_') === 0) { neg.push(cid); return; }
      need.push(cid);
    });

    var ok = need.filter(function (c) { return haveCids[c]; });
    if (!ok.length) return;

    var missing = [], violated = [];
    need.forEach(function (c) {
      if (haveCids[c]) return;
      if (RSINGLE[c]) { if (haveTags[RSINGLE[c]]) missing.push(c); return; }
      missing.push(c);
    });

    neg.forEach(function (c) {
      if (c === 'NO_INDUSTRIAL_MACHINERY' && haveTags.IndustrialMachinery) violated.push(c);
      if (c === 'NO_OUTHOUSES' && !haveTags.FlushToiletType) violated.push(c);
      if ((c === 'NO_MESS_STATION' || c === 'NO_BASIC_MESS_STATIONS') && haveTags.DiningTableType) violated.push(c);
      if (c === 'NO_COTS' && haveTags.BedType && !haveTags.LuxuryBedType) violated.push(c);
    });

    results.push({
      id: r.id, name_cn: r.name_cn, category: r.category,
      min: sizes.min, max: sizes.max, height: sizes.height,
      ok: ok, missing: missing, violated: violated,
      ratio: need.length ? ok.length / need.length : 0,
      complete: !missing.length && !violated.length
    });
  });

  results.sort(function (a, b) {
    if (a.complete !== b.complete) return a.complete ? -1 : 1;
    if (b.ratio !== a.ratio) return b.ratio - a.ratio;
    return (a.name_cn || '').localeCompare(b.name_cn || '', 'zh');
  });

  // 只显示完整 或 达成度 >= 50% 的
  var show = results.filter(function (r) { return r.complete || r.ratio >= 0.5; });

  if (!show.length) {
    out.innerHTML = '<div class="empty">当前这套建筑还构不成任何房间。<br>' +
      '<span class="dim">试试再加一张床、马桶或餐桌。</span></div>';
    return;
  }

  out.innerHTML = show.map(roomCardHTML).join('');
}

function roomCardHTML(r) {
  var cls = r.complete ? 'ok' : (r.violated.length ? 'bad' : 'partial');

  var size = '';
  if (r.min || r.max) {
    size = (r.min || '?') + '~' + (r.max || '?') + ' 格';
  } else {
    size = '不限格数';
  }
  var sub = r.height ? ' 层高≥' + r.height : '';

  var lines = [];
  if (r.ok.length) {
    lines.push('<div class="rline"><span class="k">满足：</span><span class="ok">' +
      r.ok.map(function (c) { return esc(cidCN(c)); }).join('、') + '</span></div>');
  }
  if (r.missing.length) {
    lines.push('<div class="rline"><span class="k">还缺：</span><span class="miss">' +
      r.missing.map(function (c) { return esc(cidCN(c)); }).join('、') + '</span></div>');
  }
  if (r.violated.length) {
    lines.push('<div class="rline"><span class="k">冲突：</span><span class="bad">' +
      r.violated.map(function (c) { return esc(cidCN(c)); }).join('、') + '</span></div>');
  }

  var hint = '';
  if (r.complete) {
    hint = '<div class="rhint">条件已满足 —— 用砖块围出 ' + size + ' 的空间即可</div>';
  }

  var pct = Math.round(r.ratio * 100);

  return '<div class="rcard ' + cls + '">' +
    '<div class="rcard-head">' +
      '<span class="rcard-name">' + esc(r.name_cn) + '</span>' +
      '<span class="rcard-cat">' + esc(roomCatCN(r.category)) + '</span>' +
      '<span class="rcard-size">' + size + '<span class="sub">' + sub + '</span></span>' +
    '</div>' +
    lines.join('') + hint +
    '<div class="rbar"><i style="width:' + pct + '%"></i></div>' +
  '</div>';
}

// ---------- 初始化 ----------
function bootRooms() {
  Promise.all([
    fetch('/api/data/buildings_rooms.json').then(function (r) { return r.json(); }),
    fetch('/api/data/rooms.json').then(function (r) { return r.json(); }),
    fetch('/api/data/tags.json').then(function (r) { return r.json(); })
  ]).then(function (res) {
    roomState.buildings = res[0] || [];
    roomState.rooms = res[1] || [];
    roomState.tags = (res[2] && res[2].buildings) || {};
    roomState.ready = true;

    var n = roomState.buildings.filter(function (b) {
      return (roomState.tags[b['class']] || []).length;
    }).length;
    document.getElementById('rcount').textContent = n + ' 个房间相关建筑 / ' + roomState.rooms.length + ' 种房间';

    renderSuggest();
    computeRooms();
  }).catch(function (e) {
    document.getElementById('rsuggest').innerHTML =
      '<div class="rsug-none">房间数据加载失败: ' + esc(e.message) + '</div>';
  });

  var q = document.getElementById('rq');
  q.addEventListener('input', renderSuggest);
  q.addEventListener('focus', function () { renderSuggest(); });
  document.getElementById('rclear').addEventListener('click', function () {
    roomState.picked = [];
    renderSuggest(); renderPicked(); computeRooms();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootRooms);
} else {
  bootRooms();
}

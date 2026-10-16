/* 缺氧计算查询工具 —— 制氧测算 / 供电测算
 *
 * 算法与 calc_engine.py 保持一致（无 node 环境，只能靠人工比对两边逻辑）。
 * 数据来自 constants.json（游戏源码提取）。
 */
(function () {
  'use strict';

  var CONST = null;          // constants.json
  var BUILDINGS = null;      // buildings.json

  // ---------- 基础工具 ----------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // 去掉多余小数尾随 0 —— 只在有小数点时处理（老 bug 的教训）
  function trim0(s) {
    if (s.indexOf('.') < 0) return s;
    s = s.replace(/0+$/, '');
    s = s.replace(/\.$/, '');
    return s;
  }

  function num(v, digits) {
    if (v == null || isNaN(v)) return '—';
    var d = digits == null ? 2 : digits;
    var s = Number(v).toFixed(d);
    return trim0(s);
  }

  // kg/s -> g/s 显示
  function gps(kg) { return num(kg * 1000, 1); }

  function q(id) { return document.getElementById(id); }

  // ---------- 制氧测算 ----------
  // 正算: 人口 -> 需要几台
  function oxyByPopulation(pop) {
    var perMinion = CONST.oxygen_used_per_second;
    var co2Ratio = CONST.oxygen_to_co2_conversion;
    var need = pop * perMinion;

    var makers = (CONST.oxygen_makers || []).filter(function (m) {
      return m.oxygen_kg_s > 0;
    }).sort(function (a, b) { return b.oxygen_kg_s - a.oxygen_kg_s; });

    var options = makers.map(function (m) {
      var n = Math.ceil(need / m.oxygen_kg_s);
      var inputs = (m.inputs || []).map(function (i) {
        return {
          element: i.element,
          rate: i.rate_kg_s * n,
          perCycle: i.rate_kg_s * n * 600
        };
      });
      var byprod = (m.outputs || []).filter(function (o) {
        return o.element !== 'Oxygen';
      }).map(function (o) {
        return { element: o.element, rate: o.rate_kg_s * n };
      });
      return {
        id: m.id, name: m.name_cn, count: n,
        each: m.oxygen_kg_s, capacity: m.oxygen_kg_s * n,
        margin: m.oxygen_kg_s * n - need,
        powerEach: m.power_w, powerTotal: m.power_w ? m.power_w * n : null,
        inputs: inputs, byproducts: byprod
      };
    });

    return {
      need: need, co2: need * co2Ratio, options: options
    };
  }

  // 反算: 机器 -> 能养几个人
  function oxyByMachine(machineId, count) {
    var perMinion = CONST.oxygen_used_per_second;
    var co2Ratio = CONST.oxygen_to_co2_conversion;
    var m = (CONST.oxygen_makers || []).filter(function (x) {
      return x.id === machineId;
    })[0];
    if (!m) return null;
    var supply = m.oxygen_kg_s * count;
    return {
      name: m.name_cn, id: m.id, count: count,
      supply: supply,
      pop: Math.floor(supply / perMinion),
      popExact: supply / perMinion,
      co2: supply * co2Ratio,
      powerTotal: m.power_w ? m.power_w * count : null,
      inputs: (m.inputs || []).map(function (i) {
        return {
          element: i.element, rate: i.rate_kg_s * count,
          perCycle: i.rate_kg_s * count * 600
        };
      }),
      byproducts: (m.outputs || []).filter(function (o) {
        return o.element !== 'Oxygen';
      }).map(function (o) {
        return { element: o.element, rate: o.rate_kg_s * count };
      })
    };
  }

  // 优先用 app.js 的全量映射，没有时用它自己的小表；都没有就原样显示
  function elemCN(id) {
    if (window.ELEM_CN && window.ELEM_CN[id]) return window.ELEM_CN[id];
    return id;
  }

  // ---------- 供电测算 ----------
  var powerUsage = [];   // [{key, count}]

  function buildIndex() {
    var idx = {};
    (BUILDINGS || []).forEach(function (b) {
      if (b.id) idx[b.id] = b;
      if (b.class) idx[b.class] = b;
      if (b.name_cn) idx[b.name_cn] = b;
    });
    return idx;
  }

  function powerCalc() {
    var idx = buildIndex();
    var consumers = [], unknown = [], total = 0;
    powerUsage.forEach(function (u) {
      var b = idx[u.key];
      if (!b) { unknown.push(u.key); return; }
      var w = b.power_w || 0;
      total += w * u.count;
      consumers.push({
        name: b.name_cn || b.id, id: b.id, count: u.count,
        each: w, sub: w * u.count
      });
    });
    consumers.sort(function (a, b) { return b.sub - a.sub; });

    var gens = (CONST.generators || []).map(function (g) {
      var n = total > 0 ? Math.ceil(total / g.wattage) : 0;
      var ff = g.fuel_formula || {};
      var item = {
        name: g.name_cn, id: g.id, wattage: g.wattage, count: n,
        output: g.wattage * n, margin: g.wattage * n - total,
        fuel: ff.fuel, fuelRate: ff.fuel_rate_kg_s
      };
      if (ff.fuel_rate_kg_s && n) {
        item.fuelTotal = ff.fuel_rate_kg_s * n;
        item.fuelPerCycle = ff.fuel_rate_kg_s * n * 600;
      }
      return item;
    });
    gens.sort(function (a, b) {
      return (a.count - b.count) || (a.wattage - b.wattage);
    });

    return {
      consumers: consumers, unknown: unknown, total: total, generators: gens
    };
  }

  // ---------- 渲染: 制氧 ----------
  function renderOxy() {
    var box = q('oxyResult');
    if (!box || !CONST) return;
    var mode = document.querySelector('input[name="oxyMode"]:checked').value;
    var html = '';

    if (mode === 'pop') {
      var pop = parseInt(q('oxyPop').value, 10);
      if (!pop || pop < 1) { box.innerHTML = '<p class="dim">请输入人口数。</p>'; return; }
      var r = oxyByPopulation(pop);
      html += '<div class="calc-head">';
      html += '<div class="calc-stat"><span class="k">氧气需求</span>' +
        '<span class="v">' + gps(r.need) + ' <small>g/s</small></span></div>';
      html += '<div class="calc-stat"><span class="k">呼出二氧化碳</span>' +
        '<span class="v">' + gps(r.co2) + ' <small>g/s</small></span></div>';
      html += '</div>';
      html += '<h3>可选方案</h3>';
      html += '<div class="calc-cards">';
      r.options.forEach(function (o) {
        html += '<div class="calc-card">';
        html += '<div class="calc-card-head"><strong>' + esc(o.name) +
          '</strong><span class="calc-badge">×' + o.count + '</span></div>';
        html += '<div class="calc-row"><span>总产能</span><b>' + gps(o.capacity) +
          ' g/s</b> <em class="' + (o.margin >= 0 ? 'ok' : 'bad') + '">(余 ' +
          (o.margin >= 0 ? '+' : '') + gps(o.margin) + ')</em></div>';
        html += '<div class="calc-row"><span>单台产氧</span><b>' + gps(o.each) +
          ' g/s</b></div>';
        if (o.powerTotal != null) {
          html += '<div class="calc-row"><span>耗电</span><b>' +
            num(o.powerEach, 0) + ' W/台</b> <em>合计 ' +
            num(o.powerTotal, 0) + ' W</em></div>';
        }
        o.inputs.forEach(function (i) {
          html += '<div class="calc-row"><span>消耗 ' + esc(elemCN(i.element)) +
            '</span><b>' + num(i.rate, 3) + ' kg/s</b> <em>' +
            num(i.perCycle, 1) + ' kg/周期</em></div>';
        });
        o.byproducts.forEach(function (b) {
          html += '<div class="calc-row"><span>副产 ' + esc(elemCN(b.element)) +
            '</span><b>' + num(b.rate, 4) + ' kg/s</b></div>';
        });
        html += '</div>';
      });
      html += '</div>';
    } else {
      var mid = q('oxyMachine').value;
      var cnt = parseInt(q('oxyCount').value, 10);
      if (!mid || !cnt || cnt < 1) {
        box.innerHTML = '<p class="dim">请选择设备并输入台数。</p>'; return;
      }
      var m = oxyByMachine(mid, cnt);
      if (!m) { box.innerHTML = '<p class="dim">找不到该设备。</p>'; return; }
      html += '<div class="calc-head">';
      html += '<div class="calc-stat"><span class="k">氧气产量</span>' +
        '<span class="v">' + gps(m.supply) + ' <small>g/s</small></span></div>';
      html += '<div class="calc-stat hi"><span class="k">可养活</span>' +
        '<span class="v">' + m.pop + ' <small>人</small></span>' +
        '<span class="sub">精确 ' + num(m.popExact, 2) + ' 人</span></div>';
      html += '<div class="calc-stat"><span class="k">呼出二氧化碳</span>' +
        '<span class="v">' + gps(m.co2) + ' <small>g/s</small></span></div>';
      html += '</div>';
      html += '<div class="calc-cards"><div class="calc-card">';
      html += '<div class="calc-card-head"><strong>' + esc(m.name) +
        '</strong><span class="calc-badge">×' + m.count + '</span></div>';
      if (m.powerTotal != null) {
        html += '<div class="calc-row"><span>耗电合计</span><b>' +
          num(m.powerTotal, 0) + ' W</b></div>';
      }
      m.inputs.forEach(function (i) {
        html += '<div class="calc-row"><span>消耗 ' + esc(elemCN(i.element)) +
          '</span><b>' + num(i.rate, 4) + ' kg/s</b> <em>' +
          num(i.perCycle, 1) + ' kg/周期</em></div>';
      });
      m.byproducts.forEach(function (b) {
        html += '<div class="calc-row"><span>副产 ' + esc(elemCN(b.element)) +
          '</span><b>' + num(b.rate, 4) + ' kg/s</b></div>';
      });
      html += '</div></div>';
    }
    box.innerHTML = html;
  }

  // ---------- 渲染: 供电 ----------
  function renderPower() {
    var box = q('powerResult');
    if (!box || !CONST) return;
    if (!powerUsage.length) {
      box.innerHTML = '<p class="dim">还没添加用电设备。上面搜一个加进来，' +
        '就会算出总耗电和需要几台发电机。</p>';
      return;
    }
    var r = powerCalc();
    var html = '';

    html += '<h3>用电清单</h3><div class="calc-cards"><div class="calc-card">';
    r.consumers.forEach(function (c) {
      html += '<div class="calc-row"><span>' + esc(c.name) + ' ×' + c.count +
        '</span><b>' + num(c.sub, 0) + ' W</b> <em>' + num(c.each, 0) +
        ' W/台</em></div>';
    });
    r.unknown.forEach(function (u) {
      html += '<div class="calc-row bad"><span>⚠ 未找到</span><b>' +
        esc(u) + '</b></div>';
    });
    html += '<div class="calc-row total"><span>合计</span><b>' +
      num(r.total, 0) + ' W</b> <em>' + num(r.total / 1000, 2) + ' kW</em></div>';
    html += '</div></div>';

    html += '<h3>发电机配比</h3><div class="calc-cards">';
    r.generators.forEach(function (g) {
      html += '<div class="calc-card">';
      html += '<div class="calc-card-head"><strong>' + esc(g.name) +
        '</strong><span class="calc-badge">×' + g.count + '</span></div>';
      html += '<div class="calc-row"><span>输出</span><b>' + num(g.output, 0) +
        ' W</b> <em>' + num(g.wattage, 0) + ' W/台</em></div>';
      html += '<div class="calc-row"><span>余量</span><b class="ok">+' +
        num(g.margin, 0) + ' W</b></div>';
      if (g.fuelTotal) {
        html += '<div class="calc-row"><span>燃料 ' + esc(elemCN(g.fuel)) +
          '</span><b>' + num(g.fuelTotal, 4) + ' kg/s</b> <em>' +
          num(g.fuelPerCycle, 1) + ' kg/周期</em></div>';
      }
      html += '</div>';
    });
    html += '</div>';
    box.innerHTML = html;
  }

  // ---------- 供电: 搜索与选择 ----------
  function renderPowerChips() {
    var box = q('powerChips');
    if (!box) return;
    if (!powerUsage.length) { box.innerHTML = ''; return; }
    var idx = buildIndex();
    box.innerHTML = powerUsage.map(function (u, i) {
      var b = idx[u.key] || {};
      return '<span class="pchip">' + esc(b.name_cn || u.key) +
        ' <input class="pchip-n" type="number" min="1" max="999" value="' +
        u.count + '" data-i="' + i + '"> ' +
        '<button class="pchip-x" data-i="' + i + '" title="移除">×</button></span>';
    }).join('');
  }

  function powerSearch(term) {
    var box = q('powerSuggest');
    if (!box) return;
    term = (term || '').trim().toLowerCase();
    if (!term) { box.innerHTML = ''; return; }
    var hits = (BUILDINGS || []).filter(function (b) {
      if (!b.power_w || b.power_w <= 0) return false;
      var hay = ((b.name_cn || '') + ' ' + (b.id || '') + ' ' +
        (b.class || '')).toLowerCase();
      return hay.indexOf(term) >= 0;
    }).sort(function (a, b) { return b.power_w - a.power_w; }).slice(0, 12);

    if (!hits.length) {
      box.innerHTML = '<div class="dim" style="padding:6px 2px">' +
        '没有耗电建筑匹配「' + esc(term) + '」</div>';
      return;
    }
    box.innerHTML = hits.map(function (b) {
      return '<button class="psug" data-id="' + esc(b.id) + '">' +
        esc(b.name_cn || b.id) + ' <em>' + num(b.power_w, 0) + ' W</em></button>';
    }).join('');
  }

  // ---------- 初始化 ----------
  function fillMachineSelect() {
    var sel = q('oxyMachine');
    if (!sel || !CONST) return;
    sel.innerHTML = (CONST.oxygen_makers || []).map(function (m) {
      return '<option value="' + esc(m.id) + '">' + esc(m.name_cn) +
        '（' + gps(m.oxygen_kg_s) + ' g/s）</option>';
    }).join('');
  }

  function bindCalc() {
    // 制氧: 模式切换
    document.querySelectorAll('input[name="oxyMode"]').forEach(function (r) {
      r.addEventListener('change', function () {
        var m = document.querySelector('input[name="oxyMode"]:checked').value;
        q('oxyPopBox').hidden = (m !== 'pop');
        q('oxyMachBox').hidden = (m !== 'machine');
        renderOxy();
      });
    });
    ['oxyPop', 'oxyCount'].forEach(function (id) {
      var el = q(id);
      if (el) el.addEventListener('input', renderOxy);
    });
    var ms = q('oxyMachine');
    if (ms) ms.addEventListener('change', renderOxy);

    // 供电: 搜索
    var pq = q('powerQ');
    if (pq) {
      pq.addEventListener('input', function () { powerSearch(pq.value); });
      pq.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { pq.value = ''; powerSearch(''); }
      });
    }
    var sug = q('powerSuggest');
    if (sug) {
      sug.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('.psug') : null;
        if (!btn) return;
        addPower(btn.getAttribute('data-id'));
        pq.value = '';
        powerSearch('');
        pq.focus();
      });
    }
    var chips = q('powerChips');
    if (chips) {
      chips.addEventListener('click', function (e) {
        var x = e.target.closest ? e.target.closest('.pchip-x') : null;
        if (x) {
          powerUsage.splice(parseInt(x.getAttribute('data-i'), 10), 1);
          renderPowerChips(); renderPower();
        }
      });
      chips.addEventListener('input', function (e) {
        var n = e.target.closest ? e.target.closest('.pchip-n') : null;
        if (!n) return;
        var v = parseInt(n.value, 10);
        if (!v || v < 1) v = 1;
        if (v > 999) v = 999;
        powerUsage[parseInt(n.getAttribute('data-i'), 10)].count = v;
        renderPower();
      });
    }
    var pc = q('powerClear');
    if (pc) {
      pc.addEventListener('click', function () {
        powerUsage = [];
        renderPowerChips(); renderPower();
      });
    }
  }

  function addPower(id) {
    var ex = powerUsage.filter(function (u) { return u.key === id; })[0];
    if (ex) { ex.count += 1; }
    else { powerUsage.push({ key: id, count: 1 }); }
    renderPowerChips();
    renderPower();
  }

  function loadJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
      return r.json();
    });
  }

  function bootCalc() {
    // 依赖 app.js 的 ELEM_CN，先确保它在
    Promise.all([
      loadJSON('/api/data/constants.json'),
      loadJSON('/api/data/buildings.json')
    ]).then(function (arr) {
      CONST = arr[0]; BUILDINGS = arr[1];
      fillMachineSelect();
      bindCalc();
      renderOxy();
      renderPower();
      var info = q('calcInfo');
      if (info) {
        info.textContent = '每名复制人每秒消耗 ' +
          gps(CONST.oxygen_used_per_second) + ' g 氧气，呼出 ' +
          gps(CONST.oxygen_used_per_second * CONST.oxygen_to_co2_conversion) +
          ' g 二氧化碳；一个周期 ' + 600 + ' 秒。';
      }
    }).catch(function (e) {
      var b = q('oxyResult');
      if (b) b.innerHTML = '<div class="empty">数据加载失败: ' +
        esc(e.message) + '</div>';
    });
  }

  window.CALC = { oxyByPopulation: oxyByPopulation, oxyByMachine: oxyByMachine,
                  powerCalc: powerCalc, setConst: function (c) { CONST = c; },
                  setBuildings: function (b) { BUILDINGS = b; } };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootCalc);
  } else {
    bootCalc();
  }
})();

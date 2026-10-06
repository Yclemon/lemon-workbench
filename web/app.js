'use strict';

/* ------------------------------------------------------------------ *
 *  Steam 游玩报告 · 前端（无依赖）
 * ------------------------------------------------------------------ */

const HOUR = 3600, DAY = 86400;
const IDLE_DAYS = 90;              // 超过这么多天没碰 = 吃灰
const NEW_PLAY_WINDOW = 30 * DAY;  // “最近玩过”窗口

const COVER = [
  id => `https://cdn.cloudflare.steamstatic.com/steam/apps/${id}/header.jpg`,
  id => `https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/${id}/header.jpg`,
  id => `https://steamcdn-a.akamaihd.net/steam/apps/${id}/header.jpg`,
];
const HERO = [
  id => `https://cdn.cloudflare.steamstatic.com/steam/apps/${id}/library_hero.jpg`,
  id => `https://cdn.cloudflare.steamstatic.com/steam/apps/${id}/header.jpg`,
  id => `https://steamcdn-a.akamaihd.net/steam/apps/${id}/header.jpg`,
];

const state = {
  data: null,
  cfg: null,
  account: null,
  showTools: false,
  filter: 'all',
  sort: 'playtime',
  q: '',
  accountTouched: false,
  tab: 'info',        // 详情弹窗当前标签页：info | ach
  pics: {},           // {appid: [{file,url,size,at}]}，点开详情时按需拉
};

const $ = s => document.querySelector(s);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/* --------------------------- 格式化 --------------------------- */

function fmtHours(min) {
  if (!min) return '0 小时';
  const h = min / 60;
  if (h < 1) return `${min} 分钟`;
  if (h < 10) return `${h.toFixed(1)} 小时`;
  if (h < 1000) return `${Math.round(h)} 小时`;
  return `${(h / 1000).toFixed(2)} 千小时`;
}
function fmtHoursShort(min) {
  const h = min / 60;
  if (!min) return '0h';
  if (h < 1) return `${min}m`;
  if (h < 10) return `${h.toFixed(1)}h`;
  return `${Math.round(h)}h`;
}
function fmtSize(b) {
  if (!b) return '—';
  const g = b / 1024 ** 3;
  if (g >= 1) return `${g.toFixed(g >= 100 ? 0 : 1)} GB`;
  return `${(b / 1024 ** 2).toFixed(0)} MB`;
}
function relTime(ts) {
  if (!ts) return '从未运行';
  const d = (Date.now() / 1000) - ts;
  if (d < 0) return '刚刚';
  if (d < 3600) return `${Math.max(1, Math.round(d / 60))} 分钟前`;
  if (d < DAY) return `${Math.round(d / HOUR)} 小时前`;
  if (d < 30 * DAY) return `${Math.round(d / DAY)} 天前`;
  if (d < 365 * DAY) return `${Math.round(d / (30 * DAY))} 个月前`;
  return `${(d / (365 * DAY)).toFixed(1)} 年前`;
}
function dateStr(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function daysSince(ts) { return ts ? Math.floor((Date.now() / 1000 - ts) / DAY) : null; }

function hueOf(appid) { return (appid * 47) % 360; }
function placeholder(name, appid, cls) {
  const h = hueOf(appid);
  const ch = esc((name || '?').trim().charAt(0) || '?');
  return `<div class="${cls}" style="background:linear-gradient(135deg,hsl(${h} 44% 90%),hsl(${(h + 40) % 360} 40% 80%));color:hsl(${h} 42% 27%)">${ch}</div>`;
}
function imgTag(appid, name, urls, cls) {
  const first = urls[0](appid);
  return `<img src="${first}" alt="${esc(name)}" loading="lazy"
    data-idx="1" data-kind="${urls === HERO ? 'hero' : 'cover'}" data-appid="${appid}"
    onerror="imgFail(this)">`;
}
window.imgFail = function (img) {
  const list = img.dataset.kind === 'hero' ? HERO : COVER;
  const i = Number(img.dataset.idx || 1);
  if (i < list.length) {
    img.dataset.idx = i + 1;
    img.src = list[i](Number(img.dataset.appid));
    return;
  }
  const ph = document.createElement('div');
  ph.className = img.className === 'heroImg' ? 'ph' : (img.parentElement.classList.contains('thumb') ? 'ph' : 'ph');
  ph.innerHTML = placeholder(img.alt, Number(img.dataset.appid), 'ph').replace(/^<div[^>]*>|<\/div>$/g, '');
  const style = placeholder(img.alt, Number(img.dataset.appid), 'ph').match(/style="([^"]*)"/);
  ph.setAttribute('style', style ? style[1] : '');
  img.replaceWith(ph);
};

/* --------------------------- 计算 --------------------------- */

/* 卡片上那行小成就；没数据就返回空串 */
function achLine(g) {
  if (g.ach == null) {
    return g.ach_none ? '<span class="stTxt zero">无成就系统</span>' : '';
  }
  const a = Number(g.ach);
  const t = g.ach_total ? Number(g.ach_total) : 0;
  const pct = t ? Math.max(0, Math.min(100, Math.round(a / t * 100))) : 0;
  const st = playStatus(g);
  return `<span>🏆 ${a}${t ? ' / ' + t : ''}</span>` +
    (t ? `<span class="miniBar"><i style="width:${pct}%"></i></span><span>${pct}%</span>` : '') +
    (st ? `<span class="stTxt ${st.cls}">${st.short}</span>` : '');
}

function visibleGames() {
  return state.data.games.filter(g => state.showTools || !g.is_tool);
}

/* 成就全解锁 = 自动认定为「全部游玩」 */
function allAchDone(g) {
  const t = g.ach_total ? Number(g.ach_total) : 0;
  return !!(t && g.ach != null && Number(g.ach) >= t);
}

function markLabel(g) {
  if (g.done) return '✓ 全部游玩（手动标记）';
  if (allAchDone(g)) return '✓ 全部游玩（成就全解锁）';
  return '☐ 标记全部游玩';
}

/* 游玩情况：完全由成就完成数推出来 */
function playStatus(g) {
  const t = g.ach_total ? Number(g.ach_total) : 0;
  if (!t) return null;
  const a = Number(g.ach || 0);
  const pct = Math.max(0, Math.min(100, Math.round(a / t * 100)));
  if (a >= t) return { txt: '全部游玩 · 全成就', short: '全成就', cls: 'full', pct };
  if (pct >= 80) return { txt: '快全成就了 · ' + pct + '%', short: '快全成就', cls: 'near', pct };
  if (a > 0) return { txt: '还在推成就 · ' + pct + '%', short: '在推成就', cls: 'ing', pct };
  return { txt: '一个成就都还没解锁 · 0%', short: '没解锁', cls: 'zero', pct };
}

function classify(g) {
  const idle = daysSince(g.last_played);
  const dust = g.installed && (g.playtime_min === 0 || (idle !== null && idle >= IDLE_DAYS));
  const achPct = (g.ach != null && g.ach_total) ? g.ach / g.ach_total : null;
  const allAch = allAchDone(g);
  return {
    dust,
    neverPlayed: g.playtime_min === 0,
    recent: g.last_played && (Date.now() / 1000 - g.last_played) < NEW_PLAY_WINDOW,
    idleDays: idle,
    done: !!g.done || allAch,     // 手动标的，或成就全解锁自动算的
    allAch,
    achPct,
  };
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  let list = visibleGames().filter(g => {
    if (q && !(g.name.toLowerCase().includes(q) || String(g.appid).includes(q))) return false;
    const c = classify(g);
    switch (state.filter) {
      case 'installed': return g.installed;
      case 'played': return g.playtime_min > 0;
      case 'never': return g.installed && g.playtime_min === 0;
      case 'dust': return c.dust;
      case 'gone': return !g.installed && g.playtime_min > 0;
      case 'done': return c.done;
      case 'ach': return g.ach != null;
      default: return true;
    }
  });
  const by = {
    playtime: (a, b) => b.playtime_min - a.playtime_min || b.last_played - a.last_played,
    recent: (a, b) => b.last_played - a.last_played,
    size: (a, b) => b.size_bytes - a.size_bytes,
    name: (a, b) => a.name.localeCompare(b.name, 'zh'),
    updated: (a, b) => b.last_updated - a.last_updated,
    ach: (a, b) => ((b.ach || 0) / (b.ach_total || 1e9)) - ((a.ach || 0) / (a.ach_total || 1e9))
      || (b.ach || 0) - (a.ach || 0),
  }[state.sort];
  return list.sort(by || by.playtime);
}

/* --------------------------- 渲染 --------------------------- */

function renderAll() {
  renderHeader();
  renderStats();
  renderOnline();
  renderTop();
  renderDust();
  renderFilters();
  renderGrid();
}

function onlineInfo() {
  return (state.data && state.data.online) || {};
}

function renderHeader() {
  const d = state.data;
  const acct = d.account;
  const sel = $('#accountSel');
  if (!state.accountTouched) {
    sel.innerHTML = d.accounts.map(a =>
      `<option value="${a.folder}"${acct && a.folder === acct.folder ? ' selected' : ''}>${esc(a.persona_name)}</option>`
    ).join('') || '<option>（未找到账号）</option>';
    state.account = acct ? acct.folder : null;
  }
  const libs = d.libraries.map(l => l.path + (l.exists ? '' : '(缺失)')).join(' · ');
  let extra = '';
  if (d.unnamed_count) {
    extra = ` &nbsp;·&nbsp; <a href="#" id="enrichLink" style="color:var(--orange);text-decoration:none">补全 ${d.unnamed_count} 个游戏名（联网一次）</a>`;
  }
  const on = onlineInfo();
  const onTxt = on.ok
    ? ` &nbsp;|&nbsp; <span style="color:var(--green)">🌐 账号数据 ${esc(on.persona || '')} ${on.game_count} 款</span>`
    : '';
  $('#scanInfo').innerHTML =
    `库目录 ${esc(libs)} &nbsp;|&nbsp; 账号 ${esc(acct ? acct.persona_name : '—')} &nbsp;|&nbsp; ` +
    `扫描于 ${dateStr(d.generated_at)}（${d.elapsed_ms} ms）` +
    (d.names_cached ? ` &nbsp;|&nbsp; 名称缓存 ${d.names_cached} 条` : '') + onTxt + extra;
  const link = $('#enrichLink');
  if (link) link.onclick = e => { e.preventDefault(); load({ force: true, enrich: true }); };
}

/* 顶栏那个按钮的文案，随时反映「连没连上」 */
function renderOnline() {
  const on = onlineInfo();
  const cfg = state.cfg || {};
  const btn = $('#onlineBtn');
  if (!btn) return;
  btn.textContent = on.ok ? '账号已连接' : (cfg.key_set ? '账号连接有问题' : '连接 Steam 账号');
  btn.classList.toggle('ghost', !on.ok);

  const n = $('#notice');
  if (on.enabled && !on.ok) {
    n.hidden = false;
    n.innerHTML = `<b>账号数据没取到：</b>${esc(on.error || '未知原因')}
      <a href="#" id="noticeCfg">检查设置</a>`;
    const a = $('#noticeCfg');
    if (a) a.onclick = e => { e.preventDefault(); openCfg(); };
  } else {
    n.hidden = true;
  }

  const panel = $('#recentPanel');
  const list = (state.data.games || []).filter(g => g.playtime_2weeks_min > 0)
    .sort((a, b) => b.playtime_2weeks_min - a.playtime_2weeks_min);
  panel.hidden = list.length === 0;
  if (!list.length) return;
  $('#recentList').innerHTML = list.map(g => `
    <div class="recent" data-appid="${g.appid}">
      <div class="thumb">${imgTag(g.appid, g.name, COVER, 'coverImg')}</div>
      <div class="body">
        <div class="nm" title="${esc(g.name)}">${esc(g.name)}</div>
        <div class="mins">${fmtHours(g.playtime_2weeks_min)}<small>近两周</small></div>
      </div>
    </div>`).join('');
  $('#recentList').querySelectorAll('.recent').forEach(n =>
    n.onclick = () => openDetail(Number(n.dataset.appid)));
}


function renderStats() {
  const gs = visibleGames();
  const inst = gs.filter(g => g.installed);
  const totalMin = gs.reduce((s, g) => s + g.playtime_min, 0);
  const totalSize = inst.reduce((s, g) => s + g.size_bytes, 0);
  const never = inst.filter(g => g.playtime_min === 0);
  const dust = gs.filter(g => classify(g).dust);
  const recent = gs.filter(g => classify(g).recent);
  const best = gs.slice().sort((a, b) => b.playtime_min - a.playtime_min)[0];

  const cards = [
    ['k', '收录游戏', gs.length, '款', `已安装 ${inst.length} · 玩过 ${gs.filter(g => g.playtime_min > 0).length}`],
    ['', '累计游玩', (totalMin / 60).toFixed(0), '小时',
      best ? `≈ ${(totalMin / 1440).toFixed(0)} 天 · 最长《${esc(best.name)}》` : ''],
    ['g', '磁盘占用', (totalSize / 1024 ** 3).toFixed(1), 'GB', `${inst.length} 款已安装游戏`],
    ['r', '从未启动', never.length, '款', never.length ? `白占 ${fmtSize(never.reduce((s, g) => s + g.size_bytes, 0))}` : '全都玩过了'],
    ['o', `吃灰 ≥${IDLE_DAYS} 天`, dust.length, '款', '装了没碰 / 久未打开'],
    ['', '近 30 天玩过', recent.length, '款', recent.length ? '最近还在活跃' : '最近没怎么玩'],
  ];

  // 连上官方接口后，时长口径就从「这台电脑」变成「整个账号」
  const on = onlineInfo();
  if (on.ok) {
    cards[1][1] = '账号累计游玩';
    cards[1][4] = `整个账号 · 含其他设备${on.added ? ` · 多出 ${on.added} 款本机没有的` : ''}`;
    const twoWeek = gs.filter(g => g.playtime_2weeks_min > 0).length;
    cards.push(['g', '最近两周', (on.two_weeks_min / 60).toFixed(1), '小时',
      twoWeek ? `${twoWeek} 款在玩` : '两周没开张']);
  }

  // 成就 / 游玩情况汇总（含自动从 Steam 读来的）；一条都没有就不占位
  const gs2 = visibleGames();
  const achList = gs2.filter(g => g.ach != null);
  const doneN = gs2.filter(g => classify(g).done).length;
  if (doneN || achList.length) {
    let dAch = 0, tAch = 0;
    achList.forEach(g => { dAch += Number(g.ach) || 0; tAch += Number(g.ach_total) || 0; });
    const note = achList.length
      ? `已记 ${achList.length} 款成就 · 共 ${dAch}${tAch ? ' / ' + tAch : ''} 个`
      : '标了就算通关';
    cards.push(['k', '全部游玩', doneN, '款', note]);
  }

  $('#stats').innerHTML = cards.map(([cls, k, v, unit, note]) => `
    <div class="stat ${cls}">
      <div class="k">${k}</div>
      <div class="v">${v}<small>${unit}</small></div>
      <div class="n">${note}</div>
    </div>`).join('');
}

function renderTop() {
  const list = visibleGames()
    .filter(g => g.playtime_min > 0)
    .sort((a, b) => b.playtime_min - a.playtime_min)
    .slice(0, 10);
  const max = list.length ? list[0].playtime_min : 1;
  $('#topN').textContent = list.length;
  $('#topBars').innerHTML = list.map(g => `
    <div class="bar" data-appid="${g.appid}">
      <div class="nm" title="${esc(g.name)}">${esc(g.name)}</div>
      <div class="track"><div class="fill" style="width:${Math.max(2, g.playtime_min / max * 100).toFixed(1)}%"></div></div>
      <div class="vl">${fmtHours(g.playtime_min)}</div>
    </div>`).join('') || '<div class="empty">还没有游玩记录</div>';
  $('#topBars').querySelectorAll('.bar').forEach(b =>
    b.onclick = () => openDetail(Number(b.dataset.appid)));
}

function renderDust() {
  const gs = visibleGames().filter(g => g.installed);
  const never = gs.filter(g => g.playtime_min === 0).sort((a, b) => b.size_bytes - a.size_bytes);
  const idle = gs.filter(g => g.playtime_min > 0 && (classify(g).idleDays ?? 0) >= IDLE_DAYS)
    .sort((a, b) => a.last_played - b.last_played);
  const list = never.concat(idle).slice(0, 20);

  $('#dustList').innerHTML = list.map(g => {
    const d = classify(g);
    const why = d.neverPlayed ? '装了但一次没打开' : `${d.idleDays} 天没碰了`;
    return `<div class="dust" data-appid="${g.appid}">
      <div class="thumb">${imgTag(g.appid, g.name, COVER, 'coverImg')}</div>
      <div class="body">
        <div class="nm" title="${esc(g.name)}">${esc(g.name)}</div>
        <div class="why">${why}</div>
        <div class="sz">${fmtSize(g.size_bytes)}${g.last_played ? ' · 上次 ' + dateStr(g.last_played).slice(0, 10) : ''}</div>
      </div>
    </div>`;
  }).join('') || '<div class="empty">没有吃灰的游戏，真厉害 🎉</div>';

  $('#dustList').querySelectorAll('.dust').forEach(n =>
    n.onclick = () => openDetail(Number(n.dataset.appid)));
}

function renderFilters() {
  const gs = visibleGames();
  const defs = [
    ['all', '全部', gs.length],
    ['installed', '已安装', gs.filter(g => g.installed).length],
    ['played', '玩过', gs.filter(g => g.playtime_min > 0).length],
    ['never', '从未启动', gs.filter(g => g.installed && g.playtime_min === 0).length],
    ['dust', '吃灰', gs.filter(g => classify(g).dust).length],
    ['gone', '已卸载但玩过', gs.filter(g => !g.installed && g.playtime_min > 0).length],
  ];
  const nDone = gs.filter(g => g.done).length;
  const nAch = gs.filter(g => g.ach != null).length;
  if (nDone) defs.push(['done', '全部游玩', nDone]);
  if (nAch) defs.push(['ach', '有成就记录', nAch]);
  $('#chips').innerHTML = defs.map(([k, label, n]) =>
    `<div class="chip${state.filter === k ? ' on' : ''}" data-f="${k}">${label}<b>${n}</b></div>`).join('');
  $('#chips').querySelectorAll('.chip').forEach(c => c.onclick = () => {
    state.filter = c.dataset.f;
    renderFilters(); renderGrid();
  });

  const sorts = [['playtime', '按时长'], ['recent', '按最近玩过'], ['size', '按占用空间'],
    ['updated', '按最近更新'], ['name', '按名称']];
  if (nAch) sorts.push(['ach', '按成就完成度']);
  const sel = $('#sortSel');
  if (sel.options.length !== sorts.length) {
    sel.innerHTML = sorts.map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
    sel.value = state.sort;
  }
}

function renderGrid() {
  const list = filtered();
  $('#listCount').textContent = `(${list.length})`;
  $('#empty').hidden = list.length > 0;

  $('#grid').innerHTML = list.map(g => {
    const c = classify(g);
    let tag = '';
    if (!g.installed) tag = '<span class="tag">已卸载</span>';
    else if (c.neverPlayed) tag = '<span class="tag new">没玩过</span>';
    else if (c.dust) tag = `<span class="tag dust">${c.idleDays} 天没碰</span>`;
    const done = c.done ? '<span class="tag done">✓ 全部游玩</span>' : '';
    const right = g.installed ? fmtSize(g.size_bytes) : (g.last_played ? relTime(g.last_played) : '—');
    const ach = achLine(g);
    const pics = g.image_count ? `<span class="tag pic">📷 ${g.image_count}</span>` : '';
    return `<div class="card" data-appid="${g.appid}">
      <div class="thumb">${imgTag(g.appid, g.name, COVER, 'coverImg')}<span class="tagL">${tag}</span><span class="tagR">${done}${pics}</span></div>
      <div class="body">
        <div class="nm">${esc(g.name)}</div>
        ${ach ? `<div class="achMini">${ach}</div>` : ''}
        <div class="meta">
          <span class="hrs${g.playtime_min ? '' : ' zero'}">${fmtHoursShort(g.playtime_min)}</span>
          <span>${right}</span>
        </div>
        <button class="markBtn${c.done ? ' on' : ''}" data-mark="${g.appid}"
          title="按一下手动标记 / 取消；成就全部解锁时会自动算「全部游玩」">${markLabel(g)}</button>
      </div>
    </div>`;
  }).join('');

  $('#grid').querySelectorAll('.card').forEach(n =>
    n.onclick = () => openDetail(Number(n.dataset.appid)));
  $('#grid').querySelectorAll('[data-mark]').forEach(n => {
    n.onclick = async e => {
      e.stopPropagation();                       // 别顺手把详情弹窗也打开
      const id = Number(n.dataset.mark);
      const g = state.data.games.find(x => x.appid === id);
      if (!g) return;
      n.disabled = true;
      try {
        await postManual(id, { done: !g.done });
      } catch (err) {
        n.disabled = false;
        alert('标记没保存成功：' + err.message);
      }
    };
  });
}

/* --------------------------- 详情 --------------------------- */

function openDetail(appid) {
  const g = state.data.games.find(x => x.appid === appid);
  if (!g) return;
  const c = classify(g);
  const SUB = 'font-size:11px;color:var(--dim);font-weight:400';
  const boxes = [
    ['游玩时长', fmtHours(g.playtime_min)],
    ['最后运行', g.last_played ? `${relTime(g.last_played)}<div style="${SUB}">${dateStr(g.last_played)}</div>` : '从未运行'],
    ['磁盘占用', g.installed ? fmtSize(g.size_bytes) : '未安装'],
    ['安装状态', g.installed ? (c.neverPlayed ? '已安装 · 从未启动' : '已安装') : '未安装'],
    ['安装目录', g.installdir ? esc(g.installdir) : '—'],
    ['所在库', g.library ? esc(g.library) : '—'],
    ['最近更新', g.last_updated ? dateStr(g.last_updated) : '—'],
    ['AppID', String(g.appid)],
  ];
  if (g.playtime_disconnected_min) boxes.push(['离线游玩', fmtHours(g.playtime_disconnected_min)]);
  // 连上账号后：把「这台电脑」和「整个账号」摆在一起对照
  if (g.playtime_total_min != null) {
    boxes[0] = ['游玩时长（账号）',
      `${fmtHours(g.playtime_total_min)}<div style="${SUB}">这台电脑 ${fmtHours(g.playtime_local_min || 0)}</div>`];
    boxes.push(['最近两周', g.playtime_2weeks_min ? fmtHours(g.playtime_2weeks_min) : '—']);
    if (g.online_only) boxes.push(['备注', '本机没有记录（别的设备上玩的）']);
  }

  const a = g.ach == null ? null : Number(g.ach);
  const t = g.ach_total ? Number(g.ach_total) : 0;
  const achTxt = a == null ? '还没记成就' : `${a}${t ? ' / ' + t : ' 个'}`;

  $('#modalCard').innerHTML = `
    <button class="closeBtn" data-close>✕</button>
    <div class="hero">
      ${imgTag(g.appid, g.name, HERO, 'heroImg')}
      <div class="fade"></div>
      <div class="ttl">
        <h3>${esc(g.name)}</h3>
        <div class="sid">AppID ${g.appid}${g.is_tool ? ' · 非游戏（工具/软件）' : ''}${c.dust ? ' · 🕸 吃灰中' : ''}</div>
      </div>
    </div>

    <div class="quick">
      <span class="q"><b>${fmtHours(g.playtime_min)}</b><i>游玩时长</i></span>
      <span class="q"><b>${g.last_played ? relTime(g.last_played) : '从未'}</b><i>最后运行</i></span>
      <span class="q"><b>🏆 ${achTxt}</b><i>成就</i></span>
      <span class="q"><b>${g.image_count || 0}</b><i>我的图片</i></span>
      <button class="markBtn${(g.done || allAchDone(g)) ? ' on' : ''}" id="qDone"
        title="按一下手动标记 / 取消；成就全部解锁时会自动算「全部游玩」">${markLabel(g)}</button>
    </div>

    <div class="tabs">
      <button class="tab" data-tab="info">📋 游戏基本信息</button>
      <button class="tab" data-tab="ach">🏆 成就情况</button>
      <button class="tab" data-tab="pics">🖼 我的图片</button>
    </div>

    <div class="tabPane" id="paneInfo">
      <div class="kv">${boxes.map(([k, v]) =>
        `<div class="box"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('')}</div>
      <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap" class="link">
        <a class="btn" href="steam://rungameid/${g.appid}" style="text-decoration:none">▶ 启动游戏</a>
        <a class="btn ghost" target="_blank"
           href="https://store.steampowered.com/app/${g.appid}/">商店页面</a>
        ${g.installed ? `<a class="btn ghost" target="_blank"
           href="steam://open/console">Steam 控制台</a>` : ''}
      </div>
    </div>

    <div class="tabPane" id="paneAch" hidden>
      ${achCardHtml(g)}
    </div>

    <div class="tabPane" id="panePics" hidden>
      <div class="pics">
        <div class="picsHead">
          <span class="picsTitle">存在本机 <code>${imgDirOf(g.appid)}</code> <span class="dim" id="picCount"></span></span>
          <label class="btn ghost small">＋ 添加图片
            <input type="file" id="picInput" accept="image/*" multiple hidden>
          </label>
        </div>
        <div class="picsGrid empty" id="picsGrid"><p class="hint small">还没有图片。点「＋ 添加图片」从本机选一张（可以多选），文件会直接拷进这个文件夹，不会上传到任何地方。</p></div>
        <p class="hint small" id="picTip"></p>
      </div>
    </div>`;

  $('#modal').hidden = false;
  $('#modalCard').querySelector('[data-close]').onclick = closeDetail;
  wireQuick(g);
  wireTabs();
  wireAchCard(g);
  wirePicInput(appid);
  loadPics(appid);
  document.addEventListener('keydown', escClose);
  state.openId = appid;
  setHash(detailHash(appid));
  autoAch(appid);        // 打开就自动去读一次成就（没有数据 / 数据过期时）
}

function detailHash(appid) {
  return '#app=' + appid + (state.tab && state.tab !== 'info' ? '&tab=' + state.tab : '');
}

/* 弹窗里那排快捷按钮 + 两个标签页 */
function wireQuick(g) {
  $('#qDone').onclick = async e => {
    const b = e.currentTarget;
    b.disabled = true;
    try {
      await postManual(g.appid, { done: !g.done });
      openDetail(g.appid);            // 就地刷新（含这排数字）
    } catch (err) {
      b.disabled = false;
      alert('标记没保存成功：' + err.message);
    }
  };
}

function wireTabs() {
  const set = name => {
    state.tab = name;
    $('#modalCard').querySelectorAll('.tab').forEach(b =>
      b.classList.toggle('on', b.dataset.tab === name));
    $('#paneInfo').hidden = name !== 'info';
    $('#paneAch').hidden = name !== 'ach';
    $('#panePics').hidden = name !== 'pics';
    if (state.openId) setHash(detailHash(state.openId));
  };
  $('#modalCard').querySelectorAll('.tab').forEach(b => b.onclick = () => set(b.dataset.tab));
  set(state.tab || 'info');
}

/* --------------------- 我的图片（存在本机 web/images/） --------------------- */

/* 单独拼这个路径：反斜杠紧挨着 ${ 会被模板字符串吃掉转义 */
function imgDirOf(appid) {
  return 'web' + String.fromCharCode(92) + 'images' + String.fromCharCode(92) +
         appid + String.fromCharCode(92);
}

async function loadPics(appid) {
  const grid = $('#picsGrid');
  if (!grid) return;
  try {
    const r = await fetch('/api/images?appid=' + appid);
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
    state.pics = state.pics || {};
    state.pics[appid] = j.images || [];
    renderPics(appid, null);
  } catch (e) {
    grid.innerHTML = `<p class="hint small">图片列表没读出来：${esc(e.message)}</p>`;
  }
}

function renderPics(appid, busyText) {
  const grid = $('#picsGrid');
  if (!grid) return;
  const list = (state.pics && state.pics[appid]) || [];
  const cnt = $('#picCount');
  if (cnt) cnt.textContent = list.length ? `(${list.length})` : '';
  const tip = $('#picTip');
  if (tip) {
    tip.textContent = list.length
      ? '图片存在本机 ' + imgDirOf(appid) + ' 里，只有这台电脑能看到；点图片可放大，点 ✕ 删除。'
      : '';
  }
  if (!list.length) {
    grid.classList.add('empty');
    grid.innerHTML = '<p class="hint small">还没有图片。点「＋ 添加图片」从本机选一张（可以多选），文件会直接拷进这个文件夹，不会上传到任何地方。</p>';
  } else {
    grid.classList.remove('empty');
    grid.innerHTML = list.map(it => `
      <figure class="pic">
        <a href="${esc(it.url)}" target="_blank" rel="noreferrer"><img src="${esc(it.url)}" alt="${esc(it.file)}" loading="lazy"></a>
        <button class="picDel" data-del="${esc(it.file)}" title="删除这张">✕</button>
      </figure>`).join('');
    grid.querySelectorAll('[data-del]').forEach(b => {
      b.onclick = async () => {
        if (!confirm('删除这张图片？（只删本机文件，不影响 Steam）')) return;
        b.disabled = true;
        try {
          const r = await fetch('/api/images', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appid, op: 'del', name: b.dataset.del }),
          });
          const j = await r.json();
          if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
          state.pics[appid] = j.images || [];
          renderPics(appid, null);
          syncPicCount(appid);
        } catch (e) {
          b.disabled = false;
          alert('删不掉：' + e.message);
        }
      };
    });
  }
  if (busyText) {
    const t = $('#picTip');
    if (t) t.textContent = busyText;
  }
}

function syncPicCount(appid) {
  const g = state.data.games.find(x => x.appid === appid);
  if (!g) return;
  g.image_count = ((state.pics && state.pics[appid]) || []).length;
  renderGrid();
}

function wirePicInput(appid) {
  const inp = $('#picInput');
  if (!inp) return;
  inp.onchange = async () => {
    const files = Array.from(inp.files || []);
    if (!files.length) return;
    inp.value = '';
    let ok = 0;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const t = $('#picTip');
      if (t) t.textContent = `正在存第 ${i + 1} / ${files.length} 张：${f.name}`;
      try {
        const data = await readAsDataURL(f);
        const r = await fetch('/api/images', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ appid, op: 'add', name: f.name, data }),
        });
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
        state.pics = state.pics || {};
        state.pics[appid] = j.images || [];
        ok++;
      } catch (e) {
        alert(`「${f.name}」没存进去：${e.message}`);
      }
    }
    renderPics(appid, ok ? `存好了 ${ok} 张。` : '');
    syncPicCount(appid);
  };
}

function readAsDataURL(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result));
    fr.onerror = () => rej(new Error('读不到这个文件'));
    fr.readAsDataURL(file);
  });
}

/* ---------------------- 成就 / 我的标记 ---------------------- */

function achCardHtml(g) {
  const a = g.ach == null ? null : Number(g.ach);
  const t = g.ach_total ? Number(g.ach_total) : 0;
  const pct = t ? Math.max(0, Math.min(100, Math.round(a / t * 100))) : 0;
  const sum = (a == null)
    ? '<span class="achSum dim">还没数据</span>'
    : `<span class="achSum"><b>${a}</b>${t ? ' / ' + t : ''}${t ? ` · ${pct}%` : ''}</span>`;
  const srcTip = {
    steam: '数字是从 Steam 官方接口自动读来的',
    '手填': '数字是你自己填的（手填的不会被自动覆盖）',
  }[g.mark_source] || '';

  const configured = !!(state.cfg && state.cfg.configured);
  const st = playStatus(g);
  let stRow;
  if (st) {
    stRow = `<div class="playSt ${st.cls}">
        <span class="lab">游玩情况</span><b>${st.txt}</b>
        <i>按成就完成数自动判定</i></div>`;
  } else if (g.ach_none) {
    stRow = `<div class="playSt none">
        <span class="lab">游玩情况</span><b>这款游戏没有成就系统</b>
        <i>下面可以手动标记「全部游玩」</i></div>`;
  } else if (!configured) {
    stRow = `<div class="playSt none">
        <span class="lab">游玩情况</span><b>还没连 Steam 账号</b>
        <i>连上之后打开这页就会自动读成就</i></div>`;
  } else {
    stRow = `<div class="playSt none">
        <span class="lab">游玩情况</span><b id="achWait">正在从 Steam 读取成就…</b>
        <i>读到就自动填上，不用点任何按钮</i></div>`;
  }

  return `
    <div class="achCard">
      ${stRow}
      <div class="achHead">
        <span class="achTitle">🏆 成就进度</span>
        ${sum}
      </div>
      <div class="achBar"><i style="width:${pct}%"></i></div>
      <div class="achEdit">
        <label class="switch"><input type="checkbox" id="mkDone"${g.done ? ' checked' : ''}>
          <span>全部游玩（手动标记；成就有数据时上面会自动判定）</span></label>
        <div class="achNums">
          <label><span>已完成成就</span><input id="mkAch" type="number" min="0" step="1"
            value="${a == null ? '' : a}" placeholder="比如 24"></label>
          <label><span>成就总数</span><input id="mkTotal" type="number" min="0" step="1"
            value="${t || ''}" placeholder="比如 30"></label>
        </div>
        <div class="acts">
          <button class="btn" id="mkSave">保存标记</button>
          <button class="btn ghost" id="mkClear">清除标记</button>
          ${configured
            ? '<button class="btn ghost" id="mkFetch" title="强制重新问一次 Steam">🔄 重新读取成就</button>' : ''}
        </div>
        <div class="err" id="mkErr" hidden></div>
        <p class="hint small" id="achNote"></p>
        <p class="hint small" id="mkTip">${srcTip || '打开这一页会自动从 Steam 读这款游戏的成就；读不到也可以手动填。只写进本机 manual.json，不动 Steam 的任何东西。'}</p>
      </div>
    </div>`;
}

function achFail(msg) {
  const e = $('#mkErr');
  if (!e) return;
  e.hidden = !msg;
  e.textContent = msg || '';
}

function wireAchCard(g) {
  const appid = g.appid;
  const val = id => {
    const el = $('#' + id);
    return el && el.value.trim() !== '' ? Number(el.value) : '';
  };
  const apply = async (payload, btn) => {
    const old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
    achFail('');
    try {
      await postManual(appid, payload);
      openDetail(appid);                      // 就地刷新这张卡
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = old; }
      achFail(e.message);
    }
  };
  $('#mkSave').onclick = e => apply({
    done: $('#mkDone').checked, ach: val('mkAch'), ach_total: val('mkTotal'), source: '手填',
  }, e.target).catch(() => {});
  $('#mkClear').onclick = e => {
    $('#mkDone').checked = false;
    apply({ clear: true }, e.target).catch(() => {});
  };
  const f = $('#mkFetch');
  if (f) {
    f.onclick = async () => {
      f.disabled = true; f.textContent = '正在读取…'; achFail(''); achNote('');
      try {
        await fetchAch(appid, true);
        await postManual(appid, {});
        openDetail(appid);
      } catch (e) {
        f.disabled = false; f.textContent = '🔄 重新读取成就';
        achFail(e.message);
      }
    };
  }
}

/* --------------------------- 自动读成就 --------------------------- */

function achNote(msg) {
  const n = $('#achNote');
  if (!n) return;
  n.textContent = msg || '';
  n.hidden = !msg;
}

/* 是不是该去问一次 Steam：没数据要问；steam 来的且过了 6 小时要问；
   自己手填的、Steam 说没有成就系统的，都不碰。 */
function needAchFetch(g) {
  if (!(state.cfg && state.cfg.configured)) return false;
  if (!g || g.ach_none) return false;
  if (g.ach_total) {
    if (g.mark_source !== 'steam') return false;
    const at = Number(g.ach_at || 0);
    return !at || (Date.now() / 1000 - at) > 6 * 3600;
  }
  return true;
}

async function fetchAch(appid, force) {
  const r = await fetch('/api/achievements?appid=' + appid + (force ? '&force=1' : ''));
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

async function autoAch(appid) {
  const g = state.data.games.find(x => x.appid === appid);
  if (!g || !needAchFetch(g)) return;
  state.achBusy = state.achBusy || {};
  if (state.achBusy[appid]) return;
  state.achBusy[appid] = true;
  if (state.openId === appid) achNote('正在从 Steam 读取成就…');
  try {
    const j = await fetchAch(appid, false);
    await postManual(appid, {});              // 把刚读到的写回 state 并重画
    if (state.openId === appid) {
      openDetail(appid);
      achNote(j.none ? '这款游戏在 Steam 那边没有成就系统。'
        : (j.cached ? '成就是刚刚从 Steam 读来的（6 小时内不会重复问）。'
                    : '已从 Steam 读到成就。'));
    }
  } catch (e) {
    if (state.openId === appid) {
      achNote('自动读取失败：' + e.message + '（可以点「🔄 重新读取成就」重试）');
    }
  } finally {
    state.achBusy[appid] = false;
  }
}

async function postManual(appid, payload) {
  const r = await fetch('/api/manual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ appid }, payload)),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
  const g = state.data.games.find(x => x.appid === appid);
  if (g) {
    const m = j.manual;
    g.done = !!(m && m.done);
    g.ach = m && m.ach != null ? m.ach : null;
    g.ach_total = m && m.ach_total != null ? m.ach_total : null;
    g.mark_source = (m && m.source) || '';
    g.ach_none = !!(m && m.noach);
    g.ach_at = (m && m.at != null) ? m.at : null;
  }
  if (j.summary) state.data.manual = j.summary;
  renderStats(); renderFilters(); renderGrid();
  return j;
}
function closeDetail() {
  $('#modal').hidden = true;
  document.removeEventListener('keydown', escClose);
  setHash('');
}
function escClose(e) { if (e.key === 'Escape') closeDetail(); }

/* --------------------------- 连接 Steam 账号 --------------------------- */

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    if (r.ok) state.cfg = await r.json();
  } catch (e) { /* 拿不到就按未配置显示 */ }
}

function openCfg() {
  const cfg = state.cfg || {};
  const acct = state.data && state.data.account;
  $('#cfgKey').value = '';
  $('#cfgKey').placeholder = cfg.key_set ? `已保存 ${cfg.key_hint}（留空就不改动）` : '32 位十六进制字符串';
  $('#cfgSid').value = cfg.steamid || (acct && acct.steamid64) || '';
  $('#cfgOn').checked = !!cfg.online;
  $('#cfgErr').hidden = true;
  $('#cfgNow').innerHTML = cfg.key_set
    ? `当前：Key ${esc(cfg.key_hint)} · SteamID ${esc(cfg.steamid || '（没填）')}`
    : '尚未配置。不连也能用，只是数字只反映这台电脑。';
  $('#cfgModal').hidden = false;
  document.addEventListener('keydown', escCfg);
}
function closeCfg() {
  $('#cfgModal').hidden = true;
  document.removeEventListener('keydown', escCfg);
}
function escCfg(e) { if (e.key === 'Escape') closeCfg(); }

async function saveCfg(payload, test) {
  const err = $('#cfgErr');
  err.hidden = true;
  const btn = $('#cfgSave');
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '连接中…';
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const out = await r.json();
    if (!r.ok || !out.ok) throw new Error(out.error || ('HTTP ' + r.status));
    state.cfg = out;
    closeCfg();
    await load({ force: true, online: !!test });
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}


/* 地址栏深链：#app=<id> 可直接打开某款游戏的详情（#app=<id>&tab=ach 直接落在成就页），也方便收藏/分享 */
function setHash(h) {
  const base = location.pathname + location.search;
  const want = h ? base + h : base;
  if (location.href !== want) history.replaceState(null, '', want);
}
function openFromHash() {
  if (location.hash === '#cfg') { openCfg(); return; }
  const m = /^#app=(\d+)(?:[&?]tab=(\w+))?$/.exec(location.hash);
  if (!m) return;
  if (m[2] === 'info' || m[2] === 'ach' || m[2] === 'pics') state.tab = m[2];
  openDetail(Number(m[1]));
}

/* ---------------------- 打不开时的说明页 ---------------------- */

/* 直接双击 index.html（file:// 协议）时，浏览器读不到 Steam 存档，
   页面也不该是一张白纸 —— 直接把「正确打开方式」摆在正中间。 */
function showFatal(title, rows) {
  const f = $('#fatal');
  f.hidden = false;
  f.innerHTML = '<h2>' + title + '</h2><ul class="fsteps">' +
    rows.map(r => '<li>' + r + '</li>').join('') + '</ul>';
  for (const el of document.querySelectorAll('main > *')) {
    /* 用内联 display 而不是 hidden：.stats / .panel 有作者样式 display，会盖掉 hidden 属性 */
    if (el !== f) el.style.display = 'none';
  }
  window.scrollTo(0, 0);
}

/* --------------------------- 数据加载 --------------------------- */

async function load(opts) {
  const o = (typeof opts === 'object' && opts) || {};
  const btn = $('#refreshBtn');
  btn.disabled = true;
  btn.textContent = o.enrich ? '联网补名中…' : '扫描中…';
  try {
    const qs = new URLSearchParams();
    if (o.force) qs.set('force', '1');
    if (o.enrich) qs.set('enrich', '1');
    if (o.online) qs.set('online', '1');
    if (state.account && state.accountTouched) qs.set('account', state.account);
    const r = await fetch('/api/data' + (qs.toString() ? '?' + qs : ''));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    state.data = await r.json();
    renderAll();
    openFromHash();
  } catch (e) {
    $('#scanInfo').textContent = '读取失败：' + e.message;
    showFatal('连不上本地服务', [
      '页面是从 <code>' + location.origin + '</code> 打开的，但读数据失败了：<code>' + e.message + '</code>',
      '服务多半已经关掉了 —— 回到 <code>steam-play</code> 文件夹，<strong>双击 run.bat</strong> 重新起一个。',
      '如果 run.bat 的黑窗口还开着，看它打印的地址，端口不一定是 8770。',
      '弄好之后 → <a href="./">刷新重试</a>',
    ]);
  } finally {
    btn.disabled = false;
    btn.textContent = '重新扫描';
  }
}

function bind() {
  $('#refreshBtn').onclick = () => load({ force: true });
  $('#onlineBtn').onclick = openCfg;
  $('#cfgSave').onclick = () => {
    const body = { online: $('#cfgOn').checked, steamid: $('#cfgSid').value.trim() };
    const k = $('#cfgKey').value.trim();
    if (k) body.api_key = k;
    saveCfg(body, true);
  };
  $('#cfgClear').onclick = () => saveCfg({ api_key: '', steamid: '', online: false }, false);
  $('#accountSel').onchange = e => {
    state.account = e.target.value;
    state.accountTouched = true;
    load({ force: true });
  };
  $('#showTools').onchange = e => { state.showTools = e.target.checked; renderAll(); };
  $('#sortSel').onchange = e => { state.sort = e.target.value; renderGrid(); };
  let t = null;
  $('#search').oninput = e => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = e.target.value; renderGrid(); }, 120);
  };
  document.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) closeDetail();
    if (e.target.closest('[data-cfg-close]')) closeCfg();
  });
  window.addEventListener('hashchange', openFromHash);
}

bind();

if (location.protocol === 'file:') {
  /* 双击打开的情况：别再发 fetch，直接告诉用户该怎么开 */
  $('#scanInfo').textContent = '没有连上本地服务';
  showFatal('这个页面不能直接双击打开', [
    '页面本身不含数据 —— 游玩记录是由一个本地小服务从你 Steam 的存档文件里读出来、再喂给页面的。浏览器直接打开文件读不到那些文件，所以这里只会是一片空白。',
    '正确的打开方式：回到 <code>steam-play</code> 文件夹，<strong>双击 run.bat</strong>（会弹出一个黑窗口，别关它），浏览器会自动打开页面。',
    '以后固定用这个地址访问：<a href="http://127.0.0.1:8770/">http://127.0.0.1:8770/</a>',
    '想把它加进收藏夹、或者发到手机上看（同一台机器），都用这个地址。',
  ]);
} else {
  loadConfig().then(() => load({}));
}

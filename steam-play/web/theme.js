'use strict';

/* ------------------------------------------------------------------ *
 *  外观：配色方案 + 自定义背景色
 *
 *  设计取舍：
 *  1. 只做「换颜色」，不做「换布局」—— 颜色是偏好，布局是功能，混在一起改坏了分不清是谁的锅。
 *  2. 所有颜色最终都落到 CSS 变量上，所以这份 JS 不需要知道任何选择器，
 *     以后 CSS 怎么改都不影响这里。
 *  3. 深色底配浅字、浅色底配深字。用户手动挑了一个很浅的底色却没换字色，
 *     整页会糊成一片 —— 所以自动判定明暗，但也允许手动覆盖。
 * ------------------------------------------------------------------ */

const THEME_KEY = 'sp.theme.v1';

/* 预设：每套只给 5 个关键色，其余由 buildTokens() 推导，避免手写几十个色值还配不平 */
const PRESETS = [
  {
    id: 'ink', name: '墨黑',
    bg: '#0e1013', surface: '#171a1f', surface2: '#1e2228', surface3: '#262b32',
    accent: '#4ade80', accentDeep: '#22c55e', glow: 'rgba(74,222,128,.05)', glow2: 'rgba(74,159,255,.035)',
  },
  {
    id: 'midnight', name: '午夜蓝',
    bg: '#0b1020', surface: '#141b2e', surface2: '#1b2439', surface3: '#232e47',
    accent: '#60a5fa', accentDeep: '#3b82f6', glow: 'rgba(96,165,250,.07)', glow2: 'rgba(139,92,246,.04)',
  },
  {
    id: 'forest', name: '深林',
    bg: '#0c1210', surface: '#141c19', surface2: '#1b2521', surface3: '#23302a',
    accent: '#5eead4', accentDeep: '#14b8a6', glow: 'rgba(94,234,212,.05)', glow2: 'rgba(74,222,128,.03)',
  },
  {
    id: 'plum', name: '暗紫',
    bg: '#110e16', surface: '#1a1621', surface2: '#221d2b', surface3: '#2b2436',
    accent: '#c084fc', accentDeep: '#a855f7', glow: 'rgba(192,132,252,.06)', glow2: 'rgba(244,114,182,.03)',
  },
  {
    id: 'amber', name: '暖褐',
    bg: '#14110d', surface: '#1d1915', surface2: '#26211b', surface3: '#302a22',
    accent: '#fbbf24', accentDeep: '#f59e0b', glow: 'rgba(251,191,36,.05)', glow2: 'rgba(249,115,22,.03)',
  },
  {
    id: 'slate', name: '石板',
    bg: '#0f1316', surface: '#181d21', surface2: '#1f252a', surface3: '#272e34',
    accent: '#38bdf8', accentDeep: '#0ea5e9', glow: 'rgba(56,189,248,.05)', glow2: 'rgba(148,163,184,.03)',
  },
  {
    id: 'paper', name: '纸白',
    bg: '#f4f5f7', surface: '#ffffff', surface2: '#f8f9fb', surface3: '#eef0f3',
    accent: '#16a34a', accentDeep: '#15803d', glow: 'rgba(22,163,74,.04)', glow2: 'rgba(59,130,246,.03)',
  },
];

/* 当前生效的配色（默认 = 第一套） */
let theme = loadTheme();

/* ---------------- 颜色工具（不依赖任何库） ---------------- */

function clamp255(n) { return Math.max(0, Math.min(255, Math.round(n))); }

function parseHex(h) {
  if (typeof h !== 'string') return null;
  let s = h.trim().replace(/^#/, '');
  if (/^[0-9a-fA-F]{3}$/.test(s)) s = s.split('').map(c => c + c).join('');
  if (!/^[0-9a-fA-F]{6}$/.test(s)) return null;
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

function toHex(rgb) {
  return '#' + rgb.map(v => clamp255(v).toString(16).padStart(2, '0')).join('');
}

/* 往目标色靠 %：amount=0 原样，1 全变目标 */
function mix(hexA, hexB, amount) {
  const a = parseHex(hexA), b = parseHex(hexB);
  if (!a || !b) return hexA;
  return toHex(a.map((v, i) => v + (b[i] - v) * amount));
}
function lighten(h, n) { return mix(h, '#ffffff', n); }
function darken(h, n) { return mix(h, '#000000', n); }

/* 感知亮度（0~1）。用它判断「该配浅字还是深字」 */
function luminance(hex) {
  const c = parseHex(hex);
  if (!c) return 0;
  const f = v => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}

/* 半透明颜色：给光晕和强调色底用 */
function alpha(hex, a) {
  const c = parseHex(hex);
  return c ? `rgba(${c[0]},${c[1]},${c[2]},${a})` : hex;
}

/* ---------------- 由少量输入推导出整套变量 ---------------- */

/* 深色模式：底色越浅，文字越亮；浅色模式反过来。
   中间几档过渡色一律用 mix 现算，保证无论用户挑什么底，文字都不会糊在一起。 */
function buildTokens(t) {
  const isLight = t.mode === 'light';
  const bg = t.bg, surface = t.surface;

  /* 二级、三级底色：如果预设里给了就用预设的，自定义底色时按深浅自动推 */
  const surface2 = t.surface2 || (isLight ? darken(surface, 0.025) : lighten(surface, 0.026));
  const surface3 = t.surface3 || (isLight ? darken(surface, 0.055) : lighten(surface, 0.055));

  const line = isLight ? darken(bg, 0.10) : lighten(bg, 0.12);
  const lineSoft = isLight ? darken(bg, 0.055) : lighten(bg, 0.055);
  const lineStrong = isLight ? darken(bg, 0.20) : lighten(bg, 0.22);

  /* 文字四档：主文字跟底色反着来 */
  const base = isLight ? '#111418' : '#e8eaed';
  const txt = base;
  const txt2 = isLight ? mix(base, bg, 0.30) : mix(base, bg, 0.32);
  const txt3 = isLight ? mix(base, bg, 0.52) : mix(base, bg, 0.56);
  const txt4 = isLight ? mix(base, bg, 0.68) : mix(base, bg, 0.72);

  /* 强调色会消耗按钮上的文字色：主色够亮就用深字，够深就用白字 */
  const onAccent = luminance(t.accentDeep) > 0.45 ? '#06210f' : '#ffffff';

  return {
    '--bg': bg,
    '--surface': surface,
    '--surface2': surface2,
    '--surface3': surface3,
    '--line': line,
    '--lineSoft': lineSoft,
    '--lineStrong': lineStrong,
    '--txt': txt,
    '--txt2': txt2,
    '--txt3': txt3,
    '--txt4': txt4,
    '--accent': t.accent,
    '--accentDeep': t.accentDeep,
    '--accentSoft': alpha(t.accent, isLight ? 0.14 : 0.10),
    '--accentGlow': alpha(t.accent, 0.18),
    '--onAccent': onAccent,
    '--warn': isLight ? '#b45309' : '#f5a524',
    '--warnSoft': isLight ? 'rgba(180,83,9,.08)' : 'rgba(245,165,36,.10)',
    '--danger': isLight ? '#dc2626' : '#f05252',
    '--dangerSoft': isLight ? 'rgba(220,38,38,.08)' : 'rgba(240,82,82,.10)',
    /* 页面顶部两团光晕：浅色模式下要更淡，否则像脏了 */
    '--glow1': t.glow || alpha(t.accent, isLight ? 0.05 : 0.05),
    '--glow2': t.glow2 || 'transparent',
    /* 占位色块：深色底上用暗底亮字，浅色底上用亮底暗字 */
    '--phL': isLight ? '82%' : '20%',
    '--phL2': isLight ? '72%' : '15%',
    '--phTextL': isLight ? '28%' : '72%',
    /* 顶栏底色：必须跟着主题走，否则浅色主题下顶栏还是黑的（吸顶时特别明显） */
    '--topbarBg': isLight ? 'rgba(255,255,255,.86)' : alpha(bg, 0.82),
    /* 弹层背后那层遮罩：浅色主题下用浅灰压暗，纯黑会像关机 */
    '--scrim': isLight ? 'rgba(17,20,24,.38)' : 'rgba(6,8,10,.72)',
  };
}

function applyTheme(t) {
  const root = document.documentElement;
  const tokens = buildTokens(t);
  for (const k in tokens) root.style.setProperty(k, tokens[k]);
  /* 给浏览器自己和滚动条一个明暗提示 */
  root.style.colorScheme = t.mode === 'light' ? 'light' : 'dark';
  root.dataset.themeLight = t.mode === 'light' ? '1' : '';
}

/* ---------------- 存取 ---------------- */

function loadTheme() {
  const base = { ...PRESETS[0], mode: 'auto', customBg: false, forceMode: false, preset: PRESETS[0].id };
  try {
    const raw = localStorage.getItem(THEME_KEY);
    if (!raw) return resolveMode(base);
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return resolveMode(base);
    const merged = { ...base, ...saved };
    /* 存了非法色值就当没存，别让一个坏字符串把整页搞黑 */
    for (const k of ['bg', 'surface', 'surface2', 'surface3', 'accent', 'accentDeep']) {
      if (merged[k] && !parseHex(merged[k])) merged[k] = base[k];
    }
    return resolveMode(merged);
  } catch (e) {
    return resolveMode(base);
  }
}

function saveTheme() {
  try {
    const { id, name, glow, glow2, ...rest } = theme;
    localStorage.setItem(THEME_KEY, JSON.stringify(rest));
  } catch (e) { /* 隐私模式可能禁用 localStorage，忽略即可，页面照常能用 */ }
}

/* auto 模式：底色浅就配深字，深就配浅字 */
function resolveMode(t) {
  if (t.mode !== 'auto') return t;
  return { ...t, mode: luminance(t.bg) > 0.5 ? 'light' : 'dark' };
}

/* ---------------- 预设切换 ---------------- */

function applyPreset(id) {
  const p = PRESETS.find(x => x.id === id) || PRESETS[0];
  /* 用户手动改过底色的话，切预设不该把它冲掉 —— 只换强调色和卡片色 */
  if (theme.customBg) {
    theme = resolveMode({ ...theme, preset: p.id, name: p.name, accent: p.accent, accentDeep: p.accentDeep,
      surface: p.surface, surface2: p.surface2, surface3: p.surface3, glow: p.glow, glow2: p.glow2 });
  } else {
    theme = resolveMode({ ...theme, ...p, preset: p.id, mode: theme.forceMode ? theme.mode : 'auto' });
  }
  renderThemeUi();
  applyTheme(theme);
  saveTheme();
}

function setBg(hex, which) {
  if (!parseHex(hex)) return false;
  theme.customBg = true;
  theme.forceMode = false;
  if (which === 'surface') { theme.surface = hex; theme.surface2 = null; theme.surface3 = null; }
  else { theme.bg = hex; }
  theme.mode = 'auto';
  theme = resolveMode(theme);
  applyTheme(theme);
  renderThemeUi();
  saveTheme();
  return true;
}

function setAccent(hex) {
  if (!parseHex(hex)) return false;
  theme.accent = hex;
  /* 深一档按底色明暗反着推：浅色底需要更深才压得住 */
  theme.accentDeep = theme.mode === 'light' ? darken(hex, 0.18) : lighten(hex, 0.12);
  applyTheme(theme);
  renderThemeUi();
  saveTheme();
  return true;
}

function resetTheme() {
  theme = resolveMode({ ...PRESETS[0], mode: 'auto', customBg: false, forceMode: false, preset: PRESETS[0].id });
  applyTheme(theme);
  renderThemeUi();
  saveTheme();
}

/* ---------------- 界面渲染 ---------------- */

function renderThemeUi() {
  const box = document.getElementById('themePresets');
  if (box) {
    box.innerHTML = PRESETS.map(p => `
      <button type="button" class="preset${theme.preset === p.id && !theme.customBg ? ' on' : ''}" data-preset="${p.id}">
        <span class="swatches">
          <i style="background:${p.bg}"></i>
          <i style="background:${p.surface}"></i>
          <i style="background:${p.accent}"></i>
        </span>
        <span class="pname">${p.name}</span>
      </button>`).join('');
    box.querySelectorAll('.preset').forEach(n => {
      n.onclick = () => applyPreset(n.dataset.preset);
    });
  }

  const custom = document.getElementById('themeCustomBg');
  if (custom) custom.checked = !!theme.customBg;

  const bgRows = document.getElementById('themeBgRows');
  if (bgRows) bgRows.style.display = theme.customBg ? '' : 'none';

  const bind = (colorId, hexId, val, which) => {
    const c = document.getElementById(colorId);
    const h = document.getElementById(hexId);
    if (c && c.value !== val) c.value = val;
    if (h && h.value !== val) h.value = val;
  };
  bind('themeBg', 'themeBgHex', theme.bg, 'bg');
  bind('themeSurface', 'themeSurfaceHex', theme.surface, 'surface');

  const accNow = document.getElementById('themeAccentNow');
  if (accNow) accNow.textContent = theme.accent + ' / ' + theme.accentDeep;

  const force = document.getElementById('themeForceText');
  if (force) force.checked = !!theme.forceMode;
  const modeSel = document.getElementById('themeModeSel');
  if (modeSel) {
    modeSel.disabled = !theme.forceMode;
    modeSel.value = theme.mode;
  }
  const now = document.getElementById('themeModeNow');
  if (now) {
    const auto = luminance(theme.bg) > 0.5 ? '浅色' : '深色';
    now.textContent = theme.forceMode ? '手动：' + (theme.mode === 'light' ? '深字' : '浅字')
                                     : '自动识别为' + auto + '底，已配' + (auto === '浅色' ? '深字' : '浅字');
  }

  const prev = document.getElementById('themePrev');
  if (prev) {
    prev.innerHTML = `
      <div class="pvBar"><span class="pvDot"></span><b>Steam 游玩报告</b><span class="pvBtn">按钮</span></div>
      <div class="pvRow">
        <span class="pvCard"><i class="pvK">收录游戏</i><i class="pvV">106</i></span>
        <span class="pvCard"><i class="pvK">累计游玩</i><i class="pvV">2002</i></span>
      </div>
      <div class="pvBar2"><i style="width:62%"></i></div>`;
  }
}

/* ---------------- 弹层 ---------------- */

function openTheme() {
  renderThemeUi();
  const m = document.getElementById('themeModal');
  if (!m) return;
  m.hidden = false;
  document.addEventListener('keydown', escTheme);
}
function closeTheme() {
  const m = document.getElementById('themeModal');
  if (m) m.hidden = true;
  document.removeEventListener('keydown', escTheme);
}
function escTheme(e) { if (e.key === 'Escape') closeTheme(); }

/* ---------------- 绑定 ---------------- */

function bindTheme() {
  const btn = document.getElementById('themeBtn');
  if (btn) btn.onclick = openTheme;

  document.addEventListener('click', e => {
    if (e.target.closest('[data-theme-close]')) closeTheme();
  });

  /* 绑定颜色对：取色器与十六进制输入框互相同步 */
  const pair = (colorId, hexId, which) => {
    const c = document.getElementById(colorId);
    const h = document.getElementById(hexId);
    if (c) c.oninput = () => { setBg(c.value, which); h.value = c.value; };
    if (h) {
      /* 输入过程中不打扰：只有填满 7 位才生效 */
      h.oninput = () => {
        const v = h.value.trim();
        if (/^#?[0-9a-fA-F]{6}$/.test(v)) {
          const hex = v.startsWith('#') ? v : '#' + v;
          if (setBg(hex, which)) { c.value = hex; h.value = hex; }
        }
      };
      /* 失焦时收口：合法就写回规范值，非法就退回当前值 */
      h.onblur = () => {
        const v = h.value.trim().replace(/^#/, '');
        if (!/^[0-9a-fA-F]{6}$/.test(v)) h.value = which === 'surface' ? theme.surface : theme.bg;
        else h.value = '#' + v.toLowerCase();
      };
    }
  };
  pair('themeBg', 'themeBgHex', 'bg');
  pair('themeSurface', 'themeSurfaceHex', 'surface');

  const accBtn = document.getElementById('themeAccentBtn');
  if (accBtn) accBtn.onclick = () => {
    /* 用一个临时的 <input type=color>，点完即弃，不往页面里塞长期存在的元素 */
    const inp = document.createElement('input');
    inp.type = 'color';
    inp.value = theme.accent;
    inp.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(inp);
    inp.addEventListener('change', () => { setAccent(inp.value); inp.remove(); });
    inp.click();
    setTimeout(() => { if (inp.parentNode) inp.remove(); }, 60000);
  };

  const custom = document.getElementById('themeCustomBg');
  if (custom) custom.onchange = () => {
    theme.customBg = custom.checked;
    if (!custom.checked) {
      /* 关掉自定义时，回到当前预设的底色，别留一半自定义一半预设的怪状态 */
      const p = PRESETS.find(x => x.id === theme.preset) || PRESETS[0];
      theme = resolveMode({ ...theme, bg: p.bg, surface: p.surface, surface2: p.surface2,
        surface3: p.surface3, glow: p.glow, glow2: p.glow2, customBg: false, mode: 'auto' });
      applyTheme(theme);
    }
    renderThemeUi();
    saveTheme();
  };

  const force = document.getElementById('themeForceText');
  if (force) force.onchange = () => {
    theme.forceMode = force.checked;
    if (!theme.forceMode) theme = resolveMode({ ...theme, mode: 'auto' });
    else theme.mode = luminance(theme.bg) > 0.5 ? 'light' : 'dark';
    applyTheme(theme);
    renderThemeUi();
    saveTheme();
  };

  const modeSel = document.getElementById('themeModeSel');
  if (modeSel) modeSel.onchange = () => {
    theme.mode = modeSel.value;
    theme.forceMode = true;
    applyTheme(theme);
    renderThemeUi();
    saveTheme();
  };

  const rst = document.getElementById('themeReset');
  if (rst) rst.onclick = resetTheme;
  const done = document.getElementById('themeDone');
  if (done) done.onclick = closeTheme;
}

/* 立刻生效，别等 DOMContentLoaded —— 否则会先闪一下默认色 */
applyTheme(theme);
bindTheme();

/* 地址栏深链：#theme 打开外观面板，#theme=<预设id> 顺便套用该预设。
   和 app.js 的 #app=<id> 一样，方便收藏某个配色。
   注意：套用后会写进 localStorage —— 不然刷新一下就退回旧配色，很反直觉。 */
function themeFromHash() {
  const h = location.hash || '';
  if (!h.startsWith('#theme')) return false;
  const m = /^#theme=([a-z0-9-]+)$/.exec(h);
  if (m) {
    const hit = PRESETS.find(p => p.id === m[1]);
    if (hit) { theme.customBg = false; applyPreset(hit.id); }
  }
  openTheme();
  return true;
}
themeFromHash();
window.addEventListener('hashchange', () => { themeFromHash(); });

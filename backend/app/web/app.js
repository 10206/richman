'use strict';

/* ============================ 상수 (APIModels 계약과 1:1) ============================ */
const SIGNAL = {
  hold: { label: '보유', cls: 'hold', ico: '▲' },
  cash: { label: '현금보유', cls: 'cash', ico: '■' },
  keep: { label: '유지', cls: 'keep', ico: '▶' },
};
const STANCE = { LONG: '보유 포지션', CASH: '현금 대기' };
const REGIME = {
  G: { label: '이상적 성장 국면', cls: 'G', ico: '☀️', detail: '위험선호 + 금리 하락. 성장주에 가장 유리한 조합.' },
  R: { label: '경기 과열 국면', cls: 'R', ico: '🔥', detail: '위험선호 + 금리 상승. 경기 재팽창, 실물·가치주 우위.' },
  T: { label: '긴축 스트레스 국면', cls: 'T', ico: '⚠️', detail: '위험회피 + 금리 상승. 긴축 충격, 대부분 자산에 역풍.' },
  F: { label: '위험회피(안전자산) 국면', cls: 'F', ico: '🛡️', detail: '위험회피 + 금리 하락. 안전자산(국채·금) 도피 수요.' },
};
const SECTOR = {
  semiconductor: { label: '반도체', ico: '💻' },
  robotics: { label: '로봇', ico: '🤖' },
  power: { label: '전력', ico: '⚡' },
  healthcare: { label: '헬스케어', ico: '🩺' },
  gold: { label: '금', ico: '🪙' },
  bonds: { label: '국채', ico: '🏛️' },
};
const MARKET = { KR: '한국', US: '미국' };

/* ============================ 설정 (localStorage) ============================ */
const Settings = {
  get apiKey() { return localStorage.getItem('apiKey') || ''; },
  set apiKey(v) { localStorage.setItem('apiKey', v); },
  get baseURL() { return localStorage.getItem('baseURL') || ''; },  // 비우면 동일 출처
  set baseURL(v) { localStorage.setItem('baseURL', v.replace(/\/+$/, '')); },
  get lastSync() { return Number(localStorage.getItem('lastSync') || 0); },
  set lastSync(v) { localStorage.setItem('lastSync', String(v)); },
};

/* ============================ API 클라이언트 ============================ */
async function api(path, opts = {}) {
  const base = Settings.baseURL; // '' → 동일 출처
  const url = base + '/api/v1' + path;
  const headers = Object.assign({}, opts.headers);
  if (Settings.apiKey) headers['X-API-Key'] = Settings.apiKey;
  if (opts.body) headers['Content-Type'] = 'application/json';
  const res = await fetch(url, { ...opts, headers });
  if (!res.ok) {
    let detail = 'HTTP ' + res.status;
    try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (e) {}
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return res.json();
}
const API = {
  health: () => fetch((Settings.baseURL || '') + '/health').then((r) => r.json()),
  dashboard: () => api('/dashboard'),
  detail: (m, s) => api(`/sectors/${m}/${s}/detail`),
  history: (m, s, days = 180) => api(`/sectors/${m}/${s}/history?days=${days}`),
  calendar: (month) => api('/calendar' + (month ? `?month=${month}` : '')),
  vapidKey: () => api('/push/vapid-public-key'),
  subscribe: (sub) => api('/push/subscribe', { method: 'POST', body: JSON.stringify(sub) }),
  unsubscribe: (endpoint) => api('/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint }) }),
  testPush: () => api('/push/test', { method: 'POST', body: '{}' }),
};

/* ============================ 포맷 헬퍼 ============================ */
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fnum = (v, d = 0) => (v == null || isNaN(v) ? '—' : Number(v).toFixed(d));
const localTrendLabel = (raw) => {
  const k = String(raw || '').toLowerCase();
  if (['bull', 'bullish', 'up', 'strong', '강세'].includes(k)) return '강세';
  if (['bear', 'bearish', 'down', 'weak', '약세'].includes(k)) return '약세';
  if (['neutral', 'flat', '중립'].includes(k)) return '중립';
  return raw || '—';
};
function deltaHTML(d) {
  if (d == null) return '<span class="delta flat">—</span>';
  const cls = d > 0.05 ? 'up' : d < -0.05 ? 'down' : 'flat';
  const arw = d > 0.05 ? '↑' : d < -0.05 ? '↓' : '·';
  return `<span class="delta ${cls}">${arw} ${d > 0 ? '+' : ''}${d.toFixed(1)}</span>`;
}
function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const WD = ['일', '월', '화', '수', '목', '금', '토'];
function dayWeekday(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const wd = new Date(y, m - 1, d).getDay();
  return { day: String(d), wd: WD[wd], wdIdx: wd };
}

/* ============================ 컴포넌트 렌더러 ============================ */
function signalIcon(sig) {
  const s = SIGNAL[sig] || SIGNAL.keep;
  return `<div class="sig-ico sig-${s.cls} bg-${s.cls}">${s.ico}</div>`;
}
function signalBadge(sig) {
  const s = SIGNAL[sig] || SIGNAL.keep;
  return `<span class="sig-badge sig-${s.cls} bg-${s.cls}">${s.ico} ${s.label}</span>`;
}
function componentBars(sc) {
  const rows = [
    { label: '추세', w: sc.w_trend, v: sc.trend, c: 'c-blue' },
    { label: '거래량', w: sc.w_volume, v: sc.volume, c: 'c-teal' },
    { label: '거시', w: sc.w_macro, v: sc.macro, c: 'c-purple' },
  ];
  const maxW = Math.max(...rows.map((r) => r.w || 0), 0.01);
  return `<div class="bars">${rows.map((r) => {
    const trackPct = ((r.w || 0) / maxW) * 100;
    const fillPct = (r.v || 0) * 100;
    const contrib = (r.w || 0) * (r.v || 0) * 100;
    return `<div class="bar-row">
      <span class="bar-label">${r.label}</span>
      <span class="bar-track-wrap"><span class="bar-track" style="width:${trackPct}%">
        <span class="bar-fill ${r.c}" style="width:${fillPct}%"></span></span></span>
      <span class="bar-val mono">${contrib.toFixed(0)}점</span>
    </div>`;
  }).join('')}</div>`;
}
function biasLabel(bias) {
  const map = {
    2: ['↑', '강한 강세 방향', 'sig-hold'], 1: ['↗', '강세 방향', 'sig-hold'],
    0: ['→', '중립 방향', 'muted'], '-1': ['↘', '약세 방향', 'sig-cash'], '-2': ['↓', '강한 약세 방향', 'sig-cash'],
  };
  const [a, t, c] = map[bias] || map[0];
  return `<span class="${c}" style="font-weight:700">${a} ${t}</span>`;
}
function rationale(text) {
  return `<div class="rationale"><div class="stripe"></div><p>${esc(text)}</p></div>`;
}

/* 점수 근거 요약 (ScoreExplainer 간이 이식) */
function explainOverall(sc, regimeBias) {
  const parts = [`총점 ${sc.score.toFixed(0)}점으로 신호는 '${(SIGNAL[sc.signal] || {}).label || sc.signal}'.`];
  const comp = [
    ['추세', sc.w_trend * sc.trend * 100],
    ['거래량', sc.w_volume * sc.volume * 100],
    ['거시', sc.w_macro * sc.macro * 100],
  ].sort((a, b) => b[1] - a[1]);
  parts.push(`${comp[0][0]}(${comp[0][1].toFixed(0)}점)가 가장 크게 기여했고, ${comp[2][0]}(${comp[2][1].toFixed(0)}점)가 가장 작습니다.`);
  if (sc.score_delta_1d != null) {
    const d = sc.score_delta_1d;
    parts.push(d > 0.05 ? `어제보다 ${d.toFixed(1)}점 올랐습니다.` : d < -0.05 ? `어제보다 ${Math.abs(d).toFixed(1)}점 내렸습니다.` : '어제와 큰 변화 없습니다.');
  }
  return parts.join(' ');
}

/* ============================ SVG 라인 차트 ============================ */
function lineChart(items, w = 320, h = 200) {
  if (!items.length) return '<div class="center tiny">히스토리 없음</div>';
  const padL = 26, padR = 8, padT = 10, padB = 18;
  const iw = w - padL - padR, ih = h - padT - padB;
  const n = items.length;
  const x = (i) => padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => padT + (1 - v / 100) * ih;
  const pts = items.map((it, i) => `${x(i).toFixed(1)},${y(it.score).toFixed(1)}`).join(' ');
  // 신호 전환 지점 마커
  const markers = [];
  for (let i = 1; i < n; i++) {
    if (items[i].signal !== items[i - 1].signal) {
      const s = SIGNAL[items[i].signal] || SIGNAL.keep;
      markers.push(`<circle cx="${x(i).toFixed(1)}" cy="${y(items[i].score).toFixed(1)}" r="4"
        fill="var(--${s.cls})" stroke="var(--card)" stroke-width="1.5"/>`);
    }
  }
  const gridY = [0, 25, 50, 75, 100].map((v) =>
    `<line x1="${padL}" y1="${y(v)}" x2="${w - padR}" y2="${y(v)}" stroke="var(--sep)" stroke-width="0.5"/>
     <text x="2" y="${(y(v) + 3).toFixed(1)}" fill="var(--text-3)" font-size="9">${v}</text>`).join('');
  const first = items[0].date.slice(5), last = items[n - 1].date.slice(5);
  return `<div class="chart-wrap"><svg viewBox="0 0 ${w} ${h}" width="100%" preserveAspectRatio="xMidYMid meet">
    ${gridY}
    <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${markers.join('')}
    <text x="${padL}" y="${h - 4}" fill="var(--text-3)" font-size="9">${first}</text>
    <text x="${w - padR}" y="${h - 4}" fill="var(--text-3)" font-size="9" text-anchor="end">${last}</text>
  </svg></div>`;
}

/* ============================ 화면: 대시보드 ============================ */
let dashCache = null;
let dashMarket = localStorage.getItem('dashMarket') || 'KR';

async function viewDashboard() {
  setActiveTab('dashboard');
  setTitle('리치시그널');
  if (!dashCache) renderLoading();
  try {
    const [data, cal] = await Promise.all([
      API.dashboard(),
      API.calendar(null).catch(() => null),
    ]);
    dashCache = data; Settings.lastSync = Date.now(); setBadge(null);
    renderDashboard(data, cal);
  } catch (e) {
    if (e.status === 401) setBadge('키 확인 필요', 'err'); else setBadge('연결 실패', 'err');
    if (!dashCache) renderError(e.message, viewDashboard);
    else renderDashboard(dashCache, null);
  }
}

function renderDashboard(data, cal) {
  const changed = (data.sectors || []).filter((s) => s.signal_changed);
  const sectors = (data.sectors || []).filter((s) => s.market === dashMarket);

  const changedHTML = changed.length
    ? changed.map((sc) => signalChangeCard(sc)).join('')
    : `<div class="card muted tiny">✓ 오늘 변경된 신호 없음</div>`;

  const regimeHTML = `<div class="regime-grid">${['KR', 'US'].map((m) => {
    const r = (data.markets || {})[m];
    if (!r) return '';
    const rg = REGIME[r.regime] || {};
    return `<div class="regime-card bgrg-${rg.cls}">
      <div class="regime-head rg-${rg.cls}">${rg.ico} ${MARKET[m]}</div>
      <div class="regime-label">${esc(rg.label || r.regime_label)}</div>
      <div class="regime-sub">로컬 추세: ${localTrendLabel(r.local_trend)}</div>
    </div>`;
  }).join('')}</div>`;

  const sectorHTML = `
    <div class="seg" id="mkt-seg">
      ${['KR', 'US'].map((m) => `<button data-mkt="${m}" class="${m === dashMarket ? 'active' : ''}">${MARKET[m]}</button>`).join('')}
    </div>
    ${sectors.map((sc) => sectorCard(sc)).join('')}`;

  let calHTML = '';
  if (cal && cal.events && cal.events.length) {
    const upcoming = calSort(cal.events).slice(0, 4);
    calHTML = `<div class="section-title">이달의 캘린더 · ${calMonthTitle(cal.month)}</div>
      <div class="card">${upcoming.map((e) => calRow(e)).join('')}</div>
      <a class="footnote" href="#/calendar">전체 캘린더 보기 ›</a>`;
  }

  setView(`
    <div class="section-title">신호 변경 <span class="muted tiny">· 기준일 ${esc(data.as_of || '')}</span></div>
    ${changedHTML}
    <div class="section-title">오늘의 거시 국면</div>
    ${regimeHTML}
    <div class="section-title">섹터 현황</div>
    ${sectorHTML}
    ${calHTML}
  `);

  const seg = document.getElementById('mkt-seg');
  if (seg) seg.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    dashMarket = b.dataset.mkt; localStorage.setItem('dashMarket', dashMarket);
    renderDashboard(data, cal);
  }));
}

function signalChangeCard(sc) {
  const sec = SECTOR[sc.sector] || {};
  return `<div class="card tap" onclick="location.hash='#/sector/${sc.market}/${sc.sector}'">
    <div class="row between">
      <span class="wrap-title">${sec.ico || ''} ${esc(sc.label)} · ${MARKET[sc.market]}</span>
      <span class="muted mono">${sc.score.toFixed(0)}점</span>
    </div>
    <div class="row" style="margin-top:8px;gap:8px">
      ${sc.prev_signal ? signalBadge(sc.prev_signal) + '<span class="muted">→</span>' : ''}
      ${signalBadge(sc.signal)}
      <span class="spacer"></span>
      ${deltaHTML(sc.score_delta_1d)}
    </div>
  </div>`;
}

function sectorCard(sc) {
  const s = SIGNAL[sc.signal] || SIGNAL.keep;
  return `<div class="card tap" onclick="location.hash='#/sector/${sc.market}/${sc.sector}'">
    <div class="row">
      ${signalIcon(sc.signal)}
      <div class="col grow">
        <span class="wrap-title">${esc(sc.label)}</span>
        <span class="row tiny" style="gap:6px">
          <span class="sig-${s.cls}">${s.label}</span> ${deltaHTML(sc.score_delta_1d)}
        </span>
      </div>
      <span class="score-big sig-${s.cls} mono">${sc.score.toFixed(0)}</span>
    </div>
    ${componentBars(sc)}
  </div>`;
}

/* ============================ 화면: 섹터 상세 ============================ */
let detailPeriod = 6;

async function viewSector(market, sector) {
  setActiveTab('dashboard');
  const sec = SECTOR[sector] || {};
  setTitle(`${sec.label || sector} · ${MARKET[market] || market}`);
  renderLoading();
  try {
    const [detail, hist] = await Promise.all([API.detail(market, sector), API.history(market, sector, 180)]);
    setBadge(null);
    renderSector(market, sector, detail, hist.items || []);
  } catch (e) {
    renderError(e.message, () => viewSector(market, sector));
  }
}

function renderSector(market, sector, d, history) {
  const sc = d.sector;
  const s = SIGNAL[sc.signal] || SIGNAL.keep;

  const summary = `<div class="card">
    <div class="row between">
      <div class="row" style="gap:12px">
        ${signalIcon(sc.signal)}
        <div class="col">
          <span class="wrap-title sig-${s.cls}" style="font-size:20px">${s.label}</span>
          <span class="muted tiny">${STANCE[sc.stance] || sc.stance}</span>
        </div>
      </div>
      <div class="col" style="align-items:flex-end">
        <span class="score-xl mono">${sc.score.toFixed(1)}</span>
        ${deltaHTML(sc.score_delta_1d)}
      </div>
    </div>
    <div class="kv" style="margin-top:12px;border-top:0.5px solid var(--sep);padding-top:12px">
      <span class="k">현재 국면에서 이 섹터는</span><span>${biasLabel(d.regime_bias)}</span>
    </div>
    ${rationale(explainOverall(sc, d.regime_bias))}
  </div>`;

  // 섹터 구성
  let basketHTML = '';
  if (d.basket) {
    const b = d.basket;
    const cons = (b.constituents || []).map((c) => `<span class="chip">${esc(c.ticker ? `${c.name} (${c.ticker})` : c.name)}</span>`).join('');
    basketHTML = `<div class="section-title">섹터 구성</div><div class="card">
      <div class="row" style="gap:10px"><span style="font-size:18px">📊</span>
        <div class="col"><span style="font-weight:600">${esc(b.proxy.name)}</span>
        <span class="muted tiny">종목코드 ${esc(b.proxy.ticker)} · 이 ETF의 가격·거래량으로 측정</span></div></div>
      ${b.note ? `<p class="muted tiny" style="margin:10px 0 0">${esc(b.note)}</p>`
        : cons ? `<div class="muted tiny" style="margin-top:10px">대표 구성종목</div><div class="chips">${cons}</div>` : ''}
    </div>`;
  }

  // 구성요소 (T/V/M) drill-down
  const macroRows = macroRawRows(d.macro_raw || {});
  const comp = `<div class="section-title">구성요소</div><div class="card">
    ${discl('추세 (T)', 'c-blue', sc.w_trend * sc.trend * 100, `
      ${kv('컴포넌트 값', sc.trend.toFixed(2) + ' / 1.00')}${kv('가중치', (sc.w_trend * 100).toFixed(0) + '%')}`)}
    ${discl('거래량 (V)', 'c-teal', sc.w_volume * sc.volume * 100, `
      ${kv('컴포넌트 값', sc.volume.toFixed(2) + ' / 1.00')}${kv('가중치', (sc.w_volume * 100).toFixed(0) + '%')}`)}
    ${discl('거시 (M)', 'c-purple', sc.w_macro * sc.macro * 100, `
      ${kv('컴포넌트 값', sc.macro.toFixed(2) + ' / 1.00')}${kv('가중치', (sc.w_macro * 100).toFixed(0) + '%')}${macroRows}`)}
  </div>`;

  // 차트
  const filtered = history.slice(-detailPeriod * 30);
  const transitions = filtered.filter((it, i) => i > 0 && it.signal !== filtered[i - 1].signal).length;
  const chart = `<div class="section-title">점수 추이</div><div class="card">
    <div class="seg" id="period-seg">
      <button data-p="3" class="${detailPeriod === 3 ? 'active' : ''}">3개월</button>
      <button data-p="6" class="${detailPeriod === 6 ? 'active' : ''}">6개월</button>
    </div>
    ${lineChart(filtered)}
    <div class="legend">
      ${['hold', 'cash', 'keep'].map((k) => `<span class="sig-${SIGNAL[k].cls}">${SIGNAL[k].ico} ${SIGNAL[k].label} 전환</span>`).join('')}
    </div>
  </div>`;

  // 뉴스
  let newsHTML = `<div class="section-title">뉴스</div><div class="card">`;
  if (d.news_summary) newsHTML += `<p style="margin:0 0 6px;font-size:14px;line-height:1.5">${esc(d.news_summary)}</p>`;
  const items = d.news_items || [];
  if (!items.length) newsHTML += `<div class="muted tiny">표시할 뉴스 없음</div>`;
  else newsHTML += items.map((it) => newsRow(it)).join('');
  newsHTML += `</div>`;

  setView(`<span class="back" onclick="history.back()">‹ 대시보드</span>${summary}${basketHTML}${comp}${chart}${newsHTML}`);

  const seg = document.getElementById('period-seg');
  if (seg) seg.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    detailPeriod = Number(b.dataset.p); renderSector(market, sector, d, history);
  }));
}

function discl(label, dotCls, contrib, inner) {
  return `<details class="disclosure"><summary>
    <span class="dot ${dotCls}"></span>${label}
    <span class="muted mono tiny" style="margin-left:auto">${contrib.toFixed(1)}점 기여</span>
  </summary>${inner}</details>`;
}
function kv(k, v) { return `<div class="kv"><span class="k">${k}</span><span class="v mono">${v}</span></div>`; }
function macroRawRows(r) {
  const rows = [];
  const add = (k, v) => { if (v != null) rows.push(kv(k, v)); };
  add('단기 금리', r.y_short != null ? r.y_short.toFixed(2) + '%' : null);
  add('장기 금리', r.y_long != null ? r.y_long.toFixed(2) + '%' : null);
  add('장기 금리 63일 변화', r.y_long_chg_63d != null ? (r.y_long_chg_63d > 0 ? '+' : '') + r.y_long_chg_63d.toFixed(2) + '%p' : null);
  add('VIX', r.vix != null ? r.vix.toFixed(1) : null);
  add('HY 스프레드', r.hy_spread != null ? r.hy_spread.toFixed(2) + '%p' : null);
  add('실질금리', r.real_rate != null ? r.real_rate.toFixed(2) + '%' : null);
  add('달러 인덱스', r.dollar_index != null ? r.dollar_index.toFixed(1) : null);
  if (r.news_score != null) {
    const sent = (r.news_score - 0.5) * 2;
    const face = sent > 0.15 ? '🙂 긍정' : sent < -0.15 ? '🌧️ 부정' : '· 중립';
    rows.push(kv('뉴스 감성', `${face} ${r.news_score.toFixed(2)}`));
  }
  add('뉴스 감성 z-score', r.news_z != null ? (r.news_z > 0 ? '+' : '') + r.news_z.toFixed(2) : null);
  return rows.join('');
}
function newsRow(it) {
  const sent = it.sentiment > 0.15 ? '🙂' : it.sentiment < -0.15 ? '🌧️' : '·';
  const inner = `<div class="news-title">${esc(it.title)}</div>
    <div class="news-meta">${sent} <span>${esc(it.source)}</span> <span>${esc(it.date)}</span></div>`;
  return it.url ? `<a class="news-item" href="${esc(it.url)}" target="_blank" rel="noopener">${inner}</a>`
    : `<div class="news-item">${inner}</div>`;
}

/* ============================ 화면: 캘린더 ============================ */
function calSort(events) {
  const today = todayStr();
  const sorted = [...events].sort((a, b) => a.date.localeCompare(b.date));
  return sorted.filter((e) => e.date >= today).concat(sorted.filter((e) => e.date < today));
}
function calMonthTitle(month) {
  const [y, m] = month.split('-'); return `${y}년 ${Number(m)}월`;
}
function calRow(e) {
  const dw = dayWeekday(e.date);
  const isToday = e.date === todayStr();
  const isPast = e.date < todayStr();
  const wdCls = isToday ? 'today' : dw.wdIdx === 0 ? 'sun' : dw.wdIdx === 6 ? 'sat' : '';
  const catIco = e.category === 'earnings' ? '🏢' : '📈';
  let res = '';
  if (e.result) {
    const macro = e.category === 'macro';
    const map = {
      beat: [macro ? 'macro-up' : 'up', '↑', '예상치 상회'],
      meet: ['flat', '=', '예상치 부합'],
      miss: [macro ? 'macro-down' : 'down', '↓', '예상치 하회'],
    };
    const [c, a, t] = map[e.result] || map.meet;
    res = `<span class="res ${c}">${a} ${t}</span>`;
  } else if (e.actual == null && e.estimate == null && !e.confirmed) {
    res = `<span class="res flat">예상</span>`;
  }
  const vals = [];
  if (e.actual != null) vals.push(`실제 ${esc(e.actual)}`);
  if (e.estimate != null) vals.push(`예상 ${esc(e.estimate)}`);
  return `<div class="cal-row ${isToday ? 'today' : ''} ${isPast ? 'past' : ''}">
    <div class="cal-date"><div class="cal-day">${dw.day}</div><div class="cal-wd ${wdCls}">${isToday ? '오늘' : dw.wd}</div></div>
    <span class="mk mk-${e.market}">${MARKET[e.market]}</span>
    <div class="cal-body">
      <div class="cal-title">${catIco} <span class="t">${esc(e.title)}</span> ${e.importance >= 3 ? '<span class="imp">중요!</span>' : ''}</div>
      ${vals.length ? `<div class="cal-vals">${vals.join(' · ')}</div>` : ''}
      ${isToday && e.release_time ? `<div class="cal-vals">🕒 ${esc(e.release_time)}</div>` : ''}
    </div>
    ${res}
  </div>`;
}

async function viewCalendar() {
  setActiveTab('calendar'); setTitle('경제 캘린더');
  renderLoading();
  try {
    const cal = await API.calendar(null); setBadge(null);
    const events = calSort(cal.events || []);
    setView(`<div class="section-title">${calMonthTitle(cal.month)}</div>
      ${events.length ? `<div class="card">${events.map((e) => calRow(e)).join('')}</div>`
        : '<div class="card muted tiny">이달 예정된 일정 없음</div>'}
      <div class="footnote">실적은 확정 발표일, 거시 지표는 정례 주기 기반 예상일입니다.</div>`);
  } catch (e) {
    renderError(e.message, viewCalendar);
  }
}

/* ============================ 화면: 설정 ============================ */
async function viewSettings() {
  setActiveTab('settings'); setTitle('설정');
  const pushState = await getPushState();
  const lastSync = Settings.lastSync ? new Date(Settings.lastSync).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : '없음';
  const standalone = isStandalone();

  setView(`
    <div class="section-title">서버</div>
    <div class="card">
      <div class="field"><label>서버 URL <span class="muted">(비우면 이 사이트)</span></label>
        <input id="in-base" type="url" placeholder="https://richman-production.up.railway.app" value="${esc(Settings.baseURL)}"></div>
      <div class="field"><label>API 키 (X-API-Key)</label>
        <input id="in-key" type="password" placeholder="Railway API_KEY" value="${esc(Settings.apiKey)}"></div>
      <button class="btn secondary" id="btn-save">저장</button>
      <button class="btn secondary" id="btn-test" style="margin-top:8px">연결 테스트 <span id="test-res" class="muted tiny"></span></button>
    </div>

    <div class="section-title">알림 (웹 푸시)</div>
    <div class="card">
      <div class="toggle-row">
        <div class="col"><span>푸시 알림 받기</span><span class="muted tiny">신호 변경 시 잠금화면 알림</span></div>
        <label class="switch"><input type="checkbox" id="tg-push" ${pushState.subscribed ? 'checked' : ''}><span class="slider"></span></label>
      </div>
      <button class="btn secondary" id="btn-testpush" style="margin-top:4px" ${pushState.subscribed ? '' : 'disabled'}>테스트 푸시 보내기</button>
      <p class="footnote" id="push-hint" style="margin-top:10px">${pushHint(pushState, standalone)}</p>
    </div>

    <div class="section-title">상태</div>
    <div class="card">
      ${kv('마지막 동기화', esc(lastSync))}
      ${kv('홈 화면 앱', standalone ? '설치됨 ✓' : '미설치 (Safari)')}
      ${kv('푸시 상태', pushState.enabled ? (pushState.subscribed ? '구독 중 ✓' : '꺼짐') : '서버 미설정')}
    </div>
    <div class="footnote">현금보유 전환은 즉시, 그 외(보유 전환·국면 변경)는 배치 실행 시 묶어서 알립니다.</div>
  `);

  document.getElementById('btn-save').addEventListener('click', () => {
    Settings.baseURL = document.getElementById('in-base').value.trim();
    Settings.apiKey = document.getElementById('in-key').value.trim();
    dashCache = null; setBadge('저장됨', 'ok'); setTimeout(() => setBadge(null), 1500);
  });
  document.getElementById('btn-test').addEventListener('click', async () => {
    const el = document.getElementById('test-res'); el.textContent = '…';
    try {
      Settings.baseURL = document.getElementById('in-base').value.trim();
      const h = await API.health(); el.textContent = h.status === 'ok' ? '정상 ✓' : h.status;
    } catch (e) { el.textContent = '실패'; }
  });
  document.getElementById('tg-push').addEventListener('change', async (ev) => {
    const hint = document.getElementById('push-hint');
    try {
      if (ev.target.checked) { await enablePush(); hint.textContent = '알림이 켜졌습니다.'; }
      else { await disablePush(); hint.textContent = '알림이 꺼졌습니다.'; }
    } catch (e) {
      ev.target.checked = false; hint.textContent = '실패: ' + e.message;
    }
    document.getElementById('btn-testpush').disabled = !ev.target.checked;
  });
  document.getElementById('btn-testpush').addEventListener('click', async () => {
    const el = document.getElementById('push-hint'); el.textContent = '전송 중…';
    try { const r = await API.testPush(); el.textContent = `테스트 전송: ${r.sent}건 (구독 ${r.subscriptions || 0})`; }
    catch (e) { el.textContent = '실패: ' + e.message; }
  });
}
function pushHint(st, standalone) {
  if (!st.enabled) return '서버에 VAPID 키가 설정되지 않아 푸시를 사용할 수 없습니다.';
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return '이 브라우저는 웹 푸시를 지원하지 않습니다.';
  if (!standalone && isIOS()) return '⚠️ iOS에서는 먼저 공유 → "홈 화면에 추가"로 설치한 뒤, 홈 화면 아이콘으로 열어야 푸시를 켤 수 있습니다.';
  return '신호가 바뀔 때만 알림을 보냅니다.';
}

/* ============================ 웹 푸시 ============================ */
function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}
function isIOS() { return /iphone|ipad|ipod/i.test(navigator.userAgent); }
function urlBase64ToUint8Array(base64) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}
async function getPushState() {
  const state = { enabled: false, subscribed: false };
  try { const k = await API.vapidKey(); state.enabled = !!k.enabled; state.publicKey = k.public_key; }
  catch (e) { return state; }
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return state;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    state.subscribed = !!sub;
  } catch (e) {}
  return state;
}
async function enablePush() {
  const k = await API.vapidKey();
  if (!k.enabled) throw new Error('서버 푸시 미설정');
  if (isIOS() && !isStandalone()) throw new Error('홈 화면에 추가 후 실행하세요');
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('알림 권한 거부됨');
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(k.public_key),
  });
  await API.subscribe(sub.toJSON());
}
async function disablePush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) { try { await API.unsubscribe(sub.endpoint); } catch (e) {} await sub.unsubscribe(); }
}

/* ============================ 셸/라우터 ============================ */
const viewEl = () => document.getElementById('view');
function setView(html) { viewEl().innerHTML = html; window.scrollTo(0, 0); }
function setTitle(t) { document.getElementById('title').textContent = t; }
function setBadge(text, cls) {
  const b = document.getElementById('badge');
  if (!text) { b.classList.add('hidden'); return; }
  b.textContent = text; b.className = 'badge ' + (cls || ''); b.classList.remove('hidden');
}
function renderLoading() { setView('<div class="center"><div class="spinner"></div><span class="tiny">불러오는 중…</span></div>'); }
function renderError(msg, retry) {
  setView(`<div class="center"><div style="font-size:32px">📡</div><span class="tiny">${esc(msg)}</span>
    <button class="btn secondary" id="retry" style="width:auto;padding:10px 20px">다시 시도</button></div>`);
  const r = document.getElementById('retry'); if (r) r.addEventListener('click', retry);
}
function setActiveTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
}

function router() {
  const hash = location.hash.replace(/^#/, '') || '/';
  const parts = hash.split('/').filter(Boolean);
  if (parts[0] === 'sector' && parts[1] && parts[2]) return viewSector(parts[1], parts[2]);
  if (parts[0] === 'calendar') return viewCalendar();
  if (parts[0] === 'settings') return viewSettings();
  return viewDashboard();
}

window.addEventListener('hashchange', router);
window.addEventListener('load', () => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  router();
});

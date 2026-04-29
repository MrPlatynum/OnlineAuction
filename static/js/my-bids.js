const API = 'http://localhost:8000';
const token = localStorage.getItem('token');

/* ---- Helpers ---- */
function esc(s) {
  return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtMoney(n) {
  return '$' + Number(n).toFixed(2);
}
function fmtDate(ts) {
  if (!ts) return '';
  return new Date(ts).toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
}
function apiFetch(url, opts={}) {
  const headers = { ...(opts.headers||{}) };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  return fetch(url, { ...opts, headers });
}

/* ---- Auth UI ---- */
async function initAuth() {
  if (!token) {
    document.getElementById('guestBtn').style.display = 'flex';
    return null;
  }
  try {
    const r = await apiFetch(`${API}/api/me`);
    if (!r.ok) { document.getElementById('guestBtn').style.display = 'flex'; return null; }
    const me = await r.json();
    document.getElementById('userProfile').style.display = 'flex';
    const avEl = document.getElementById('userAvatar');
    avEl.textContent = (me.username||'?')[0].toUpperCase();
    if (me.avatar_url) {
      const img = document.createElement('img');
      img.src = me.avatar_url.startsWith('http') ? me.avatar_url : `${API}${me.avatar_url}`;
      img.alt = me.username;
      avEl.appendChild(img);
    }
    document.getElementById('userName').textContent    = me.username || '—';
    document.getElementById('userBalance').textContent = Number(me.balance||0).toFixed(2);
    return me;
  } catch { return null; }
}

/* ---- Skeleton ---- */
function renderSkeleton() {
  return Array(4).fill(0).map(() => `
    <div class="skeleton-card">
      <div class="skeleton" style="width:40px;height:40px;border-radius:10px;flex-shrink:0"></div>
      <div style="flex:1;display:flex;flex-direction:column;gap:8px">
        <div class="skeleton" style="height:14px;width:60%"></div>
        <div class="skeleton" style="height:11px;width:35%"></div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
        <div class="skeleton" style="height:16px;width:70px"></div>
        <div class="skeleton" style="height:18px;width:50px;border-radius:5px"></div>
      </div>
    </div>
  `).join('');
}

/* ---- Render bid card ---- */
function renderBidCard(item, type) {
  let iconEmoji, iconCls, amountCls, badgeHtml, cardCls;

  if (type === 'active_winning') {
    iconEmoji = '🥇'; iconCls = 'winning'; amountCls = 'green';
    badgeHtml = `<span class="bid-status-badge badge-winning">● Лидирую</span>`;
    cardCls = 'winning';
  } else if (type === 'active_outbid') {
    iconEmoji = '⚡'; iconCls = 'outbid'; amountCls = 'amber';
    badgeHtml = `<span class="bid-status-badge badge-outbid">Перебили</span>`;
    cardCls = 'outbid';
  } else if (type === 'won') {
    iconEmoji = '🏆'; iconCls = 'won'; amountCls = 'accent';
    badgeHtml = `<span class="bid-status-badge badge-won">🏆 Победа</span>`;
    cardCls = 'won';
  } else {
    iconEmoji = '😔'; iconCls = 'lost'; amountCls = 'red';
    badgeHtml = `<span class="bid-status-badge badge-lost">Проигрыш</span>`;
    cardCls = 'lost';
  }

  const price = item.current_price || item.my_bid;
  const endTime = item.end_time ? fmtDate(item.end_time) : '';

  return `
    <a class="bid-card ${cardCls}" href="auction.html?id=${item.auction_id}">
      <div class="bid-card-icon ${iconCls}">${iconEmoji}</div>
      <div class="bid-card-info">
        <div class="bid-card-title">${esc(item.title)}</div>
        <div class="bid-card-meta">
          <span>Моя ставка: <strong>${fmtMoney(item.my_bid)}</strong></span>
          ${endTime ? `<span>· ${endTime}</span>` : ''}
        </div>
      </div>
      <div class="bid-card-right">
        <div class="bid-card-amount ${amountCls}">${fmtMoney(price)}</div>
        ${badgeHtml}
      </div>
    </a>
  `;
}

/* ---- Render created lot card ---- */
function renderCreatedCard(item) {
  const isActive = item.is_active;
  return `
    <a class="bid-card ${isActive ? '' : 'lost'}" href="auction.html?id=${item.auction_id}">
      <div class="bid-card-icon active">${isActive ? '📦' : '✅'}</div>
      <div class="bid-card-info">
        <div class="bid-card-title">${esc(item.title)}</div>
        <div class="bid-card-meta">
          <span>Стартовая: ${fmtMoney(item.starting_price)}</span>
        </div>
      </div>
      <div class="bid-card-right">
        <div class="bid-card-amount ${isActive ? 'green' : 'accent'}">${fmtMoney(item.current_price)}</div>
        <span class="bid-status-badge ${isActive ? 'badge-winning' : 'badge-active'}">${isActive ? '● Активен' : 'Завершён'}</span>
      </div>
    </a>
  `;
}

/* ---- Main render ---- */
let currentTab = 'active';
let data = null;

function getTabData(tab) {
  if (!data) return [];
  if (tab === 'active') {
    const winning = (data.active_bids||[]).filter(b => b.is_winning).map(b => ({...b, _type:'active_winning'}));
    const outbid  = (data.active_bids||[]).filter(b => !b.is_winning).map(b => ({...b, _type:'active_outbid'}));
    return [...winning, ...outbid];
  }
  if (tab === 'won')     return (data.won_auctions||[]).map(b => ({...b, _type:'won'}));
  if (tab === 'lost')    return (data.lost_auctions||[]).map(b => ({...b, _type:'lost'}));
  if (tab === 'created') return data.created_auctions||[];
  return [];
}

function renderTabs() {
  const stats = data?.stats || {};
  const activeCount  = (data?.active_bids||[]).length;
  const wonCount     = (data?.won_auctions||[]).length;
  const lostCount    = (data?.lost_auctions||[]).length;
  const createdCount = (data?.created_auctions||[]).length;

  return `
    <div class="tabs">
      <button class="tab-btn ${currentTab==='active'?'active':''}" onclick="switchTab('active')">
        Активные <span class="tab-count">${activeCount}</span>
      </button>
      <button class="tab-btn ${currentTab==='won'?'active':''}" onclick="switchTab('won')">
        Выиграно <span class="tab-count">${wonCount}</span>
      </button>
      <button class="tab-btn ${currentTab==='lost'?'active':''}" onclick="switchTab('lost')">
        Проиграно <span class="tab-count">${lostCount}</span>
      </button>
      <button class="tab-btn ${currentTab==='created'?'active':''}" onclick="switchTab('created')">
        Мои лоты <span class="tab-count">${createdCount}</span>
      </button>
    </div>
  `;
}

function renderList() {
  const items = getTabData(currentTab);

  if (!items.length) {
    const msgs = {
      active:  ['🎯', 'Нет активных ставок', 'Найдите интересный лот и сделайте первую ставку'],
      won:     ['🏆', 'Побед пока нет', 'Участвуйте в аукционах — удача будет на вашей стороне'],
      lost:    ['😤', 'Проигрышей нет', 'Отличный результат!'],
      created: ['📦', 'Вы ещё не создали лотов', 'Создайте свой первый лот прямо сейчас'],
    };
    const [icon, title, sub] = msgs[currentTab] || ['🔍', 'Пусто', ''];
    return `
      <div class="empty-state">
        <div class="empty-icon">${icon}</div>
        <div class="empty-title">${title}</div>
        <div class="empty-sub">${sub}</div>
        ${currentTab === 'active' || currentTab === 'created'
          ? `<a href="index.html" class="btn btn-primary">${currentTab==='created'?'Создать лот':'К аукционам'}</a>`
          : ''}
      </div>
    `;
  }

  if (currentTab === 'created') {
    return `<div class="bids-list">${items.map(renderCreatedCard).join('')}</div>`;
  }
  return `<div class="bids-list">${items.map(b => renderBidCard(b, b._type)).join('')}</div>`;
}

function renderPage() {
  const stats = data?.stats || {};
  const winningCount = (data?.active_bids||[]).filter(b=>b.is_winning).length;
  const totalSpent   = [...(data?.active_bids||[]), ...(data?.won_auctions||[]), ...(data?.lost_auctions||[])]
    .reduce((s, b) => s + (b.my_bid||0), 0);

  document.getElementById('mainContent').innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Мои ставки</h1>
        <p class="page-subtitle">История вашего участия в аукционах</p>
      </div>
      <a href="index.html" class="btn btn-primary">+ Найти лоты</a>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-card-label">Активных</span>
        <span class="stat-card-value amber">${stats.active_count ?? 0}</span>
      </div>
      <div class="stat-card">
        <span class="stat-card-label">Лидирую</span>
        <span class="stat-card-value green">${winningCount}</span>
      </div>
      <div class="stat-card">
        <span class="stat-card-label">Побед</span>
        <span class="stat-card-value accent">${stats.won_count ?? 0}</span>
      </div>
      <div class="stat-card">
        <span class="stat-card-label">Всего ставок</span>
        <span class="stat-card-value">${stats.total_bids ?? 0}</span>
      </div>
    </div>

    ${renderTabs()}
    <div id="tabContent">${renderList()}</div>
  `;
}

function switchTab(tab) {
  currentTab = tab;
  // Перерисовываем только табы и контент
  document.querySelector('.tabs').outerHTML = renderTabs();
  document.getElementById('tabContent').innerHTML = renderList();
  // querySelector не работает после outerHTML, нужно перерисовать через innerHTML
  renderPage();
}

/* ---- Init ---- */
async function init() {
  const main = document.getElementById('mainContent');

  if (!token) {
    main.innerHTML = `
      <div class="auth-wall">
        <div class="auth-wall-icon">🔐</div>
        <div class="auth-wall-title">Войдите в аккаунт</div>
        <div class="auth-wall-sub">Чтобы видеть свои ставки, необходимо авторизоваться</div>
        <a href="index.html" class="btn btn-primary">Перейти к аукционам</a>
      </div>
    `;
    document.getElementById('guestBtn').style.display = 'flex';
    return;
  }

  // Скелетон пока грузим
  main.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Мои ставки</h1>
        <p class="page-subtitle">Загрузка…</p>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">${renderSkeleton()}</div>
  `;

  const [me] = await Promise.all([initAuth()]);

  try {
    const r = await apiFetch(`${API}/api/my/participation`);
    if (!r.ok) throw new Error();
    data = await r.json();
    renderPage();
  } catch {
    main.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">❌</div>
        <div class="empty-title">Ошибка загрузки</div>
        <div class="empty-sub">Не удалось загрузить данные. Проверьте подключение.</div>
        <button class="btn btn-primary" onclick="init()">Повторить</button>
      </div>
    `;
  }
}

init();

(function() {
  const API_URL = 'http://localhost:8000';
  function getToken() { return localStorage.getItem('token'); }

  const btn        = document.getElementById('notifBtn');
  const badge      = document.getElementById('notifBadge');
  const dropdown   = document.getElementById('notifDropdown');
  const list       = document.getElementById('notifList');
  const markAllBtn = document.getElementById('notifMarkAll');

  if (!btn || !dropdown) return;

  let unreadCount = 0, wsNotif = null, currentUserId = null, isOpen = false;

  const ICONS = {
    bid_outbid:     { emoji: '⚡', cls: 'bid_outbid' },
    bid_placed:     { emoji: '💰', cls: 'bid_placed' },
    auction_won:    { emoji: '🏆', cls: 'auction_won' },
    auction_lost:   { emoji: '😔', cls: 'auction_lost' },
    auction_sold:   { emoji: '✅', cls: 'auction_sold' },
    auction_ending: { emoji: '⏰', cls: 'auction_ending' },
  };

  function fmtAge(iso) {
    const utcIso = iso && !iso.endsWith('Z') && !iso.includes('+') ? iso + 'Z' : iso;
    const diff = Math.floor((Date.now() - new Date(utcIso)) / 1000);
    if (diff < 60)    return 'только что';
    if (diff < 3600)  return `${Math.floor(diff / 60)} мин назад`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
    return new Date(utcIso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
  } мин назад`;
    if (diff < 86400) return `${Math.floor(diff/3600)} ч назад`;
    return new Date(iso).toLocaleDateString('ru-RU', { day:'2-digit', month:'2-digit' });
  }
  function esc2(s) { return String(s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  function setCount(n) {
    unreadCount = Math.max(0, n);
    if (unreadCount > 0) {
      badge.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
      badge.style.display = 'flex'; btn.classList.add('has-unread');
    } else {
      badge.style.display = 'none'; btn.classList.remove('has-unread');
    }
  }

  function renderList(items) {
    if (!items.length) { list.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Уведомлений пока нет</div>`; return; }
    list.innerHTML = items.map(n => {
      const ico = ICONS[n.type] || { emoji: '🔔', cls: '' };
      return `<div class="notif-item ${n.is_read?'':'unread'}" data-id="${n.id}" data-auction="${n.auction_id||''}">
        <div class="notif-icon ${ico.cls}">${ico.emoji}</div>
        <div class="notif-body">
          <div class="notif-title">${esc2(n.title)}</div>
          <div class="notif-msg">${esc2(n.message)}</div>
          <div class="notif-time">${fmtAge(n.created_at)}</div>
        </div></div>`;
    }).join('');
  }

  async function apiFetch2(url, opts={}) {
    const tk = getToken();
    const headers = {...(opts.headers||{})};
    if (tk) headers['Authorization'] = 'Bearer ' + tk;
    return fetch(url, {...opts, headers});
  }

  async function fetchCount() {
    if (!getToken()) return;
    try { const r = await apiFetch2(`${API_URL}/api/notifications/unread-count`); if (r.ok) { const d=await r.json(); setCount(d.count??0); } } catch {}
  }

  async function fetchNotifications() {
    if (!getToken()) { list.innerHTML=`<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Войдите для уведомлений</div>`; return; }
    list.innerHTML = `<div class="notif-empty">Загрузка…</div>`;
    try { const r=await apiFetch2(`${API_URL}/api/notifications?limit=30`); if (r.ok) renderList(await r.json()); else list.innerHTML=`<div class="notif-empty">Ошибка загрузки</div>`; } catch { list.innerHTML=`<div class="notif-empty">Нет связи с сервером</div>`; }
  }

  async function markAllRead() {
    try { await apiFetch2(`${API_URL}/api/notifications/mark-all-read`,{method:'POST'}); setCount(0); await fetchNotifications(); } catch {}
  }

  function openDropdown()  { isOpen=true;  dropdown.classList.add('open');    fetchNotifications(); }
  function closeDropdown() { isOpen=false; dropdown.classList.remove('open'); }

  btn.addEventListener('click', e => { e.stopPropagation(); isOpen ? closeDropdown() : openDropdown(); });
  document.addEventListener('click', e => { if (isOpen && !dropdown.contains(e.target) && e.target!==btn) closeDropdown(); });
  markAllBtn.addEventListener('click', e => { e.stopPropagation(); markAllRead(); });

  list.addEventListener('click', async e => {
    const item = e.target.closest('.notif-item');
    if (!item) return;
    const id = item.dataset.id, aId = item.dataset.auction;
    if (id && item.classList.contains('unread')) { item.classList.remove('unread'); setCount(unreadCount-1); try { await apiFetch2(`${API_URL}/api/notifications/${id}/read`,{method:'POST'}); } catch {} }
    if (aId) { closeDropdown(); window.location.href=`auction.html?id=${aId}`; }
  });

  function connectNotifWS(userId) {
    if (wsNotif) { try { wsNotif.close(); } catch {} }
    const tk = getToken();
    if (!tk) return;
    wsNotif = new WebSocket(`${API_URL.replace(/^http/i,'ws')}/ws/notifications/${userId}?token=${encodeURIComponent(tk)}`);
    wsNotif.onmessage = e => { try { const d=JSON.parse(e.data); if (d.type==='notification') { setCount(unreadCount+1); if (isOpen) fetchNotifications(); } } catch {} };
    wsNotif.onclose = () => setTimeout(()=>{ if (currentUserId) connectNotifWS(currentUserId); }, 3000);
  }

  async function initNotifBell() {
    if (!getToken()) { btn.style.display='none'; return; }
    btn.style.display='flex';
    await fetchCount();
    try { const r=await apiFetch2(`${API_URL}/api/me`); if (r.ok) { const me=await r.json(); currentUserId=me.id; if (currentUserId) connectNotifWS(currentUserId); } } catch {}
    setInterval(fetchCount, 60000);
  }

  setTimeout(initNotifBell, 800);
  window.addEventListener('storage', e => { if (e.key==='token') setTimeout(initNotifBell, 300); });
})();

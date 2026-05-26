const token = localStorage.getItem('token');

function logout() { localStorage.removeItem('token'); location.href = 'index.html'; }
if (!token) { showToast('Требуется вход', 'Войдите, чтобы открыть профиль', 'warn'); setTimeout(() => location.href = 'index.html', 1200); }

/* ---- Progress ---- */
function setProg(labelId, barId, cur, max) {
  $(labelId).textContent = Math.min(cur, max);
  setTimeout(() => { $(barId).style.width = Math.min((cur / max) * 100, 100) + '%'; }, 150);
}

/* ---- Achievements ---- */
function renderAch(s) {
  const list = [
    { emoji: '🎯', name: 'Первая ставка',  desc: 'Сделайте первую ставку',   ok: s.total_bids >= 1 },
    { emoji: '🏆', name: 'Первая победа',  desc: 'Выиграйте первый аукцион', ok: s.won_count >= 1 },
    { emoji: '📦', name: 'Продавец',       desc: 'Создайте первый лот',      ok: s.created_count >= 1 },
    { emoji: '💎', name: 'Коллекционер',   desc: 'Выиграйте 5 аукционов',    ok: s.won_count >= 5 },
  ];
  $('ach').innerHTML = list.map(a => `
    <div class="achieve-item ${a.ok ? 'unlocked' : 'locked'}">
      <div class="achieve-emoji">${a.emoji}</div>
      <div style="flex:1;min-width:0;">
        <div class="achieve-name">${esc(a.name)}</div>
        <div class="achieve-desc">${esc(a.desc)}</div>
      </div>
      ${a.ok ? '<div class="achieve-check">✓</div>' : ''}
    </div>`).join('');
}

/* ---- Chart ---- */
let chartInstance = null;
let chartData = null;

function makeChart(data) {
  chartData = data;
}

function renderChart() {
  if (!chartData) return;
  const canvas = $('chart');
  if (!canvas) return;

  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }

  const activeCount  = chartData.active_bids?.length  || 0;
  const wonCount     = chartData.won_auctions?.length  || 0;
  const lostCount    = chartData.lost_auctions?.length || 0;
  const createdCount = chartData.created_auctions?.length || 0;
  const total = activeCount + wonCount + lostCount + createdCount;

  if (!total) {
    canvas.parentElement.innerHTML = '<div style="text-align:center;color:var(--text-3);padding:40px 0;font-size:13px;">📊 Нет данных для отображения</div>';
    return;
  }

  const ctx = canvas.getContext('2d');
  chartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Активные', 'Выиграно', 'Проиграно', 'Создано'],
      datasets: [{
        data: [activeCount, wonCount, lostCount, createdCount],
        backgroundColor: ['#3b82f6','#22c55e','#ef4444','#e8a020'],
        borderColor: 'var(--bg-2)',
        borderWidth: 4,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#a1a1aa', padding: 18, font: { size: 12, weight: '600', family: 'Inter' }}},
        tooltip: { backgroundColor: '#18181b', titleColor: '#fafafa', bodyColor: '#a1a1aa', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 12, cornerRadius: 10 }
      },
      cutout: '68%',
      animation: false,
    }
  });
}

/* ---- Panel navigation ---- */
let partCache = null, subsCache = null;
const VALID_PANELS = ['overview','balance','my-bids','created','subs','notifications','badges','settings'];

function showPanel(name, pushState = true) {
  if (!VALID_PANELS.includes(name)) name = 'overview';
  document.querySelectorAll('.profile-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sb-item[data-panel]').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById(`panel-${name}`);
  if (panel) panel.classList.add('active');
  const btn = document.querySelector(`.sb-item[data-panel="${name}"]`);
  if (btn) btn.classList.add('active');
  if (pushState) history.pushState({ panel: name }, '', `#${name}`);

  if (name === 'subs') renderSubs();
  else if (name === 'my-bids') renderMyBidsPanel();
  else if (['won','lost','created'].includes(name)) renderList(name);
  else if (name === 'notifications') loadNotifPanel();
  else if (name === 'badges') renderBadgesPanel();
  else if (name === 'balance') loadBalance();
  else if (name === 'overview') setTimeout(renderChart, 50);
}

window.addEventListener('popstate', e => {
  const name = e.state?.panel || location.hash.replace('#', '') || 'overview';
  showPanel(name, false);
});
function initPanelFromHash() {
  const hash = location.hash.replace('#', '');
  showPanel(VALID_PANELS.includes(hash) ? hash : 'overview', false);
}
function setTab(tab) { showPanel(tab); }

/* ---- Settings tabs ---- */
function showSettingsTab(name) {
  document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.settings-sub-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.settings-tab[data-stab="${name}"]`)?.classList.add('active');
  document.getElementById(`stab-${name}`)?.classList.add('active');
}

/* ---- Password change ---- */
function checkStrength() {
  const pw = $('pwNew')?.value || '';
  const bars = [1,2,3,4].map(i => $(`pwBar${i}`));
  const label = $('pwStrengthLabel');
  const strength = pw.length < 6 ? 0 : pw.length < 8 ? 1 : /[A-Z]/.test(pw) && /[0-9]/.test(pw) ? 3 : 2;
  const colors = ['','var(--red)','var(--amber)','var(--green)','var(--green)'];
  const labels = ['','Слабый','Средний','Хороший','Сильный'];
  bars.forEach((b, i) => { if (b) b.style.background = i < strength ? colors[strength] : 'var(--bg-4)'; });
  if (label) { label.textContent = pw ? labels[strength] : ''; label.style.color = colors[strength]; }
}

async function changePassword() {
  [$('pwCurrentErr'), $('pwNewErr'), $('pwConfirmErr')].forEach(e => { if(e) e.textContent = ''; });
  const cur = $('pwCurrent')?.value, nw = $('pwNew')?.value, cfm = $('pwConfirm')?.value;
  if (!cur) { if($('pwCurrentErr')) $('pwCurrentErr').textContent = 'Введите текущий пароль'; return; }
  if (!nw || nw.length < 6) { if($('pwNewErr')) $('pwNewErr').textContent = 'Минимум 6 символов'; return; }
  if (nw !== cfm) { if($('pwConfirmErr')) $('pwConfirmErr').textContent = 'Пароли не совпадают'; return; }
  try {
    const r = await apiFetch(`${API}/api/change-password`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: cur, new_password: nw })
    });
    const d = await r.json();
    if (r.ok) {
      const s = $('pwStatus'); if(s) { s.textContent = '✓ Пароль изменён'; setTimeout(() => s.textContent = '', 3000); }
      [$('pwCurrent'),$('pwNew'),$('pwConfirm')].forEach(f => { if(f) f.value = ''; });
      checkStrength();
    } else { if($('pwCurrentErr')) $('pwCurrentErr').textContent = d.detail || 'Ошибка'; }
  } catch { if($('pwCurrentErr')) $('pwCurrentErr').textContent = 'Ошибка соединения'; }
}

/* ---- Notification settings ---- */
function onNotifChange() {
  const btn = $('saveNotifBtn'); if(btn) btn.disabled = false;
  const s = $('notifStatus'); if(s) s.textContent = '';
}
function loadNotifSettings(user) {
  if ($('s_email'))   $('s_email').checked   = user.email_notifications ?? true;
  if ($('s_outbid'))  $('s_outbid').checked  = user.notify_outbid  ?? true;
  if ($('s_winning')) $('s_winning').checked = user.notify_winning ?? true;
  if ($('s_ending'))  $('s_ending').checked  = user.notify_ending  ?? true;
  if ($('s_sold'))    $('s_sold').checked    = user.notify_sold    ?? true;
  const btn = $('saveNotifBtn'); if(btn) btn.disabled = true;
}
async function saveNotifications() {
  const btn = $('saveNotifBtn'); if(btn) { btn.disabled = true; btn.textContent = 'Сохранение…'; }
  try {
    const r = await apiFetch(`${API}/api/notification-settings`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email_notifications: $('s_email')?.checked,
        notify_outbid:       $('s_outbid')?.checked,
        notify_winning:      $('s_winning')?.checked,
        notify_ending:       $('s_ending')?.checked,
        notify_sold:         $('s_sold')?.checked,
      })
    });
    const s = $('notifStatus');
    if (r.ok) { if(s) { s.textContent = '✓ Сохранено'; setTimeout(() => s.textContent = '', 3000); } }
    else { if(s) s.textContent = 'Ошибка сохранения'; if(btn) btn.disabled = false; }
  } catch { const s = $('notifStatus'); if(s) s.textContent = 'Ошибка соединения'; if(btn) btn.disabled = false; }
  finally { if(btn) btn.textContent = 'Сохранить'; }
}

/* ---- Theme ---- */
function setTheme(theme) {
  localStorage.setItem('theme', theme);
  if (theme === 'dark') document.documentElement.removeAttribute('data-theme');
  else if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
  else if (theme === 'auto') {
    if (!window.matchMedia('(prefers-color-scheme: dark)').matches) document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
  }
  document.querySelectorAll('.theme-option').forEach(b => b.classList.toggle('active', b.dataset.theme === theme));
}
function initTheme() {
  const t = localStorage.getItem('theme') || 'dark';
  document.querySelectorAll('.theme-option').forEach(b => b.classList.toggle('active', b.dataset.theme === t));
}

/* ---- Notifications panel ---- */
async function loadNotifPanel() {
  const el = $('notifPanelList');
  if (!el) return;
  el.innerHTML = '<div class="notif-panel-empty">Загрузка…</div>';
  try {
    const r = await apiFetch(API + '/api/notifications');
    if (!r.ok) return;
    const data = await r.json();
    const items = data.notifications || data || [];

    const unread = items.filter(n => !n.is_read).length;
    const badge = $('sbNotifBadge');
    if (badge) { badge.textContent = unread; badge.style.display = unread ? 'flex' : 'none'; }

    if (!items.length) {
      el.innerHTML = '<div class="notif-panel-empty">🔔 Нет уведомлений</div>';
      return;
    }
    const icons = {
      bid_outbid:    { icon: '😔', bg: 'rgba(239,68,68,.15)' },
      bid_placed:    { icon: '🎯', bg: 'rgba(232,160,32,.15)' },
      auction_ending:{ icon: '⏰', bg: 'rgba(245,158,11,.15)' },
      auction_won:   { icon: '🏆', bg: 'rgba(34,197,94,.15)' },
      auction_lost:  { icon: '💔', bg: 'rgba(239,68,68,.15)' },
      auction_sold:  { icon: '✅', bg: 'rgba(34,197,94,.15)' },
      new_lot:       { icon: '🔖', bg: 'rgba(59,130,246,.15)' },
    };
    el.innerHTML = items.slice(0, 50).map(n => {
      const ic = icons[n.type] || { icon: 'ℹ️', bg: 'var(--bg-3)' };
      const utc = n.created_at && !n.created_at.endsWith('Z') ? n.created_at + 'Z' : n.created_at;
      const diff = Math.floor((Date.now() - new Date(utc)) / 1000);
      const ago = diff < 60 ? 'только что'
        : diff < 3600  ? `${Math.floor(diff/60)} мин назад`
        : diff < 86400 ? `${Math.floor(diff/3600)} ч назад`
        : `${Math.floor(diff/86400)} дн назад`;
      return `
        <div class="notif-card${n.is_read ? '' : ' unread'}" onclick="markNotifRead(${n.id}, this)">
          <div class="notif-card-icon" style="background:${ic.bg};">${ic.icon}</div>
          <div class="notif-card-body">
            <div class="notif-card-text"><strong>${esc(n.title)}</strong><br>${esc(n.message || '')}</div>
            <div class="notif-card-meta">
              <span class="notif-card-time">🕐 ${ago}</span>
              ${n.auction_id ? `<a class="notif-card-action" href="auction.html?id=${n.auction_id}">Открыть ›</a>` : ''}
            </div>
          </div>
        </div>`;
    }).join('');
  } catch { el.innerHTML = '<div class="notif-panel-empty">Ошибка загрузки</div>'; }
}

async function markNotifRead(id, el) {
  el?.classList.remove('unread');
  try { await apiFetch(`${API}/api/notifications/${id}/read`, { method: 'POST' }); } catch {}
}
async function markAllReadPanel() {
  try {
    await apiFetch(API + '/api/notifications/mark-all-read', { method: 'POST' });
    document.querySelectorAll('.notif-card.unread').forEach(c => c.classList.remove('unread'));
    const badge = $('sbNotifBadge'); if (badge) badge.style.display = 'none';
  } catch {}
}

/* ---- Badges panel ---- */
function renderBadgesPanel() {
  const el = $('badgesGrid');
  if (!el || !partCache) return;
  const s = partCache.stats || {};
  const bids = s.total_bids || 0, won = s.won_count || 0, created = s.created_count || 0;
  const defs = [
    { id: 'shopaholic', emoji: '🛒', name: 'Покупатель', desc: 'За успешные победы в аукционах',
      levels: [{ name:'Bronze',req:1,cur:won,reward_xp:30,reward_gems:3},{name:'Silver',req:5,cur:won,reward_xp:150,reward_gems:10},{name:'Gold',req:20,cur:won,reward_xp:500,reward_gems:30}] },
    { id: 'bidder', emoji: '🎯', name: 'Участник', desc: 'За активное участие в торгах',
      levels: [{ name:'Bronze',req:5,cur:bids,reward_xp:20,reward_gems:2},{name:'Silver',req:25,cur:bids,reward_xp:100,reward_gems:8},{name:'Gold',req:100,cur:bids,reward_xp:400,reward_gems:25}] },
    { id: 'seller', emoji: '📦', name: 'Продавец', desc: 'За создание лотов на платформе',
      levels: [{ name:'Bronze',req:1,cur:created,reward_xp:25,reward_gems:3},{name:'Silver',req:5,cur:created,reward_xp:200,reward_gems:12},{name:'Gold',req:15,cur:created,reward_xp:600,reward_gems:35}] },
  ];
  el.innerHTML = defs.map(badge => {
    let curLevel = null, nextLevel = null;
    for (let i = badge.levels.length - 1; i >= 0; i--) {
      if (badge.levels[i].cur >= badge.levels[i].req) { curLevel = badge.levels[i]; break; }
    }
    for (let i = 0; i < badge.levels.length; i++) {
      if (badge.levels[i].cur < badge.levels[i].req) { nextLevel = badge.levels[i]; break; }
    }
    const display = nextLevel || curLevel || badge.levels[0];
    const tierRaw = (curLevel?.name || 'locked').toLowerCase();
    const tier = tierRaw === 'locked' ? 'locked' : tierRaw;
    const pct = display ? Math.min(100, Math.round((display.cur / display.req) * 100)) : 0;
    const dotsFilled = curLevel ? (badge.levels.indexOf(curLevel) + 1) : 0;
    return `
      <div class="badge-row">
        <div class="badge-icon-wrap">
          <div class="badge-circle ${tier}">${badge.emoji}</div>
          <div class="badge-level-name ${tier}">${tier === 'locked' ? 'Locked' : curLevel?.name || ''}</div>
          <div class="badge-dots">
            ${Array.from({length:5},(_,i) => `<div class="badge-dot${i < dotsFilled ? ` filled ${tier}` : ''}"></div>`).join('')}
          </div>
        </div>
        <div class="badge-info">
          <div class="badge-name">${badge.name}</div>
          <div class="badge-level-tag ${tier}">${tier === 'locked' ? 'LOCKED' : curLevel?.name.toUpperCase()}</div>
          <div class="badge-rewards">
            <span class="badge-reward"><span class="r-icon">⭐</span> ${display.reward_xp} опыта</span>
            <span class="badge-reward"><span class="r-icon">💎</span> ${display.reward_gems} алмазов</span>
          </div>
          <div class="badge-progress-label">Выполнено: ${pct}% (${display.cur}/${display.req})</div>
          <div class="badge-progress-track">
            <div class="badge-progress-fill ${tier}" style="width:${pct}%"></div>
          </div>
          <div class="badge-progress-desc">${badge.desc}</div>
        </div>
      </div>`;
  }).join('');
}

/* ---- Active bids ---- */
function fmtTimer(sec) {
  if (sec <= 0) return 'Завершён';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}ч ${m}м`;
  if (m > 0) return `${m}м ${s}с`;
  return `${s}с`;
}

function renderActiveBids(items, container) {
  const c = $(container);
  if (!c) return;
  if (!items.length) {
    c.innerHTML = `<div class="part-empty"><div class="part-empty-icon">🔥</div>Нет активных ставок</div>`;
    return;
  }
  c.innerHTML = `<div class="active-bids-grid">${items.map(i => {
    const cur = Number(i.current_price || 0);
    const my  = Number(i.my_bid || 0);
    const sec = Number(i.time_remaining || 0);
    const winning = i.is_winning;

    const timerCls = sec < 300 ? 'urgent' : sec < 3600 ? 'soon' : 'normal';
    const timerIcon = sec < 300 ? '🔴' : sec < 3600 ? '🟡' : '⏱';

    const imgHtml = i.image_url
      ? `<img src="${esc(i.image_url.startsWith('http') ? i.image_url : API + i.image_url)}" onerror="this.style.display='none'">`
      : `<div class="active-bid-thumb-ph">🖼️</div>`;

    return `
      <div class="active-bid-card ${winning ? 'winning' : 'losing'}">
        <div class="active-bid-thumb">${imgHtml}</div>
        <div class="active-bid-body">
          <div class="active-bid-title">${esc(i.title)}</div>
          <div class="active-bid-prices">
            <div>
              <div class="active-bid-price-label">Моя ставка</div>
              <div class="active-bid-price-val my">${fmtMoney(my)}</div>
            </div>
            <div>
              <div class="active-bid-price-label">Текущая</div>
              <div class="active-bid-price-val ${winning ? 'cur-win' : 'cur-lose'}">${fmtMoney(cur)}</div>
            </div>
          </div>
          <div class="active-bid-timer ${timerCls}">${timerIcon} ${fmtTimer(sec)}</div>
        </div>
        <div class="active-bid-right">
          ${winning
            ? '<span class="badge badge-green">🏁 Лидируете</span>'
            : '<span class="badge badge-amber">⚡ Перебили</span>'}
          <a class="part-link" href="auction.html?id=${i.auction_id}">Открыть ↗</a>
        </div>
      </div>`;
  }).join('')}</div>`;
}

/* ---- My bids panel ---- */
function showBidsTab(name) {
  document.querySelectorAll('.settings-tab[data-btab]').forEach(t => t.classList.toggle('active', t.dataset.btab === name));
  ['active','won','lost'].forEach(n => {
    const el = document.getElementById(`btab-${n}`);
    if (el) el.style.display = n === name ? 'block' : 'none';
  });
}

function renderMyBidsPanel() {
  if (!partCache) return;
  renderActiveBids(partCache.active_bids || [], 'listActive');
  renderList('won');
  renderList('lost');
}

/* ---- My lots tabs ---- */
function showCreatedTab(name) {
  document.querySelectorAll('.settings-tab[data-ctab]').forEach(t => t.classList.toggle('active', t.dataset.ctab === name));
  ['active-offers','finished-offers'].forEach(n => {
    const el = document.getElementById(`ctab-${n}`);
    if (el) el.style.display = n === name ? 'block' : 'none';
  });
}

function renderCreatedList(items, containerId, emptyIcon, emptyText) {
  const c = $(containerId);
  if (!c) return;
  if (!items.length) {
    c.innerHTML = `<div class="part-empty"><div class="part-empty-icon">${emptyIcon}</div>${esc(emptyText)}</div>`;
    return;
  }
  c.innerHTML = items.map(i => {
    const cur = Number(i.current_price || 0);
    const badge = i.is_active
      ? '<span class="badge badge-blue">🟢 Активен</span>'
      : (i.winner_id
          ? '<span class="badge badge-green">✅ Продан</span>'
          : '<span class="badge badge-amber">⏹ Завершён</span>');
    const sub = `Текущая: ${fmtMoney(cur)} · Старт: ${fmtMoney(i.starting_price)}`;
    const imgUrl = i.image_url
      ? `<img src="${esc(i.image_url.startsWith('http') ? i.image_url : API + i.image_url)}" onerror="this.style.display='none'">`
      : '🖼️';
    return `
      <div class="part-item">
        <div class="part-thumb">${imgUrl}</div>
        <div class="part-body">
          <div class="part-item-title">${esc(i.title)}</div>
          <div class="part-item-sub">${esc(sub)} · ${i.bids_count} ставок</div>
        </div>
        <div class="part-item-right">
          ${badge}
          <a class="part-link" href="auction.html?id=${i.auction_id}">Открыть ↗</a>
          ${i.is_active && !i.bids_count ? `<a class="part-link" href="auction.html?id=${i.auction_id}&edit=1" style="color:var(--accent);border-color:rgba(232,160,32,.3);">✏️ Изменить</a>` : ''}
        </div>
      </div>`;
  }).join('');
}

/* ---- Participation lists ---- */
function renderList(tab) {
  if (!partCache) return;
  if (tab === 'active') {
    renderActiveBids(partCache.active_bids || [], 'listActive');
    return;
  }
  const map = {
    won:     { items: partCache.won_auctions || [],     empty: 'Нет выигранных лотов',  emptyIcon: '🏆', container: 'listWon' },
    lost:    { items: partCache.lost_auctions || [],    empty: 'Нет проигранных лотов', emptyIcon: '💔', container: 'listLost' },
    created: { items: partCache.created_auctions || [], empty: 'Вы не создавали лоты',  emptyIcon: '📦', container: 'listCreatedActive' },
  };
  if (tab === 'created') {
    const all = partCache.created_auctions || [];
    renderCreatedList(all.filter(i => i.is_active),  'listCreatedActive',  '📦', 'Нет активных лотов');
    renderCreatedList(all.filter(i => !i.is_active), 'listCreatedFinished','⏹',  'Нет завершённых лотов');
    return;
  }
  const { items, empty, emptyIcon, container } = map[tab] || {};
  if (!container) return;
  const c = $(container);
  if (!c) return;
  if (!items.length) {
    c.innerHTML = `<div class="part-empty"><div class="part-empty-icon">${emptyIcon}</div>${esc(empty)}</div>`;
    return;
  }
  c.innerHTML = items.map(i => {
    const cur = Number(i.current_price || 0);
    const my  = Number(i.my_bid || 0);
    let badge = '';
    if (tab === 'active') badge = i.is_winning
      ? '<span class="badge badge-green">🏁 Лидируете</span>'
      : '<span class="badge badge-amber">⚡ Перебили</span>';
    else if (tab === 'won')  badge = '<span class="badge badge-green">🏆 Выиграно</span>';
    else if (tab === 'lost') badge = '<span class="badge badge-red">💔 Проиграно</span>';
    else badge = i.is_active
      ? '<span class="badge badge-blue">🟢 Активен</span>'
      : '<span class="badge badge-amber">⏹ Завершён</span>';
    const sub = tab === 'created'
      ? `Текущая: ${fmtMoney(cur)} · Старт: ${fmtMoney(i.starting_price)}`
      : `Ваша: ${fmtMoney(my)} · Текущая: ${fmtMoney(cur)}`;
    const imgUrl = i.image_url
      ? `<img src="${esc(i.image_url.startsWith('http') ? i.image_url : API + i.image_url)}" onerror="this.style.display='none'">`
      : '🖼️';
    return `
      <div class="part-item">
        <div class="part-thumb">${imgUrl}</div>
        <div class="part-body">
          <div class="part-item-title">${esc(i.title)}</div>
          <div class="part-item-sub">${esc(sub)}</div>
        </div>
        <div class="part-item-right">
          ${badge}
          <a class="part-link" href="auction.html?id=${i.auction_id}">Открыть ↗</a>
          ${tab === 'created' && i.is_active && !i.bids_count ? `<a class="part-link" href="auction.html?id=${i.auction_id}&edit=1" style="color:var(--accent);border-color:rgba(232,160,32,.3);">✏️ Изменить</a>` : ''}
        </div>
      </div>`;
  }).join('');
}

/* ---- Subscriptions ---- */
async function loadSubscriptions() {
  try {
    const r = await apiFetch(API + '/api/my/subscriptions');
    if (!r.ok) return;
    subsCache = await r.json();
  } catch {}
}
function renderSubs() {
  const c = $('listSubs');
  if (!c) return;
  if (subsCache === null) {
    c.innerHTML = '<div class="part-empty"><div class="part-empty-icon">🔔</div>Загрузка…</div>';
    loadSubscriptions().then(() => renderSubs());
    return;
  }
  if (!subsCache.length) {
    c.innerHTML = `<div class="part-empty"><div class="part-empty-icon">🔔</div>Вы не подписаны ни на одного продавца<br><small style="color:var(--text-3);margin-top:6px;display:block;">Подписывайтесь на продавцов со страницы лота</small></div>`;
    return;
  }
  c.innerHTML = subsCache.map(s => {
    const avg = s.avg_rating || 0;
    const stars = avg > 0
      ? [1,2,3,4,5].map(i => `<span style="color:${i<=Math.round(avg)?'var(--accent-2)':'var(--text-3)'}">★</span>`).join('')
      : '';
    const avatarSrc = resolveAvatarUrl(s.avatar_url);
    const avatarHtml = avatarSrc
      ? `<img src="${esc(avatarSrc)}" alt="${esc(s.username)}">`
      : (s.username||'?')[0].toUpperCase();
    const since = s.subscribed_at
      ? new Date(s.subscribed_at.endsWith('Z') ? s.subscribed_at : s.subscribed_at + 'Z')
          .toLocaleDateString('ru-RU', { day:'2-digit', month:'short', year:'numeric' })
      : '-';
    return `
      <div class="sub-seller-card">
        <div class="sub-seller-top">
          <div class="sub-seller-avatar">${avatarHtml}</div>
          <div style="min-width:0;">
            <div class="sub-seller-name">@${esc(s.username)}</div>
            <div class="sub-seller-since">Подписан с ${since}</div>
            ${stars ? `<div class="sub-seller-stars" title="${avg.toFixed(1)}">${stars} <span style="font-size:11px;color:var(--text-3);">${avg.toFixed(1)}</span></div>` : ''}
          </div>
        </div>
        <div class="sub-seller-stats">
          <div class="sub-stat">
            <div class="sub-stat-val">${s.lots_count}</div>
            <div class="sub-stat-label">Лотов</div>
          </div>
          <div class="sub-stat">
            <div class="sub-stat-val green">${s.active_lots_count ?? 0}</div>
            <div class="sub-stat-label">Активных</div>
          </div>
          <div class="sub-stat">
            <div class="sub-stat-val">${s.reviews_count}</div>
            <div class="sub-stat-label">Отзывов</div>
          </div>
        </div>
        <div class="sub-seller-actions">
          <a href="user.html?username=${encodeURIComponent(s.username)}" class="btn btn-secondary">Профиль ↗</a>
          <button class="sub-unsub-btn" onclick="unsubscribeFrom(${s.seller_id}, this)">Отписаться</button>
        </div>
      </div>`;
  }).join('');
}
async function unsubscribeFrom(sellerId, btn) {
  try {
    const r = await apiFetch(`${API}/api/sellers/${sellerId}/subscribe`, { method: 'DELETE' });
    if (r.ok) { subsCache = subsCache.filter(s => s.seller_id !== sellerId); renderSubs(); }
  } catch {}
}

/* ---- Timeline ---- */
function renderTimeline(data) {
  const tl = $('timeline');
  const events = [];
  (data.won_auctions||[]).slice(0,2).forEach(i => events.push({ type:'win', icon:'🏆', title:'Победа в аукционе', desc: i.title || '-' }));
  (data.active_bids||[]).slice(0,3).forEach(i => events.push({ type:'bid', icon:'🎯', title:'Активная ставка', desc: i.title || '-' }));
  (data.created_auctions||[]).slice(0,2).forEach(i => events.push({ type:'created', icon:'📦', title:'Создан лот', desc: i.title || '-' }));
  if (!events.length) { tl.innerHTML = '<div class="tl-empty">📋 Нет активности</div>'; return; }
  tl.innerHTML = events.slice(0,6).map(e => `
    <div class="tl-item">
      <div class="tl-icon ${e.type}">${e.icon}</div>
      <div class="tl-body">
        <div class="tl-title">${esc(String(e.title))}</div>
        <div class="tl-desc">${esc(String(e.desc))}</div>
      </div>
    </div>`).join('');
}

/* ---- Avatar upload ---- */
/* ---- Avatar crop & upload ---- */
let cropper = null;

function uploadAvatar(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = ''; // сбрасываем чтобы можно было выбрать тот же файл снова

  const reader = new FileReader();
  reader.onload = e => openCropModal(e.target.result);
  reader.readAsDataURL(file);
}

function openCropModal(src) {
  const img = $('cropImg');
  img.src = src;

  // Уничтожаем предыдущий кроппер если был
  if (cropper) { cropper.destroy(); cropper = null; }

  $('cropModal').classList.add('open');

  // Инициализируем Cropper после того как изображение загрузится
  img.onload = () => {
    cropper = new Cropper(img, {
      aspectRatio: 1,          // квадрат - для аватара
      viewMode: 1,
      dragMode: 'move',
      autoCropArea: 0.8,
      restore: false,
      guides: true,
      center: true,
      highlight: false,
      cropBoxMovable: true,
      cropBoxResizable: true,
      toggleDragModeOnDblclick: false,
    });
  };
  // Если картинка уже загружена (кеш)
  if (img.complete) img.onload();
}

function closeCropModal() {
  $('cropModal').classList.remove('open');
  if (cropper) { cropper.destroy(); cropper = null; }
}

async function confirmCrop() {
  if (!cropper) return;

  const btn = $('cropConfirmBtn');
  btn.disabled = true;
  btn.textContent = 'Загрузка…';

  try {
    // Получаем обрезанный canvas (256×256)
    const canvas = cropper.getCroppedCanvas({ width: 256, height: 256, imageSmoothingQuality: 'high' });

    // Конвертируем в Blob
    const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.9));

    // Показываем превью в аватаре сразу
    const previewSrc = canvas.toDataURL('image/jpeg', 0.9);
    applyAvatarPreview(previewSrc);

    closeCropModal();

    // Загружаем на сервер
    const formData = new FormData();
    formData.append('file', blob, 'avatar.jpg');

    const avatarEl = $('avatar');
    avatarEl.style.opacity = '0.6';

    const r = await apiFetch(`${API}/api/upload-avatar`, {
      method: 'POST',
      body: formData,
    });

    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      showToast('Ошибка', err.detail || 'Не удалось загрузить аватар', 'bad');
      // Откатываем превью
      removeAvatarImg();
    } else {
      const data = await r.json();
      const src = resolveAvatarUrl(data.avatar_url);
      // Обновляем src на финальный
      const img = $('avatar').querySelector('img');
      if (img) img.src = src;
      syncSettingsAvatar(src);
      showToast('Готово', 'Аватар обновлён', 'ok');
    }
  } catch {
    showToast('Ошибка', 'Нет связи с сервером', 'bad');
    removeAvatarImg();
  } finally {
    const avatarEl = $('avatar');
    if (avatarEl) avatarEl.style.opacity = '1';
    btn.disabled = false;
    btn.textContent = 'Применить';
  }
}

function applyAvatarPreview(src) {
  const old = $('avatar').querySelector('img');
  if (old) old.remove();
  const img = document.createElement('img');
  img.src = src;
  $('avatar').prepend(img);
}

function removeAvatarImg() {
  const img = $('avatar').querySelector('img');
  if (img) img.remove();
}

async function deleteAvatar() {
  try {
    const r = await apiFetch(`${API}/api/upload-avatar`, {
      method: 'DELETE',
    });
    if (r.ok) {
      // Убираем картинку из сайдбара
      const img = $('avatar').querySelector('img');
      if (img) img.remove();
      // Убираем из настроек
      const settingsAv = $('settingsAvatar');
      if (settingsAv) {
        const img2 = settingsAv.querySelector('img');
        if (img2) img2.remove();
        settingsAv.textContent = $('avatarLetter').textContent;
      }
      const delBtn = $('deleteAvatarBtn');
      if (delBtn) delBtn.style.display = 'none';
      showToast('Готово', 'Аватар удалён', 'ok');
    }
  } catch { showToast('Ошибка', 'Нет связи с сервером', 'bad'); }
}

function syncSettingsAvatar(src) {
  const settingsAv = $('settingsAvatar');
  if (!settingsAv) return;
  settingsAv.textContent = '';
  const img = document.createElement('img');
  img.src = src; img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
  settingsAv.appendChild(img);
  const delBtn = $('deleteAvatarBtn');
  if (delBtn) delBtn.style.display = '';
}

/* ================================================================
   BALANCE PANEL
   ================================================================ */
let txPage = 1, txHasMore = false;

const TX_META = {
  deposit:      { icon: '💳', label: 'Пополнение',         plus: true  },
  withdrawal:   { icon: '🏦', label: 'Вывод средств',      plus: false },
  bid_win:      { icon: '🏆', label: 'Победа в аукционе',  plus: false },
  auction_sale: { icon: '✅', label: 'Продажа лота',       plus: true  },
  bin_purchase: { icon: '⚡', label: 'Покупка BIN',        plus: false },
  commission:   { icon: '🧾', label: 'Комиссия платформы', plus: false },
};

function updateBalanceDisplay(val) {
  const v = Number(val).toFixed(2);
  if ($('bal'))             $('bal').textContent = v;
  if ($('balancePanelVal')) $('balancePanelVal').textContent = v;
  if ($('infoBalance'))     $('infoBalance').textContent = v + ' ₽';
  if ($('balBadge'))        $('balBadge').textContent = v + ' ₽';
  if ($('navBalancePill'))  $('navBalancePill').textContent = v;
}

async function loadBalance(reset = true) {
  if (reset) { txPage = 1; }
  try {
    const r = await apiFetch(`${API}/api/transactions?page=${txPage}&page_size=15`);
    if (!r.ok) return;
    const data = await r.json();

    updateBalanceDisplay(data.balance);
    if ($('txTotal')) $('txTotal').textContent = `Всего: ${data.total}`;

    txHasMore = txPage < data.total_pages;
    $('txLoadMore').style.display = txHasMore ? 'block' : 'none';

    const listEl = $('txList');
    if (data.items.length === 0 && txPage === 1) {
      listEl.innerHTML = `<div class="tx-empty"><div class="tx-empty-icon">📋</div>Операций пока нет</div>`;
      return;
    }

    const html = data.items.map(t => {
      const meta = TX_META[t.type] || { icon: '💰', label: t.type, plus: true };
      const sign = meta.plus ? '+' : '−';
      const cls  = meta.plus ? 'plus' : 'minus';
      const desc = t.description || meta.label;
      const utc  = t.created_at.endsWith('Z') ? t.created_at : t.created_at + 'Z';
      const date = new Date(utc).toLocaleString('ru-RU', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
      const auctionLink = t.auction_id
        ? `<a href="auction.html?id=${t.auction_id}" style="font-size:11px;color:var(--accent);margin-left:6px;">Открыть ↗</a>`
        : '';
      return `
        <div class="tx-item">
          <div class="tx-icon ${t.type}">${meta.icon}</div>
          <div class="tx-body">
            <div class="tx-desc">${esc(desc)}${auctionLink}</div>
            <div class="tx-date">${date}</div>
          </div>
          <div class="tx-right">
            <div class="tx-amount ${cls}">${sign}${Number(t.amount).toFixed(2)} ₽</div>
            <div class="tx-balance">Остаток: ${Number(t.balance_after).toFixed(2)} ₽</div>
          </div>
        </div>`;
    }).join('');

    if (reset) {
      listEl.innerHTML = html;
    } else {
      listEl.insertAdjacentHTML('beforeend', html);
    }
  } catch { if ($('txList')) $('txList').innerHTML = `<div class="tx-empty">Ошибка загрузки</div>`; }
}

async function loadMoreTx() {
  txPage++;
  await loadBalance(false);
}

function setAmount(type, val) {
  const inp = $(type === 'deposit' ? 'depositInput' : 'withdrawInput');
  if (val === 'all') {
    inp.value = Number($('bal').textContent || 0).toFixed(2);
  } else {
    inp.value = val;
  }
  // подсвечиваем пресет
  const presetsId = type === 'deposit' ? 'depositPresets' : 'withdrawPresets';
  document.querySelectorAll(`#${presetsId} .amount-preset`).forEach(b => {
    const bVal = b.textContent.replace(/[^0-9]/g, '');
    b.classList.toggle('sel', String(val) === bVal || val === 'all' && b.textContent === 'Всё');
  });
}

function clearPresets(type) {
  const presetsId = type === 'deposit' ? 'depositPresets' : 'withdrawPresets';
  document.querySelectorAll(`#${presetsId} .amount-preset`).forEach(b => b.classList.remove('sel'));
}

function focusDeposit()  { showPanel('balance'); setTimeout(() => $('depositInput').focus(), 200); }
function focusWithdraw() { showPanel('balance'); setTimeout(() => $('withdrawInput').focus(), 200); }

async function doDepositPanel() {
  const amount = Number($('depositInput').value);
  const result = $('depositResult');
  const btn = $('depositPanelBtn');
  result.className = 'balance-form-result';

  if (!amount || amount <= 0) {
    result.textContent = 'Введите корректную сумму'; result.className = 'balance-form-result err'; return;
  }
  btn.disabled = true; btn.textContent = 'Отправка…';
  try {
    const r = await apiFetch(`${API}/api/deposit`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Ошибка');
    updateBalanceDisplay(d.balance);
    $('depositInput').value = '';
    clearPresets('deposit');
    result.textContent = `✓ Баланс пополнен на ${amount.toFixed(2)} ₽`;
    result.className = 'balance-form-result ok';
    setTimeout(() => { result.className = 'balance-form-result'; }, 3000);
    // Обновляем историю
    txPage = 1; await loadBalance(true);
  } catch(e) {
    result.textContent = e.message; result.className = 'balance-form-result err';
  } finally { btn.disabled = false; btn.textContent = 'Пополнить'; }
}

async function doWithdraw() {
  const amount = Number($('withdrawInput').value);
  const result = $('withdrawResult');
  const btn = $('withdrawBtn');
  result.className = 'balance-form-result';

  if (!amount || amount <= 0) {
    result.textContent = 'Введите корректную сумму'; result.className = 'balance-form-result err'; return;
  }
  btn.disabled = true; btn.textContent = 'Отправка…';
  try {
    const r = await apiFetch(`${API}/api/withdraw`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Ошибка');
    updateBalanceDisplay(d.balance);
    $('withdrawInput').value = '';
    clearPresets('withdraw');
    result.textContent = `✓ Заявка на вывод ${amount.toFixed(2)} ₽ принята`;
    result.className = 'balance-form-result ok';
    setTimeout(() => { result.className = 'balance-form-result'; }, 3000);
    txPage = 1; await loadBalance(true);
  } catch(e) {
    result.textContent = e.message; result.className = 'balance-form-result err';
  } finally { btn.disabled = false; btn.textContent = 'Вывести'; }
}

/* ---- Init ---- */
async function load() {
  const r1 = await apiFetch(API + '/api/me');
  if (!r1.ok) { localStorage.removeItem('token'); location.href = 'index.html'; return; }
  const user = await r1.json();

  $('avatarLetter').textContent = (user.username[0] || '?').toUpperCase();
  // Синхронизируем miniAvatar в настройках
  const settingsAv = $('settingsAvatar');
  if (settingsAv) settingsAv.textContent = (user.username[0] || '?').toUpperCase();

  if (user.avatar_url) {
    const src = resolveAvatarUrl(user.avatar_url);
    const img = document.createElement('img');
    img.src = src; img.alt = user.username;
    $('avatar').prepend(img);
    // В настройках
    if (settingsAv) {
      settingsAv.textContent = '';
      const img2 = document.createElement('img');
      img2.src = src; img2.style.cssText = 'width:100%;height:100%;object-fit:cover;';
      settingsAv.appendChild(img2);
    }
    const delBtn = $('deleteAvatarBtn');
    if (delBtn) delBtn.style.display = '';
  }
  $('name').textContent   = user.username;
  $('email').textContent  = user.email;
  const pubLink = $('sbPublicProfileLink');
  if (pubLink && user.username) {
    pubLink.href = `user.html?username=${encodeURIComponent(user.username)}`;
    pubLink.style.display = '';
  }
  $('bal').textContent    = Number(user.balance || 0).toFixed(2);
  if ($('balBadge'))       $('balBadge').textContent = Number(user.balance || 0).toFixed(2) + ' ₽';
  document.title = `${user.username} - Лотус`;

  // Nav-пилюля
  const navPill = $('navUserPill');
  const navAv   = $('navAvatarPill');
  if ($('navUserNamePill')) $('navUserNamePill').textContent = user.username;
  if ($('navBalancePill'))  $('navBalancePill').textContent  = Number(user.balance || 0).toFixed(2);
  if (navAv) {
    if (user.avatar_url) {
      const src = resolveAvatarUrl(user.avatar_url);
      const img = document.createElement('img');
      img.src = src;
      img.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:50%;';
      navAv.innerHTML = ''; navAv.prepend(img);
    } else { navAv.textContent = (user.username[0] || '?').toUpperCase(); }
  }
  if (navPill) navPill.style.display = 'flex';

  if ($('infoUsername'))  $('infoUsername').textContent  = user.username || '-';
  if ($('infoEmail'))     $('infoEmail').textContent     = user.email    || '-';
  if ($('emailVerifiedBadge'))   $('emailVerifiedBadge').style.display   = user.email_verified ? 'inline-flex' : 'none';
  if ($('emailUnverifiedBadge')) $('emailUnverifiedBadge').style.display = user.email_verified ? 'none' : 'inline-flex';
  if ($('resendVerifyBtn'))      $('resendVerifyBtn').style.display      = user.email_verified ? 'none' : 'inline-flex';
  if ($('infoBalance'))   $('infoBalance').textContent   = Number(user.balance || 0).toFixed(2) + ' ₽';
  if ($('infoCreatedAt')) $('infoCreatedAt').textContent = user.created_at ? new Date(user.created_at + 'Z').toLocaleDateString('ru-RU') : '-';
  loadNotifSettings(user);
  initTheme();

  const r2 = await apiFetch(API + '/api/my/participation');
  if (!r2.ok) return;
  const data = await r2.json();

  const tb = data.stats.total_bids;
  const wc = data.stats.won_count;
  const lc = data.lost_auctions?.length || 0;
  const wr = (wc + lc) > 0 ? Math.round((wc / (wc + lc)) * 100) : 0;

  $('rate').textContent      = wr + '%';
  $('totalBids').textContent = tb;
  $('wonCount').textContent  = wc;
  if ($('lostCount')) $('lostCount').textContent = lc;

  partCache = data;
  renderMyBidsPanel();
  ['won','lost','created'].forEach(t => renderList(t));
  renderTimeline(data);
  makeChart(data);

  loadSubscriptions();

  try {
    const rn = await apiFetch(API + '/api/notifications/unread-count');
    if (rn.ok) {
      const nd = await rn.json();
      const cnt = nd.count || 0;
      const badge = $('sbNotifBadge');
      if (badge) { badge.textContent = cnt; badge.style.display = cnt ? 'flex' : 'none'; }
    }
  } catch {}
}

load().catch(err => {
  console.error('[profile.html] load failed:', err);
  const target = document.querySelector('.profile-right') || document.querySelector('.page');
  if (window.renderLoadError) {
    window.renderLoadError(target, 'Не удалось загрузить профиль', () => location.reload());
  }
}).finally(() => {
  initPanelFromHash();
  // Ждём пока canvas получит реальные размеры, затем рисуем
  const canvas = document.getElementById('chart');
  if (!canvas) return;
  const observer = new ResizeObserver(() => {
    if (canvas.offsetWidth > 0) {
      observer.disconnect();
      renderChart();
    }
  });
  observer.observe(canvas.parentElement);
  // Fallback - если панель уже видима
  setTimeout(() => { if (canvas.offsetWidth > 0) renderChart(); }, 100);
});

/* ================================================================
   DEPOSIT MODAL
   ================================================================ */
function openDeposit() {
  $('depositAmount').value = '';
  $('depositResult').style.display = 'none';
  $('depositResult').className = 'deposit-result';
  document.querySelectorAll('.deposit-preset').forEach(b => b.classList.remove('selected'));
  $('depositModal').classList.add('open');
  setTimeout(() => $('depositAmount').focus(), 150);
}
function closeDeposit() { $('depositModal').classList.remove('open'); }
function handleModalClick(e) { if (e.target === $('depositModal')) closeDeposit(); }
function selectPreset(val) {
  $('depositAmount').value = val;
  document.querySelectorAll('.deposit-preset').forEach(b => {
    b.classList.toggle('selected', Number(b.textContent.replace(/[^0-9]/g,'')) === val);
  });
}
function onDepositInput() {
  document.querySelectorAll('.deposit-preset').forEach(b => b.classList.remove('selected'));
}
async function doDeposit() {
  const raw = $('depositAmount').value;
  const amount = Number(raw);
  const result = $('depositResult');
  const btn = $('depositBtn');
  if (!raw || !Number.isFinite(amount) || amount <= 0) {
    result.textContent = 'Введите корректную сумму';
    result.className = 'deposit-result err'; result.style.display = 'block';
    return;
  }
  btn.disabled = true; btn.textContent = 'Отправка…'; result.style.display = 'none';
  try {
    const r = await apiFetch(API + '/api/deposit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount })
    });
    if (!r.ok) { const err = await r.json().catch(() => ({})); throw new Error(err.detail || 'Ошибка сервера'); }
    const data = await r.json();
    const newBalance = Number(data.balance).toFixed(2);

    updateBalanceDisplay(newBalance);
    const balEl = $('bal');
    balEl.classList.remove('balance-pop');
    void balEl.offsetWidth;
    balEl.classList.add('balance-pop');

    result.textContent = `✓ Баланс пополнен на ${amount.toFixed(2)} ₽. Новый: ${newBalance} ₽`;
    result.className = 'deposit-result ok'; result.style.display = 'block';
    $('depositAmount').value = '';
    document.querySelectorAll('.deposit-preset').forEach(b => b.classList.remove('selected'));
    // Обновляем историю если панель открыта
    if (document.getElementById('panel-balance')?.classList.contains('active')) {
      txPage = 1; loadBalance(true);
    }
    setTimeout(closeDeposit, 1800);
  } catch (e) {
    result.textContent = e.message || 'Не удалось пополнить баланс';
    result.className = 'deposit-result err'; result.style.display = 'block';
  } finally { btn.disabled = false; btn.textContent = 'Пополнить'; }
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDeposit(); });

async function resendVerification() {
  const btn = document.getElementById('resendVerifyBtn');
  if (!btn) return;
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = 'Отправка…';
  try {
    const r = await window.apiFetch(`${window.API}/api/verify-email/resend`, {
      method: 'POST',
    });
    if (r.ok) {
      window.showToast('Письмо отправлено', 'Проверьте почтовый ящик, ссылка действует 24 часа', 'ok');
    } else if (r.status === 429) {
      window.showToast('Слишком часто', 'Подождите и попробуйте позже', 'warn');
    } else {
      let detail = 'Не удалось отправить письмо';
      try {
        const data = await r.json();
        if (data && data.detail) detail = data.detail;
      } catch (_) {}
      window.showToast('Ошибка', detail, 'err');
    }
  } catch (_) {
    window.showToast('Нет связи', 'Попробуйте позже', 'err');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}


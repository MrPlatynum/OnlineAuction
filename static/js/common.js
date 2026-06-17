/* ================================================================
   Лотус - Common JS utilities
   Подключается ПЕРЕД per-page JS.
   Экспортирует: API, WS_BASE, esc, fmtMoney, fmtDate, fmtDateShort,
                 fmtMonthYear, apiFetch, getToken, resolveAvatarUrl,
                 showToast. Авто-инициализирует nav-колокольчик.
   ================================================================ */

// Theme bootstrap runs in its own IIFE BEFORE the main one so data-theme is set
// before first paint. Live in common.js so per-page scripts (index.js, profile.js)
// don't each need their own copy - the block was diverging already (index.js had
// `if(t==='auto') { ... }`, profile.js had `else if (t==='auto' && ...)`).
(function() {
  const t = localStorage.getItem('theme') || 'dark';
  if (t === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else if (t === 'auto' && !window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();

(function() {
  'use strict';

  // ---- API base / WS base ----
  window.API = window.location.origin;
  window.WS_BASE = window.location.origin.replace(/^http/i, 'ws');

  // ---- helpers ----
  // Exposed on window so per-page scripts can read the live token instead of
  // capturing localStorage.getItem('token') in a module-level const that goes
  // stale after login/logout in the same tab.
  window.getToken = function() { return localStorage.getItem('token'); };
  function getToken() { return window.getToken(); }

  // Avatar URLs come in two shapes: absolute (uploaded to a CDN or external host,
  // starts with http(s)) or path-relative ("/static/uploads/..."). Same dance was
  // copy-pasted in 11 places across 5 files; centralised here so a future hosting
  // tweak doesn't have to chase them all.
  window.resolveAvatarUrl = function(url) {
    if (!url) return null;
    // Require the full ``://`` so a value like ``"httpfoo"`` or a
    // malformed scheme can't slip past as "looks absolute". An attacker
    // can't pick avatar URLs today (server-set on upload), but the
    // predicate is the kind of thing that bites the second a path
    // changes upstream.
    return /^https?:\/\//i.test(url) ? url : window.API + url;
  };

  // Single logout entry point. Per-page scripts that need to tear down their own
  // resources (open WebSockets, intervals, in-memory caches) subscribe to the
  // 'lotus:logout' event - keeps page-specific cleanup local without forcing
  // each page to re-implement the token drop + redirect dance.
  window.logout = function() {
    try { window.dispatchEvent(new CustomEvent('lotus:logout')); } catch (_) {}
    try { localStorage.removeItem('token'); } catch (_) {}
    window.location.href = 'index.html';
  };

  // Shorthand for `document.getElementById` - per-page scripts used to
  // each declare their own `const $ = ...`. Exposed on window because
  // common.js loads before every per-page bundle.
  window.$ = (id) => document.getElementById(id);

  window.esc = function(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  };

  window.fmtMoney = function(n) {
    const num = Number(n);
    return Number.isFinite(num) ? num.toFixed(2) + ' ₽' : '-';
  };

  window.fmtDate = function(iso, opts) {
    if (!iso) return '';
    const utc = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
    return new Date(utc).toLocaleString('ru-RU', opts || {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  };

  // Short calendar date ("12 мая 2026") used in transaction lists, review
  // headers, and seller-profile metadata. Was a one-line copy in user.js,
  // profile.js (x2), and auction.js with subtly different option objects.
  window.fmtDateShort = function(iso) {
    if (!iso) return '';
    const utc = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
    return new Date(utc).toLocaleDateString('ru-RU', {
      day: '2-digit', month: 'short', year: 'numeric',
    });
  };

  // "С нами с май 2026" string in seller bios. user.js had its own fmtMonthYear,
  // auction.js inlined the same toLocaleDateString call.
  window.fmtMonthYear = function(iso) {
    if (!iso) return '';
    const utc = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
    return new Date(utc).toLocaleDateString('ru-RU', {
      month: 'long', year: 'numeric',
    });
  };

  // Reconnect backoff for WebSockets. Three per-page sockets (notifications
  // bell here in common.js, the index card grid, the auction-detail room)
  // had each grown their own copy of "exponential + half-jitter, cap 30s,
  // skip these close codes". The values drifted (auction.js capped at 8
  // attempts implicitly via 500*2^N, index.js had an explicit attempt
  // ceiling, common.js had neither) and the close-code allowlists grew
  // independently. Pull both knobs into one helper so a future tweak to
  // the cap or the policy-code list lands in one place.
  //
  // wsReconnectDelay(attempt, {start, cap}) returns a half-jittered delay
  // in ms for the given attempt number (0-indexed). Half-jitter keeps the
  // worst-case ceiling at `base` while still desynchronising N clients
  // that all dropped on the same server tick.
  window.wsReconnectDelay = function(attempt, opts) {
    const o = opts || {};
    const start = o.start || 1000;
    const cap = o.cap || 30000;
    const base = Math.min(start * Math.pow(2, attempt), cap);
    return base / 2 + Math.random() * (base / 2);
  };

  // wsIsFinalCloseCode(code) returns true for any close code where a
  // reconnect attempt would just hit the same wall (clean shutdown,
  // policy violation incl. tv-bump invalidation, internal error, auth
  // failure / forbidden on the protected sockets). Treat the union of
  // every per-socket allowlist as final - none of the codes apply on a
  // socket where they shouldn't, and unifying them prevents the drift.
  window.wsIsFinalCloseCode = function(code) {
    return code === 1000 || code === 1008 || code === 1011 ||
           code === 4001 || code === 4003;
  };

  window.apiFetch = function(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    const tk = getToken();
    if (tk) headers['Authorization'] = 'Bearer ' + tk;
    // Timeout (default 15s) via AbortController - keeps the request from
    // hanging indefinitely on a stalled connection.
    const ctrl = new AbortController();
    const timeoutMs = opts.timeout ?? 15000;
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const sig = opts.signal
      ? (function(a, b) { a.addEventListener('abort', () => b.abort()); return b.signal; })(opts.signal, ctrl)
      : ctrl.signal;
    return fetch(url, { ...opts, headers, signal: sig })
      .finally(() => clearTimeout(timer));
  };

  // FastAPI/Pydantic returns 422 with a detail array - each item shaped
  // {loc: ["body","field"], msg: "...", type: "..."}. The plain-4xx case
  // returns detail as a string. Boil both down to one user-facing line.
  const FIELD_RU = {
    title: 'Название',
    description: 'Описание',
    starting_price: 'Стартовая цена',
    bin_price: 'Цена «Купить сразу»',
    duration_minutes: 'Длительность',
    image_url: 'Изображение',
    image_urls: 'Изображения',
    category_id: 'Категория',
    auction_type: 'Тип лота',
    extend_minutes: 'Продление',
  };
  function _humanizePydanticItem(it) {
    const loc = Array.isArray(it.loc) ? it.loc : [];
    const field = loc.length > 1 ? loc[loc.length - 1] : (loc[0] || '');
    const ru = FIELD_RU[field] || field;
    const m = (it.msg || '').toLowerCase();
    if (m.includes('string should have at most')) {
      const maxMatch = (it.ctx && it.ctx.max_length) || (it.msg.match(/at most (\d+)/) || [])[1];
      return `${ru}: слишком длинно${maxMatch ? ` (макс. ${maxMatch} симв.)` : ''}`;
    }
    if (m.includes('string should have at least')) {
      return `${ru}: обязательное поле`;
    }
    if (m.includes('greater than') || m.includes('input should be greater')) {
      return `${ru}: должно быть больше 0`;
    }
    if (m.includes('less than or equal') || m.includes('less than')) {
      return `${ru}: значение слишком большое`;
    }
    if (m.includes('field required') || m.includes('missing')) {
      return `${ru}: обязательное поле`;
    }
    if (m.includes('url must be')) {
      return `${ru}: некорректный URL`;
    }
    if (m.includes('input should be')) {
      return `${ru}: недопустимое значение`;
    }
    return `${ru}: ${it.msg || 'ошибка валидации'}`;
  }
  window.formatError = function(err, fallback) {
    const detail = err && err.detail;
    if (Array.isArray(detail)) {
      return detail.map(_humanizePydanticItem).join('; ') || (fallback || 'Ошибка валидации');
    }
    if (typeof detail === 'string') return detail;
    // Rare case: detail is an object (hand-rolled HTTPException with a
    // dict body) or there's no detail at all and only err.message is set.
    // Don't fall silent.
    if (detail && typeof detail === 'object') {
      if (typeof detail.msg === 'string') return detail.msg;
      try { return JSON.stringify(detail); } catch { /* fallthrough */ }
    }
    if (err && typeof err.message === 'string' && err.message) return err.message;
    return fallback || 'Ошибка';
  };

  // Switch any block container into a "load failed" state with a retry button.
  window.renderLoadError = function(container, msg, onRetry) {
    if (!container) return;
    const id = 'lotusRetryBtn_' + Math.random().toString(36).slice(2, 8);
    container.innerHTML =
      `<div class="load-error">` +
        `<div class="load-error-icon">⚠️</div>` +
        `<div class="load-error-title">${window.esc(msg || 'Не удалось загрузить данные')}</div>` +
        `<div class="load-error-sub">Проверьте соединение или попробуйте ещё раз.</div>` +
        (onRetry ? `<button id="${id}" class="btn btn-secondary" type="button">Повторить</button>` : '') +
      `</div>`;
    if (onRetry) {
      const b = document.getElementById(id);
      if (b) b.addEventListener('click', onRetry, { once: true });
    }
  };

  // Placeholder for sections that aren't built yet.
  window.comingSoon = function(name) {
    window.showToast('Скоро', name ? `Раздел «${name}» в разработке` : 'Раздел в разработке', 'info');
  };

  // ---- Toast ----
  function ensureToastEl() {
    let el = document.getElementById('lotusToast');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'lotusToast';
    el.className = 'lotus-toast';
    el.innerHTML =
      '<span class="lotus-toast-dot"></span>' +
      '<div class="lotus-toast-body">' +
        '<div class="lotus-toast-title"></div>' +
        '<div class="lotus-toast-msg"></div>' +
      '</div>';
    document.body.appendChild(el);
    return el;
  }

  let toastTimer = null;
  /**
   * showToast(title, msg, tone)
   *   tone: 'info' | 'ok' | 'warn' | 'bad'
   */
  window.showToast = function(title, msg, tone) {
    const el = ensureToastEl();
    el.querySelector('.lotus-toast-title').textContent = String(title ?? '');
    el.querySelector('.lotus-toast-msg').textContent = String(msg ?? '');
    const dot = el.querySelector('.lotus-toast-dot');
    dot.style.background =
      tone === 'ok'   ? 'var(--green)' :
      tone === 'warn' ? 'var(--amber)' :
      tone === 'bad'  ? 'var(--red)'   :
                        'var(--accent)';
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
  };

  // ================================================================
  // Platform commission cache - fetched once per page load from
  // /api/platform and reused by every payout-hint helper on the page.
  // Default falls back to 7%, matching the server-side default in
  // app/config.py so the UI keeps showing a plausible figure when the
  // network blip happens.
  // ================================================================
  let _platformCommissionPromise = null;
  window.getPlatformCommission = function() {
    if (_platformCommissionPromise) return _platformCommissionPromise;
    _platformCommissionPromise = fetch(`${window.API}/api/platform`)
      .then(r => r.ok ? r.json() : null)
      .then(d => (d && typeof d.commission_percent === 'number') ? d.commission_percent : 7)
      .catch(() => 7);
    return _platformCommissionPromise;
  };

  /**
   * attachPayoutHint(inputEl, hintEl, options?)
   *
   * Wires a price input to a hint element so the seller sees, in real
   * time, how much will land on their balance after the platform
   * takes its commission. Idempotent - calling twice with the same
   * input just re-binds the listener.
   *
   * options.label  - leading word in the hint, defaults to "К получению".
   *                  For BID start-price use "Со стартовой цены" so the
   *                  copy doesn't mislead about the final settled amount.
   */
  window.attachPayoutHint = function(inputEl, hintEl, options) {
    if (!inputEl || !hintEl) return;
    const label = (options && options.label) || 'К получению';
    window.getPlatformCommission().then(pct => {
      const pctLabel = Number.isInteger(pct) ? pct : pct.toFixed(1);
      const update = () => {
        const gross = Number(inputEl.value);
        if (!Number.isFinite(gross) || gross <= 0) {
          hintEl.hidden = true;
          return;
        }
        const net = gross * (1 - pct / 100);
        hintEl.hidden = false;
        hintEl.innerHTML =
          `${label}: <span class="payout-net">${window.fmtMoney(net)} ₽</span> ` +
          `<span class="payout-rate">(комиссия ${pctLabel}%)</span>`;
      };
      inputEl.addEventListener('input', update);
      // Run once so a pre-filled input (edit modal opening with the
      // current price) shows the hint without a keystroke.
      update();
    });
  };

  // ================================================================
  // Notification bell - auto-init when #notifBtn is present on the page.
  // ================================================================
  function initNotifBell() {
    const btn      = document.getElementById('notifBtn');
    const dropdown = document.getElementById('notifDropdown');
    if (!btn || !dropdown) return;

    const list       = document.getElementById('notifList');
    const badge      = document.getElementById('notifBadge');
    const markAllBtn = document.getElementById('notifMarkAll');

    let unreadCount = 0;
    let isOpen = false;
    let wsNotif = null;
    let currentUserId = null;
    let notifReconnectAttempts = 0;
    // Handle for the 60s unread-count poll. Held so cross-tab token
    // changes (each one re-runs ``start()``) don't stack a new
    // setInterval on top of the previous - without this the polling
    // count grows linearly with the number of cross-tab logins.
    let pollHandle = null;

    const ICONS = {
      bid_outbid:     '⚡',
      bid_placed:     '💰',
      auction_won:    '🏆',
      auction_lost:   '😔',
      auction_sold:   '✅',
      new_lot:        '🔖',
      auction_ending: '⏰',
    };

    function fmtAge(iso) {
      const utc = iso && !String(iso).endsWith('Z') && !String(iso).includes('+') ? iso + 'Z' : iso;
      const diff = Math.floor((Date.now() - new Date(utc)) / 1000);
      if (diff < 60)    return 'только что';
      if (diff < 3600)  return `${Math.floor(diff/60)} мин назад`;
      if (diff < 86400) return `${Math.floor(diff/3600)} ч назад`;
      return new Date(utc).toLocaleDateString('ru-RU', { day:'2-digit', month:'2-digit' });
    }

    function setCount(n) {
      unreadCount = Math.max(0, n);
      if (unreadCount > 0) {
        if (badge) {
          badge.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
          badge.style.display = 'flex';
        }
        btn.classList.add('has-unread');
      } else {
        if (badge) badge.style.display = 'none';
        btn.classList.remove('has-unread');
      }
    }

    function renderList(items) {
      if (!list) return;
      if (!items || !items.length) {
        list.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Уведомлений пока нет</div>`;
        return;
      }
      list.innerHTML = items.map(n => {
        const ico = ICONS[n.type] || '🔔';
        return (
          `<div class="notif-item ${n.is_read ? '' : 'unread'}" data-id="${n.id}" data-auction="${n.auction_id || ''}">` +
            `<div class="notif-icon ${n.type || ''}">${ico}</div>` +
            `<div class="notif-body">` +
              `<div class="notif-title">${window.esc(n.title)}</div>` +
              `<div class="notif-msg">${window.esc(n.message)}</div>` +
              `<div class="notif-time">${fmtAge(n.created_at)}</div>` +
            `</div>` +
          `</div>`
        );
      }).join('');
    }

    async function fetchCount() {
      if (!getToken()) return;
      try {
        const r = await window.apiFetch(`${window.API}/api/notifications/unread-count`);
        if (r.ok) {
          const d = await r.json();
          setCount(d.count ?? 0);
        }
      } catch {
        // Bell badge is decorative - if the count fetch times out or
        // the user is offline, keep the current value rather than
        // surfacing an unhandled rejection.
      }
    }

    async function fetchNotifications() {
      if (!list) return;
      if (!getToken()) {
        list.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Войдите</div>`;
        return;
      }
      list.innerHTML = `<div class="notif-empty">Загрузка…</div>`;
      try {
        const r = await window.apiFetch(`${window.API}/api/notifications?limit=30`);
        if (r.ok) {
          const body = await r.json();
          // GET /api/notifications now returns {items,total,limit,offset}.
          // Keep the bare-list fallback so an old proxy/cached response
          // (or a future revert) doesn't blow up the bell dropdown.
          renderList(Array.isArray(body) ? body : (body.items || []));
        }
        else list.innerHTML = `<div class="notif-empty">Ошибка</div>`;
      } catch {
        list.innerHTML = `<div class="notif-empty">Нет связи</div>`;
      }
    }

    async function markAllRead() {
      try {
        await window.apiFetch(`${window.API}/api/notifications/mark-all-read`, { method: 'POST' });
        setCount(0);
        await fetchNotifications();
      } catch {
        // Same story as fetchCount - user can retry by tapping the bell.
      }
    }

    function openDropdown()  { isOpen = true;  dropdown.classList.add('open'); fetchNotifications(); }
    function closeDropdown() { isOpen = false; dropdown.classList.remove('open'); }

    btn.addEventListener('click', e => { e.stopPropagation(); isOpen ? closeDropdown() : openDropdown(); });
    document.addEventListener('click', e => {
      if (isOpen && !dropdown.contains(e.target) && e.target !== btn && !btn.contains(e.target)) closeDropdown();
    });
    if (markAllBtn) markAllBtn.addEventListener('click', e => { e.stopPropagation(); markAllRead(); });

    if (list) {
      list.addEventListener('click', async e => {
        const item = e.target.closest('.notif-item');
        if (!item) return;
        const id = item.dataset.id;
        const aId = item.dataset.auction;
        if (id && item.classList.contains('unread')) {
          item.classList.remove('unread');
          setCount(unreadCount - 1);
          // Optimistically flip the unread class first - if the POST
          // fails the worst case is a stale "unread" badge that the
          // next page load will reconcile against the server.
          try { await window.apiFetch(`${window.API}/api/notifications/${id}/read`, { method: 'POST' }); } catch {}
        }
        if (aId) {
          closeDropdown();
          window.location.href = `auction.html?id=${aId}`;
        }
      });
    }

    function connectNotifWS(userId) {
      // Drop any half-open socket from a prior connect attempt. .close()
      // on a CLOSED/CLOSING socket throws InvalidStateError in some
      // browsers - irrelevant for the reconnect, swallow.
      if (wsNotif) { try { wsNotif.close(); } catch {} }
      const tk = getToken();
      if (!tk) return;
      // Token rides as a Sec-WebSocket-Protocol subprotocol so it never
      // lands in URLs (proxy access logs, browser history). Server echoes
      // back 'bearer' on accept.
      wsNotif = new WebSocket(`${window.WS_BASE}/ws/notifications/${userId}`, ['bearer', tk]);
      wsNotif.onopen = () => { notifReconnectAttempts = 0; };
      wsNotif.onmessage = e => {
        try {
          const d = JSON.parse(e.data);
          if (d.type === 'notification') {
            setCount(unreadCount + 1);
            if (isOpen) fetchNotifications();
          }
        } catch {
          // Server only ever sends JSON; if it doesn't parse, ignore
          // the frame rather than tearing down the socket - the next
          // valid frame works fine.
        }
      };
      wsNotif.onclose = (e) => {
        // Skip reconnect on final-codes (clean shutdown, auth-failure,
        // tv-bump invalidation) - retrying the same token would just
        // re-hit the wall.
        if (e && window.wsIsFinalCloseCode(e.code)) {
          return;
        }
        const jittered = window.wsReconnectDelay(notifReconnectAttempts, { start: 1500 });
        notifReconnectAttempts++;
        setTimeout(() => { if (currentUserId) connectNotifWS(currentUserId); }, jittered);
      };
    }

    async function start() {
      if (!getToken()) { btn.style.display = 'none'; return; }
      btn.style.display = 'flex';
      await fetchCount();
      try {
        const r = await window.apiFetch(`${window.API}/api/me`);
        if (r.ok) {
          const me = await r.json();
          currentUserId = me.id;
          if (currentUserId) connectNotifWS(currentUserId);
        }
      } catch {
        // /me fails → WebSocket stays off. Polling below still keeps
        // the badge up to date until the user logs in again.
      }
      if (pollHandle !== null) clearInterval(pollHandle);
      pollHandle = setInterval(fetchCount, 60000);
    }

    setTimeout(start, 800);
    window.addEventListener('storage', e => { if (e.key === 'token') setTimeout(start, 300); });
  }

  // Auto-init notif bell
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNotifBell);
  } else {
    initNotifBell();
  }
})();

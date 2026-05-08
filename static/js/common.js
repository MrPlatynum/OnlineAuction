/* ================================================================
   Лотус — Common JS utilities
   Подключается ПЕРЕД per-page JS.
   Экспортирует: API, WS_BASE, esc, fmtMoney, fmtDate, apiFetch,
                 showToast. Авто-инициализирует nav-колокольчик.
   ================================================================ */
(function() {
  'use strict';

  // ---- API base / WS base ----
  window.API = window.location.origin;
  window.WS_BASE = window.location.origin.replace(/^http/i, 'ws');

  // ---- helpers ----
  function getToken() { return localStorage.getItem('token'); }

  window.esc = function(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  };

  window.fmtMoney = function(n) {
    const num = Number(n);
    return Number.isFinite(num) ? '$' + num.toFixed(2) : '—';
  };

  window.fmtDate = function(iso, opts) {
    if (!iso) return '';
    const utc = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
    return new Date(utc).toLocaleString('ru-RU', opts || {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  };

  window.apiFetch = function(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    const tk = getToken();
    if (tk) headers['Authorization'] = 'Bearer ' + tk;
    // Timeout (default 15s) через AbortController — чтобы не висеть бесконечно
    const ctrl = new AbortController();
    const timeoutMs = opts.timeout ?? 15000;
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const sig = opts.signal
      ? (function(a, b) { a.addEventListener('abort', () => b.abort()); return b.signal; })(opts.signal, ctrl)
      : ctrl.signal;
    return fetch(url, { ...opts, headers, signal: sig })
      .finally(() => clearTimeout(timer));
  };

  // Перенаправляет любой блок-контейнер в состояние «не удалось загрузить» с кнопкой повтора
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

  // Заглушка для будущих разделов
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
  // Notification bell — авто-инициализация при наличии #notifBtn
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
    let reconnectDelay = 1500;

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
      } catch {}
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
        if (r.ok) renderList(await r.json());
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
      } catch {}
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
          try { await window.apiFetch(`${window.API}/api/notifications/${id}/read`, { method: 'POST' }); } catch {}
        }
        if (aId) {
          closeDropdown();
          window.location.href = `auction.html?id=${aId}`;
        }
      });
    }

    function connectNotifWS(userId) {
      if (wsNotif) { try { wsNotif.close(); } catch {} }
      const tk = getToken();
      if (!tk) return;
      wsNotif = new WebSocket(`${window.WS_BASE}/ws/notifications/${userId}?token=${encodeURIComponent(tk)}`);
      wsNotif.onopen = () => { reconnectDelay = 1500; };
      wsNotif.onmessage = e => {
        try {
          const d = JSON.parse(e.data);
          if (d.type === 'notification') {
            setCount(unreadCount + 1);
            if (isOpen) fetchNotifications();
          }
        } catch {}
      };
      wsNotif.onclose = () => {
        // Half-jitter on the exponential backoff: if the server drops
        // every connection at once (deploy, restart) clients reconnect
        // spread across [delay/2, delay] instead of all on the same tick.
        const jittered = reconnectDelay / 2 + Math.random() * (reconnectDelay / 2);
        setTimeout(() => { if (currentUserId) connectNotifWS(currentUserId); }, jittered);
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
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
      } catch {}
      setInterval(fetchCount, 60000);
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

/* ================================================================
   Лотус — index page init bundle
   Five IIFEs that used to live as inline <script> blocks at the end
   of index.html. Extracted so CSP can ship with ``script-src 'self'``
   without ``'unsafe-inline'`` — inline event handlers and inline
   <script> tags would both be blocked otherwise.
   ================================================================ */

// ---- Hero stat: live count of active auctions ----
(function () {
  const el = document.getElementById('statActive');
  if (!el) return;

  const animate = (to) => {
    const dur = 900, t0 = performance.now();
    const fmt = (n) => n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(Math.round(to * eased));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  fetch('/api/auctions?status=active&page=1&page_size=1')
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d && typeof d.total === 'number') animate(d.total); })
    .catch(() => {});
})();

// ---- Featured strip: ending soon ----
(function () {
  const section = document.getElementById('featuredStrip');
  const scroll = document.getElementById('featuredScroll');
  const prevBtn = document.getElementById('featuredPrev');
  const nextBtn = document.getElementById('featuredNext');
  if (!section || !scroll) return;

  const fmt = (sec) => {
    if (sec <= 0) return 'завершён';
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (d > 0) return `${d}д ${h}ч`;
    if (h > 0) return `${h}ч ${String(m).padStart(2, '0')}м`;
    if (m > 0) return `${m}:${String(s).padStart(2, '0')}`;
    return `0:${String(s).padStart(2, '0')}`;
  };

  const urgencyClass = (sec) => {
    if (sec <= 0) return 'ended';
    if (sec < 3600) return 'critical';
    if (sec < 21600) return 'urgent';
    return 'normal';
  };

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  const fmtPrice = (p) => {
    const n = Number(p);
    if (!isFinite(n)) return p;
    return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  };

  const updateArrows = () => {
    const max = scroll.scrollWidth - scroll.clientWidth;
    prevBtn.disabled = scroll.scrollLeft <= 2;
    nextBtn.disabled = scroll.scrollLeft >= max - 2;
  };

  const tick = () => {
    const now = Date.now();
    scroll.querySelectorAll('.featured-card').forEach((card) => {
      const end = parseInt(card.dataset.end, 10);
      if (!end) return;
      const sec = Math.floor((end - now) / 1000);
      const t = card.querySelector('.featured-timer-text');
      if (t) t.textContent = fmt(sec);
      const b = card.querySelector('.featured-timer');
      if (b) {
        b.classList.remove('ended', 'critical', 'urgent', 'normal');
        b.classList.add(urgencyClass(sec));
      }
    });
  };

  const render = (items) => {
    if (!items || !items.length) { section.hidden = true; return; }
    section.hidden = false;

    // Используем time_remaining от сервера (он считает в UTC корректно).
    // end_time в API — naive-UTC без 'Z', поэтому браузер парсит его как
    // локальное время и таймер «уезжает» на UTC-offset.
    const baseTs = Date.now();
    scroll.innerHTML = items.map((a) => {
      const remaining = Number.isFinite(a.time_remaining) ? a.time_remaining : 0;
      const end = baseTs + remaining * 1000;
      const sec = Math.max(0, remaining);
      const cls = urgencyClass(sec);

      const cover = (a.image_urls && a.image_urls[0]) || a.image_url;
      const coverUrl = cover
        ? (String(cover).startsWith('http') ? cover : (window.location.origin + cover))
        : null;

      const imgInner = coverUrl
        ? `<img src="${escapeHtml(coverUrl)}" alt="" loading="lazy">`
        : `<div class="featured-ph">${a.category && a.category.icon ? a.category.icon : '🏷️'}</div>`;

      const typeBadge = a.auction_type === 'bin'
        ? `<span class="featured-type bin">⚡ BIN</span>`
        : `<span class="featured-type bid">🔨 BID</span>`;

      return `
        <a class="featured-card" href="auction.html?id=${a.id}" data-end="${end}">
          <div class="featured-img">
            ${imgInner}
            <div class="featured-timer ${cls}">
              <span class="featured-pulse"></span>
              <span class="featured-timer-text">${fmt(sec)}</span>
            </div>
            ${typeBadge}
          </div>
          <div class="featured-body">
            <div class="featured-card-title">${escapeHtml(a.title)}</div>
            <div class="featured-card-meta">
              <span class="featured-card-price">${fmtPrice(a.current_price)}</span>
              <span class="featured-card-bids">${a.bids_count || 0} ст.</span>
            </div>
          </div>
        </a>
      `;
    }).join('');

    requestAnimationFrame(updateArrows);
  };

  // Scroll arrows
  prevBtn.addEventListener('click', () => {
    scroll.scrollBy({ left: -scroll.clientWidth * 0.8, behavior: 'smooth' });
  });
  nextBtn.addEventListener('click', () => {
    scroll.scrollBy({ left: scroll.clientWidth * 0.8, behavior: 'smooth' });
  });
  scroll.addEventListener('scroll', updateArrows, { passive: true });
  window.addEventListener('resize', updateArrows);

  // Fetch + render
  fetch('/api/auctions?status=active&sort_by=time&page=1&page_size=12')
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d && d.items) render(d.items); })
    .catch(() => { section.hidden = true; });

  // Live countdown
  setInterval(tick, 1000);
})();

// ---- Custom dropdown (sidebar sort) ----
(function () {
  document.querySelectorAll('.fs-dropdown').forEach((dd) => {
    const trigger = dd.querySelector('.fs-dd-trigger');
    const menu = dd.querySelector('.fs-dd-menu');
    const current = dd.querySelector('.fs-dd-current');
    const native = dd.querySelector('.fs-dd-native');
    const opts = dd.querySelectorAll('.fs-dd-opt');

    const close = () => {
      dd.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
    };
    const open = () => {
      document.querySelectorAll('.fs-dropdown.open').forEach((o) => o.classList.remove('open'));
      dd.classList.add('open');
      trigger.setAttribute('aria-expanded', 'true');
    };
    const select = (value) => {
      opts.forEach((o) => {
        const sel = o.dataset.value === value;
        o.classList.toggle('is-selected', sel);
        o.setAttribute('aria-selected', sel ? 'true' : 'false');
        if (sel) current.textContent = o.querySelector('.fs-dd-opt-label').textContent;
      });
      if (native && native.value !== value) {
        native.value = value;
        native.dispatchEvent(new Event('change', { bubbles: true }));
      }
    };

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      dd.classList.contains('open') ? close() : open();
    });

    opts.forEach((o) => {
      o.addEventListener('click', () => { select(o.dataset.value); close(); });
    });

    document.addEventListener('click', (e) => {
      if (!dd.contains(e.target)) close();
    });

    document.addEventListener('keydown', (e) => {
      if (!dd.classList.contains('open')) return;
      if (e.key === 'Escape') { close(); trigger.focus(); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const list = Array.from(opts);
        const idx = list.findIndex((o) => o.classList.contains('is-selected'));
        const nextIdx = e.key === 'ArrowDown'
          ? (idx + 1) % list.length
          : (idx - 1 + list.length) % list.length;
        select(list[nextIdx].dataset.value);
      }
      if (e.key === 'Enter') close();
    });

    // Initial sync
    if (native) select(native.value);
  });
})();

// ---- Custom number steppers (sidebar price filter) ----
(function () {
  document.querySelectorAll('.fs-num-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = btn.closest('.fs-num').querySelector('input[type=number]');
      if (!input) return;
      if (btn.dataset.step === 'up') input.stepUp(); else input.stepDown();
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
})();

// ---- Reveal-on-scroll for hero + footer + cards ----
(function () {
  if (!('IntersectionObserver' in window)) return;
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add('reveal-in');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.08 });
  document.querySelectorAll('.reveal').forEach((el) => io.observe(el));
})();

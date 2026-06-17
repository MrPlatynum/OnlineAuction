const token = window.getToken();

// fmtMonthYear / fmtDateShort come from common.js (window.fmtMonthYear /
// window.fmtDateShort). The shared versions normalise naive-UTC server
// timestamps via a trailing 'Z' before formatting, so a user in a non-UTC
// timezone no longer sees the displayed day shifted by their offset for
// dates near the midnight boundary - the old local copies skipped that
// step and inherited the browser's localisation.
function fmtTimer(sec) {
  if (!sec || sec <= 0) return null;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}д ${h}ч`;
  if (h > 0) return `${h}ч ${m}м`;
  return `${m}м`;
}
function starsHtml(n) {
  return [1,2,3,4,5].map(i => `<span class="star${i <= Math.round(n) ? ' on' : ''}">★</span>`).join('');
}
function ago(iso) {
  const utc = iso && !iso.endsWith('Z') ? iso + 'Z' : iso;
  const days = Math.floor((Date.now() - new Date(utc)) / 86400000);
  if (days === 0) return 'сегодня';
  if (days === 1) return 'вчера';
  if (days < 7)   return `${days} дн. назад`;
  if (days < 30)  return `${Math.floor(days/7)} нед. назад`;
  if (days < 365) return `${Math.floor(days/30)} мес. назад`;
  return `${Math.floor(days/365)} г. назад`;
}
function pluralReviews(n) {
  const m = n % 100;
  if (m >= 11 && m <= 14) return 'отзывов';
  const m1 = n % 10;
  if (m1 === 1) return 'отзыв';
  if (m1 >= 2 && m1 <= 4) return 'отзыва';
  return 'отзывов';
}

const params = new URLSearchParams(location.search);
const username = params.get('username') || params.get('user') || '';
if (!username) showNotFound('Пользователь не указан');

let sellerId = null, isSubscribed = false;
let allReviews = [], currentFilter = 'all';

async function init() {
  if (!username) return;
  try {
    const r = await apiFetch(`${API}/api/users/${encodeURIComponent(username)}`);
    if (!r.ok) { showNotFound('Пользователь не найден'); return; }
    await render(await r.json());
  } catch (e) {
    console.error('[user.html] load failed:', e);
    showNotFound('Ошибка загрузки');
  }
}

async function render(data) {
  const { user, auctions, stats } = data;
  sellerId = user.id;
  document.title = `${user.username} - Лотус`;
  document.getElementById('crumbName').textContent = user.username;

  const isMe = token && (() => {
    try {
      // JWTs are URL-safe base64 (RFC 7515): ``-`` instead of ``+``,
      // ``_`` instead of ``/``, and padding is allowed to be omitted.
      // Browser ``atob`` only accepts standard base64, so translate
      // the characters and pad the length to a multiple of 4. Without
      // this an otherwise valid token with one of those characters
      // throws InvalidCharacterError, the catch hides the failure and
      // ``isMe`` silently falls back to false - the user sees the
      // "Subscribe" button on their own profile page.
      let b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      const p = JSON.parse(atob(b64));
      return p.user_id === user.id;
    } catch { return false; }
  })();
  const activeLots    = (auctions || []).filter(a => a.is_active);
  const completedLots = (auctions || []).filter(a => !a.is_active).slice(0, 8);
  const totalDecided  = stats.won_count + stats.lost_count;
  const winRate       = totalDecided > 0 ? Math.round(stats.won_count / totalDecided * 100) : null;
  const avatarBig = resolveAvatarUrl(user.avatar_url);

  let subHtml = '';
  if (!isMe && token) {
    try {
      const rs = await apiFetch(`${API}/api/sellers/${user.id}/subscription`);
      if (rs.ok) { const sd = await rs.json(); isSubscribed = sd.subscribed; subHtml = renderSubBtn(isSubscribed); }
    } catch {}
  }

  // Reviews
  let reviewData = null;
  try {
    const rr = await apiFetch(`${API}/api/sellers/${user.id}/reviews`);
    if (rr.ok) reviewData = await rr.json();
  } catch {}
  allReviews = reviewData?.reviews || [];
  const rstats = reviewData?.stats || { total: 0, avg: 0, distribution: {} };
  const dist = rstats.distribution || {};
  const posCount = (+dist[4] || 0) + (+dist[5] || 0);
  const pctPos = rstats.total ? Math.round((posCount / rstats.total) * 100) : 0;

  document.getElementById('page').innerHTML = `
    <!-- ===== HERO ===== -->
    <div class="profile-header">
      <div class="ph-body">
        <div class="ph-avatar">
          ${avatarBig
            ? `<img src="${esc(avatarBig)}" alt="${esc(user.username)}">`
            : esc((user.username[0] || '?').toUpperCase())}
        </div>
        <div class="ph-info">
          <div class="ph-name">
            ${esc(user.username)}
            <span class="ph-name-handle">@${esc(user.username)}</span>
          </div>
          <div class="ph-meta-row">
            <span>📅 На сайте с <span class="meta-strong">${fmtMonthYear(user.created_at)}</span></span>
            <span>📦 <span class="meta-strong">${stats.created_count}</span> ${stats.created_count === 1 ? 'лот' : 'лотов'}</span>
            <span>🏆 <span class="meta-strong">${stats.won_count}</span> побед</span>
            ${winRate !== null ? `<span>🎯 Винрейт <span class="meta-strong">${winRate}%</span></span>` : ''}
          </div>
        </div>
        <div class="ph-right">
          ${subHtml ? `<span id="subBtnWrap">${subHtml}</span>` : ''}
          ${isMe ? `<a href="profile.html" class="btn btn-primary btn-sm">Мой профиль</a>` : ''}
          <a href="index.html?created_by=${encodeURIComponent(user.username)}" class="btn btn-secondary btn-sm">Все лоты →</a>
        </div>
      </div>
    </div>

    <!-- ===== RATING SPOTLIGHT (full width) ===== -->
    ${rstats.total > 0 ? `
    <div class="rating-spotlight">
      <div class="rs-score">
        <div class="rs-num">${rstats.avg.toFixed(1)}</div>
        <div class="rs-stars">${starsHtml(rstats.avg)}</div>
        <div class="rs-count">${rstats.total} ${pluralReviews(rstats.total)}</div>
      </div>
      <div class="rs-side">
        <div class="rs-bars">${renderRatingBars(dist, rstats.total)}</div>
        <span class="rs-pct">${pctPos}% положительных</span>
      </div>
    </div>
    ` : ''}

    <!-- ===== SECTION: Active lots ===== -->
    <div class="profile-section" id="section-lots">
      <div class="profile-section-head">
        <div class="profile-section-title">
          Активные лоты
          <span class="count">${activeLots.length}</span>
        </div>
        ${activeLots.length > 6
          ? `<a class="profile-section-link" href="index.html?created_by=${encodeURIComponent(user.username)}">Все →</a>`
          : ''}
      </div>
      ${activeLots.length === 0
        ? `<div class="empty-msg"><div class="empty-msg-icon">📭</div>Нет активных лотов</div>`
        : `<div class="lots-grid">${activeLots.slice(0, 6).map(renderActiveLot).join('')}</div>`}
    </div>

    ${completedLots.length > 0 ? `
    <!-- ===== SECTION: Completed ===== -->
    <div class="profile-section" id="section-completed">
      <div class="profile-section-head">
        <div class="profile-section-title">
          Завершённые
          <span class="count">${completedLots.length}</span>
        </div>
        <a class="profile-section-link" href="index.html?created_by=${encodeURIComponent(user.username)}&status=completed">Все →</a>
      </div>
      <div>${completedLots.map(renderCompletedRow).join('')}</div>
    </div>
    ` : ''}

    <!-- ===== SECTION: Reviews ===== -->
    <div class="profile-section" id="section-reviews">
      <div class="profile-section-head">
        <div class="profile-section-title">
          Отзывы
          <span class="count">${rstats.total}</span>
        </div>
      </div>
      ${rstats.total > 0 ? `
        <div class="rev-filter" id="userRevFilter">
          <button class="rev-pill active" data-rating="all" type="button" onclick="filterReviewsByRating('all',this)">
            Все <span class="rev-pill-count">${rstats.total}</span>
          </button>
          ${[5,4,3,2,1].map(n => `
            <button class="rev-pill" data-rating="${n}" type="button" ${(dist[n]||0) === 0 ? 'disabled' : ''} onclick="filterReviewsByRating(${n},this)">
              ${n}<span class="rev-pill-star">★</span> <span class="rev-pill-count">${dist[n]||0}</span>
            </button>
          `).join('')}
        </div>
        <div class="review-feed" id="reviewsContainer"></div>
      ` : `<div class="empty-msg"><div class="empty-msg-icon">📝</div>Отзывов пока нет</div>`}
    </div>
  `;

  if (rstats.total > 0) renderReviews();
  // Deep-link: #reviews smoothly scrolls to the reviews section.
  if (location.hash === '#reviews') {
    setTimeout(() => document.getElementById('section-reviews')?.scrollIntoView({ behavior: 'smooth' }), 200);
  }
}

function renderRatingBars(dist, total) {
  return [5,4,3,2,1].map(rating => {
    const count = +dist[rating] || 0;
    const pct = total ? (count / total * 100) : 0;
    const cls = rating >= 4 ? '' : rating <= 2 ? 'low' : 'mid';
    return `
      <div class="rs-bar-row">
        <span class="rs-bar-label">${rating}<span class="star-glyph">★</span></span>
        <div class="rs-bar-track"><div class="rs-bar-fill ${cls}" style="width:${pct}%"></div></div>
        <span class="rs-bar-count">${count}</span>
      </div>`;
  }).join('');
}

function renderActiveLot(a) {
  const timer = fmtTimer(a.time_remaining ?? null);
  return `
    <a class="lot-mini" href="auction.html?id=${a.id}">
      <div class="lot-mini-thumb">
        ${a.image_url
          ? `<img src="${esc(a.image_url.startsWith('http') ? a.image_url : API + a.image_url)}" alt="">`
          : '🏷️'}
        <span class="lot-mini-status">LIVE</span>
        ${timer ? `<span class="lot-mini-timer">⏱ ${timer}</span>` : ''}
      </div>
      <div class="lot-mini-body">
        <div class="lot-mini-title">${esc(a.title)}</div>
        <div class="lot-mini-price">${fmtMoney(a.current_price)}</div>
      </div>
    </a>`;
}

function renderCompletedRow(a) {
  return `
    <a class="lot-row" href="auction.html?id=${a.id}">
      <div class="lot-row-thumb">
        ${a.image_url
          ? `<img src="${esc(a.image_url.startsWith('http') ? a.image_url : API + a.image_url)}" alt="">`
          : '🏷️'}
      </div>
      <div class="lot-row-body">
        <div class="lot-row-title">${esc(a.title)}</div>
        <div class="lot-row-meta">${fmtDateShort(a.end_time)}${a.winner_id ? ' · продано' : ' · не продано'}</div>
      </div>
      <div class="lot-row-price">${fmtMoney(a.current_price)}</div>
    </a>`;
}

function filterReviewsByRating(rating, btn) {
  currentFilter = rating;
  document.querySelectorAll('.rev-pill').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderReviews();
}

function renderReviews() {
  const el = document.getElementById('reviewsContainer');
  if (!el) return;
  const filtered = currentFilter === 'all'
    ? allReviews
    : allReviews.filter(r => r.rating === currentFilter);

  if (!filtered.length) {
    const msg = currentFilter === 'all'
      ? 'У этого продавца пока нет отзывов'
      : `Нет отзывов с оценкой ${currentFilter}★`;
    el.innerHTML = `<div class="empty-msg"><div class="empty-msg-icon">📝</div>${msg}</div>`;
    return;
  }

  el.innerHTML = filtered.map(rev => {
    const tone = rev.rating >= 4 ? 'positive' : rev.rating <= 2 ? 'negative' : 'neutral';
    const numCls = rev.rating >= 4 ? '' : rev.rating <= 2 ? 'low' : 'mid';
    const avaSrc = resolveAvatarUrl(rev.reviewer_avatar_url);
    const avaHtml = avaSrc
      ? `<img src="${esc(avaSrc)}" alt="">`
      : esc((rev.reviewer_username || '?')[0].toUpperCase());
    const auctionLink = rev.auction_id && rev.auction_title
      ? `<a class="rc-lot" href="auction.html?id=${rev.auction_id}" title="${esc(rev.auction_title)}">
          <span class="rc-lot-icon">🔨</span>${esc(rev.auction_title)}
         </a>`
      : '';
    const stars = [1,2,3,4,5].map(i => `<span class="review-star${i <= rev.rating ? ' on' : ''}">★</span>`).join('');

    return `<div class="review-card ${tone}">
      <div class="rc-head">
        <div class="rc-avatar">${avaHtml}</div>
        <div class="rc-meta">
          <span class="rc-author">${esc(rev.reviewer_username)}</span>
          <span class="rc-date">${ago(rev.created_at)}</span>
        </div>
        <div class="rc-rating">
          <span class="rc-rating-num ${numCls}">${rev.rating}.0</span>
          <div class="rc-stars">${stars}</div>
        </div>
      </div>
      ${rev.comment ? `<div class="rc-text">${esc(rev.comment)}</div>` : ''}
      ${auctionLink}
    </div>`;
  }).join('');
}

function renderSubBtn(sub) {
  return `<button class="sub-btn${sub ? ' subscribed' : ''}" onclick="toggleSub()" id="subBtn">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
      <circle cx="9" cy="7" r="4"/>
      ${sub
        ? `<line x1="22" y1="11" x2="16" y2="11"/>`
        : `<line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>`}
    </svg>
    ${sub ? 'Отписаться' : 'Подписаться'}
  </button>`;
}

async function toggleSub() {
  if (!token || !sellerId) return;
  try {
    const r = await apiFetch(`${API}/api/sellers/${sellerId}/subscribe`, {
      method: isSubscribed ? 'DELETE' : 'POST',
    });
    if (r.ok) {
      isSubscribed = !isSubscribed;
      const w = document.getElementById('subBtnWrap');
      if (w) w.innerHTML = renderSubBtn(isSubscribed);
      showToast(isSubscribed ? 'Подписка оформлена' : 'Подписка отменена', '', 'ok');
    }
  } catch {
    showToast('Ошибка', 'Не удалось обновить подписку', 'bad');
  }
}

function showNotFound(msg) {
  const page = document.getElementById('page');
  if (!page) return;
  page.innerHTML = `
    <div class="not-found">
      <div class="not-found-icon">👤</div>
      <div class="not-found-title">${esc(msg)}</div>
      <div class="not-found-sub">Проверьте ссылку или вернитесь к списку аукционов.</div>
      <a href="index.html" class="btn btn-secondary">← К аукционам</a>
    </div>`;
}

window.filterReviewsByRating = filterReviewsByRating;
window.toggleSub = toggleSub;

init();

(function(){
  const t = localStorage.getItem('theme') || 'dark';
  if (t === 'light') document.documentElement.setAttribute('data-theme','light');
  else if (t === 'auto') {
    if (!window.matchMedia('(prefers-color-scheme: dark)').matches)
      document.documentElement.setAttribute('data-theme','light');
  }
})();

// Mobile nav
function openMobileNav() { document.getElementById('mobileNav').classList.add('open'); }
function closeMobileNavFull() { document.getElementById('mobileNav').classList.remove('open'); }
function closeMobileNav(e) {
  if (e.target === document.getElementById('mobileNav')) closeMobileNavFull();
}

// Status filter buttons
function setStatus(el, status) {
  document.querySelectorAll('[data-status]').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  if (typeof currentFilters !== 'undefined') {
    currentFilters.status = status;
    currentFilters.page = 1;
    if (typeof loadAuctions === 'function') loadAuctions();
  }
}

function onSortChange() { /* применяется через кнопку Применить */ }
function onCategoryChange() { /* применяется через selectCategory */ }

// Записать текущие фильтры в URL (без перезагрузки страницы).
// Параметры опускаются, если соответствуют дефолтному значению,
// чтобы «чистая» главная давала чистый адрес index.html.
window.syncUrlFromFilters = function() {
  if (typeof currentFilters === 'undefined') return;
  const f = currentFilters;
  const p = new URLSearchParams();
  if (f.status && f.status !== 'active')   p.set('status',       f.status);
  if (f.search)                            p.set('search',       f.search);
  if (f.category)                          p.set('category',     f.category);
  if (f.minPrice)                          p.set('min_price',    f.minPrice);
  if (f.maxPrice)                          p.set('max_price',    f.maxPrice);
  if (f.createdBy)                         p.set('created_by',   f.createdBy);
  if (f.auctionType)                       p.set('auction_type', f.auctionType);
  if (f.sortBy && f.sortBy !== 'time')     p.set('sort_by',      f.sortBy);
  if (f.page && f.page > 1)                p.set('page',         f.page);
  const qs = p.toString();
  const newUrl = location.pathname + (qs ? '?' + qs : '') + location.hash;
  if (newUrl === location.pathname + location.search + location.hash) return;
  // pushState (а не replaceState), чтобы Back/Forward работали как
  // ожидает пользователь — каждый коммит фильтра = отдельная запись
  // истории. popstate-обработчик ниже перезагружает страницу: проще
  // и надёжнее чем дублировать всю логику UI-sync из init-IIFE.
  history.pushState({ filters: true }, '', newUrl);
};

// При навигации Back/Forward — перезагружаем страницу, чтобы инициализация
// полностью отработала по новой URL. Альтернатива — вручную синхронизировать
// все инпуты/чекбоксы/активные классы/breadcrumb — на ~80 строк кода больше
// и легче расходится с init IIFE.
window.addEventListener('popstate', () => {
  // Защита от случая, когда наша же pushState внутри loadAuctions
  // как-то прокатилась — реальный popstate всегда несёт state≠null от нас
  // или null от первой записи. Перезагрузка идемпотентна в обоих случаях.
  location.reload();
});

document.addEventListener('DOMContentLoaded', () => setTimeout(loadCategories, 150));

// Fetch the live platform constants and reflect the seller commission
// in the hero strip. Falls back silently to the hard-coded "7%" already
// in the HTML if the endpoint is unreachable — the page must not break
// because a marketing badge couldn't update.
document.addEventListener('DOMContentLoaded', async () => {
  const el = document.getElementById('statCommission');
  if (!el) return;
  try {
    const r = await fetch(`${API_URL}/api/platform`);
    if (!r.ok) return;
    const data = await r.json();
    if (typeof data.commission_percent === 'number') {
      // Integer percent looks better in the marketing strip; the
      // backend stores Decimal so we render whatever it ships.
      const pct = Number.isInteger(data.commission_percent)
        ? data.commission_percent
        : data.commission_percent.toFixed(1);
      el.textContent = `${pct}%`;
    }
  } catch {
    /* keep the hard-coded fallback */
  }
});

// Загрузка категорий с сервера
// ===== Search History =====
const SEARCH_HISTORY_KEY = 'auction_search_history';
const SEARCH_HISTORY_MAX = 8;

function getSearchHistory() {
  try { return JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY)) || []; } catch { return []; }
}

function saveSearchHistory() {
  try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(getSearchHistory())); } catch {}
}

function addToSearchHistory(query) {
  if (!query || query.length < 2) return;
  let history = getSearchHistory().filter(q => q !== query);
  history.unshift(query);
  if (history.length > SEARCH_HISTORY_MAX) history = history.slice(0, SEARCH_HISTORY_MAX);
  try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history)); } catch {}
}

function removeFromSearchHistory(query) {
  const history = getSearchHistory().filter(q => q !== query);
  try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history)); } catch {}
  renderSearchHistory();
}

window.clearSearchHistory = function() {
  try { localStorage.removeItem(SEARCH_HISTORY_KEY); } catch {}
  hideSearchHistory();
}

function renderSearchHistory() {
  const list = document.getElementById('shList');
  const history = getSearchHistory();
  if (!list) return;
  if (!history.length) {
    list.innerHTML = '<div class="sh-empty">История пуста</div>';
    return;
  }
  list.innerHTML = history.map(q => {
    const safe = esc(q);
    return `<div class="sh-item" data-query="${safe}" onclick="applyHistorySearch(this.dataset.query)">
      <span class="sh-item-icon">🕐</span>
      <span class="sh-item-text">${safe}</span>
      <button class="sh-item-del" onclick="event.stopPropagation();removeFromSearchHistory(this.parentElement.dataset.query)">×</button>
    </div>`;
  }).join('');
}

function showSearchHistory() {
  const el = document.getElementById('searchHistory');
  if (!el) return;
  renderSearchHistory();
  el.style.display = 'block';
}

function hideSearchHistory() {
  const el = document.getElementById('searchHistory');
  if (el) el.style.display = 'none';
}

window.applyHistorySearch = function(query) {
  const input = document.getElementById('searchInput');
  if (input) {
    input.value = query;
    input.dispatchEvent(new Event('input'));
  }
  hideSearchHistory();
  if (typeof currentFilters !== 'undefined') {
    currentFilters.search = query;
    currentFilters.page = 1;
  }
  addToSearchHistory(query);
  if (typeof window.renderFilterTags === 'function') window.renderFilterTags();
  if (typeof loadAuctions === 'function') loadAuctions();
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('searchInput');
  const wrap  = document.getElementById('searchWrap');

  if (input) {
    // Показать историю при фокусе
    input.addEventListener('focus', () => {
      if (!input.value) showSearchHistory();
    });
    // Скрыть при вводе (показываем только когда поле пустое)
    input.addEventListener('input', () => {
      if (input.value) hideSearchHistory();
      else showSearchHistory();
    });
  }

  // Скрыть при клике вне
  document.addEventListener('click', e => {
    const nav = document.querySelector('.nav-search');
    if (nav && !nav.contains(e.target)) hideSearchHistory();
  });
});


window.currentAuctionType = 'bid';

function setAuctionType(type) {
  window.currentAuctionType = type;
  document.querySelectorAll('.type-tab').forEach(t => t.classList.toggle('active', t.dataset.type === type));

  const isBin = type === 'bin';
  const hint  = document.getElementById('auctionTypeHint');
  if (hint) hint.textContent = isBin
    ? 'Фиксированная цена — первый покупатель забирает лот'
    : 'Покупатели делают ставки — побеждает наибольшая';

  const bidFields = document.getElementById('bidFields');
  const binFields = document.getElementById('binFields');
  if (bidFields) bidFields.style.display = isBin ? 'none' : 'block';
  if (binFields) binFields.style.display = isBin ? 'block' : 'none';
}


async function loadCategories() {
  const apiBase = (typeof API_URL !== 'undefined' ? API_URL : null)
               || (typeof API !== 'undefined' ? API : null)
               || window.location.origin;
  try {
    const r = await fetch(`${apiBase}/api/categories`);
    if (!r.ok) return;
    const cats = await r.json();

    // Заполняем боковую панель — дерево категорий
    const listEl = document.getElementById('fsCatList');
    if (listEl) {
      // Убираем дубли если уже есть
      listEl.querySelectorAll('.fs-cat-item:not([data-slug=""]),.fs-cat-subs').forEach(e => e.remove());
      cats.forEach(cat => {
        const btn = document.createElement('button');
        btn.className = 'fs-cat-item';
        btn.dataset.slug = cat.slug;
        btn.textContent = cat.name;
        btn.onclick = () => selectCategory(btn, cat.slug, null, cat.name, null);
        listEl.appendChild(btn);

        if (cat.children && cat.children.length) {
          const subs = document.createElement('div');
          subs.className = 'fs-cat-subs';
          subs.id = `subs-${cat.slug}`;
          subs.style.display = 'none';
          cat.children.forEach(ch => {
            const sb = document.createElement('button');
            sb.className = 'fs-sub-item';
            sb.dataset.slug = ch.slug;
            sb.dataset.parent = cat.slug;
            sb.textContent = ch.name;
            sb.onclick = () => selectCategory(sb, ch.slug, cat.slug, ch.name, cat.name);
            subs.appendChild(sb);
          });
          listEl.appendChild(subs);
        }
      });
    }

    // Восстановить визуальное состояние выбранной категории из URL.
    // Без этого после reload чип «📂 …» отрисуется по slug, но активная
    // кнопка в сайдбаре и breadcrumb не подсветятся.
    if (typeof currentFilters !== 'undefined' && currentFilters.category && listEl) {
      const slug = currentFilters.category;
      let parentSlug = null, parentName = null, name = slug;
      let sub = null, parent = null;
      for (const cat of cats) {
        if (cat.slug === slug) { parent = cat; name = cat.name; break; }
        if (cat.children) {
          const ch = cat.children.find(c => c.slug === slug);
          if (ch) { sub = ch; parent = cat; parentSlug = cat.slug; parentName = cat.name; name = ch.name; break; }
        }
      }
      if (parent || sub) {
        document.querySelectorAll('.fs-cat-item,.fs-sub-item').forEach(b => b.classList.remove('active'));
        const sel = listEl.querySelector(
          sub ? `.fs-sub-item[data-slug="${CSS.escape(slug)}"]`
              : `.fs-cat-item[data-slug="${CSS.escape(slug)}"]`
        );
        if (sel) sel.classList.add('active');
        const containerSlug = parentSlug || slug;
        const subs = document.getElementById(`subs-${containerSlug}`);
        if (subs) subs.style.display = 'block';
        currentFilters.categoryName = name;
        currentFilters.categoryParentSlug = parentSlug;
        currentFilters.categoryParentName = parentName;
        currentFilters.categoryLabel = parentName ? `${parentName} → ${name}` : name;
      } else {
        // Slug из URL не найден в каталоге (категория удалена / переименована).
        // Сбрасываем фильтр, иначе сервер ответит пустым результатом, а чип
        // будет залипать со slug'ом, не имеющим смысла для пользователя.
        currentFilters.category = '';
        currentFilters.categoryName = '';
        currentFilters.categoryParentSlug = null;
        currentFilters.categoryParentName = null;
        currentFilters.categoryLabel = '';
        if (typeof showToast === 'function') {
          showToast('Категория не найдена', 'Фильтр по категории сброшен.', 'warn');
        }
      }
      if (typeof window.renderFilterTags === 'function') window.renderFilterTags();
      if (typeof window.syncUrlFromFilters === 'function') window.syncUrlFromFilters();
    }

    // Двухшаговый пикер категорий в форме создания
    window._catsData = cats; // кэшируем для sub-select
    const parentSel = document.getElementById('auctionCategoryParent');
    const subSel    = document.getElementById('auctionCategory');
    if (parentSel && parentSel.options.length <= 1) {
      cats.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat.id;
        opt.dataset.slug = cat.slug;
        opt.textContent = cat.name;
        parentSel.appendChild(opt);
      });
      parentSel.addEventListener('change', () => {
        const catId = +parentSel.value;
        const cat = cats.find(c => c.id === catId);
        subSel.innerHTML = '<option value="">— Вся категория —</option>';
        if (cat && cat.children && cat.children.length) {
          cat.children.forEach(ch => {
            const o = document.createElement('option');
            o.value = ch.id; o.textContent = ch.name;
            subSel.appendChild(o);
          });
          subSel.style.display = 'block';
        } else {
          subSel.style.display = 'none';
        }
        // Если нет подкатегорий — sub = parent
        if (!cat || !cat.children || !cat.children.length) {
          subSel.value = parentSel.value || '';
        } else {
          subSel.value = '';
        }
      });
    }
  } catch(e) { console.warn('loadCategories error:', e); }
}

window.applyFilters = function() {
  if (typeof currentFilters === 'undefined') return;
  const searchVal = document.getElementById('searchInput')?.value.trim() || '';
  if (searchVal) addToSearchHistory(searchVal);
  hideSearchHistory();
  currentFilters.search    = searchVal;
  currentFilters.minPrice  = document.getElementById('minPrice')?.value || null;
  currentFilters.maxPrice  = document.getElementById('maxPrice')?.value || null;
  currentFilters.createdBy = document.getElementById('creatorInput')?.value.trim() || '';
  currentFilters.sortBy    = document.getElementById('sortFilter')?.value || 'time';
  currentFilters.page = 1;

  const bidChecked = document.getElementById('filterBid')?.checked;
  const binChecked = document.getElementById('filterBin')?.checked;
  if (bidChecked && !binChecked)       currentFilters.auctionType = 'bid';
  else if (binChecked && !bidChecked)  currentFilters.auctionType = 'bin';
  else                                 currentFilters.auctionType = '';

  window.renderFilterTags();
  if (typeof loadAuctions === 'function') loadAuctions();
}

window.selectCategory = function(el, slug, parentSlug, name, parentName) {
  document.querySelectorAll('.fs-cat-item,.fs-sub-item').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.fs-cat-subs').forEach(s => s.style.display = 'none');
  if (parentSlug) {
    const subs = document.getElementById(`subs-${parentSlug}`);
    if (subs) subs.style.display = 'block';
  } else if (slug) {
    const subs = document.getElementById(`subs-${slug}`);
    if (subs) subs.style.display = 'block';
  }
  if (typeof currentFilters !== 'undefined') {
    currentFilters.category = slug;
    currentFilters.categoryLabel = parentName
      ? `${parentName} → ${name}`
      : (name || slug);
    currentFilters.categoryName   = name || slug;
    currentFilters.categoryParentSlug  = parentSlug || null;
    currentFilters.categoryParentName  = parentName || null;
    currentFilters.page = 1;
  }
  window.renderFilterTags();
  if (typeof loadAuctions === 'function') loadAuctions();
}

window.renderFilterTags = function() {
  const el = document.getElementById('filterTags');
  if (!el || typeof currentFilters === 'undefined') return;
  const tags = [];
  if (currentFilters.search)     tags.push({ label: `🔍 ${esc(currentFilters.search)}`, key: 'search' });
  if (currentFilters.category) {
    const parentSlug = currentFilters.categoryParentSlug;
    const parentName = currentFilters.categoryParentName;
    // Имена приходят из loadCategories асинхронно (~150мс задержка после
    // DOMContentLoaded). До этого либо если slug отсутствует в каталоге,
    // имя пустое — показываем сам slug как fallback, иначе чип будет
    // выглядеть пустым «📂 ».
    const name = currentFilters.categoryName || currentFilters.category;
    let label;
    if (parentSlug && parentName) {
      // Подкатегория — "Одежда → Мужская", клик на "Одежда" переключает на родителя
      label = `📂 <span class="crumb-link" onclick="clickCrumbParent()" title="Выбрать категорию ${esc(parentName)}">${esc(parentName)}</span> <span style="opacity:.5;">›</span> ${esc(name)}`;
    } else {
      label = `📂 ${esc(name)}`;
    }
    tags.push({ label, key: 'category', raw: true });
  }
  if (currentFilters.minPrice)   tags.push({ label: `от ${esc(String(currentFilters.minPrice))} ₽`, key: 'minPrice' });
  if (currentFilters.maxPrice)   tags.push({ label: `до ${esc(String(currentFilters.maxPrice))} ₽`, key: 'maxPrice' });
  if (currentFilters.createdBy)  tags.push({ label: `@${esc(currentFilters.createdBy)}`, key: 'createdBy' });
  if (currentFilters.auctionType) tags.push({
    label: currentFilters.auctionType === 'bin' ? '⚡ BIN' : '🔨 BID', key: 'auctionType'
  });
  const chips = tags.map(t => `
    <div class="filter-tag" data-key="${t.key}">
      <span class="filter-tag-label">${t.raw ? t.label : t.label}</span>
      <button class="filter-tag-remove" onclick="removeFilterTag('${t.key}')" aria-label="Удалить фильтр">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>
      </button>
    </div>`).join('');
  const clearAll = tags.length >= 2
    ? `<button class="filter-tag-clear" type="button" onclick="resetFilters()">
         <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
         Очистить все
       </button>`
    : '';
  el.innerHTML = chips + clearAll;
}

window.clickCrumbParent = function() {
  if (typeof currentFilters === 'undefined') return;
  const parentSlug = currentFilters.categoryParentSlug;
  const parentName = currentFilters.categoryParentName;
  if (!parentSlug) return;

  // Найти кнопку родительской категории и кликнуть её
  const btn = document.querySelector(`.fs-cat-item[data-slug="${parentSlug}"]`);
  if (btn) {
    selectCategory(btn, parentSlug, null, parentName, null);
  }
}

window.removeFilterTag = function(key) {
  if (typeof currentFilters === 'undefined') return;
  if (key === 'search')   { currentFilters.search = ''; const el = document.getElementById('searchInput'); if(el) el.value = ''; }
  if (key === 'category') {
    currentFilters.category = '';
    currentFilters.categoryLabel = '';
    currentFilters.categoryName = '';
    currentFilters.categoryParentSlug = null;
    currentFilters.categoryParentName = null;
    document.querySelectorAll('.fs-cat-item,.fs-sub-item').forEach(b => b.classList.remove('active'));
    document.querySelector('.fs-cat-item[data-slug=""]')?.classList.add('active');
    document.querySelectorAll('.fs-cat-subs').forEach(s => s.style.display = 'none');
  }
  if (key === 'minPrice')  { currentFilters.minPrice = null;  const el = document.getElementById('minPrice');    if(el) el.value = ''; }
  if (key === 'maxPrice')  { currentFilters.maxPrice = null;  const el = document.getElementById('maxPrice');    if(el) el.value = ''; }
  if (key === 'createdBy') { currentFilters.createdBy = '';   const el = document.getElementById('creatorInput'); if(el) el.value = ''; }
  if (key === 'auctionType') {
    currentFilters.auctionType = '';
    const bid = document.getElementById('filterBid'); if(bid) bid.checked = false;
    const bin = document.getElementById('filterBin'); if(bin) bin.checked = false;
  }
  currentFilters.page = 1;
  window.renderFilterTags();
  if (typeof loadAuctions === 'function') loadAuctions();
}

window.resetFilters = function() {
  if (typeof currentFilters === 'undefined') return;

  // Сбрасываем инпуты
  ['searchInput','minPrice','maxPrice','creatorInput'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const sort = document.getElementById('sortFilter'); if (sort) sort.value = 'time';
  const bid = document.getElementById('filterBid');  if (bid)  bid.checked = false;
  const bin = document.getElementById('filterBin');  if (bin)  bin.checked = false;

  // Сбрасываем категории
  document.querySelectorAll('.fs-cat-item,.fs-sub-item').forEach(b => b.classList.remove('active'));
  document.querySelector('.fs-cat-item[data-slug=""]')?.classList.add('active');
  document.querySelectorAll('.fs-cat-subs').forEach(s => s.style.display = 'none');

  // Сбрасываем статус-табы
  document.querySelectorAll('[data-status]').forEach(b => b.classList.remove('active'));
  document.querySelector('[data-status="active"]')?.classList.add('active');

  // Сбрасываем объект фильтров
  currentFilters.search = '';
  currentFilters.minPrice = null;
  currentFilters.maxPrice = null;
  currentFilters.createdBy = '';
  currentFilters.sortBy = 'time';
  currentFilters.category = '';
  currentFilters.categoryLabel = '';
  currentFilters.categoryName = '';
  currentFilters.categoryParentSlug = null;
  currentFilters.categoryParentName = null;
  currentFilters.auctionType = '';
  currentFilters.status = 'active';
  currentFilters.page = 1;

  window.renderFilterTags();
  if (typeof loadAuctions === 'function') loadAuctions();
}



// Duration hint — показывает время окончания в реальном времени
document.addEventListener('DOMContentLoaded', () => {
  const dur = document.getElementById('auctionDuration');
  const hint = document.getElementById('durationHint');
  if (!dur || !hint) return;

  function updateHint() {
    const mins = parseInt(dur.value) || 0;
    if (!mins) { hint.textContent = ''; return; }
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    let label = '';
    if (h > 0 && m > 0)  label = `${h} ч ${m} мин`;
    else if (h > 0)      label = `${h > 1 ? h + ' ч' : '1 час'}`;
    else                 label = `${m} мин`;

    const end = new Date(Date.now() + mins * 60000);
    const endStr = end.toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
    hint.textContent = `${label} — завершится ${endStr}`;
  }

  dur.addEventListener('input', updateHint);
  // Также обновлять когда модалка открывается
  document.getElementById('createModal')?.addEventListener('transitionend', updateHint);
  updateHint();
});

// Sync create button on desktop
function syncCreateBtns() {
  const show = (typeof currentUser !== 'undefined') && currentUser;
  const fab = document.getElementById('fabCreate');
  if (fab) fab.style.display = show ? 'flex' : 'none';
}

// Card image carousel
function cardSlide(e, btn, dir) {
  e.preventDefault(); e.stopPropagation();
  const card = btn.closest('.auction-card');
  if (!card) return;
  const slides = card.querySelectorAll('.card-slide');
  const dots   = card.querySelectorAll('.card-dot');
  if (!slides.length) return;
  let cur = [...slides].findIndex(s => s.classList.contains('active'));
  slides[cur].classList.remove('active');
  if (dots[cur]) dots[cur].classList.remove('active');
  cur = (cur + dir + slides.length) % slides.length;
  slides[cur].classList.add('active');
  if (dots[cur]) dots[cur].classList.add('active');
}



// Advanced filters toggle
document.addEventListener('click', e => {
  if (!e.target.closest('#toggleAdvanced')) return;
  const p = document.getElementById('advancedFilters');
  if (!p) return;
  p.classList.toggle('open');
  e.target.setAttribute('aria-expanded', p.classList.contains('open'));
});

// Apply advanced filters
document.addEventListener('click', e => {
  if (!e.target.closest('#applyBtn')) return;
  if (typeof currentFilters === 'undefined') return;
  currentFilters.minPrice = document.getElementById('minPrice')?.value || null;
  currentFilters.maxPrice = document.getElementById('maxPrice')?.value || null;
  currentFilters.page = 1;
  if (typeof loadAuctions === 'function') loadAuctions();
});

/* Advanced filter panel open class handler */
document.addEventListener('DOMContentLoaded', () => {
  const adv = document.getElementById('advancedFilters');
  const toggle = document.getElementById('toggleAdvanced');
  if (toggle && adv) {
    toggle.addEventListener('click', () => {
      adv.classList.toggle('open');
    });
  }

  // Clear search button + Enter to apply
  const clearBtn = document.getElementById('clearSearch');
  const searchInput = document.getElementById('searchInput');
  if (clearBtn && searchInput) {
    const toggleClear = () => { clearBtn.style.display = searchInput.value ? 'flex' : 'none'; };
    searchInput.addEventListener('input', toggleClear);
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      toggleClear();
      if (typeof currentFilters !== 'undefined') {
        currentFilters.search = '';
        currentFilters.page = 1;
        if (typeof renderFilterTags === 'function') renderFilterTags();
        if (typeof loadAuctions === 'function') loadAuctions();
      }
    });
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && typeof applyFilters === 'function') {
        if (searchInput.value.trim()) addToSearchHistory(searchInput.value.trim());
        hideSearchHistory();
        applyFilters();
      }
      if (e.key === 'Escape') hideSearchHistory();
    });
  }
});

        // API / WS_BASE приходят из common.js (window.API, window.WS_BASE)
        const API_URL = window.API;
        const WS_URL  = window.WS_BASE;
        let token = localStorage.getItem('token');
        let currentUser = null;
        // Зеркалим currentUser на window, чтобы inline-обработчики в
        // шаблоне (например, кнопка «Выставить свой лот») могли
        // отличить гостя от авторизованного. Используется как
        // window.currentUser? showCreateModal() : showAuth().
        window.currentUser = null;
        let websockets = {};
        let timers = {};
        let reconnectAttempts = {};
        let currentFilters = {
            status: 'active',
            search: '',
            minPrice: null,
            maxPrice: null,
            sortBy: 'time',
            createdBy: '',
            category: '',
            categoryLabel: '',
            auctionType: '',
            page: 1,
            pageSize: 20
        };

        // Читаем параметры из URL при загрузке
        (function() {
            const p = new URLSearchParams(location.search);
            if (p.get('created_by')) {
                currentFilters.createdBy = p.get('created_by');
                const inp = document.getElementById('creatorInput');
                if (inp) inp.value = p.get('created_by');
            }
            if (p.get('search')) {
                currentFilters.search = p.get('search');
                const inp = document.getElementById('searchInput');
                if (inp) inp.value = p.get('search');
            }
            const st = p.get('status');
            if (st === 'active' || st === 'completed' || st === 'all') {
                currentFilters.status = st;
                // переключить активную кнопку статуса
                document.querySelectorAll('[data-status]').forEach(b => {
                    b.classList.toggle('active', b.dataset.status === st);
                });
                // обновить заголовок страницы под выбранный статус
                const titleEl = document.getElementById('pageTitle');
                if (titleEl) {
                    titleEl.textContent = st === 'completed' ? 'Завершённые аукционы'
                                        : st === 'all'       ? 'Все аукционы'
                                                             : 'Активные аукционы';
                }
            }
            // Категория — slug может прийти из хлебных крошек страницы лота.
            // Названия категорий подгрузятся в loadCategories(), но фильтр работает по slug.
            if (p.get('category')) {
                currentFilters.category = p.get('category');
            }
            const minP = p.get('min_price');
            if (minP) {
                currentFilters.minPrice = minP;
                const inp = document.getElementById('minPrice');
                if (inp) inp.value = minP;
            }
            const maxP = p.get('max_price');
            if (maxP) {
                currentFilters.maxPrice = maxP;
                const inp = document.getElementById('maxPrice');
                if (inp) inp.value = maxP;
            }
            const at = p.get('auction_type');
            if (at === 'bid' || at === 'bin') {
                currentFilters.auctionType = at;
                const box = document.getElementById(at === 'bid' ? 'filterBid' : 'filterBin');
                if (box) box.checked = true;
            }
            const sb = p.get('sort_by');
            if (sb === 'time' || sb === 'price_asc' || sb === 'price_desc') {
                currentFilters.sortBy = sb;
                const sel = document.getElementById('sortFilter');
                if (sel) sel.value = sb;
                // обновить декоративный dropdown — селект + лейбл
                document.querySelectorAll('.fs-dd-opt').forEach(o => {
                    const isSel = o.dataset.value === sb;
                    o.classList.toggle('is-selected', isSel);
                    o.setAttribute('aria-selected', isSel ? 'true' : 'false');
                    if (isSel) {
                        const labelEl = o.querySelector('.fs-dd-opt-label');
                        const ddCurrent = o.closest('.fs-dropdown')?.querySelector('.fs-dd-current');
                        if (labelEl && ddCurrent) ddCurrent.textContent = labelEl.textContent;
                    }
                });
            }
            const pg = parseInt(p.get('page') || '', 10);
            if (Number.isFinite(pg) && pg > 1) currentFilters.page = pg;
            // Если в URL есть фильтры — пользователь пришёл из ссылки
            // «Все лоты» / «Все завершённые». После первой загрузки лотов
            // плавно прокручиваем к началу списка.
            const hasUrlFilters = !!(
                p.get('created_by') || p.get('status') || p.get('search') || p.get('category')
                || p.get('min_price') || p.get('max_price') || p.get('auction_type')
                || p.get('sort_by') || p.get('page')
            );
            window._scrollToLotsOnLoad = hasUrlFilters || !!p.get('scroll');
            // URL — авторитетный источник фильтров: запретить позже
            // loadFiltersFromStorage перезаписывать значения из localStorage,
            // иначе расшаренная ссылка перестанет восстанавливаться один-в-один.
            window._filtersFromUrl = hasUrlFilters;
        })();

        // ===== Multi-image upload =====
        let lotSelectedFiles = []; // массив File объектов

        function renderMultiImgPreview() {
            const preview = document.getElementById('multiImgPreview');
            const addBtn = document.getElementById('multiImgAddBtn');
            if (!preview) return;
            preview.innerHTML = lotSelectedFiles.map((f, i) => `
                <div class="multi-img-thumb ${i === 0 ? 'is-cover' : ''}" data-idx="${i}">
                    <img src="${URL.createObjectURL(f)}" alt="фото ${i+1}">
                    <button class="thumb-del" type="button" onclick="removeThumb(${i})">✕</button>
                </div>
            `).join('');
            if (addBtn) addBtn.style.display = lotSelectedFiles.length >= 5 ? 'none' : 'inline-flex';
        }

        function removeThumb(idx) {
            lotSelectedFiles.splice(idx, 1);
            renderMultiImgPreview();
        }

        function clearLotImage() {
            lotSelectedFiles = [];
            const file = document.getElementById('auctionImageFile');
            if (file) file.value = '';
            renderMultiImgPreview();
        }

        function wireLotImageUI() {
            const fileInput = document.getElementById('auctionImageFile');
            if (!fileInput || fileInput._wired) return;
            fileInput._wired = true;
            fileInput.addEventListener('change', (e) => {
                const newFiles = Array.from(e.target.files || []);
                for (const f of newFiles) {
                    if (lotSelectedFiles.length >= 5) break;
                    if (f.type.startsWith('image/')) lotSelectedFiles.push(f);
                }
                fileInput.value = '';
                renderMultiImgPreview();
            });
        }

        async function uploadOneFile(file) {
            const fd = new FormData();
            fd.append('file', file, file.name || 'lot.jpg');
            const r = await fetch(`${API_URL}/api/upload-image`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: fd
            });
            if (!r.ok) {
                const j = await r.json().catch(() => ({}));
                throw new Error(j.detail || 'Ошибка загрузки изображения');
            }
            const d = await r.json();
            return d.image_url;
        }

        async function uploadLotImageIfAny() {
            if (!token || lotSelectedFiles.length === 0) return { image_url: null, image_urls: [] };
            const urls = [];
            for (const f of lotSelectedFiles) {
                const url = await uploadOneFile(f);
                urls.push(url);
            }
            return { image_url: urls[0] || null, image_urls: urls };
        }

        // ===== UX Quick Wins: saved filters + skeleton + clickable cards =====
        const FILTERS_KEY = 'auction_filters_v1';

        function saveFiltersToStorage() {
            try {
                localStorage.setItem(FILTERS_KEY, JSON.stringify({
                    status: currentFilters.status,
                    search: currentFilters.search,
                    minPrice: currentFilters.minPrice,
                    maxPrice: currentFilters.maxPrice,
                    sortBy: currentFilters.sortBy
                }));
            } catch {}
        }

        function loadFiltersFromStorage() {
            if (window._filtersFromUrl) return;
            try {
                const raw = localStorage.getItem(FILTERS_KEY);
                if (!raw) return;
                const f = JSON.parse(raw);
                if (f && typeof f === 'object') {
                    if (f.status) currentFilters.status = f.status;
                    if (typeof f.search === 'string') currentFilters.search = f.search;
                    if (f.minPrice !== undefined && f.minPrice !== null && f.minPrice !== '') currentFilters.minPrice = f.minPrice;
                    if (f.maxPrice !== undefined && f.maxPrice !== null && f.maxPrice !== '') currentFilters.maxPrice = f.maxPrice;
                    if (f.sortBy) currentFilters.sortBy = f.sortBy;
                }
            } catch {}
        }

        function syncFilterInputsFromState() {
            const s = document.getElementById('searchInput');
            const st = document.getElementById('statusFilter');
            const so = document.getElementById('sortFilter');
            const min = document.getElementById('minPrice');
            const max = document.getElementById('maxPrice');
            if (s) s.value = currentFilters.search || '';
            if (st) st.value = currentFilters.status || 'active';
            if (so) so.value = currentFilters.sortBy || 'time';
            if (min) min.value = currentFilters.minPrice ?? '';
            if (max) max.value = currentFilters.maxPrice ?? '';
        }

        function renderSkeleton(count = 6) {
            const container = document.getElementById('auctionsContainer');
            if (!container) return;
            container.innerHTML = `<div class="skeleton-grid">${
                Array.from({length: count}).map(() => `
                    <div class="skeleton-card shimmer">
                        <div class="sk-img"></div>
                        <div class="sk-body">
                            <div class="sk-line lg"></div>
                            <div class="sk-line md"></div>
                            <div class="sk-line sm"></div>
                            <div class="sk-line lg"></div>
                            <div class="sk-line md"></div>
                        </div>
                    </div>
                `).join('')
            }</div>`;
        }

        // Cards are now <a> tags — no click handler needed

        let totalPages = 1;

        // Инициализация
        async function init() {
            // всегда подтягиваем token из localStorage
            token = localStorage.getItem('token');

            // wired once: image upload + crop UI
            try { wireLotImageUI(); } catch {}

            

            // восстановить фильтры
            loadFiltersFromStorage();if (token) {
                await loadCurrentUser();
            }

            // Показать/скрыть блоки (без падений если элементов нет)
            const userProfile = document.getElementById('userProfile');
            const guestProfile = document.getElementById('guestProfile');
            const createBtn = document.getElementById('createBtn');

            if (currentUser) {
                if (userProfile) userProfile.style.display = 'flex';
                if (guestProfile) guestProfile.style.display = 'none';
                if (createBtn) createBtn.style.display = 'inline-flex';
            } else {
                if (userProfile) userProfile.style.display = 'none';
                if (guestProfile) guestProfile.style.display = 'flex';
                if (createBtn) createBtn.style.display = 'none';
            }
            syncFilterInputsFromState();
            renderSkeleton(6);
            await loadAuctions();
            try {
                const flashEmail = localStorage.getItem('flash_verify_email');
                if (flashEmail) {
                    localStorage.removeItem('flash_verify_email');
                    showToast(
                        'Подтвердите email',
                        `Мы отправили письмо на ${flashEmail}. Чтобы делать ставки и создавать лоты — подтвердите адрес.`,
                        'info'
                    );
                }
            } catch (_) {}
// Инициализация новой панели фильтров (если есть)
            if (typeof initFiltersUI === 'function') initFiltersUI();
        }

        async function loadCurrentUser() {
            // синхронизируем token с localStorage (важно при переходах между страницами)
            token = localStorage.getItem('token');

            // wired once: image upload + crop UI
            try { wireLotImageUI(); } catch {}

            // если токена нет — гость
            if (!token) {
                currentUser = null;
                window.currentUser = null;
                return null;
            }

            let response;
            try {
                response = await fetch(`${API_URL}/api/me`, {
                    method: 'GET',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
            } catch (err) {
                // сеть/сервер недоступен — НЕ разлогиниваем
                console.warn('loadCurrentUser: network error', err);
                return null;
            }

            if (response.status === 401 || response.status === 403) {
                // токен реально невалидный → удаляем
                localStorage.removeItem('token');
                token = null;
                currentUser = null;
                window.currentUser = null;
                return null;
            }

            if (!response.ok) {
                console.warn('loadCurrentUser: api error', response.status);
                return null;
            }

            currentUser = await response.json();
            window.currentUser = currentUser;

            // безопасно обновляем UI, если элементы существуют
            const userNameEl = document.getElementById('userName');
            const balEl = document.getElementById('userBalanceSmall');
            const avEl = document.getElementById('userAvatarSmall');
            if (userNameEl) userNameEl.textContent = currentUser.username;
            if (balEl && typeof currentUser.balance === 'number') balEl.textContent = currentUser.balance.toFixed(2);
            if (avEl) {
              avEl.textContent = (currentUser.username || '?').charAt(0).toUpperCase();
              if (currentUser.avatar_url) {
                const img = document.createElement('img');
                img.src = currentUser.avatar_url.startsWith('http') ? currentUser.avatar_url : `${API_URL}${currentUser.avatar_url}`;
                img.alt = currentUser.username;
                avEl.appendChild(img);
              }
            }

            return currentUser;
        }

        async function loadAuctions() {
            const container = document.getElementById('auctionsContainer');
            // Любой запрос — это и есть «зафиксированные фильтры»: синхронизируем
            // URL и активные чипы фильтров, чтобы оба индикатора шли в ногу.
            if (typeof window.syncUrlFromFilters === 'function') window.syncUrlFromFilters();
            if (typeof window.renderFilterTags === 'function') window.renderFilterTags();

            // 1. Fade-out — гарантированно ждём конца анимации
            if (container) {
                container.classList.remove('fade-in');
                container.classList.add('fade-out');
                await new Promise(r => setTimeout(r, 190)); // ждём конец fade-out (180ms)
            }

            try {
                const params = new URLSearchParams({
                    status: currentFilters.status,
                    sort_by: currentFilters.sortBy,
                    page: currentFilters.page,
                    page_size: currentFilters.pageSize
                });
                if (currentFilters.search)      params.append('search',       currentFilters.search);
                if (currentFilters.minPrice)    params.append('min_price',    currentFilters.minPrice);
                if (currentFilters.maxPrice)    params.append('max_price',    currentFilters.maxPrice);
                if (currentFilters.createdBy)   params.append('created_by',   currentFilters.createdBy);
                if (currentFilters.category)    params.append('category',     currentFilters.category);
                if (currentFilters.auctionType) params.append('auction_type', currentFilters.auctionType);
                
                const response = await fetch(`${API_URL}/api/auctions?${params}`);
                const data = await response.json();
                
                totalPages = data.total_pages;
                updatePagination(data.page, data.total_pages, data.total);
                updateResultsInfo(data.total, data.page, data.total_pages);

                // 2. Обновляем DOM пока контейнер невидим
                displayAuctions(data.items);

                // 3. Fade-in
                if (container) {
                    container.classList.remove('fade-out');
                    container.classList.add('fade-in');
                }
                // Одноразовый скролл к ленте лотов, если пришли по ссылке
                // с фильтром (например, «Все лоты» из user.html).
                if (window._scrollToLotsOnLoad) {
                    window._scrollToLotsOnLoad = false;
                    setTimeout(scrollToAuctionsTop, 50);
                }
            } catch (e) {
                if (container) { container.classList.remove('fade-out'); container.classList.add('fade-in'); }
                document.getElementById('auctionsContainer').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">❌</div>
                        <div class="empty-title">Ошибка загрузки</div>
                        <p>Не удалось загрузить аукционы</p>
                    </div>`;
            }
        }

        
        function updateResultsInfo(total, page, totalPages) {
            const inline = document.getElementById('resultInfoInline');
            const adv = document.getElementById('resultInfo');
            const text = total === 0
                ? 'Ничего не найдено'
                : `Найдено: ${total} • Страница ${page} из ${totalPages}`;
            if (inline) inline.textContent = text;
            if (adv) adv.textContent = text;
        }

function buildPageList(current, total) {
            // Returns array of numbers (1..total) and '...' separators.
            // Window: first, last, and ±2 around current.
            if (total <= 7) return Array.from({length: total}, (_, i) => i + 1);
            const pages = new Set([1, total, current - 1, current, current + 1, 2, total - 1]);
            const sorted = [...pages].filter(p => p >= 1 && p <= total).sort((a, b) => a - b);
            const out = [];
            for (let i = 0; i < sorted.length; i++) {
                if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push('...');
                out.push(sorted[i]);
            }
            return out;
        }

        function updatePagination(page, total, itemsCount) {
            const paginationDiv = document.getElementById('pagination');
            const prevBtn = document.getElementById('prevBtn');
            const nextBtn = document.getElementById('nextBtn');
            const pagesEl = document.getElementById('paginationPages');
            const jumpInput = document.getElementById('pageJumpInput');

            if (total <= 1) {
                paginationDiv.style.display = 'none';
                return;
            }

            paginationDiv.style.display = 'flex';
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= total;

            if (pagesEl) {
                pagesEl.innerHTML = '';
                buildPageList(page, total).forEach(p => {
                    if (p === '...') {
                        const span = document.createElement('span');
                        span.className = 'pagination-ellipsis';
                        span.textContent = '…';
                        pagesEl.appendChild(span);
                    } else {
                        const btn = document.createElement('button');
                        btn.className = 'pagination-btn pagination-num' + (p === page ? ' active' : '');
                        btn.type = 'button';
                        btn.textContent = String(p);
                        btn.onclick = () => goToPage(p);
                        pagesEl.appendChild(btn);
                    }
                });
            }

            if (jumpInput) {
                jumpInput.max = String(total);
                if (document.activeElement !== jumpInput) jumpInput.value = '';
            }
        }

        function scrollToAuctionsTop() {
            const headerEl = document.querySelector('.page-header')
                          || document.getElementById('auctionsContainer');
            if (!headerEl) return;
            const nav = document.querySelector('.navbar');
            const navH = nav ? nav.getBoundingClientRect().height : 60;
            const y = headerEl.getBoundingClientRect().top + window.pageYOffset - navH - 12;
            window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
        }

        // Магнитный снэп: когда пользователь после прокрутки hero останавливается
        // в «промежуточной» зоне (верх ленты лотов ещё ниже навбара, но уже близко),
        // плавно докатываем к началу лотов. Подражает поведению кнопки «Смотреть лоты»,
        // только запускается само, без клика. Срабатывает после ~150 мс простоя в скролле.
        (function setupAuctionsSnap() {
            // Уважать пользовательский запрос на минимум анимаций
            if (typeof matchMedia === 'function'
                && matchMedia('(prefers-reduced-motion: reduce)').matches) return;

            let timer = null;
            let isAutoScrolling = false;
            // Активна ли зона снэпа: верх «.page-header» (или фоллбек на ленту лотов)
            // находится в коридоре [navH+12, navH+12+SNAP_ZONE_PX] от верха viewport.
            // Меньше значение — позже срабатывает, ближе к самому началу лотов.
            const SNAP_ZONE_PX = 120;
            const DEBOUNCE_MS = 150;
            const COOLDOWN_MS = 700;

            function maybeSnap() {
                if (isAutoScrolling) return;
                // не вмешиваемся при открытой модалке (auth / create / sort dropdown и пр.)
                if (document.body.classList.contains('modal-open')) return;
                // если фокус в поле ввода (поиск, фильтр) — пользователь печатает, не трогаем
                const ae = document.activeElement;
                if (ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) return;

                const headerEl = document.querySelector('.page-header')
                              || document.getElementById('auctionsContainer');
                if (!headerEl) return;
                const nav = document.querySelector('.navbar');
                const navH = nav ? nav.getBoundingClientRect().height : 60;
                const offset = navH + 12;
                const top = headerEl.getBoundingClientRect().top;
                if (top > offset && top < offset + SNAP_ZONE_PX) {
                    isAutoScrolling = true;
                    scrollToAuctionsTop();
                    setTimeout(() => { isAutoScrolling = false; }, COOLDOWN_MS);
                }
            }

            window.addEventListener('scroll', () => {
                if (timer) clearTimeout(timer);
                timer = setTimeout(maybeSnap, DEBOUNCE_MS);
            }, { passive: true });
        })();

        function goToPage(n) {
            const target = Math.max(1, Math.min(n, totalPages));
            if (target === currentFilters.page) return;
            currentFilters.page = target;
            loadAuctions();
            scrollToAuctionsTop();
        }

        function changePage(delta) {
            goToPage(currentFilters.page + delta);
        }

        // Page-jump input — Enter or blur applies
        document.addEventListener('DOMContentLoaded', () => {
            const jumpInput = document.getElementById('pageJumpInput');
            if (!jumpInput) return;
            const apply = () => {
                const v = parseInt(jumpInput.value, 10);
                if (!isNaN(v)) goToPage(v);
                jumpInput.value = '';
                jumpInput.blur();
            };
            jumpInput.addEventListener('keydown', e => {
                if (e.key === 'Enter') { e.preventDefault(); apply(); }
            });
            jumpInput.addEventListener('blur', () => {
                if (jumpInput.value !== '') apply();
            });
        });

        // Observer, поднимающий WS на видимые карточки и закрывающий на
        // ушедшие из viewport. Один экземпляр на страницу, заново
        // привязываемся к новым [data-auction-id] после каждой перерисовки.
        let auctionWsObserver = null;
        const lastPriceRefresh = {};
        function refreshAuctionPrice(auctionId) {
            // Если карточка только что попала в viewport, пока она была
            // скрыта, цена могла измениться (новая ставка / buy-now).
            // WS подпишется только на будущие сообщения, текущее состояние
            // нужно подтянуть отдельным REST-запросом. Throttle 5 с,
            // чтобы быстрый скролл не спамил сервер на один и тот же лот.
            const now = Date.now();
            if (lastPriceRefresh[auctionId] && now - lastPriceRefresh[auctionId] < 5000) return;
            lastPriceRefresh[auctionId] = now;
            fetch(`${API_URL}/api/auctions/${auctionId}`)
                .then(r => r.ok ? r.json() : null)
                .then(d => {
                    if (d && typeof d.current_price === 'number') {
                        updatePrice(auctionId, d.current_price);
                    }
                })
                .catch(() => {});
        }

        function attachAuctionWsObserver() {
            if (!auctionWsObserver) {
                auctionWsObserver = new IntersectionObserver((entries) => {
                    entries.forEach((entry) => {
                        const id = +entry.target.dataset.auctionId;
                        if (!id) return;
                        if (entry.isIntersecting) {
                            refreshAuctionPrice(id);
                            if (token && !websockets[id]) connectWebSocket(id);
                        } else {
                            const ws = websockets[id];
                            if (!ws) return;
                            safeCloseWs(ws);
                            delete websockets[id];
                        }
                    });
                }, { rootMargin: '200px' });
            }
            const container = document.getElementById('auctionsContainer');
            if (!container) return;
            container.querySelectorAll('[data-auction-id]').forEach((el) => {
                auctionWsObserver.observe(el);
            });
        }

        // Безопасное закрытие WebSocket с учётом состояния. Если ws ещё
        // в CONNECTING (readyState=0), браузер логирует «closed before
        // connection established» — это безобидно, но шумно. Дожидаемся
        // onopen и закрываем уже установленное соединение.
        function safeCloseWs(ws) {
            if (!ws) return;
            ws.intentionallyClosed = true;
            if (ws.pingInterval) clearInterval(ws.pingInterval);
            // При быстром скролле наблюдатель может попросить закрыть
            // сокет, который ещё не успел соединиться — сетевая ошибка
            // в такой момент не должна копить счётчик реконнектов.
            const id = ws._auctionId;
            if (id != null) reconnectAttempts[id] = 0;
            try {
                if (ws.readyState === WebSocket.CONNECTING) {
                    ws.addEventListener('open', () => {
                        try { ws.close(1000, 'list refresh'); } catch (_) {}
                    }, { once: true });
                } else if (ws.readyState === WebSocket.OPEN) {
                    ws.close(1000, 'list refresh');
                }
            } catch (_) {}
        }

        // Закрываем все активные WS-подключения и таймеры перед сменой
        // содержимого списка. Без этого старые соединения копятся: сервер
        // быстро упирается в лимит коннектов с IP и отдаёт 1008.
        function clearAuctionConnections() {
            Object.entries(websockets).forEach(([id, ws]) => {
                safeCloseWs(ws);
                delete websockets[id];
            });
            Object.values(timers).forEach(t => clearInterval(t));
            Object.keys(timers).forEach(k => delete timers[k]);
            Object.keys(reconnectAttempts).forEach(k => delete reconnectAttempts[k]);
        }

        function displayAuctions(auctions) {
            const container = document.getElementById('auctionsContainer');
            clearAuctionConnections();

            if (auctions.length === 0) {
                const hasFilters =
                    (currentFilters.search && currentFilters.search.length > 0) ||
                    (currentFilters.status && currentFilters.status !== 'active') ||
                    currentFilters.minPrice || currentFilters.maxPrice ||
                    (currentFilters.sortBy && currentFilters.sortBy !== 'time');

                container.innerHTML = hasFilters ? `
                    <div class="empty-state">
                        <div class="empty-icon">🔎</div>
                        <div class="empty-title">Ничего не найдено</div>
                        <p>Попробуйте изменить фильтры или сбросить их.</p>
                        <div class="empty-actions">
                            <button class="btn btn-primary" type="button" onclick="resetFilters()">Сбросить фильтры</button>
                        </div>
                    </div>
                ` : `
                    <div class="empty-state">
                        <div class="empty-icon">🔨</div>
                        <div class="empty-title">Пока нет лотов</div>
                        <p>Создайте свой первый лот и начните торги.</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = auctions.map(auction => {
                const timeRemaining = auction.time_remaining;
                let badgeClass = 'badge-live';
                let badgeText = '🔴 В эфире';
                
                if (timeRemaining === 0) {
                    badgeClass = 'badge-ended';
                    badgeText = 'Завершён';
                } else if (timeRemaining < 300) {
                    badgeClass = 'badge-ending';
                    badgeText = '⚠️ Скоро конец';
                }

                const imgSrc = auction.image_url
                    ? (String(auction.image_url).startsWith('http') ? auction.image_url : `${API_URL}${auction.image_url}`)
                    : null;

                const isEnded = timeRemaining === 0;
                const bidsCount = auction.bids_count ?? '';
                const creatorName = auction.creator_username || '';
                const safeCreator = esc(creatorName);
                const creatorAvatarUrl = auction.creator_avatar_url || null;
                const creatorAvatarHtml = creatorName ? (() => {
                  const src = creatorAvatarUrl
                    ? (creatorAvatarUrl.startsWith('http') ? creatorAvatarUrl : `${API_URL}${creatorAvatarUrl}`)
                    : null;
                  return `<div class="mini-avatar">${src ? `<img src="${esc(src)}" alt="${safeCreator}">` : esc(creatorName[0].toUpperCase())}</div>`;
                })() : '';

                const isOwner = currentUser && auction.created_by === currentUser.id;
                const canDelete = isOwner && !(auction.is_completed && auction.winner_id);
                const catLabel = auction.category_icon && auction.category_name
                    ? esc(`${auction.category_icon} ${auction.category_name}`) : '';
                const safeTitle = esc(auction.title);

                const allImgUrls = (auction.image_urls && auction.image_urls.length)
                    ? auction.image_urls.map(u => String(u).startsWith('http') ? u : `${API_URL}${u}`)
                    : (imgSrc ? [imgSrc] : []);

                const hasMultiple = allImgUrls.length > 1;

                const imagesHtml = allImgUrls.length
                    ? allImgUrls.map((u, i) => `<img class="card-slide${i === 0 ? ' active' : ''}" src="${esc(u)}" alt="${safeTitle}" data-slide="${i}">`).join('')
                    : `<div class="card-placeholder"><div class="card-placeholder-icon">🖼</div><div class="card-placeholder-label">Нет фото</div></div>`;

                const isBinType = auction.auction_type === 'bin';
                const binBadge = isBinType
                    ? `<div class="auction-badge" style="background:rgba(232,160,32,0.9);color:#000;top:auto;bottom:8px;left:8px;">⚡ BIN</div>`
                    : '';

                return `
                    <div class="auction-card" data-auction-id="${auction.id}"
                       data-title="${safeTitle}"
                       data-price="${isBinType ? '⚡ ' : ''}${auction.current_price.toFixed(2)} ₽"
                       data-start="от ${auction.starting_price.toFixed(2)} ₽"
                       data-bids="${bidsCount !== '' ? '💬 ' + bidsCount : ''}"
                       data-creator="${creatorName ? '@' + safeCreator : ''}"
                       data-category="${catLabel}"
                       data-slide-count="${allImgUrls.length}">

                        <!-- Картинка — кликабельна -->
                        <a href="auction.html?id=${auction.id}" class="auction-image-link">
                            <div class="auction-image">
                                ${imagesHtml}
                                ${badgeClass === 'badge-ending' ? `<div class="auction-badge badge-ending">⏰ Скоро конец</div>` : ''}
                                ${binBadge}
                                ${canDelete ? `<button class="card-delete-btn" title="Удалить лот" onclick="deleteAuction(event, ${auction.id})">✕</button>` : ''}
                                ${hasMultiple ? `
                                <button class="card-nav card-nav-prev" onclick="cardSlide(event,this,-1)">‹</button>
                                <button class="card-nav card-nav-next" onclick="cardSlide(event,this,1)">›</button>
                                <div class="card-dots">${allImgUrls.map((_,i)=>`<span class="card-dot${i===0?' active':''}" data-dot="${i}"></span>`).join('')}</div>` : ''}
                            </div>
                        </a>

                        <!-- Текстовый блок — статичный -->
                        <div class="auction-body">
                            <a href="auction.html?id=${auction.id}" class="auction-title-link">
                                <div class="auction-title">${safeTitle}</div>
                            </a>
                            <div class="auction-price">${auction.current_price.toFixed(2)} ₽</div>
                            ${!isEnded
                                ? `<div class="auction-start auction-timer-row"><span class="auction-pulse" aria-hidden="true"></span><span class="auction-timer-text" data-timer="${auction.id}">${formatTime(timeRemaining)}</span></div>`
                                : `<div class="auction-start">Завершён · от ${auction.starting_price.toFixed(2)} ₽</div>`}
                            ${creatorName ? `<div class="auction-meta-row"><span class="auction-creator">${creatorAvatarHtml}<a href="user.html?username=${encodeURIComponent(creatorName)}" onclick="event.stopPropagation()">@${safeCreator}</a></span></div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            // Таймеры — на все лоты сразу: дёшево, идёт чисто по DOM.
            auctions.forEach(auction => {
                startTimer(auction.id, auction.time_remaining);
            });

            // WS открываем только для тех лотов, чьи карточки в видимой
            // области. Без этого 25-50 одновременных подключений с одного
            // IP пробивают лимит сервера и часть карточек получает 1008
            // Policy Violation. IntersectionObserver сам поднимает /
            // закрывает соединение при скролле — естественный rate limit.
            if (token) attachAuctionWsObserver();
        }

        function formatTime(seconds) {
            if (seconds <= 0) return 'Завершён';
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            
            if (hours > 0) return `${hours}ч ${minutes}м ${secs}с`;
            if (minutes > 0) return `${minutes}м ${secs}с`;
            return `${secs}с`;
        }

        function startTimer(auctionId, initialTime) {
            // Если аукцион уже завершён — просто выставляем текст и НЕ запускаем интервал
            const timerElementNow = document.querySelector(`[data-timer="${auctionId}"]`);
            const init = Number(initialTime);

            if (!Number.isFinite(init) || init <= 0) {
                if (timerElementNow) timerElementNow.textContent = 'Завершён';
                if (timers[auctionId]) {
                    clearInterval(timers[auctionId]);
                    delete timers[auctionId];
                }
                return;
            }

            if (timers[auctionId]) clearInterval(timers[auctionId]);

            let timeRemaining = init;
            timers[auctionId] = setInterval(() => {
                timeRemaining--;
                const timerElement = document.querySelector(`[data-timer="${auctionId}"]`);
                if (timerElement) {
                    timerElement.textContent = formatTime(timeRemaining);
                }
                if (timeRemaining <= 0) {
                    clearInterval(timers[auctionId]);
                    delete timers[auctionId];
                    const timerEl = document.querySelector(`[data-timer="${auctionId}"]`);
                    if (timerEl) timerEl.textContent = 'Завершён';
                    // НЕ перезагружаем страницу/список каждую секунду
                }
            }, 1000);
        }

        // УЛУЧШЕНИЕ: WebSocket с экспоненциальной задержкой переподключения
        function connectWebSocket(auctionId) {
            if (websockets[auctionId]) return;
            
            const ws = new WebSocket(`${WS_URL}/ws/auction/${auctionId}`);
            ws._auctionId = auctionId;
            
            if (!reconnectAttempts[auctionId]) {
                reconnectAttempts[auctionId] = 0;
            }
            
            ws.onopen = () => {
                reconnectAttempts[auctionId] = 0; // Сброс счетчика при успешном подключении
                
                // Ping каждые 25 секунд
                ws.pingInterval = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send('ping');
                    }
                }, 25000);
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'new_bid') {
                    updatePrice(auctionId, data.current_price);
                }
            };

            ws.onclose = (event) => {
                delete websockets[auctionId];

                if (ws.pingInterval) {
                    clearInterval(ws.pingInterval);
                }

                // Не реконнектиться при намеренном закрытии (смена страницы,
                // фильтр) и при отказе сервера по политике (1008 — лимит
                // подключений с IP, 1011 — внутренняя ошибка). Иначе
                // получится reconnect-шторм против лимита коннектов.
                if (ws.intentionallyClosed) return;
                if (event && (event.code === 1000 || event.code === 1008 || event.code === 1011)) {
                    return;
                }

                // Экспоненциальная задержка с half-jitter: при разовом
                // падении сервера сотня вкладок не штормит обратно
                // одной секундой — равномерно размазывается по [base/2, base].
                if (!reconnectAttempts[auctionId]) reconnectAttempts[auctionId] = 0;
                const base = Math.min(1000 * Math.pow(2, reconnectAttempts[auctionId]), 30000);
                const delay = base / 2 + Math.random() * (base / 2);
                reconnectAttempts[auctionId]++;
                setTimeout(() => {
                    const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
                    if (card) { // Переподключаемся только если карточка еще на странице
                        connectWebSocket(auctionId);
                    }
                }, delay);
            };

            ws.onerror = () => {
                // WS error по сути дублирует событие onclose: браузер
                // эмитит "error" непосредственно перед "close" на любом
                // ненормальном разрыве (включая отказ сервера 1008 и
                // наше же намеренное закрытие во время CONNECTING).
                if (ws.intentionallyClosed) return;
                if (reconnectAttempts[auctionId] >= 3) {
                    console.warn(`WS auction ${auctionId}: repeated failures`);
                }
            };

            websockets[auctionId] = ws;
        }

        function updatePrice(auctionId, newPrice) {
            const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
            if (!card) return;
            const priceEl = card.querySelector('.auction-price');
            if (!priceEl) return;
            const next = Number(newPrice).toFixed(2) + ' ₽';
            // Если цена не изменилась — ничего не трогаем, анимация-флэш
            // только для реальных обновлений. Иначе при refresh-on-view
            // (REST-запросе при первом появлении карточки в viewport)
            // карточка моргала бы зря.
            if (priceEl.textContent === next) return;
            priceEl.textContent = next;
            priceEl.classList.remove('price-flash');
            void priceEl.offsetWidth;
            priceEl.classList.add('price-flash');
        }

        async function deleteAuction(e, auctionId) {
            e.preventDefault();
            e.stopPropagation();
            const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
            const title = card?.dataset.title || 'этот лот';
            if (!confirm(`Удалить «${title}»?\n\nЭто действие нельзя отменить.`)) return;
            try {
                const r = await fetch(`${API_URL}/api/auctions/${auctionId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                if (r.ok) {
                    if (card) {
                        card.style.transition = 'opacity .3s, transform .3s';
                        card.style.opacity = '0';
                        card.style.transform = 'scale(.95)';
                        setTimeout(() => card.remove(), 300);
                    }
                } else {
                    const err = await r.json().catch(() => ({}));
                    showToast('Не удалось удалить', err.detail || 'Попробуйте позже', 'bad');
                }
            } catch { showToast('Ошибка сети', 'Проверьте соединение', 'bad'); }
        }

        async function placeBid(auctionId) {
            const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
            const input = card.querySelector('.bid-input');
            const amount = parseFloat(input.value);

            if (!amount || amount <= 0) {
                showToast('Неверная сумма', 'Введите корректное число', 'warn');
                return;
            }

            try {
                const response = await fetch(`${API_URL}/api/bids`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ auction_id: auctionId, amount })
                });

                if (response.ok) {
                    input.value = '';
                    await loadCurrentUser();
                } else {
                    const error = await response.json();
                    showToast('Ставка не принята', error.detail || 'Попробуйте ещё раз', 'bad');
                }
            } catch (e) {
                showToast('Ошибка сети', 'Проверьте соединение', 'bad');
            }
        }

        
        let filtersInitialized = false;
        
        function initFiltersUI() {
            // Защита от повторной инициализации
            if (filtersInitialized) return;
            
            const searchEl = document.getElementById('searchInput');
            const statusEl = document.getElementById('statusFilter');
            const sortEl = document.getElementById('sortFilter');
            const minEl = document.getElementById('minPrice');
            const maxEl = document.getElementById('maxPrice');
            const clearBtn = document.getElementById('clearSearch');
            const toggleBtn = document.getElementById('toggleAdvanced');
            const adv = document.getElementById('advancedFilters');
            const applyBtn = document.getElementById('applyBtn');

            if (!searchEl || !sortEl) {
                console.warn('initFiltersUI: некоторые элементы не найдены');
                return;
            }

            const debouncedApply = debounce(applyFilters, 450);

            searchEl.addEventListener('input', debouncedApply);
            sortEl.addEventListener('change', applyFilters);

            if (minEl) minEl.addEventListener('input', debouncedApply);
            if (maxEl) maxEl.addEventListener('input', debouncedApply);

            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    searchEl.value = '';
                    applyFilters();
                    searchEl.focus();
                });
            }

            // toggleAdvanced теперь обрабатывается глобальным обработчиком ниже
            
            if (applyBtn) applyBtn.addEventListener('click', applyFilters);

            wireMobileFilterDrawer();

            filtersInitialized = true;
        }

        /**
         * Mobile filter drawer: ≤768px viewport turns the always-visible
         * desktop sidebar into an off-canvas drawer. CSS owns the slide-
         * in animation; JS owns the open/close state, body-scroll lock,
         * Esc / overlay / Apply dismissal, and the active-filter badge.
         *
         * Initialised once from initFiltersUI; the elements are present
         * unconditionally in the markup so this is safe to call before
         * the first viewport-resize event.
         */
        function wireMobileFilterDrawer() {
            const sidebar = document.getElementById('filterSidebar');
            const toggle  = document.getElementById('filterToggleBtn');
            const closeBtn = document.getElementById('filterCloseBtn');
            const backdrop = document.getElementById('filterBackdrop');
            const badge   = document.getElementById('filterActiveBadge');
            if (!sidebar || !toggle || !backdrop) return;

            const setOpen = (open) => {
                sidebar.classList.toggle('is-open', open);
                backdrop.classList.toggle('is-visible', open);
                backdrop.hidden = !open;
                document.body.classList.toggle('no-scroll', open);
                toggle.setAttribute('aria-expanded', String(open));
            };

            toggle.addEventListener('click', () => setOpen(true));
            if (closeBtn) closeBtn.addEventListener('click', () => setOpen(false));
            backdrop.addEventListener('click', () => setOpen(false));

            // Esc dismisses — keyboard accessibility + a useful escape
            // hatch for desktop testing in DevTools mobile emulation.
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && sidebar.classList.contains('is-open')) {
                    setOpen(false);
                }
            });

            // Apply / Reset buttons inside the drawer should dismiss it
            // on mobile — the user has expressed intent, no reason to
            // keep the overlay covering the results they're about to see.
            sidebar.addEventListener('click', (e) => {
                const btn = e.target.closest('.fs-actions .btn');
                if (btn && window.matchMedia('(max-width: 768px)').matches) {
                    setOpen(false);
                }
            });

            // Active-filter badge — recomputes whenever filters change so
            // the user can see at a glance whether the drawer hides any
            // narrowing rules. Counts: status≠active, any category, any
            // type, any price, any creator, any non-default sort.
            const updateBadge = () => {
                let n = 0;
                const status = document.getElementById('statusFilter')?.value;
                if (status && status !== 'active') n++;
                const cat = document.getElementById('categoryFilter')?.value;
                if (cat) n++;
                if (document.getElementById('filterBid')?.checked) n++;
                if (document.getElementById('filterBin')?.checked) n++;
                const minP = document.getElementById('minPrice')?.value;
                const maxP = document.getElementById('maxPrice')?.value;
                if (minP && Number(minP) > 0) n++;
                if (maxP && Number(maxP) > 0) n++;
                if (document.getElementById('creatorInput')?.value?.trim()) n++;
                const sort = document.getElementById('sortFilter')?.value;
                if (sort && sort !== 'time') n++;
                if (badge) badge.textContent = String(n);
                toggle.classList.toggle('has-active', n > 0);
            };
            updateBadge();
            // Recompute after any handler that mutates filters — the
            // sidebar fires applyFilters at the end of each change, and
            // resetFilters writes the inputs synchronously, so a single
            // listener on the sidebar is enough for both paths.
            sidebar.addEventListener('change', updateBadge);
            sidebar.addEventListener('input', updateBadge);
            sidebar.addEventListener('click', updateBadge, true);
        }

        // initFiltersUI и первичный рендер будут вызваны из wire() ниже



        function debounce(func, wait) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func(...args), wait);
            };
        }

        // Модальные окна
        function showAuth() {
            document.getElementById('authModal').classList.add('active');
        }

        function closeAuth() {
            document.getElementById('authModal').classList.remove('active');
            document.getElementById('authError').style.display = 'none';
        }

        function switchAuthTab(tab) {
            const tabs = document.querySelectorAll('.tab');
            if (tabs.length < 2) return;
            tabs.forEach(t => t.classList.remove('active'));
            if (tab === 'login') {
                tabs[0].classList.add('active');
                document.getElementById('loginForm').style.display = 'block';
                document.getElementById('registerForm').style.display = 'none';
            } else {
                tabs[1].classList.add('active');
                document.getElementById('loginForm').style.display = 'none';
                document.getElementById('registerForm').style.display = 'block';
            }
        }

        function showCreateModal() {
            document.getElementById('createModal').classList.add('active');
            // Сбрасываем тип и загружаем категории если ещё не загружены
            if (typeof setAuctionType === 'function') setAuctionType('bid');
            if (typeof loadCategories === 'function') loadCategories();
        }

        function closeCreateModal() {
            document.getElementById('createModal').classList.remove('active');
            document.getElementById('createError').style.display = 'none';
            // cleanup cropper + preview
            try { clearLotImage(); } catch {}
        }

        function logout() {
            // Закрываем все WebSocket соединения
            Object.values(websockets).forEach(ws => {
                if (ws.pingInterval) clearInterval(ws.pingInterval);
                ws.close();
            });
            websockets = {};
            reconnectAttempts = {};
            
            localStorage.removeItem('token');
            location.reload();
        }

        function showSection(e, section) {
            document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
            e.target.closest('.nav-item').classList.add('active');
            
            if (section === 'auctions') {
                currentFilters.page = 1;
                loadAuctions();
            } else if (section === 'my-bids') {
                showToast('В разработке', 'Раздел «Мои ставки» появится скоро', 'warn');
            }
        }

        
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;

            try {
                const response = await fetch(`${API_URL}/api/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                if (response.ok) {
                    const data = await response.json();
                    token = data.token;
                    localStorage.setItem('token', token);
                    token = localStorage.getItem('token');
location.reload();
                } else {
                    const error = await response.json();
                    const detail = Array.isArray(error.detail)
                        ? error.detail.map(e => e.msg || 'Ошибка валидации').join('; ')
                        : (error.detail || 'Ошибка входа');
                    const errorDiv = document.getElementById('authError');
                    errorDiv.textContent = detail;
                    errorDiv.style.display = 'block';
                }
            } catch (e) {
                showToast('Ошибка сети', 'Проверьте соединение', 'bad');
            }
        });

        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('registerUsername').value;
            const email = document.getElementById('registerEmail').value;
            const password = document.getElementById('registerPassword').value;

            try {
                const response = await fetch(`${API_URL}/api/register`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, email, password })
                });

                if (response.ok) {
                    const data = await response.json();
                    token = data.token;
                    localStorage.setItem('token', token);
                    // Surface the post-register hint via localStorage so it
                    // survives the reload below (init reads + clears it).
                    try {
                        localStorage.setItem('flash_verify_email', email);
                    } catch (_) {}
                    token = localStorage.getItem('token');
location.reload();
                } else {
                    const error = await response.json();
                    const detail = Array.isArray(error.detail)
                        ? error.detail.map(e => e.msg || 'Ошибка валидации').join('; ')
                        : (error.detail || 'Ошибка регистрации');
                    const errorDiv = document.getElementById('authError');
                    errorDiv.textContent = detail;
                    errorDiv.style.display = 'block';
                }
            } catch (e) {
                showToast('Ошибка сети', 'Проверьте соединение', 'bad');
            }
        });

        document.getElementById('createAuctionForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            const title = document.getElementById('auctionTitle').value;
            const description = document.getElementById('auctionDescription').value;
            const auction_type = window.currentAuctionType || 'bid';
            const categoryEl    = document.getElementById('auctionCategory');
            const categoryParEl = document.getElementById('auctionCategoryParent');
            // Берём подкатегорию если выбрана, иначе родительскую
            const catVal = (categoryEl && categoryEl.value && categoryEl.style.display !== 'none')
              ? categoryEl.value
              : (categoryParEl ? categoryParEl.value : '');
            const category_id = catVal ? parseInt(catVal) : null;

            let starting_price, duration_minutes, bin_price = null;

            if (auction_type === 'bin') {
                const binPrice = parseFloat(document.getElementById('auctionBinPrice').value);
                if (!binPrice || binPrice <= 0) {
                    if (errorDiv) { errorDiv.textContent = 'Укажите цену «Купить сразу»'; errorDiv.style.display = 'block'; }
                    return;
                }
                bin_price = binPrice;
                starting_price = binPrice;
                duration_minutes = parseInt(document.getElementById('auctionDurationBin').value) || 10080;
            } else {
                starting_price = parseFloat(document.getElementById('auctionPrice').value);
                duration_minutes = parseInt(document.getElementById('auctionDuration').value);
                if (!starting_price || starting_price <= 0) {
                    if (errorDiv) { errorDiv.textContent = 'Укажите стартовую цену'; errorDiv.style.display = 'block'; }
                    return;
                }
                if (!duration_minutes || duration_minutes <= 0) {
                    if (errorDiv) { errorDiv.textContent = 'Укажите длительность'; errorDiv.style.display = 'block'; }
                    return;
                }
            }

            const errorDiv = document.getElementById('createError');
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }

            const form = document.getElementById('createAuctionForm');
            const submitBtn = form?.querySelector('button[type="submit"]');
            const prevBtnText = submitBtn ? submitBtn.textContent : null;
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Создаём…';
            }

            try {
                // 1) upload images
                let image_url = null;
                let image_urls = [];
                try {
                    const uploaded = await uploadLotImageIfAny();
                    image_url = uploaded.image_url;
                    image_urls = uploaded.image_urls;
                } catch (imgErr) {
                    const msg = imgErr?.message || 'Ошибка загрузки изображения.';
                    if (errorDiv) { errorDiv.textContent = msg; errorDiv.style.display = 'block'; }
                    else showToast('Ошибка', msg, 'bad');
                    return;
                }

                // 2) create auction
                const response = await fetch(`${API_URL}/api/auctions`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ title, description, starting_price, duration_minutes, image_url, image_urls, category_id, auction_type, bin_price })
                });

                if (response.ok) {
                    closeCreateModal();
                    form.reset();
                    clearLotImage();
                    setAuctionType('bid');
                    currentFilters.page = 1;
                    await loadAuctions();
                } else {
                    const error = await response.json();
                    if (errorDiv) {
                        errorDiv.textContent = window.formatError(error, 'Ошибка создания аукциона');
                        errorDiv.style.display = 'block';
                    }
                }
            } catch (e) {
                showToast('Ошибка сети', 'Проверьте соединение', 'bad');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = prevBtnText || 'Создать';
                }
            }
        });

        // Очистка при закрытии страницы
        window.addEventListener('beforeunload', () => {
            Object.values(websockets).forEach(ws => {
                if (ws.pingInterval) clearInterval(ws.pingInterval);
                ws.close();
            });
            Object.values(timers).forEach(timer => clearInterval(timer));
        });

        // Запуск
        init();
    

document.addEventListener('DOMContentLoaded', () => {
  // Clear search button
  const clearBtn = document.getElementById('clearSearch');
  const searchInput = document.getElementById('searchInput');
  if (clearBtn && searchInput) {
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      if (typeof currentFilters !== 'undefined') {
        currentFilters.search = '';
        currentFilters.page = 1;
        if (typeof loadAuctions === 'function') loadAuctions();
      }
    });
  }

  // Auto-apply price filter with debounce
  let priceTimer;
  ['minPrice','maxPrice'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      clearTimeout(priceTimer);
      priceTimer = setTimeout(() => {
        if (typeof currentFilters === 'undefined') return;
        currentFilters.minPrice = document.getElementById('minPrice')?.value || null;
        currentFilters.maxPrice = document.getElementById('maxPrice')?.value || null;
        currentFilters.page = 1;
        if (typeof loadAuctions === 'function') loadAuctions();
      }, 600);
    });
  });

  // Creator search with debounce
  let creatorTimer;
  const creatorInput = document.getElementById('creatorInput');
  if (creatorInput) {
    creatorInput.addEventListener('input', () => {
      clearTimeout(creatorTimer);
      creatorTimer = setTimeout(() => {
        if (typeof currentFilters === 'undefined') return;
        currentFilters.createdBy = creatorInput.value.trim();
        currentFilters.page = 1;
        if (typeof loadAuctions === 'function') loadAuctions();
      }, 500);
    });
  }

  setTimeout(syncCreateBtns, 500);
});

/* ========= Unified menu controller ========= */
(function(){
  const KEY = 'menu_collapsed';

  function isMobile(){ return window.matchMedia('(max-width: 900px)').matches; }

  function readSaved(){
    try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
  }
  function save(val){
    try { localStorage.setItem(KEY, val ? '1' : '0'); } catch {}
  }

  function applyFromSaved(){
    if (isMobile()){
      // mobile: no mini mode visually
      document.body.classList.remove('menu-collapsed');
      return;
    }
    document.body.classList.toggle('menu-collapsed', readSaved());
  }

  window.toggleSidebar = function(){
    const sb = document.getElementById('sidebar') || document.querySelector('.sidebar');
    const ov = document.getElementById('overlay');
    if (!sb) return;

    if (isMobile()){
      const open = !document.body.classList.contains('menu-open');
      document.body.classList.toggle('menu-open', open);
      ov && ov.classList.toggle('show', open);
      return;
    }

    // desktop: toggle mini mode
    const next = !document.body.classList.contains('menu-collapsed');
    document.body.classList.toggle('menu-collapsed', next);
    save(next);
  };

  function closeMobile(){
    const ov = document.getElementById('overlay');
    document.body.classList.remove('menu-open');
    ov && ov.classList.remove('show');
  }

  function wire(){
    // Ensure overlay exists
    const ov = document.getElementById('overlay');
    if (ov) ov.addEventListener('click', closeMobile);

    // Buttons (support different ids/classes across pages)
    const btns = [
      document.getElementById('menuBtn'),
      document.getElementById('menuToggle'),
      document.querySelector('.menu-btn'),
      document.querySelector('[data-menu-toggle="1"]'),
    ].filter(Boolean);
    btns.forEach(b => b.addEventListener('click', (e)=>{ e.preventDefault(); window.toggleSidebar(); }));

    // Close drawer when navigating (mobile)
    document.querySelectorAll('.nav-item').forEach(el=>{
      el.addEventListener('click', ()=>{ if (isMobile()) closeMobile(); });
      // add tooltip label if missing
      if (!el.getAttribute('data-label')){
        const spans = el.querySelectorAll('span');
        if (spans.length >= 2){
          el.setAttribute('data-label', spans[1].textContent.trim());
        }
      }
    });

    applyFromSaved();
  }

  window.addEventListener('resize', ()=> {
    // when switching between mobile/desktop, reset drawer and apply saved collapsed on desktop
    const ov = document.getElementById('overlay');
    document.body.classList.remove('menu-open');
    ov && ov.classList.remove('show');
    applyFromSaved();
  });

  document.addEventListener('DOMContentLoaded', wire);
})();

/* === Menu fixes (v4): remove logo redirects + hard stop bubbling === */
document.addEventListener('DOMContentLoaded', () => {
  // Remove logo click-to-home to prevent accidental redirects
  document.querySelectorAll('.logo').forEach(logo => {
    if (logo.hasAttribute('onclick')) logo.removeAttribute('onclick');
    // also neutralize pointer events on pseudo overlays not needed; keep logo itself clickable via nav if desired
  });

  const btn = document.getElementById('menuBtn');
  if (btn){
    // remove inline onclick
    if (btn.hasAttribute('onclick')) btn.removeAttribute('onclick');

    const stop = (e) => { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); };
    // stop as early as possible
    btn.addEventListener('pointerdown', stop, true);
    btn.addEventListener('mousedown', stop, true);
    btn.addEventListener('touchstart', stop, true);
    btn.addEventListener('click', (e) => {
      stop(e);
      if (typeof window.toggleSidebar === 'function') window.toggleSidebar();
    }, true);
  }
});

  // Robust toggle for advanced filters (works even if elements were re-rendered)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('#toggleAdvanced');
    if (!btn) return;
    e.preventDefault();
    const adv = document.getElementById('advancedFilters');
    if (!adv) return;
    adv.classList.toggle('open');
    adv.style.display = adv.classList.contains('open') ? 'block' : 'none';
    btn.setAttribute('aria-expanded', adv.classList.contains('open') ? 'true' : 'false');
  }, true);


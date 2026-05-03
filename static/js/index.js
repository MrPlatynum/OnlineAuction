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

document.addEventListener('DOMContentLoaded', () => setTimeout(loadCategories, 150));

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
  list.innerHTML = history.map(q => `
    <div class="sh-item" onclick="applyHistorySearch('${q.replace(/'/g, "\\'")}')">
      <span class="sh-item-icon">🕐</span>
      <span class="sh-item-text">${q}</span>
      <button class="sh-item-del" onclick="event.stopPropagation();removeFromSearchHistory('${q.replace(/'/g, "\\'")}')">×</button>
    </div>`).join('');
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
        btn.innerHTML = `<span>${cat.icon}</span> ${cat.name}`;
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
            sb.innerHTML = `<span>${ch.icon}</span> ${ch.name}`;
            sb.onclick = () => selectCategory(sb, ch.slug, cat.slug, ch.name, cat.name);
            subs.appendChild(sb);
          });
          listEl.appendChild(subs);
        }
      });
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
        opt.textContent = `${cat.icon} ${cat.name}`;
        parentSel.appendChild(opt);
      });
      parentSel.addEventListener('change', () => {
        const catId = +parentSel.value;
        const cat = cats.find(c => c.id === catId);
        subSel.innerHTML = '<option value="">— Вся категория —</option>';
        if (cat && cat.children && cat.children.length) {
          cat.children.forEach(ch => {
            const o = document.createElement('option');
            o.value = ch.id; o.textContent = `${ch.icon} ${ch.name}`;
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
  if (currentFilters.search)     tags.push({ label: `🔍 ${currentFilters.search}`,   key: 'search' });
  if (currentFilters.category) {
    const parentSlug = currentFilters.categoryParentSlug;
    const parentName = currentFilters.categoryParentName;
    const name       = currentFilters.categoryName;
    let label;
    if (parentSlug && parentName) {
      // Подкатегория — "Одежда → Мужская", клик на "Одежда" переключает на родителя
      label = `📂 <span class="crumb-link" onclick="clickCrumbParent()" title="Выбрать категорию ${parentName}">${parentName}</span> <span style="opacity:.5;">›</span> ${name}`;
    } else {
      label = `📂 ${name}`;
    }
    tags.push({ label, key: 'category', raw: true });
  }
  if (currentFilters.minPrice)   tags.push({ label: `от $${currentFilters.minPrice}`, key: 'minPrice' });
  if (currentFilters.maxPrice)   tags.push({ label: `до $${currentFilters.maxPrice}`, key: 'maxPrice' });
  if (currentFilters.createdBy)  tags.push({ label: `@${currentFilters.createdBy}`,   key: 'createdBy' });
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

// Patch init to sync buttons after user loaded
const _origInit = window.init;
window.init = async function() {
  if (typeof _origInit === 'function') await _origInit();
  syncCreateBtns();
};

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

        const API_URL = window.location.origin;
        const WS_URL = window.location.origin.replace(/^http/i, 'ws');
        let token = localStorage.getItem('token');
        let currentUser = null;
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
                return null;
            }

            if (!response.ok) {
                console.warn('loadCurrentUser: api error', response.status);
                return null;
            }

            currentUser = await response.json();

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

        function displayAuctions(auctions) {
            const container = document.getElementById('auctionsContainer');
            
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
                const creatorAvatarUrl = auction.creator_avatar_url || null;
                const creatorAvatarHtml = creatorName ? (() => {
                  const src = creatorAvatarUrl
                    ? (creatorAvatarUrl.startsWith('http') ? creatorAvatarUrl : `${API_URL}${creatorAvatarUrl}`)
                    : null;
                  return `<div class="mini-avatar">${src ? `<img src="${src}" alt="${creatorName}">` : creatorName[0].toUpperCase()}</div>`;
                })() : '';

                const isOwner = currentUser && auction.created_by === currentUser.id;
                const canDelete = isOwner && !(auction.is_completed && auction.winner_id);
                const catLabel = auction.category_icon && auction.category_name
                    ? `${auction.category_icon} ${auction.category_name}` : '';
                const safeTitle = auction.title.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

                const allImgUrls = (auction.image_urls && auction.image_urls.length)
                    ? auction.image_urls.map(u => String(u).startsWith('http') ? u : `${API_URL}${u}`)
                    : (imgSrc ? [imgSrc] : []);

                const hasMultiple = allImgUrls.length > 1;

                const imagesHtml = allImgUrls.length
                    ? allImgUrls.map((u, i) => `<img class="card-slide${i === 0 ? ' active' : ''}" src="${u}" alt="${safeTitle}" data-slide="${i}">`).join('')
                    : `<div class="card-placeholder"><div class="card-placeholder-icon">🖼</div><div class="card-placeholder-label">Нет фото</div></div>`;

                const isBinType = auction.auction_type === 'bin';
                const binBadge = isBinType
                    ? `<div class="auction-badge" style="background:rgba(232,160,32,0.9);color:#000;top:auto;bottom:8px;left:8px;">⚡ BIN</div>`
                    : '';

                return `
                    <div class="auction-card" data-auction-id="${auction.id}"
                       data-title="${safeTitle}"
                       data-price="${isBinType ? '⚡ ' : ''}$${auction.current_price.toFixed(2)}"
                       data-start="от $${auction.starting_price.toFixed(2)}"
                       data-bids="${bidsCount !== '' ? '💬 ' + bidsCount : ''}"
                       data-creator="${creatorName ? '@' + creatorName : ''}"
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
                                <div class="auction-title">${auction.title}</div>
                            </a>
                            <div class="auction-price">$${auction.current_price.toFixed(2)}</div>
                            ${!isEnded
                                ? `<div class="auction-start auction-timer-row"><span class="auction-pulse" aria-hidden="true"></span><span class="auction-timer-text" data-timer="${auction.id}">${formatTime(timeRemaining)}</span></div>`
                                : `<div class="auction-start">Завершён · от $${auction.starting_price.toFixed(2)}</div>`}
                            ${creatorName ? `<div class="auction-meta-row"><span class="auction-creator">${creatorAvatarHtml}<a href="user.html?username=${encodeURIComponent(creatorName)}" onclick="event.stopPropagation()">@${creatorName}</a></span></div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            // Загружаем ставки и запускаем таймеры
            auctions.forEach(auction => {
                if (token && auction.time_remaining > 0) {
                    loadBids(auction.id);
                    connectWebSocket(auction.id);
                }
                startTimer(auction.id, auction.time_remaining);
            });
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
            
            if (!reconnectAttempts[auctionId]) {
                reconnectAttempts[auctionId] = 0;
            }
            
            ws.onopen = () => {
                console.log(`WebSocket connected for auction ${auctionId}`);
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
                    addBidToList(auctionId, data.bid);
                }
            };

            ws.onclose = () => {
                console.log(`WebSocket closed for auction ${auctionId}`);
                delete websockets[auctionId];
                
                if (ws.pingInterval) {
                    clearInterval(ws.pingInterval);
                }
                
                // Экспоненциальная задержка: 1s, 2s, 4s, 8s, 16s, максимум 30s
                const delay = Math.min(1000 * Math.pow(2, reconnectAttempts[auctionId]), 30000);
                reconnectAttempts[auctionId]++;
                
                console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts[auctionId]})`);
                setTimeout(() => {
                    const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
                    if (card) { // Переподключаемся только если карточка еще на странице
                        connectWebSocket(auctionId);
                    }
                }, delay);
            };

            ws.onerror = (error) => {
                console.error(`WebSocket error for auction ${auctionId}:`, error);
            };

            websockets[auctionId] = ws;
        }

        function updatePrice(auctionId, newPrice) {
            const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
            if (!card) return;
            const priceEl = card.querySelector('.auction-price');
            if (!priceEl) return;
            priceEl.textContent = '$' + Number(newPrice).toFixed(2);
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
                    alert(err.detail || 'Не удалось удалить лот');
                }
            } catch { alert('Ошибка сети'); }
        }

        async function loadBids(auctionId) {
            try {
                const response = await fetch(`${API_URL}/api/auctions/${auctionId}/bids?page=1&page_size=5`);
                const data = await response.json();
                const container = document.getElementById(`bids-${auctionId}`);
                if (container && data.items.length > 0) {
                    container.innerHTML = data.items.map(bid => `
                        <div class="bid-item">
                            <span class="bid-user">${bid.username}</span>
                            <span class="bid-amount">${bid.amount.toFixed(2)}</span>
                        </div>
                    `).join('');
                }
            } catch (e) {
                console.error('Error loading bids:', e);
            }
        }

        function addBidToList(auctionId, bid) {
            const container = document.getElementById(`bids-${auctionId}`);
            if (container) {
                const bidElement = document.createElement('div');
                bidElement.className = 'bid-item';
                bidElement.innerHTML = `
                    <span class="bid-user">${bid.username}</span>
                    <span class="bid-amount">${bid.amount.toFixed(2)}</span>
                `;
                container.insertBefore(bidElement, container.firstChild);
                while (container.children.length > 5) {
                    container.removeChild(container.lastChild);
                }
            }
        }

        async function placeBid(auctionId) {
            const card = document.querySelector(`[data-auction-id="${auctionId}"]`);
            const input = card.querySelector('.bid-input');
            const amount = parseFloat(input.value);

            if (!amount || amount <= 0) {
                alert('Введите корректную сумму');
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
                    alert(error.detail || 'Ошибка при размещении ставки');
                }
            } catch (e) {
                alert('Ошибка сети');
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
            
            filtersInitialized = true;
            console.log('✅ Фильтры инициализированы');
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
                alert('Раздел "Мои ставки" в разработке');
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
                alert('Ошибка сети');
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
                alert('Ошибка сети');
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
                    else alert(msg);
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
                        errorDiv.textContent = error.detail || 'Ошибка создания аукциона';
                        errorDiv.style.display = 'block';
                    }
                }
            } catch (e) {
                alert('Ошибка сети');
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

/* ================================================================
   NOTIFICATION BELL
   ================================================================ */
(function() {
  const API_URL = window.location.origin;

  function getToken() { return localStorage.getItem('token'); }

  const btn      = document.getElementById('notifBtn');
  const badge    = document.getElementById('notifBadge');
  const dropdown = document.getElementById('notifDropdown');
  const list     = document.getElementById('notifList');
  const markAllBtn = document.getElementById('notifMarkAll');

  if (!btn || !dropdown) return;

  let unreadCount = 0;
  let wsNotif = null;
  let currentUserId = null;
  let isOpen = false;

  const ICONS = {
    bid_outbid:     { emoji: '⚡', cls: 'bid_outbid' },
    bid_placed:     { emoji: '💰', cls: 'bid_placed' },
    auction_won:    { emoji: '🏆', cls: 'auction_won' },
    auction_lost:   { emoji: '😔', cls: 'auction_lost' },
    auction_sold:   { emoji: '✅', cls: 'auction_sold' },
    new_lot:       { emoji: '🔖', cls: 'bid_placed' },
    auction_ending: { emoji: '⏰', cls: 'auction_ending' },
  };

  function fmtAge(iso) {
    // Бэкенд отдаёт UTC без 'Z' — добавляем чтобы браузер правильно парсил
    const utcIso = iso && !iso.endsWith('Z') && !iso.includes('+') ? iso + 'Z' : iso;
    const diff = Math.floor((Date.now() - new Date(utcIso)) / 1000);
    if (diff < 60)    return 'только что';
    if (diff < 3600)  return `${Math.floor(diff / 60)} мин назад`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
    return new Date(utcIso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
  }

  function esc(str) {
    return String(str || '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function setCount(n) {
    unreadCount = Math.max(0, n);
    if (unreadCount > 0) {
      badge.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
      badge.style.display = 'flex';
      btn.classList.add('has-unread');
    } else {
      badge.style.display = 'none';
      btn.classList.remove('has-unread');
    }
  }

  function renderList(items) {
    if (!items.length) {
      list.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Уведомлений пока нет</div>`;
      return;
    }
    list.innerHTML = items.map(n => {
      const ico = ICONS[n.type] || { emoji: '🔔', cls: '' };
      return `
        <div class="notif-item ${n.is_read ? '' : 'unread'}" data-id="${n.id}" data-auction="${n.auction_id || ''}">
          <div class="notif-icon ${ico.cls}">${ico.emoji}</div>
          <div class="notif-body">
            <div class="notif-title">${esc(n.title)}</div>
            <div class="notif-msg">${esc(n.message)}</div>
            <div class="notif-time">${fmtAge(n.created_at)}</div>
          </div>
        </div>`;
    }).join('');
  }

  async function apiFetch(url, opts = {}) {
    const tk = getToken();
    const headers = { ...(opts.headers || {}) };
    if (tk) headers['Authorization'] = 'Bearer ' + tk;
    return fetch(url, { ...opts, headers });
  }

  async function fetchCount() {
    if (!getToken()) return;
    try {
      const r = await apiFetch(`${API_URL}/api/notifications/unread-count`);
      if (r.ok) { const d = await r.json(); setCount(d.count ?? 0); }
    } catch {}
  }

  async function fetchNotifications() {
    if (!getToken()) {
      list.innerHTML = `<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Войдите для уведомлений</div>`;
      return;
    }
    list.innerHTML = `<div class="notif-empty">Загрузка…</div>`;
    try {
      const r = await apiFetch(`${API_URL}/api/notifications?limit=30`);
      if (r.ok) renderList(await r.json());
      else list.innerHTML = `<div class="notif-empty">Ошибка загрузки</div>`;
    } catch {
      list.innerHTML = `<div class="notif-empty">Нет связи с сервером</div>`;
    }
  }

  async function markOneRead(id) {
    try { await apiFetch(`${API_URL}/api/notifications/${id}/read`, { method: 'POST' }); } catch {}
  }

  async function markAllRead() {
    try {
      await apiFetch(`${API_URL}/api/notifications/mark-all-read`, { method: 'POST' });
      setCount(0);
      await fetchNotifications();
    } catch {}
  }

  /* Open / close */
  function openDropdown() {
    isOpen = true;
    dropdown.classList.add('open');
    fetchNotifications();
  }
  function closeDropdown() {
    isOpen = false;
    dropdown.classList.remove('open');
  }

  btn.addEventListener('click', e => { e.stopPropagation(); isOpen ? closeDropdown() : openDropdown(); });
  document.addEventListener('click', e => {
    if (isOpen && !dropdown.contains(e.target) && e.target !== btn) closeDropdown();
  });
  markAllBtn.addEventListener('click', e => { e.stopPropagation(); markAllRead(); });

  list.addEventListener('click', async e => {
    const item = e.target.closest('.notif-item');
    if (!item) return;
    const id = item.dataset.id;
    const auctionId = item.dataset.auction;
    if (id && item.classList.contains('unread')) {
      item.classList.remove('unread');
      setCount(unreadCount - 1);
      await markOneRead(id);
    }
    if (auctionId) { closeDropdown(); window.location.href = `auction.html?id=${auctionId}`; }
  });

  /* WebSocket — realtime */
  function connectNotifWS(userId) {
    if (wsNotif) { try { wsNotif.close(); } catch {} }
    const tk = getToken();
    if (!tk) return;
    wsNotif = new WebSocket(`${API_URL.replace(/^http/i, 'ws')}/ws/notifications/${userId}?token=${encodeURIComponent(tk)}`);
    wsNotif.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'notification') {
          setCount(unreadCount + 1);
          if (isOpen) fetchNotifications();
        }
      } catch {}
    };
    wsNotif.onclose = () => setTimeout(() => { if (currentUserId) connectNotifWS(currentUserId); }, 3000);
  }

  async function initNotifBell() {
    if (!getToken()) { btn.style.display = 'none'; return; }
    btn.style.display = 'flex';
    await fetchCount();
    try {
      const r = await apiFetch(`${API_URL}/api/me`);
      if (r.ok) {
        const me = await r.json();
        currentUserId = me.id;
        if (currentUserId) connectNotifWS(currentUserId);
      }
    } catch {}
    setInterval(fetchCount, 60000);
  }

  setTimeout(initNotifBell, 800);
  window.addEventListener('storage', e => { if (e.key === 'token') setTimeout(initNotifBell, 300); });
  window.initNotifBell = initNotifBell;
})();

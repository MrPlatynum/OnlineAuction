(function() {
  'use strict';

  const auctionId = new URLSearchParams(location.search).get('id');
  const token     = localStorage.getItem('token');
  let currentPriceValue = null;
  let remainingSec      = null;
  let isActive          = null;
  let currentUserId     = null;
  let leaderUserId      = null;
  let ws = null, wsPingTimer = null;

  function isUserLeading() {
    return currentUserId !== null && leaderUserId !== null && currentUserId === leaderUserId;
  }
  const $ = id => document.getElementById(id);

  // showToast — общий из common.js (window.showToast)

  function fmtTime(sec) {
    if (!Number.isFinite(sec)||sec<=0) return '0м 00с';
    const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;
    if (h>0) return `${h}ч ${m}м ${String(s).padStart(2,'0')}с`;
    return `${m}м ${String(s).padStart(2,'0')}с`;
  }

  function syncEl(id, val) { const el=$(id); if(el) el.textContent=val; }

  function flashPrice() {
    const el = $('currentPrice');
    if (!el) return;
    el.classList.remove('flash');
    void el.offsetWidth;       /* перезапуск CSS-анимации */
    el.classList.add('flash');
  }

  // ---- Breadcrumbs ----
  let _categoriesCache = null;
  async function loadBreadcrumbs(catId) {
    try {
      if (!_categoriesCache) {
        const r = await fetch(`${API}/api/categories`);
        if (!r.ok) return;
        _categoriesCache = await r.json();
      }
      // Ищем путь до категории в дереве
      const path = findCategoryPath(_categoriesCache, catId);
      if (!path.length) return;

      const wrap = document.querySelector('.nav-crumb');
      const titleEl = $('crumbTitle');
      if (!wrap || !titleEl) return;

      // Очищаем всё внутри nav-crumb и пересобираем
      wrap.innerHTML = '';

      const root = document.createElement('a');
      root.href = 'index.html';
      root.textContent = 'Аукционы';
      wrap.appendChild(root);

      path.forEach(c => {
        const sep = document.createElement('span');
        sep.className = 'nav-crumb-sep';
        sep.textContent = '›';
        wrap.appendChild(sep);
        const a = document.createElement('a');
        a.href = `index.html?category=${encodeURIComponent(c.slug)}`;
        a.textContent = c.name;
        wrap.appendChild(a);
      });

      // Добавляем обратно слот для заголовка лота
      const sep = document.createElement('span');
      sep.className = 'nav-crumb-sep';
      sep.textContent = '›';
      wrap.appendChild(sep);
      const cur = document.createElement('span');
      cur.className = 'nav-crumb-current';
      cur.id = 'crumbTitle';
      cur.textContent = titleEl.textContent;  // сохраняем текущее значение
      wrap.appendChild(cur);
    } catch (e) {
      console.warn('[breadcrumbs] failed:', e);
    }
  }

  function findCategoryPath(cats, targetId, ancestors = []) {
    for (const c of cats || []) {
      if (c.id === targetId) return [...ancestors, c];
      const sub = findCategoryPath(c.children || [], targetId, [...ancestors, c]);
      if (sub.length) return sub;
    }
    return [];
  }

  function applyStatus(active) {
    isActive = !!active;
    const badge = $('statusBadge');
    if (isActive) {
      badge.textContent = 'Активен'; badge.className = 'status-badge active';
    } else {
      badge.textContent = 'Завершён'; badge.className = 'status-badge ended';
      syncEl('timeLeft','Завершён'); syncEl('timeLeft2','Завершён');
      const tl=$('timeLeft'),tl2=$('timeLeft2');
      if(tl) tl.className='timer-val';
      if(tl2) tl2.className='lot-stat-value red';
    }
    refreshBidControls();
  }

  function refreshBidControls() {
    const leading = isUserLeading();
    const disabled = !token || !isActive || leading;
    $('bidBtn').disabled = disabled;
    $('bidAmount').disabled = disabled;
    document.querySelectorAll('.bid-quick-btn, .bid-num-btn').forEach(b => { b.disabled = disabled; });
    updateBidHint();
  }

  function updateBidHint() {
    const hint=$('bidHint');
    if (!token) return void(hint.textContent='Войдите, чтобы делать ставки.');
    if (!isActive) return void(hint.textContent='Аукцион завершён — ставки закрыты.');
    if (isUserLeading()) return void(hint.textContent='Вы уже лидируете в этом аукционе — дождитесь чужой ставки.');
    const min=currentPriceValue!==null?currentPriceValue+0.01:null;
    hint.textContent=min!==null?`Минимальная ставка: ${fmtMoney(min)}`:'Ставка должна превышать текущую цену.';
  }

  function tick() {
    if (remainingSec===null) return;
    if (remainingSec<=0) { applyStatus(false); return; }
    const t=fmtTime(remainingSec);
    syncEl('timeLeft',t); syncEl('timeLeft2',t);
    // Urgent timer color
    const tv=$('timeLeft');
    if(tv) tv.className = remainingSec<300?'timer-val urgent':'timer-val';
    remainingSec--;
    setTimeout(tick,1000);
  }

  function setAuthUI(user) {
    const profile=$('userProfile'), authBtn=$('authBtn');
    if (!token) { profile.style.display='none'; return; }
    if (!user) return;
    $('avatar').textContent=(user.username?.[0]||'?').toUpperCase();
    if (user.avatar_url) {
      const img=document.createElement('img');
      img.src=user.avatar_url.startsWith('http')?user.avatar_url:`${API}${user.avatar_url}`;
      img.alt=user.username; $('avatar').appendChild(img);
    }
    $('userName').textContent=user.username||'—';
    $('userBalance').textContent=fmtMoney(user.balance??0);
    profile.style.display='flex'; authBtn.style.display='none';
  }

  function goAuth() {
    if (!token) { location.href='index.html'; return; }
    localStorage.removeItem('token'); location.href='index.html';
  }


  async function loadMe() {
    if (!token) return null;
    try { const r=await apiFetch(API+'/api/me'); return r.ok?r.json():null; } catch { return null; }
  }

  async function loadAuction() {
    if (!auctionId) { syncEl('title','Лот не найден'); showToast('Ошибка','Не указан id лота.','bad'); return null; }
    const r=await fetch(`${API}/api/auctions/${encodeURIComponent(auctionId)}`);
    if (!r.ok) { syncEl('title','Лот не найден'); showToast('Не найдено','Лот не существует.','warn'); return null; }
    const a=await r.json();

    document.title=`${a.title} — Лотус`;
    syncEl('title',a.title||'Лот'); syncEl('crumbTitle',a.title||'Лот');
    // Описание: если пусто, показываем muted-плейсхолдер
    const descEl = $('description');
    if (descEl) {
      const txt = (a.description || '').trim();
      if (txt) {
        descEl.textContent = txt;
        descEl.classList.remove('is-empty');
      } else {
        descEl.textContent = 'Продавец не оставил описание';
        descEl.classList.add('is-empty');
      }
    }

    // Images
    const urls=(a.image_urls&&a.image_urls.length)?a.image_urls.map(u=>String(u).startsWith('http')?u:API+u):(a.image_url?[String(a.image_url).startsWith('http')?a.image_url:API+a.image_url]:[]);
    const slidesEl=$('lotSlides'),dotsEl=$('lotDots'),prevBtn=$('lotPrev'),nextBtn=$('lotNext'),counter=$('lotCounter'),placeholder=$('imgPlaceholder');
    if (urls.length&&slidesEl) {
      if (placeholder) placeholder.style.display='none';
      slidesEl.innerHTML=urls.map((u,i)=>`<img class="lot-slide${i===0?' active':''}" src="${esc(u)}" alt="${esc(a.title)}" data-idx="${i}">`).join('');
      // Thumbnails
      const thumbsEl=$('lotThumbs');
      if (thumbsEl&&urls.length>1) {
        thumbsEl.innerHTML=urls.map((u,i)=>`<div class="lot-thumb${i===0?' active':''}" onclick="lotGoTo(${i});updateThumbs(${i})"><img src="${esc(u)}" alt="${i+1}"></div>`).join('');
      }
      if (urls.length>1) {
        dotsEl.innerHTML=urls.map((_,i)=>`<span class="lot-dot${i===0?' active':''}" onclick="lotGoTo(${i})"></span>`).join('');
        if (prevBtn) prevBtn.style.display='flex';
        if (nextBtn) nextBtn.style.display='flex';
        if (counter) { counter.style.display='block'; counter.textContent=`1 / ${urls.length}`; }
      }
    }

    // Stats — sync to both sidebar and info block
    currentPriceValue=a.current_price;
    const priceStr=fmtMoney(currentPriceValue);
    syncEl('currentPrice',priceStr); syncEl('currentPrice2',priceStr);
    const startStr=fmtMoney(a.starting_price);
    syncEl('startingPrice',startStr); syncEl('startingPrice2',startStr);
    syncEl('bidsCount',a.bids_count??'0'); syncEl('bidsCount2',a.bids_count??'0');

    remainingSec=Number.isFinite(a.time_remaining)?a.time_remaining:null;
    if (remainingSec!==null) { const t=fmtTime(remainingSec); syncEl('timeLeft',t); syncEl('timeLeft2',t); }

    applyStatus(a.is_active);

    // BIN
    const aType=a.auction_type||'bid';
    const hasBin=aType==='bin'||(a.bin_price&&a.bin_price>0);
    if (hasBin) {
      $('binBlock').style.display='block';
      syncEl('binPriceDisplay',fmtMoney(a.bin_price));
      if (!a.is_active) $('binBtn').disabled=true;
      if (aType==='bin') {
        $('bidForm').style.display='none';
        $('binDivider').style.display='none';
        $('priceStartRow').style.display='none';
        const ph=$('price-hero'); if(ph) ph.style.display='none';
        // Скрываем блок текущей ставки — показываем только цену BIN
        const priceHero=document.querySelector('.price-hero');
        if(priceHero) priceHero.style.display='none';
        syncEl('bidCardTitle','');
      }
      else syncEl('bidCardTitle','Ставка или покупка');
    }

    // Winner
    if (!a.is_active&&a.winner_username) {
      $('winnerBlock').style.display='flex'; syncEl('winnerName',a.winner_username);
      // Hide timer row when ended
      const tr=$('timerRow'); if(tr) tr.style.background='var(--bg-4)';
    }

    // Seller
    if (a.creator_username) {
      $('sellerAvatar').textContent=a.creator_username[0].toUpperCase();
      if (a.creator_avatar_url) {
        const img=document.createElement('img');
        img.src=a.creator_avatar_url.startsWith('http')?a.creator_avatar_url:`${API}${a.creator_avatar_url}`;
        img.alt=a.creator_username; $('sellerAvatar').appendChild(img);
      }
      syncEl('sellerLink','@'+a.creator_username);
      $('sellerLink').href=`user.html?username=${encodeURIComponent(a.creator_username)}`;
      $('sellerCard').style.display='block';
      if (a.created_by) loadSeller(a.created_by,a.creator_username);
    }

    // Category
    if (a.category_name) {
      const cb=$('categoryBadge');
      cb.textContent=a.category_name;
      cb.style.display='inline-flex';
    }
    // Breadcrumbs (Аукционы › Категория › Подкатегория › Лот)
    if (a.category_id) loadBreadcrumbs(a.category_id);

    // Lot byline (под заголовком в шапке)
    const byline=$('lotByline');
    if (byline && a.creator_username) {
      const parts=[];
      parts.push(`Продаёт: <a href="user.html?username=${encodeURIComponent(a.creator_username)}">@${esc(a.creator_username)}</a>`);
      if (a.category_name) parts.push(esc(a.category_name));
      byline.innerHTML = parts.join('<span class="sep">·</span>');
    }

    // Quick-bid buttons видны только для авторизованных активных торгов
    const quick=$('bidQuick');
    if (quick) {
      quick.style.display = (token && a.is_active && a.auction_type !== 'bin') ? 'flex' : 'none';
    }

    return a;
  }

  function updateThumbs(idx) {
    document.querySelectorAll('.lot-thumb').forEach((t,i)=>t.classList.toggle('active',i===idx));
  }

  function renderBids(items) {
    leaderUserId = items.length ? (items[0].user_id ?? null) : null;
    refreshBidControls();
    const list=$('bidsList');
    if (!items.length) { list.innerHTML='<div class="bids-empty">Ставок пока нет — будьте первым!</div>'; return; }
    const medals = ['🥇','🥈','🥉'];
    list.innerHTML=items.map((b,i)=>{
      const rank = medals[i] || `<span>${i+1}</span>`;
      return `<div class="bid-row ${i===0?'top-bid':''}">
        <div class="bid-rank">${i<3 ? `<span class="bid-rank-medal">${medals[i]}</span>` : (i+1)}</div>
        <div style="flex:1;min-width:0;">
          <div class="bid-who">${esc(b.username??'—')}</div>
          <div class="bid-when">${fmtDate(b.timestamp)}</div>
        </div>
        <div class="bid-amt ${i===0?'top':''}">${fmtMoney(b.amount)}</div>
      </div>`;
    }).join('');
    syncEl('bidsCount',items.length); syncEl('bidsCount2',items.length);
  }

  // Quick-bid: добавляет к минимальной ставке (текущая+0.01) указанную сумму
  function bumpBid(amount) {
    // Прибавляем к текущей цене, а не к минимально допустимой
    // (current + 0.01). Иначе на лоте с круглой стартовой ценой
    // («55») кнопка «+5» давала «60.01» — некрасиво и неудобно.
    // При current = 55 кнопка «+5» теперь даёт ровно 60, что
    // всё равно строго больше текущей цены — сервер примет.
    const base = currentPriceValue !== null ? currentPriceValue : 0;
    const target = Math.round((base + amount) * 100) / 100;
    const inp = $('bidAmount');
    if (inp) {
      inp.value = target.toFixed(2);
      inp.focus();
      // лёгкий визуальный «пинок» поля
      inp.classList.remove('flash'); void inp.offsetWidth; inp.classList.add('flash');
    }
  }

  async function loadBids() {
    try {
      const r=await fetch(`${API}/api/auctions/${encodeURIComponent(auctionId)}/bids?page=1&page_size=20`);
      if (!r.ok) throw new Error();
      const d=await r.json();
      renderBids(d.items||[]);
      if (d.total!==undefined) { syncEl('bidsCount',d.total); syncEl('bidsCount2',d.total); }
    } catch { $('bidsList').innerHTML='<div class="bids-empty" style="color:var(--red)">Не удалось загрузить ставки</div>'; }
  }

  async function placeBid() {
    const raw=$('bidAmount').value, amount=Number(raw);
    if (!token) return showToast('Нужен вход','Войдите для участия в торгах.','warn');
    if (!isActive) return showToast('Закрыто','Аукцион уже завершён.','warn');
    if (isUserLeading()) return showToast('Вы уже лидируете','Дождитесь чужой ставки, прежде чем повышать.','warn');
    if (!raw||!Number.isFinite(amount)||amount<=0) return showToast('Некорректная ставка','Введите сумму больше нуля.','warn');
    const btn=$('bidBtn'),prev=btn.textContent;
    btn.disabled=true; btn.textContent='Отправка…';
    try {
      const r=await apiFetch(`${API}/api/bids`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({auction_id:Number(auctionId),amount})});
      if (!r.ok) { let msg='Ставка не принята.'; try{msg=(await r.json()).detail||msg;}catch{} showToast('Ошибка',msg,'bad'); }
      else { $('bidAmount').value=''; showToast('Принято','Ваша ставка зарегистрирована!','ok'); await loadBids(); }
    } catch { showToast('Ошибка','Нет связи с сервером.','bad'); }
    finally { btn.textContent=prev; refreshBidControls(); }
  }

  function connectWS() {
    if (!auctionId) return;
    if (wsPingTimer) { clearInterval(wsPingTimer); wsPingTimer=null; }
    ws=new WebSocket(`${WS_BASE}/ws/auction/${encodeURIComponent(auctionId)}`);
    ws.onopen=()=>{ wsPingTimer=setInterval(()=>{try{ws.send('ping');}catch{}},25000); };
    ws.onmessage=e=>{
      let data; try{data=JSON.parse(e.data);}catch{return;}
      if (data.type==='new_bid') {
        if (data.current_price!==undefined) {
          currentPriceValue=Number(data.current_price);
          const p=fmtMoney(currentPriceValue);
          syncEl('currentPrice',p); syncEl('currentPrice2',p);
          flashPrice();
          updateBidHint();
        }
        loadBids();
      }
      if (data.type==='time_update') {
        if (Number.isFinite(data.time_remaining)) { remainingSec=data.time_remaining; const t=fmtTime(remainingSec); syncEl('timeLeft',t); syncEl('timeLeft2',t); }
        if (data.current_price!==undefined) { currentPriceValue=Number(data.current_price); const p=fmtMoney(currentPriceValue); syncEl('currentPrice',p); syncEl('currentPrice2',p); updateBidHint(); }
      }
      if (data.type==='auction_ended') {
        applyStatus(false);
        if (data.final_price!==undefined) { currentPriceValue=Number(data.final_price); const p=fmtMoney(currentPriceValue); syncEl('currentPrice',p); syncEl('currentPrice2',p); }
        showToast('Аукцион завершён','Ставки закрыты.','warn'); loadBids();
      }
    };
    ws.onclose=()=>{ if(wsPingTimer){clearInterval(wsPingTimer);wsPingTimer=null;} setTimeout(connectWS,1500); };
  }

  $('copyLinkBtn').addEventListener('click', async ()=>{
    try { await navigator.clipboard.writeText(location.href); showToast('Скопировано','Ссылка скопирована.','ok'); }
    catch { showToast('Не вышло','Браузер не дал доступ к буферу.','warn'); }
  });
  $('bidAmount').addEventListener('keydown',e=>{ if(e.key==='Enter') placeBid(); });

  // Кастомный stepper рядом с полем ставки — шаг 1 ₽
  document.querySelectorAll('.bid-num-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const inp = $('bidAmount');
      if (!inp || inp.disabled) return;
      const cur = parseFloat(inp.value);
      const base = Number.isFinite(cur) ? cur : (currentPriceValue ?? 0);
      const delta = btn.dataset.step === 'up' ? 1 : -1;
      const next = Math.max(0, Math.round((base + delta) * 100) / 100);
      inp.value = next.toFixed(2);
      inp.focus();
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });

  async function init() {
    const me=await loadMe();
    currentUserId = me?.id ?? null;
    setAuthUI(me);
    const a=await loadAuction();
    if (!a) return;
    auctionData=a;
    const hasBids=(a.bids_count??0)>0;
    if (me&&a.created_by===me.id&&!hasBids&&a.is_active) {
      $('editLotBtn').style.display='inline-flex';
      if (new URLSearchParams(location.search).get('edit')==='1') setTimeout(()=>openEditModal(),300);
    }
    tick(); await loadBids(); connectWS();
  }

  // ---- Seller + Reviews ----
  let sellerId=null, sellerUsername=null, currentRating=0, isSubscribed=false;

  function renderStars(el,rating,size=13) {
    el.innerHTML='';
    for(let i=1;i<=5;i++){const s=document.createElement('span');s.className='star'+(i<=Math.round(rating)?' filled':'');s.style.fontSize=size+'px';s.textContent='★';el.appendChild(s);}
  }

  async function loadSeller(id,username) {
    sellerId=id; sellerUsername=username;
    // Ссылка на все отзывы продавца
    const allLink=$('allReviewsLink');
    if(allLink){allLink.href=`user.html?username=${encodeURIComponent(username)}`;allLink.style.display='inline';}
    try {
      const r=await fetch(`${API}/api/users/${encodeURIComponent(username)}`);
      if (r.ok) {
        const d=await r.json();
        syncEl('sellerMeta',`С нами с ${new Date(d.user?.created_at+'Z').toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}`);
        syncEl('sellerLots',d.stats?.created_count??'—');
        if (d.user?.avatar_url&&!$('sellerAvatar').querySelector('img')) {
          const img=document.createElement('img');img.src=d.user.avatar_url.startsWith('http')?d.user.avatar_url:`${API}${d.user.avatar_url}`;img.alt=username;$('sellerAvatar').appendChild(img);
        }
      }
    } catch {}
    try {
      const r=await fetch(`${API}/api/sellers/${id}/reviews`);
      if (r.ok) {
        const d=await r.json();
        const avg=d.stats.avg,total=d.stats.total;
        syncEl('sellerReviews',total);
        if(total>0){syncEl('sellerRatingVal',avg.toFixed(1));syncEl('sellerRatingCount',`(${total} отзыв${total===1?'':total>4?'ов':'а'})`);renderStars($('sellerStars'),avg);}
        // Показываем ВСЕ отзывы о продавце (не только об этом лоте)
        renderReviews(d);
        $('reviewsSummary').style.display = total > 0 ? 'flex' : 'none';
        $('reviewsSection').style.display = 'block';
      }
    } catch {}
    if (token) {
      try {
        const r=await fetch(`${API}/api/sellers/${id}/subscription`,{headers:{'Authorization':'Bearer '+token}});
        if (r.ok) {
          const d=await r.json(); isSubscribed=d.subscribed; syncEl('sellerSubs',d.subscribers_count); updateSubBtn();
          const me=await fetch(`${API}/api/me`,{headers:{'Authorization':'Bearer '+token}});
          if (me.ok){const meData=await me.json();if(meData.id!==id){$('subBtn').style.display='flex';$('reviewForm').style.display='block';}}
        }
      } catch {}
    }
  }

  function updateSubBtn() {
    const btn=$('subBtn'); if(!btn)return;
    if(isSubscribed){btn.classList.add('subscribed');syncEl('subBtnText','Отписаться');btn.querySelector('svg').innerHTML=`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" y1="11" x2="16" y2="11"/>`;}
    else{btn.classList.remove('subscribed');syncEl('subBtnText','Подписаться');btn.querySelector('svg').innerHTML=`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>`;}
  }

  async function toggleSubscription() {
    if(!token||!sellerId)return;
    try{const method=isSubscribed?'DELETE':'POST';const r=await fetch(`${API}/api/sellers/${sellerId}/subscribe`,{method,headers:{'Authorization':'Bearer '+token}});if(r.ok){const d=await r.json();isSubscribed=d.subscribed;syncEl('sellerSubs',d.subscribers_count);updateSubBtn();showToast(isSubscribed?'Подписка':'Отписка',isSubscribed?`Вы подписались на @${sellerUsername}`:`Вы отписались от @${sellerUsername}`,'ok');}}catch{showToast('Ошибка','Не удалось изменить подписку','bad');}
  }

  // Состояние отзывов / фильтра — два независимых стейта:
  //   1) thisLotOnly — toggle (чекбокс), фильтр по auction_id
  //   2) lotReviewFilter — exclusive (звезда), фильтр по rating
  // Оба применяются последовательно.
  let lotReviews = [];
  let lotReviewFilter = 'all';   // 'all' | 1..5
  let thisLotOnly = false;

  function renderReviews(data) {
    const avg = data.stats.avg, total = data.stats.total, dist = data.stats.distribution || {};
    lotReviews = data.reviews || [];

    syncEl('revAvg', total ? avg.toFixed(1) : '—');
    syncEl('revCount', `${total} отзыв${total === 1 ? '' : total > 4 ? 'ов' : 'а'}`);
    syncEl('reviewsTabCount', total);
    renderStars($('revBigStars'), avg, 15);

    // Бары распределения
    const barsEl = $('revBars');
    if (barsEl) barsEl.innerHTML = [5,4,3,2,1].map(n => {
      const cnt = dist[n] || 0, pct = total ? Math.round(cnt/total*100) : 0;
      const cls = n <= 2 ? 'low' : n === 3 ? 'mid' : '';
      return `<div class="review-bar-row">
        <span class="review-bar-label">${n}<span class="star-glyph">★</span></span>
        <div class="review-bar-track"><div class="review-bar-fill ${cls}" style="width:${pct}%"></div></div>
        <span class="review-bar-count">${cnt}</span>
      </div>`;
    }).join('');

    // Показываем фильтр-блок если есть отзывы
    const filterEl = $('revFilter');
    if (filterEl) filterEl.style.display = total > 0 ? 'flex' : 'none';

    // Счётчик «Об этом лоте» (фиксированный — не зависит от других фильтров)
    const thisLotCount = lotReviews.filter(r => r.auction_id === +auctionId).length;
    syncEl('revPillThisLotCount', thisLotCount);
    const thisPill = $('revPillThisLot');
    if (thisPill) thisPill.disabled = thisLotCount === 0;

    refreshStarPillCounts();
    renderReviewsList();
  }

  // Считает счётчики у звёздных пилюль с учётом активного «thisLotOnly»
  function refreshStarPillCounts() {
    const base = thisLotOnly
      ? lotReviews.filter(r => r.auction_id === +auctionId)
      : lotReviews;
    syncEl('revPillAll', base.length);
    const counts = {1:0, 2:0, 3:0, 4:0, 5:0};
    for (const r of base) counts[r.rating] = (counts[r.rating] || 0) + 1;
    [1,2,3,4,5].forEach(n => {
      syncEl('revPill' + n, counts[n] || 0);
      const pill = document.querySelector(`.rev-pill[data-rating="${n}"]`);
      if (pill) pill.disabled = (counts[n] || 0) === 0;
    });
  }

  function toggleThisLotOnly() {
    thisLotOnly = !thisLotOnly;
    const pill = $('revPillThisLot');
    if (pill) pill.classList.toggle('active', thisLotOnly);
    // Если активный звёзд-фильтр станет пустым — сбрасываем на «Все»
    refreshStarPillCounts();
    if (lotReviewFilter !== 'all') {
      const activePill = document.querySelector(`.rev-pill[data-rating="${lotReviewFilter}"]`);
      if (activePill && activePill.disabled) {
        lotReviewFilter = 'all';
        document.querySelectorAll('.rev-pill[data-rating]').forEach(p => p.classList.remove('active'));
        document.querySelector('.rev-pill[data-rating="all"]')?.classList.add('active');
      }
    }
    renderReviewsList();
  }

  function renderReviewsList() {
    const listEl = $('reviewList');
    if (!listEl) return;
    // Применяем оба фильтра последовательно
    let items = lotReviews;
    if (thisLotOnly)              items = items.filter(r => r.auction_id === +auctionId);
    if (lotReviewFilter !== 'all') items = items.filter(r => r.rating === lotReviewFilter);

    if (!items.length) {
      let msg;
      if (thisLotOnly && lotReviewFilter !== 'all')
        msg = `Нет отзывов с оценкой ${lotReviewFilter}★ об этом лоте`;
      else if (thisLotOnly)
        msg = 'Об этом лоте отзывов пока нет';
      else if (lotReviewFilter !== 'all')
        msg = `Нет отзывов с оценкой ${lotReviewFilter}★`;
      else
        msg = 'У этого продавца пока нет отзывов — будьте первым!';
      listEl.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-3);font-size:13px;">${msg}</div>`;
      return;
    }

    // Сортируем: отзывы об ЭТОМ лоте в начале, остальные следом по дате
    const sorted = [...items].sort((a, b) => {
      const aThis = a.auction_id === +auctionId ? 1 : 0;
      const bThis = b.auction_id === +auctionId ? 1 : 0;
      if (aThis !== bThis) return bThis - aThis;
      return new Date(b.created_at) - new Date(a.created_at);
    });

    listEl.innerHTML = sorted.map(rev => {
      const tone = rev.rating >= 4 ? 'positive' : rev.rating <= 2 ? 'negative' : 'neutral';
      const utc = rev.created_at.endsWith('Z') ? rev.created_at : rev.created_at + 'Z';
      const date = new Date(utc).toLocaleDateString('ru-RU', { day:'2-digit', month:'short', year:'numeric' });
      const stars = [1,2,3,4,5].map(i => `<span class="review-star${i <= rev.rating ? ' on' : ''}">★</span>`).join('');
      const avatarSrc = rev.reviewer_avatar_url
        ? (rev.reviewer_avatar_url.startsWith('http') ? rev.reviewer_avatar_url : `${API}${rev.reviewer_avatar_url}`)
        : null;
      const avatarHtml = avatarSrc
        ? `<img src="${esc(avatarSrc)}" alt="${esc(rev.reviewer_username)}">`
        : (rev.reviewer_username || '?')[0].toUpperCase();

      const isThisLot = rev.auction_id === +auctionId;
      const lotChip = rev.auction_id && rev.auction_title
        ? (isThisLot
            ? `<span class="rev-lot-chip current" title="Отзыв об этом лоте">📍 Об этом лоте</span>`
            : `<a class="rev-lot-chip" href="auction.html?id=${rev.auction_id}" title="${esc(rev.auction_title)}">🔨 ${esc(rev.auction_title)}</a>`)
        : '';

      return `<div class="review-item ${tone}${isThisLot ? ' is-this-lot' : ''}">
        <div class="review-top">
          <div class="review-avatar">${avatarHtml}</div>
          <span class="review-author">${esc(rev.reviewer_username)}</span>
          <span class="review-date">${date}</span>
          ${rev._can_delete ? `<button class="review-del" onclick="deleteReview(${rev.id})">✕</button>` : ''}
        </div>
        <div class="review-stars">${stars}</div>
        ${lotChip}
        ${rev.comment ? `<div class="review-text">${esc(rev.comment)}</div>` : ''}
      </div>`;
    }).join('');
  }

  function filterReviewsByRating(rating, btn) {
    lotReviewFilter = rating;
    // Снимаем active только со звёздных пилюль (data-rating), не трогая toggle «Об этом лоте»
    document.querySelectorAll('.rev-pill[data-rating]').forEach(p => p.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderReviewsList();
  }

  function switchLotTab(tab) {
    document.querySelectorAll('.lot-tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.tab-panel').forEach(p => {
      p.classList.toggle('active', p.id === 'tab-' + tab);
    });
    // обновляем хэш для deep-link
    if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
  }

  document.addEventListener('DOMContentLoaded',()=>{
    const picker=$('starPicker');
    if(picker){picker.querySelectorAll('.star-pick').forEach(s=>{s.addEventListener('mouseover',()=>{const val=+s.dataset.val;picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=val));});s.addEventListener('click',()=>{currentRating=+s.dataset.val;picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=currentRating));});});picker.addEventListener('mouseleave',()=>{picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=currentRating));});}
  });

  const REVIEW_COMMENT_MAX = 1000;

  function updateReviewCounter() {
    const ta = $('reviewText');
    const lbl = $('reviewCharCount');
    if (!ta || !lbl) return;
    const len = ta.value.length;
    lbl.textContent = `${len} / ${REVIEW_COMMENT_MAX}`;
    lbl.classList.toggle('full', len >= REVIEW_COMMENT_MAX);
    lbl.classList.toggle('warn', len >= REVIEW_COMMENT_MAX * 0.9 && len < REVIEW_COMMENT_MAX);
  }

  async function submitReview() {
    if (!currentRating) { showToast('Оценка', 'Выберите оценку от 1 до 5', 'warn'); return; }
    if (!sellerId) return;
    const comment = $('reviewText').value.trim();
    if (comment.length > REVIEW_COMMENT_MAX) {
      showToast('Слишком длинный отзыв', `Максимум ${REVIEW_COMMENT_MAX} символов`, 'warn');
      return;
    }
    try {
      const r = await fetch(`${API}/api/reviews`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({
          seller_id: sellerId, auction_id: +auctionId || null,
          rating: currentRating, comment,
        }),
      });
      if (r.ok) {
        showToast('Отзыв', 'Ваш отзыв опубликован', 'ok');
        $('reviewText').value = '';
        updateReviewCounter();
        currentRating = 0;
        $('starPicker')?.querySelectorAll('.star-pick').forEach(s => s.classList.remove('sel'));
        const rev = await fetch(`${API}/api/sellers/${sellerId}/reviews`);
        if (rev.ok) renderReviews(await rev.json());
      } else {
        const err = await r.json();
        showToast('Ошибка', err.detail || 'Не удалось добавить отзыв', 'bad');
      }
    } catch {
      showToast('Ошибка', 'Нет соединения', 'bad');
    }
  }

  async function deleteReview(id) {
    if(!confirm('Удалить отзыв?'))return;
    try{const r=await fetch(`${API}/api/reviews/${id}`,{method:'DELETE',headers:{'Authorization':'Bearer '+token}});if(r.ok){showToast('Отзыв','Отзыв удалён','ok');const rev=await fetch(`${API}/api/sellers/${sellerId}/reviews`);if(rev.ok)renderReviews(await rev.json());}}catch{}
  }

  // ---- Edit Lot ----
  let editImageUrls=[],editNewFiles=[],auctionData=null;

  async function openEditModal() {
    if(!auctionData)return;const a=auctionData;
    $('editTitle').value=a.title||'';$('editDescription').value=a.description||'';$('editPrice').value=a.starting_price||'';$('editBinPrice').value=a.bin_price||'';$('editExtend').value='';$('editError').style.display='none';

    const isBinOnly = a.auction_type==='bin';
    $('editStartPriceWrap').style.display = isBinOnly ? 'none' : 'block';
    $('editBinPriceBlock').style.display = (a.auction_type==='bin'||a.bin_price) ? 'block' : 'none';
    $('editPriceBlock').style.flexDirection = isBinOnly ? 'column' : 'row';
    $('editExtendBlock').style.display=a.is_active?'block':'none';
    const parentSel=$('editCategoryParent'),subSel=$('editCategory');
    if(parentSel){try{const r=await fetch(`${API}/api/categories`);const cats=await r.json();parentSel.innerHTML='<option value="">— Выберите категорию —</option>';cats.forEach(cat=>{const opt=document.createElement('option');opt.value=cat.id;opt.textContent=cat.name;opt.dataset.hasChildren=cat.children&&cat.children.length?'1':'';parentSel.appendChild(opt);});const updateSub=(catId,selectSubId)=>{const cat=cats.find(c=>c.id===+catId);if(subSel){subSel.innerHTML='<option value="">— Вся категория —</option>';subSel.style.display='none';}if(cat&&cat.children&&cat.children.length){cat.children.forEach(ch=>{const o=document.createElement('option');o.value=ch.id;o.textContent=ch.name;subSel.appendChild(o);});if(subSel){subSel.style.display='block';subSel.value=selectSubId||'';}}};parentSel.onchange=()=>updateSub(parentSel.value,null);if(a.category_id){const parentCat=cats.find(c=>c.id===a.category_id);if(parentCat){parentSel.value=a.category_id;updateSub(a.category_id,null);}else{const parent=cats.find(c=>c.children&&c.children.some(ch=>ch.id===a.category_id));if(parent){parentSel.value=parent.id;updateSub(parent.id,a.category_id);}}}}catch{}}
    editImageUrls=(a.image_urls&&a.image_urls.length)?[...a.image_urls]:(a.image_url?[a.image_url]:[]);editNewFiles=[];renderEditImgPreview();
    const fileInput=$('editImageFile');if(fileInput&&!fileInput._wired){fileInput._wired=true;fileInput.addEventListener('change',e=>{Array.from(e.target.files||[]).forEach(f=>{if((editImageUrls.length+editNewFiles.length)<5)editNewFiles.push(f);});fileInput.value='';renderEditImgPreview();});}
    $('editModal').style.display='flex';
  }
  function closeEditModal(){$('editModal').style.display='none';}
  function renderEditImgPreview(){const el=$('editImgPreview');if(!el)return;const allCount=editImageUrls.length+editNewFiles.length;el.innerHTML=[...editImageUrls.map((url,i)=>{const src=String(url).startsWith('http')?url:API+url;return`<div class="multi-img-thumb${i===0?' is-cover':''}"><img src="${esc(src)}"><button class="thumb-del" type="button" onclick="removeEditImg('url',${i})">✕</button></div>`;}),...editNewFiles.map((f,i)=>`<div class="multi-img-thumb${(editImageUrls.length+i)===0?' is-cover':''}"><img src="${URL.createObjectURL(f)}"><button class="thumb-del" type="button" onclick="removeEditImg('file',${i})">✕</button></div>`)].join('');const addBtn=document.querySelector('label[for="editImageFile"]');if(addBtn)addBtn.style.display=allCount>=5?'none':'inline-flex';}
  function removeEditImg(type,idx){if(type==='url')editImageUrls.splice(idx,1);else editNewFiles.splice(idx,1);renderEditImgPreview();}
  function setExtend(mins){$('editExtend').value=mins;}
  async function saveEdit(){const btn=$('editSaveBtn');btn.disabled=true;btn.textContent='Сохраняем…';$('editError').style.display='none';try{const uploadedUrls=[];for(const f of editNewFiles){const fd=new FormData();fd.append('file',f);const r=await fetch(`${API}/api/upload-image`,{method:'POST',headers:{'Authorization':'Bearer '+token},body:fd});if(r.ok){const d=await r.json();uploadedUrls.push(d.image_url);}}const allUrls=[...editImageUrls,...uploadedUrls];const subSel=$('editCategory'),parentSel=$('editCategoryParent');const catVal=(subSel&&subSel.value&&subSel.style.display!=='none')?subSel.value:(parentSel?parentSel.value:'');const payload={title:$('editTitle').value.trim(),description:$('editDescription').value.trim(),category_id:catVal?+catVal:null,starting_price:$('editPrice').value?+$('editPrice').value:null,bin_price:$('editBinPrice').value?+$('editBinPrice').value:null,image_urls:allUrls};const ext=+$('editExtend').value;if(ext>0)payload.extend_minutes=ext;const r=await fetch(`${API}/api/auctions/${auctionId}`,{method:'PATCH',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(payload)});if(r.ok){closeEditModal();showToast('✅ Сохранено','Лот успешно обновлён','ok');setTimeout(()=>location.reload(),1200);}else{const err=await r.json();$('editError').textContent=window.formatError(err,'Ошибка сохранения');$('editError').style.display='block';}}catch{$('editError').textContent='Ошибка соединения';$('editError').style.display='block';}finally{btn.disabled=false;btn.textContent='Сохранить';}}

  async function buyNow(){if(!token){showToast('Ошибка','Войдите в аккаунт','bad');return;}const btn=$('binBtn');if(btn){btn.disabled=true;btn.textContent='Покупаем…';}try{const r=await apiFetch(`${API}/api/auctions/${auctionId}/buy-now`,{method:'POST'});if(r.ok){const d=await r.json();showToast('🎉 Покупка совершена!',`Вы купили лот за ${fmtMoney(d.price)}`,'ok');setTimeout(()=>location.reload(),2000);}else{const err=await r.json();showToast('Ошибка',err.detail||'Не удалось купить лот','bad');if(btn){btn.disabled=false;btn.textContent='⚡ Купить сразу';}}}catch{showToast('Ошибка','Нет соединения','bad');if(btn){btn.disabled=false;btn.textContent='⚡ Купить сразу';}}}

  let lotCurrentSlide=0;
  function lotGoTo(idx){const slides=document.querySelectorAll('.lot-slide'),dots=document.querySelectorAll('.lot-dot'),counter=$('lotCounter');if(!slides.length)return;slides[lotCurrentSlide]?.classList.remove('active');dots[lotCurrentSlide]?.classList.remove('active');lotCurrentSlide=(idx+slides.length)%slides.length;slides[lotCurrentSlide]?.classList.add('active');dots[lotCurrentSlide]?.classList.add('active');if(counter)counter.textContent=`${lotCurrentSlide+1} / ${slides.length}`;updateThumbs(lotCurrentSlide);}
  function lotSlide(dir){lotGoTo(lotCurrentSlide+dir);}

  // ===== Lightbox: открытие фото лота на полный экран с zoom/pan =====
  const lb = {
    idx: 0, urls: [],
    zoom: 1, panX: 0, panY: 0,
    dragging: false, dragStartX: 0, dragStartY: 0,
  };
  const ZOOM_MIN = 1, ZOOM_MAX = 4, ZOOM_STEP_WHEEL = 0.2;

  function openLightbox(idx) {
    const slides = document.querySelectorAll('.lot-slide');
    if (!slides.length) return;
    lb.urls = Array.from(slides).map(s => s.src);
    lb.idx = Math.max(0, Math.min(idx | 0, lb.urls.length - 1));
    lbResetZoom();
    lbRenderCurrent();
    $('lotLightbox').hidden = false;
    document.body.style.overflow = 'hidden';
  }
  function closeLightbox() {
    $('lotLightbox').hidden = true;
    document.body.style.overflow = '';
  }
  function lbBgClick() { /* deprecated: close теперь только × и Esc */ }
  function lbSlide(dir) {
    if (!lb.urls.length) return;
    lb.idx = (lb.idx + dir + lb.urls.length) % lb.urls.length;
    lbResetZoom();
    lbRenderCurrent();
  }
  function lbRenderCurrent() {
    const img = $('lbImg');
    if (!img) return;
    img.src = lb.urls[lb.idx] || '';
    const counter = $('lbCounter');
    if (counter) {
      counter.textContent = lb.urls.length > 1 ? `${lb.idx + 1} / ${lb.urls.length}` : '';
      counter.style.display = lb.urls.length > 1 ? '' : 'none';
    }
    const showNav = lb.urls.length > 1 ? '' : 'none';
    const prev = document.querySelector('.lb-prev'), next = document.querySelector('.lb-next');
    if (prev) prev.style.display = showNav;
    if (next) next.style.display = showNav;
  }
  function lbApplyTransform() {
    const img = $('lbImg');
    if (!img) return;
    img.style.transform = `translate(${lb.panX}px, ${lb.panY}px) scale(${lb.zoom})`;
    img.classList.toggle('zoomed', lb.zoom > 1);
    const label = $('lbZoomLabel');
    if (label) label.textContent = `${Math.round(lb.zoom * 100)}%`;
  }
  function lbZoom(delta) {
    const next = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, lb.zoom + delta));
    if (Math.abs(next - lb.zoom) < 0.001) return;
    lb.zoom = next;
    if (lb.zoom === ZOOM_MIN) { lb.panX = 0; lb.panY = 0; }
    lbApplyTransform();
  }
  function lbResetZoom() {
    lb.zoom = 1; lb.panX = 0; lb.panY = 0;
    lbApplyTransform();
  }

  // Клик по слайду открывает lightbox с текущим видимым фото.
  // Все слайды лежат друг на друге (position:absolute), и target
  // указал бы на верхний по DOM, а не на визуально активный —
  // поэтому берём индекс не из e.target, а из lotCurrentSlide.
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.lot-image-wrap')) return;
    if (e.target.closest('.lot-nav, .lot-dots, .lot-counter')) return;
    if (!e.target.closest('.lot-slide')) return;
    openLightbox(lotCurrentSlide);
  });
  // Клик по сцене вне картинки и контролов — навигация: левая
  // половина = prev, правая = next. Чтобы случайный промах по
  // визуальной стрелке не казался «глухим» нажатием.
  document.addEventListener('click', (e) => {
    if ($('lotLightbox')?.hidden) return;
    if (!lb.urls || lb.urls.length < 2) return;
    if (lb.zoom > 1) return; // в режиме зума клик может быть частью drag
    const stage = e.target.closest('#lbStage');
    if (!stage) return;
    // Игнорируем сам img — нужно чтобы wheel/drag работали без сюрпризов
    if (e.target.closest('.lb-img')) return;
    // Игнорируем клик по кнопкам и контролам
    if (e.target.closest('.lb-btn, .lb-controls, .lb-counter, .lb-nav')) return;
    const rect = stage.getBoundingClientRect();
    const xRel = e.clientX - rect.left;
    if (xRel < rect.width / 2) lbSlide(-1);
    else lbSlide(1);
  });
  // Клавиатура: Esc, стрелки, +/-, 0 (reset)
  document.addEventListener('keydown', (e) => {
    if ($('lotLightbox')?.hidden) return;
    if (e.key === 'Escape') closeLightbox();
    else if (e.key === 'ArrowLeft') lbSlide(-1);
    else if (e.key === 'ArrowRight') lbSlide(1);
    else if (e.key === '+' || e.key === '=') lbZoom(0.25);
    else if (e.key === '-' || e.key === '_') lbZoom(-0.25);
    else if (e.key === '0') lbResetZoom();
  });
  // Колесо мыши = zoom
  document.addEventListener('wheel', (e) => {
    if ($('lotLightbox')?.hidden) return;
    if (!e.target.closest('#lotLightbox')) return;
    e.preventDefault();
    lbZoom(e.deltaY < 0 ? ZOOM_STEP_WHEEL : -ZOOM_STEP_WHEEL);
  }, { passive: false });
  // Перетаскивание при zoom > 1
  document.addEventListener('mousedown', (e) => {
    if ($('lotLightbox')?.hidden || lb.zoom === 1) return;
    if (!e.target.closest('.lb-img')) return;
    lb.dragging = true;
    lb.dragStartX = e.clientX - lb.panX;
    lb.dragStartY = e.clientY - lb.panY;
    $('lbImg').classList.add('dragging');
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!lb.dragging) return;
    lb.panX = e.clientX - lb.dragStartX;
    lb.panY = e.clientY - lb.dragStartY;
    lbApplyTransform();
  });
  document.addEventListener('mouseup', () => {
    if (!lb.dragging) return;
    lb.dragging = false;
    $('lbImg').classList.remove('dragging');
  });

  // Expose handlers for inline onclick="..." in auction.html
  Object.assign(window, {
    buyNow, bumpBid, closeEditModal, closeLightbox, filterReviewsByRating,
    goAuth, lbBgClick, lbSlide, lbZoom, lbZoomReset: lbResetZoom,
    lotGoTo, lotSlide, openEditModal, openLightbox, placeBid, removeEditImg,
    saveEdit, setExtend, submitReview, switchLotTab, toggleSubscription,
    toggleThisLotOnly, updateReviewCounter,
  });

  // Deep-link: auction.html?id=...#reviews открывает таб «Отзывы» сразу
  if (location.hash === '#reviews' || location.hash === '#desc') {
    switchLotTab(location.hash.slice(1));
  }

  // Bootstrap with error boundary
  init().catch(err => {
    console.error('[auction.html] init failed:', err);
    const target = document.getElementById('lotInfoBlock') || document.querySelector('.page-wrap');
    window.renderLoadError(target, 'Не удалось загрузить лот', () => location.reload());
  });
})();


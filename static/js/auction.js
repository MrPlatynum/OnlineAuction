  const API     = 'http://localhost:8000';
  const WS_BASE = API.replace(/^http/i, 'ws');
  const auctionId = new URLSearchParams(location.search).get('id');
  const token     = localStorage.getItem('token');
  let currentPriceValue = null;
  let remainingSec      = null;
  let isActive          = null;
  let ws = null, wsPingTimer = null, toastTimer = null;
  const $ = id => document.getElementById(id);

  function showToast(title, msg, tone = 'info') {
    $('toastTitle').textContent = title;
    $('toastMsg').textContent   = msg;
    $('toastDot').style.background = tone==='ok'?'var(--green)':tone==='warn'?'var(--amber)':tone==='bad'?'var(--red)':'var(--accent)';
    $('toast').classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('toast').classList.remove('show'), 3200);
  }

  function fmtMoney(n) { const num=Number(n); return Number.isFinite(num)?'$'+num.toFixed(2):'—'; }
  function fmtTime(sec) {
    if (!Number.isFinite(sec)||sec<=0) return '0м 00с';
    const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;
    if (h>0) return `${h}ч ${m}м ${String(s).padStart(2,'0')}с`;
    return `${m}м ${String(s).padStart(2,'0')}с`;
  }
  function fmtDate(ts) { if(!ts)return''; return new Date(ts).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); }
  function esc(str) { return String(str).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  function syncEl(id, val) { const el=$(id); if(el) el.textContent=val; }

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
    $('bidBtn').disabled = !token||!isActive;
    $('bidAmount').disabled = !token||!isActive;
    updateBidHint();
  }

  function updateBidHint() {
    const hint=$('bidHint');
    if (!token) return void(hint.textContent='Войдите, чтобы делать ставки.');
    if (!isActive) return void(hint.textContent='Аукцион завершён — ставки закрыты.');
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

  async function apiFetch(url,opts={}) {
    const headers={...(opts.headers||{})};
    if (token) headers['Authorization']='Bearer '+token;
    return fetch(url,{...opts,headers});
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

    document.title=`${a.title} — AuctionHub`;
    syncEl('title',a.title||'Лот'); syncEl('crumbTitle',a.title||'Лот'); syncEl('description',a.description||'');

    // Images
    const urls=(a.image_urls&&a.image_urls.length)?a.image_urls.map(u=>String(u).startsWith('http')?u:API+u):(a.image_url?[String(a.image_url).startsWith('http')?a.image_url:API+a.image_url]:[]);
    const slidesEl=$('lotSlides'),dotsEl=$('lotDots'),prevBtn=$('lotPrev'),nextBtn=$('lotNext'),counter=$('lotCounter'),placeholder=$('imgPlaceholder');
    if (urls.length&&slidesEl) {
      if (placeholder) placeholder.style.display='none';
      slidesEl.innerHTML=urls.map((u,i)=>`<img class="lot-slide${i===0?' active':''}" src="${u}" alt="${esc(a.title)}" data-idx="${i}">`).join('');
      // Thumbnails
      const thumbsEl=$('lotThumbs');
      if (thumbsEl&&urls.length>1) {
        thumbsEl.innerHTML=urls.map((u,i)=>`<div class="lot-thumb${i===0?' active':''}" onclick="lotGoTo(${i});updateThumbs(${i})"><img src="${u}" alt="${i+1}"></div>`).join('');
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
      cb.textContent=`${a.category_icon||''} ${a.category_name}`;
      cb.style.display='inline-flex';
    }

    return a;
  }

  function updateThumbs(idx) {
    document.querySelectorAll('.lot-thumb').forEach((t,i)=>t.classList.toggle('active',i===idx));
  }

  function renderBids(items) {
    const list=$('bidsList');
    if (!items.length) { list.innerHTML='<div class="bids-empty">Ставок пока нет — будьте первым!</div>'; return; }
    list.innerHTML=items.map((b,i)=>`
      <div class="bid-row ${i===0?'top-bid':''}">
        <div><div class="bid-who">${esc(b.username??'—')}</div><div class="bid-when">${fmtDate(b.timestamp)}</div></div>
        <div class="bid-amt ${i===0?'top':''}">${fmtMoney(b.amount)}</div>
      </div>`).join('');
    syncEl('bidsCount',items.length); syncEl('bidsCount2',items.length);
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
    if (!raw||!Number.isFinite(amount)||amount<=0) return showToast('Некорректная ставка','Введите сумму больше нуля.','warn');
    const btn=$('bidBtn'),prev=btn.textContent;
    btn.disabled=true; btn.textContent='Отправка…';
    try {
      const r=await apiFetch(`${API}/api/bids`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({auction_id:Number(auctionId),amount})});
      if (!r.ok) { let msg='Ставка не принята.'; try{msg=(await r.json()).detail||msg;}catch{} showToast('Ошибка',msg,'bad'); }
      else { $('bidAmount').value=''; showToast('Принято','Ваша ставка зарегистрирована!','ok'); await loadBids(); }
    } catch { showToast('Ошибка','Нет связи с сервером.','bad'); }
    finally { btn.textContent=prev; btn.disabled=!token||!isActive; }
  }

  function connectWS() {
    if (!auctionId) return;
    if (wsPingTimer) { clearInterval(wsPingTimer); wsPingTimer=null; }
    ws=new WebSocket(`${WS_BASE}/ws/auction/${encodeURIComponent(auctionId)}`);
    ws.onopen=()=>{ wsPingTimer=setInterval(()=>{try{ws.send('ping');}catch{}},25000); };
    ws.onmessage=e=>{
      let data; try{data=JSON.parse(e.data);}catch{return;}
      if (data.type==='new_bid') {
        if (data.current_price!==undefined) { currentPriceValue=Number(data.current_price); const p=fmtMoney(currentPriceValue); syncEl('currentPrice',p); syncEl('currentPrice2',p); updateBidHint(); }
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

  async function init() {
    const me=await loadMe();
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
        // На странице лота — показываем только отзывы об этом лоте
        const lotReviews = d.reviews.filter(r => r.auction_id === +auctionId);
        const lotData = { ...d, reviews: lotReviews };
        renderReviews(lotData);
        $('reviewsSummary').style.display='none'; // summary не нужен для одного лота
        if(lotReviews.length>0) $('reviewsSection').style.display='block';
        else $('reviewsSection').style.display='block'; // показываем форму отзыва
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

  function renderReviews(data) {
    const avg=data.stats.avg,total=data.stats.total,dist=data.stats.distribution;
    syncEl('revAvg',total?avg.toFixed(1):'—');
    syncEl('revCount',`${total} отзыв${total===1?'':total>4?'ов':'а'}`);
    renderStars($('revBigStars'),avg,15);
    const barsEl=$('revBars');
    if(barsEl)barsEl.innerHTML=[5,4,3,2,1].map(n=>{const cnt=dist[n]||0,pct=total?Math.round(cnt/total*100):0,cls=n<=2?'low':n===3?'mid':'';return`<div class="review-bar-row"><span class="review-bar-label">${n}★</span><div class="review-bar-track"><div class="review-bar-fill ${cls}" style="width:${pct}%"></div></div><span class="review-bar-count">${cnt}</span></div>`;}).join('');
    const listEl=$('reviewList');if(!listEl)return;
    if(!data.reviews.length){listEl.innerHTML=`<div style="text-align:center;padding:24px;color:var(--text-3);font-size:13px;">Об этом лоте отзывов пока нет — будьте первым!</div>`;return;}
    listEl.innerHTML=data.reviews.map(rev=>{const utc=rev.created_at.endsWith('Z')?rev.created_at:rev.created_at+'Z';const date=new Date(utc).toLocaleDateString('ru-RU',{day:'2-digit',month:'short',year:'numeric'});const stars=[1,2,3,4,5].map(i=>`<span class="review-star${i<=rev.rating?' on':''}">★</span>`).join('');const avatarSrc=rev.reviewer_avatar_url?(rev.reviewer_avatar_url.startsWith('http')?rev.reviewer_avatar_url:`${API}${rev.reviewer_avatar_url}`):null;const avatarHtml=avatarSrc?`<img src="${avatarSrc}" alt="${esc(rev.reviewer_username)}">`:(rev.reviewer_username||'?')[0].toUpperCase();return`<div class="review-item"><div class="review-top"><div class="review-avatar">${avatarHtml}</div><span class="review-author">${esc(rev.reviewer_username)}</span><span class="review-date">${date}</span>${rev._can_delete?`<button class="review-del" onclick="deleteReview(${rev.id})">✕</button>`:''}</div><div class="review-stars">${stars}</div>${rev.comment?`<div class="review-text">${esc(rev.comment)}</div>`:''}</div>`;}).join('');
  }

  document.addEventListener('DOMContentLoaded',()=>{
    const picker=$('starPicker');
    if(picker){picker.querySelectorAll('.star-pick').forEach(s=>{s.addEventListener('mouseover',()=>{const val=+s.dataset.val;picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=val));});s.addEventListener('click',()=>{currentRating=+s.dataset.val;picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=currentRating));});});picker.addEventListener('mouseleave',()=>{picker.querySelectorAll('.star-pick').forEach(x=>x.classList.toggle('sel',+x.dataset.val<=currentRating));});}
  });

  async function submitReview() {
    if(!currentRating){showToast('Оценка','Выберите оценку от 1 до 5','warn');return;}
    if(!sellerId)return;
    const comment=$('reviewText').value.trim();
    try{const r=await fetch(`${API}/api/reviews`,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({seller_id:sellerId,auction_id:+auctionId||null,rating:currentRating,comment})});if(r.ok){showToast('Отзыв','Ваш отзыв опубликован','ok');$('reviewText').value='';currentRating=0;$('starPicker')?.querySelectorAll('.star-pick').forEach(s=>s.classList.remove('sel'));const rev=await fetch(`${API}/api/sellers/${sellerId}/reviews`);if(rev.ok)renderReviews(await rev.json());}else{const err=await r.json();showToast('Ошибка',err.detail||'Не удалось добавить отзыв','bad');}}catch{showToast('Ошибка','Нет соединения','bad');}
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
    if(parentSel){try{const r=await fetch(`${API}/api/categories`);const cats=await r.json();parentSel.innerHTML='<option value="">— Выберите категорию —</option>';cats.forEach(cat=>{const opt=document.createElement('option');opt.value=cat.id;opt.textContent=`${cat.icon} ${cat.name}`;opt.dataset.hasChildren=cat.children&&cat.children.length?'1':'';parentSel.appendChild(opt);});const updateSub=(catId,selectSubId)=>{const cat=cats.find(c=>c.id===+catId);if(subSel){subSel.innerHTML='<option value="">— Вся категория —</option>';subSel.style.display='none';}if(cat&&cat.children&&cat.children.length){cat.children.forEach(ch=>{const o=document.createElement('option');o.value=ch.id;o.textContent=`${ch.icon} ${ch.name}`;subSel.appendChild(o);});if(subSel){subSel.style.display='block';subSel.value=selectSubId||'';}}};parentSel.onchange=()=>updateSub(parentSel.value,null);if(a.category_id){const parentCat=cats.find(c=>c.id===a.category_id);if(parentCat){parentSel.value=a.category_id;updateSub(a.category_id,null);}else{const parent=cats.find(c=>c.children&&c.children.some(ch=>ch.id===a.category_id));if(parent){parentSel.value=parent.id;updateSub(parent.id,a.category_id);}}}}catch{}}
    editImageUrls=(a.image_urls&&a.image_urls.length)?[...a.image_urls]:(a.image_url?[a.image_url]:[]);editNewFiles=[];renderEditImgPreview();
    const fileInput=$('editImageFile');if(fileInput&&!fileInput._wired){fileInput._wired=true;fileInput.addEventListener('change',e=>{Array.from(e.target.files||[]).forEach(f=>{if((editImageUrls.length+editNewFiles.length)<5)editNewFiles.push(f);});fileInput.value='';renderEditImgPreview();});}
    $('editModal').style.display='flex';
  }
  function closeEditModal(){$('editModal').style.display='none';}
  function renderEditImgPreview(){const el=$('editImgPreview');if(!el)return;const allCount=editImageUrls.length+editNewFiles.length;el.innerHTML=[...editImageUrls.map((url,i)=>{const src=String(url).startsWith('http')?url:API+url;return`<div class="multi-img-thumb${i===0?' is-cover':''}"><img src="${src}"><button class="thumb-del" type="button" onclick="removeEditImg('url',${i})">✕</button></div>`;}),...editNewFiles.map((f,i)=>`<div class="multi-img-thumb${(editImageUrls.length+i)===0?' is-cover':''}"><img src="${URL.createObjectURL(f)}"><button class="thumb-del" type="button" onclick="removeEditImg('file',${i})">✕</button></div>`)].join('');const addBtn=document.querySelector('label[for="editImageFile"]');if(addBtn)addBtn.style.display=allCount>=5?'none':'inline-flex';}
  function removeEditImg(type,idx){if(type==='url')editImageUrls.splice(idx,1);else editNewFiles.splice(idx,1);renderEditImgPreview();}
  function setExtend(mins){$('editExtend').value=mins;}
  async function saveEdit(){const btn=$('editSaveBtn');btn.disabled=true;btn.textContent='Сохраняем…';$('editError').style.display='none';try{const uploadedUrls=[];for(const f of editNewFiles){const fd=new FormData();fd.append('file',f);const r=await fetch(`${API}/api/upload-image`,{method:'POST',headers:{'Authorization':'Bearer '+token},body:fd});if(r.ok){const d=await r.json();uploadedUrls.push(d.image_url);}}const allUrls=[...editImageUrls,...uploadedUrls];const subSel=$('editCategory'),parentSel=$('editCategoryParent');const catVal=(subSel&&subSel.value&&subSel.style.display!=='none')?subSel.value:(parentSel?parentSel.value:'');const payload={title:$('editTitle').value.trim(),description:$('editDescription').value.trim(),category_id:catVal?+catVal:null,starting_price:$('editPrice').value?+$('editPrice').value:null,bin_price:$('editBinPrice').value?+$('editBinPrice').value:null,image_urls:allUrls};const ext=+$('editExtend').value;if(ext>0)payload.extend_minutes=ext;const r=await fetch(`${API}/api/auctions/${auctionId}`,{method:'PATCH',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(payload)});if(r.ok){closeEditModal();showToast('✅ Сохранено','Лот успешно обновлён','ok');setTimeout(()=>location.reload(),1200);}else{const err=await r.json();$('editError').textContent=err.detail||'Ошибка сохранения';$('editError').style.display='block';}}catch{$('editError').textContent='Ошибка соединения';$('editError').style.display='block';}finally{btn.disabled=false;btn.textContent='Сохранить';}}

  async function buyNow(){if(!token){showToast('Ошибка','Войдите в аккаунт','bad');return;}const btn=$('binBtn');if(btn){btn.disabled=true;btn.textContent='Покупаем…';}try{const r=await apiFetch(`${API}/api/auctions/${auctionId}/buy-now`,{method:'POST'});if(r.ok){const d=await r.json();showToast('🎉 Покупка совершена!',`Вы купили лот за ${fmtMoney(d.price)}`,'ok');setTimeout(()=>location.reload(),2000);}else{const err=await r.json();showToast('Ошибка',err.detail||'Не удалось купить лот','bad');if(btn){btn.disabled=false;btn.textContent='⚡ Купить сразу';}}}catch{showToast('Ошибка','Нет соединения','bad');if(btn){btn.disabled=false;btn.textContent='⚡ Купить сразу';}}}

  let lotCurrentSlide=0;
  function lotGoTo(idx){const slides=document.querySelectorAll('.lot-slide'),dots=document.querySelectorAll('.lot-dot'),counter=$('lotCounter');if(!slides.length)return;slides[lotCurrentSlide]?.classList.remove('active');dots[lotCurrentSlide]?.classList.remove('active');lotCurrentSlide=(idx+slides.length)%slides.length;slides[lotCurrentSlide]?.classList.add('active');dots[lotCurrentSlide]?.classList.add('active');if(counter)counter.textContent=`${lotCurrentSlide+1} / ${slides.length}`;updateThumbs(lotCurrentSlide);}
  function lotSlide(dir){lotGoTo(lotCurrentSlide+dir);}

  init();

(function() {
  const API_URL='http://localhost:8000';
  function getToken(){return localStorage.getItem('token');}
  const btn=document.getElementById('notifBtn'),badge=document.getElementById('notifBadge'),dropdown=document.getElementById('notifDropdown'),list=document.getElementById('notifList'),markAllBtn=document.getElementById('notifMarkAll');
  if(!btn||!dropdown)return;
  let unreadCount=0,wsNotif=null,currentUserId=null,isOpen=false;
  const ICONS={bid_outbid:{emoji:'⚡'},bid_placed:{emoji:'💰'},auction_won:{emoji:'🏆'},auction_lost:{emoji:'😔'},auction_sold:{emoji:'✅'},new_lot:{emoji:'🔖'},auction_ending:{emoji:'⏰'}};
  function fmtAge(iso){const utcIso=iso&&!iso.endsWith('Z')&&!iso.includes('+')?iso+'Z':iso;const diff=Math.floor((Date.now()-new Date(utcIso))/1000);if(diff<60)return'только что';if(diff<3600)return`${Math.floor(diff/60)} мин назад`;if(diff<86400)return`${Math.floor(diff/3600)} ч назад`;return new Date(utcIso).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'});}
  function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function setCount(n){unreadCount=Math.max(0,n);if(unreadCount>0){badge.textContent=unreadCount>99?'99+':String(unreadCount);badge.style.display='flex';btn.classList.add('has-unread');}else{badge.style.display='none';btn.classList.remove('has-unread');}}
  function renderList(items){if(!items.length){list.innerHTML=`<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Уведомлений пока нет</div>`;return;}list.innerHTML=items.map(n=>{const ico=ICONS[n.type]||{emoji:'🔔'};return`<div class="notif-item ${n.is_read?'':'unread'}" data-id="${n.id}" data-auction="${n.auction_id||''}"><div class="notif-icon">${ico.emoji}</div><div class="notif-body"><div class="notif-title">${esc(n.title)}</div><div class="notif-msg">${esc(n.message)}</div><div class="notif-time">${fmtAge(n.created_at)}</div></div></div>`;}).join('');}
  async function apiFetch(url,opts={}){const tk=getToken();const headers={...(opts.headers||{})};if(tk)headers['Authorization']='Bearer '+tk;return fetch(url,{...opts,headers});}
  async function fetchCount(){if(!getToken())return;try{const r=await apiFetch(`${API_URL}/api/notifications/unread-count`);if(r.ok){const d=await r.json();setCount(d.count??0);}}catch{}}
  async function fetchNotifications(){if(!getToken()){list.innerHTML=`<div class="notif-empty"><div class="notif-empty-icon">🔔</div>Войдите</div>`;return;}list.innerHTML=`<div class="notif-empty">Загрузка…</div>`;try{const r=await apiFetch(`${API_URL}/api/notifications?limit=30`);if(r.ok)renderList(await r.json());else list.innerHTML=`<div class="notif-empty">Ошибка</div>`;}catch{list.innerHTML=`<div class="notif-empty">Нет связи</div>`;}}
  async function markAllRead(){try{await apiFetch(`${API_URL}/api/notifications/mark-all-read`,{method:'POST'});setCount(0);await fetchNotifications();}catch{}}
  function openDropdown(){isOpen=true;dropdown.classList.add('open');fetchNotifications();}
  function closeDropdown(){isOpen=false;dropdown.classList.remove('open');}
  btn.addEventListener('click',e=>{e.stopPropagation();isOpen?closeDropdown():openDropdown();});
  document.addEventListener('click',e=>{if(isOpen&&!dropdown.contains(e.target)&&e.target!==btn)closeDropdown();});
  markAllBtn.addEventListener('click',e=>{e.stopPropagation();markAllRead();});
  list.addEventListener('click',async e=>{const item=e.target.closest('.notif-item');if(!item)return;const id=item.dataset.id,aId=item.dataset.auction;if(id&&item.classList.contains('unread')){item.classList.remove('unread');setCount(unreadCount-1);try{await apiFetch(`${API_URL}/api/notifications/${id}/read`,{method:'POST'});}catch{}}if(aId){closeDropdown();window.location.href=`auction.html?id=${aId}`;}});
  function connectNotifWS(userId){if(wsNotif){try{wsNotif.close();}catch{}}const tk=getToken();if(!tk)return;wsNotif=new WebSocket(`${API_URL.replace(/^http/i,'ws')}/ws/notifications/${userId}?token=${encodeURIComponent(tk)}`);wsNotif.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.type==='notification'){setCount(unreadCount+1);if(isOpen)fetchNotifications();}}catch{}};wsNotif.onclose=()=>setTimeout(()=>{if(currentUserId)connectNotifWS(currentUserId);},3000);}
  async function initNotifBell(){if(!getToken()){btn.style.display='none';return;}btn.style.display='flex';await fetchCount();try{const r=await apiFetch(`${API_URL}/api/me`);if(r.ok){const me=await r.json();currentUserId=me.id;if(currentUserId)connectNotifWS(currentUserId);}}catch{}setInterval(fetchCount,60000);}
  setTimeout(initNotifBell,800);
  window.addEventListener('storage',e=>{if(e.key==='token')setTimeout(initNotifBell,300);});
})();

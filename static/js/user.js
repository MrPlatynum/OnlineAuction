const API = 'http://localhost:8000';
const token = localStorage.getItem('token');

function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtMoney(n){return '$'+Number(n||0).toFixed(2);}
function fmtDate(iso){return new Date(iso).toLocaleDateString('ru-RU',{day:'2-digit',month:'long',year:'numeric'});}
function fmtDateShort(iso){return new Date(iso).toLocaleDateString('ru-RU',{day:'2-digit',month:'short',year:'numeric'});}
function fmtTimer(sec){if(!sec||sec<=0)return null;const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60);if(h>0)return`${h}ч ${m}м`;return`${m}м`;}
function starsHtml(n,size=13){return[1,2,3,4,5].map(i=>`<span class="star${i<=Math.round(n)?' on':''}" style="font-size:${size}px;">★</span>`).join('');}

const params=new URLSearchParams(location.search);
const username=params.get('username')||params.get('user')||'';
if(!username)showNotFound('Пользователь не указан');

let sellerId=null, isSubscribed=false, allReviews=[], currentFilter='all';

async function init(){
  if(!username)return;
  try{
    const r=await fetch(`${API}/api/users/${encodeURIComponent(username)}`);
    if(!r.ok){showNotFound('Пользователь не найден');return;}
    const data=await r.json();
    await render(data);
  }catch{showNotFound('Ошибка загрузки');}
}

async function render(data){
  const {user,auctions,stats}=data;
  sellerId=user.id;
  document.title=`${user.username} — Лотус`;
  document.getElementById('crumbName').textContent=user.username;

  const isMe=token&&(()=>{try{const p=JSON.parse(atob(token.split('.')[1]));return p.user_id===user.id;}catch{return false;}})();
  const activeAuctions=(auctions||[]).filter(a=>a.is_active);
  const winRate=(stats.won_count+stats.lost_count)>0?Math.round(stats.won_count/(stats.won_count+stats.lost_count)*100):0;

  const avatarBig=user.avatar_url?(user.avatar_url.startsWith('http')?user.avatar_url:API+user.avatar_url):null;

  // Подписка
  let subHtml='';
  if(!isMe&&token){
    try{
      const rs=await fetch(`${API}/api/sellers/${user.id}/subscription`,{headers:{Authorization:'Bearer '+token}});
      if(rs.ok){const sd=await rs.json();isSubscribed=sd.subscribed;subHtml=renderSubBtn(isSubscribed);}
    }catch{}
  }

  // Отзывы
  let reviewData=null;
  try{const rr=await fetch(`${API}/api/sellers/${user.id}/reviews`);if(rr.ok)reviewData=await rr.json();}catch{}
  allReviews=reviewData?.reviews||[];
  const rstats=reviewData?.stats||{total:0,avg:0,distribution:{}};
  const posCount=Object.entries(rstats.distribution||{}).filter(([k])=>+k>=4).reduce((s,[,v])=>s+v,0);
  const negCount=Object.entries(rstats.distribution||{}).filter(([k])=>+k<=2).reduce((s,[,v])=>s+v,0);
  const neuCount=(rstats.total||0)-posCount-negCount;
  const pctPos=rstats.total?((posCount/rstats.total)*100).toFixed(1):0;

  document.getElementById('page').innerHTML=`
    <!-- Header -->
    <div class="profile-header">
      <div class="ph-avatar" id="phAvatar">${avatarBig?`<img src="${esc(avatarBig)}" alt="${esc(user.username)}">`:`${esc(user.username[0].toUpperCase())}`}</div>
      <div class="ph-info">
        <div class="ph-name">${esc(user.username)}</div>
        <div class="ph-since">На сайте с ${fmtDate(user.created_at)}</div>
        <div class="ph-badges">
          <span class="ph-badge lots">📦 ${stats.created_count} лотов</span>
          <span class="ph-badge wins">🏆 ${stats.won_count} побед</span>
          ${rstats.total>0?`<span class="ph-badge rating">★ ${rstats.avg.toFixed(1)} рейтинг</span>`:''}
        </div>
      </div>
      <div class="ph-right">
        ${subHtml?`<span id="subBtnWrap">${subHtml}</span>`:''}
        ${isMe?`<a href="profile.html" class="btn btn-primary btn-sm">Мой профиль</a>`:''}
      </div>
    </div>

    <!-- 3-col grid -->
    <div class="main-grid">

      <!-- LEFT: General info -->
      <div style="display:flex;flex-direction:column;gap:14px;">
        <div class="card">
          <div class="card-title">Информация</div>
          <div class="info-row"><span class="info-label">Пользователь</span><span class="info-value">@${esc(user.username)}</span></div>
          <div class="info-row"><span class="info-label">На сайте с</span><span class="info-value">${new Date(user.created_at).toLocaleDateString('ru-RU',{month:'short',year:'numeric'})}</span></div>
          <div class="info-row"><span class="info-label">Лотов создано</span><span class="info-value">${stats.created_count}</span></div>
          <div class="info-row"><span class="info-label">Ставок сделано</span><span class="info-value">${stats.total_bids}</span></div>
          <div class="info-row"><span class="info-label">Побед</span><span class="info-value green">${stats.won_count}</span></div>
          <div class="info-row"><span class="info-label">Процент побед</span><span class="info-value amber">${winRate}%</span></div>
          ${rstats.total>0?`<div class="info-row"><span class="info-label">Рейтинг</span><span class="info-value" style="display:flex;align-items:center;gap:5px;"><span style="color:var(--accent-2)">${starsHtml(rstats.avg,11)}</span> ${rstats.avg.toFixed(1)}</span></div>`:''}
          <div style="margin-top:14px;">
            <a href="index.html?created_by=${encodeURIComponent(user.username)}" class="btn btn-secondary" style="width:100%;justify-content:center;">📦 Все лоты автора →</a>
          </div>
        </div>
      </div>

      <!-- CENTER: Feedback score -->
      <div style="display:flex;flex-direction:column;gap:14px;">
        <div class="card">
          <div class="card-title">Оценки продавца</div>
          ${rstats.total>0?`
          <table class="feedback-table">
            <thead>
              <tr>
                <th></th>
                <th>7 дней</th>
                <th>30 дней</th>
                <th>Всего</th>
              </tr>
            </thead>
            <tbody id="fbTableBody"></tbody>
          </table>
          <div class="feedback-pct">${pctPos}% положительных отзывов</div>
          `:`<div class="empty-msg">Отзывов пока нет</div>`}
        </div>

      </div>

      <!-- RIGHT: Recent feedback -->
      <div class="card">
        <div class="card-title">Последние отзывы</div>
        <div class="feedback-filter">
          <button class="ff-btn active" onclick="filterReviews('all',this)">Все</button>
          <button class="ff-btn" onclick="filterReviews('positive',this)" style="color:var(--green);">+ Позитивные</button>
          <button class="ff-btn" onclick="filterReviews('neutral',this)" style="color:var(--text-2);">○ Нейтральные</button>
          <button class="ff-btn" onclick="filterReviews('negative',this)" style="color:var(--red);">− Негативные</button>
        </div>
        <div id="reviewsContainer" style="max-height:520px;overflow-y:auto;padding-right:2px;"></div>
      </div>

    </div>
  `;

  // Заполняем таблицу отзывов
  if(rstats.total>0){
    fillFeedbackTable(rstats,posCount,negCount,neuCount);
  }

  renderReviews();
}

function fillFeedbackTable(rstats,posCount,negCount,neuCount){
  const tbody=document.getElementById('fbTableBody');
  if(!tbody)return;
  // Для упрощения — берём total для всех периодов (в реальном проекте можно считать по датам)
  tbody.innerHTML=`
    <tr><td>Положительных</td><td class="pos">—</td><td class="pos">—</td><td class="pos">${posCount}</td></tr>
    <tr><td>Нейтральных</td><td class="neu">—</td><td class="neu">—</td><td class="neu">${neuCount}</td></tr>
    <tr><td>Отрицательных</td><td class="neg">—</td><td class="neg">—</td><td class="neg">${negCount}</td></tr>
  `;
}

function filterReviews(type,btn){
  currentFilter=type;
  document.querySelectorAll('.ff-btn').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
  renderReviews();
}

function renderReviews(){
  const el=document.getElementById('reviewsContainer');
  if(!el)return;
  let filtered=allReviews;
  if(currentFilter==='positive')filtered=allReviews.filter(r=>r.rating>=4);
  else if(currentFilter==='negative')filtered=allReviews.filter(r=>r.rating<=2);
  else if(currentFilter==='neutral')filtered=allReviews.filter(r=>r.rating===3);

  if(!filtered.length){el.innerHTML=`<div class="empty-msg">Нет отзывов</div>`;return;}

  el.innerHTML=filtered.map(rev=>{
    const tone=rev.rating>=4?'positive':rev.rating<=2?'negative':'neutral';
    const toneLabel=rev.rating>=4?'Положительный':rev.rating<=2?'Отрицательный':'Нейтральный';
    const utc=rev.created_at.endsWith('Z')?rev.created_at:rev.created_at+'Z';
    const diff=Math.floor((Date.now()-new Date(utc))/86400000);
    const ago=diff===0?'сегодня':diff===1?'вчера':`${diff} дн. назад`;
    const avaHtml=rev.reviewer_avatar_url
      ?`<img src="${esc(rev.reviewer_avatar_url.startsWith('http')?rev.reviewer_avatar_url:API+rev.reviewer_avatar_url)}">`
      :(rev.reviewer_username||'?')[0].toUpperCase();
    const auctionLink=rev.auction_id&&rev.auction_title
      ?`<a href="auction.html?id=${rev.auction_id}" style="font-size:11px;color:var(--accent);display:block;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${esc(rev.auction_title)}">🔨 ${esc(rev.auction_title)}</a>`
      :'';
    return`<div class="rev-item ${tone}">
      <div class="rev-top">
        <div class="rev-ava">${avaHtml}</div>
        <span class="rev-author">${esc(rev.reviewer_username)}</span>
        <span class="rev-date">${ago}</span>
      </div>
      ${auctionLink}
      <div class="rev-label ${tone}">${toneLabel}</div>
      <div class="rev-stars">${[1,2,3,4,5].map(i=>`<span class="rev-star${i<=rev.rating?' on':''}">★</span>`).join('')}</div>
      ${rev.comment?`<div class="rev-text">${esc(rev.comment)}</div>`:''}
    </div>`;
  }).join('');
}

function toggleShowAllReviews(){
  const el=document.getElementById('reviewsContainer');
  if(!el)return;
  el.dataset.showAll = el.dataset.showAll==='true' ? 'false' : 'true';
  renderReviews();
}

function renderSubBtn(sub){
  return`<button class="sub-btn${sub?' subscribed':''}" onclick="toggleSub()" id="subBtn">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      ${sub?`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" y1="11" x2="16" y2="11"/>`:`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>`}
    </svg>
    ${sub?'Отписаться':'Подписаться'}
  </button>`;
}

async function toggleSub(){
  if(!token||!sellerId)return;
  try{
    const r=await fetch(`${API}/api/sellers/${sellerId}/subscribe`,{method:isSubscribed?'DELETE':'POST',headers:{Authorization:'Bearer '+token}});
    if(r.ok){isSubscribed=!isSubscribed;const w=document.getElementById('subBtnWrap');if(w)w.innerHTML=renderSubBtn(isSubscribed);}
  }catch{}
}

function showNotFound(msg){
  document.getElementById('page').innerHTML=`<div class="not-found"><div class="not-found-icon">👤</div><div class="not-found-title">${esc(msg)}</div><p style="margin:8px 0 20px;">Проверьте ссылку или вернитесь на главную.</p><a href="index.html" class="btn btn-secondary">← На главную</a></div>`;
}

init();

(function(){
  const A='http://localhost:8000',tk=localStorage.getItem('token');
  if(!tk)return;
  const nb=document.getElementById('notifBtn'),nbg=document.getElementById('notifBadge'),nd=document.getElementById('notifDropdown'),nl=document.getElementById('notifList'),nma=document.getElementById('notifMarkAll'),up=document.getElementById('userProfile'),gb=document.getElementById('guestBtn'),na=document.getElementById('navAvatar'),nn=document.getElementById('navUserName'),nbl=document.getElementById('navBalance');
  let uc=0,io=false;
  fetch(`${A}/api/me`,{headers:{Authorization:'Bearer '+tk}}).then(r=>r.ok?r.json():null).then(u=>{
    if(!u)return;
    if(nn)nn.textContent=u.username;if(nbl)nbl.textContent=Number(u.balance||0).toFixed(2);
    if(u.avatar_url){const s=u.avatar_url.startsWith('http')?u.avatar_url:`${A}${u.avatar_url}`;const i=document.createElement('img');i.src=s;i.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:50%;';na.innerHTML='';na.appendChild(i);}else{na.textContent=(u.username[0]||'?').toUpperCase();}
    if(up)up.style.display='flex';if(gb)gb.style.display='none';if(nb)nb.style.display='flex';
  }).catch(()=>{});
  function sc(n){uc=Math.max(0,n);if(nbg){nbg.textContent=uc>99?'99+':String(uc);nbg.style.display=uc>0?'flex':'none';}}
  fetch(`${A}/api/notifications/unread-count`,{headers:{Authorization:'Bearer '+tk}}).then(r=>r.ok?r.json():null).then(d=>{if(d)sc(d.count??0);}).catch(()=>{});
  function open(){io=true;nd.style.display='block';nl.innerHTML='<div style="padding:24px;text-align:center;color:var(--text-3)">Загрузка…</div>';fetch(`${A}/api/notifications?limit=30`,{headers:{Authorization:'Bearer '+tk}}).then(r=>r.ok?r.json():[]).then(items=>{if(!items.length){nl.innerHTML='<div style="padding:28px;text-align:center;color:var(--text-3)">🔔 Нет уведомлений</div>';return;}nl.innerHTML=items.map(n=>{const diff=Math.floor((Date.now()-new Date(n.created_at.endsWith('Z')?n.created_at:n.created_at+'Z'))/1000);const ago=diff<60?'только что':diff<3600?`${Math.floor(diff/60)} мин`:diff<86400?`${Math.floor(diff/3600)} ч`:`${Math.floor(diff/86400)} дн`;return`<div style="display:flex;gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;" onclick="if('${n.auction_id}')location.href='auction.html?id=${n.auction_id}'"><div style="flex:1;min-width:0;"><div style="font-size:12px;font-weight:700;">${n.title||''}</div><div style="font-size:11px;color:var(--text-3);">${n.message||''}</div><div style="font-size:10px;color:var(--text-3);margin-top:3px;">${ago} назад</div></div></div>`;}).join('');}).catch(()=>{});}
  function close(){io=false;nd.style.display='none';}
  if(nb)nb.addEventListener('click',e=>{e.stopPropagation();io?close():open();});
  document.addEventListener('click',e=>{if(io&&!nd.contains(e.target)&&e.target!==nb)close();});
  if(nma)nma.addEventListener('click',e=>{e.stopPropagation();fetch(`${A}/api/notifications/mark-all-read`,{method:'POST',headers:{Authorization:'Bearer '+tk}}).catch(()=>{});sc(0);close();});
})();

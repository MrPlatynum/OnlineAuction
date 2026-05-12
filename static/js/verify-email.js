(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function renderState({ icon, title, message, showActions }) {
    $('verifyIcon').textContent = icon;
    $('verifyTitle').textContent = title;
    $('verifyMessage').textContent = message;
    $('verifyActions').style.display = showActions ? 'flex' : 'none';
  }

  async function verify() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) {
      renderState({
        icon: '⚠️',
        title: 'Нет токена',
        message: 'Ссылка для подтверждения email повреждена. Запросите новую в настройках профиля.',
        showActions: true,
      });
      return;
    }

    try {
      const r = await fetch(`${window.API}/api/verify-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      if (r.ok) {
        renderState({
          icon: '✅',
          title: 'Email подтверждён',
          message: 'Теперь вы можете делать ставки, покупать лоты и создавать аукционы.',
          showActions: true,
        });
        return;
      }
      let detail = 'Не удалось подтвердить email.';
      try {
        const data = await r.json();
        if (data && data.detail) detail = data.detail;
      } catch (_) {}
      renderState({
        icon: '❌',
        title: 'Ошибка подтверждения',
        message: detail,
        showActions: true,
      });
    } catch (err) {
      renderState({
        icon: '🌐',
        title: 'Нет связи',
        message: 'Не удалось связаться с сервером. Попробуйте позже.',
        showActions: true,
      });
    }
  }

  document.addEventListener('DOMContentLoaded', verify);
})();

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function getToken() {
    return new URLSearchParams(window.location.search).get('token');
  }

  function showError(text) {
    const msg = $('resetMsg');
    msg.className = 'pw-reset-msg err';
    msg.textContent = text;
  }

  function showOk(text) {
    const msg = $('resetMsg');
    msg.className = 'pw-reset-msg ok';
    msg.textContent = text;
  }

  async function submit(e) {
    e.preventDefault();
    const token = getToken();
    if (!token) {
      showError('Ссылка повреждена — токен не найден.');
      return;
    }
    const newPassword = $('newPassword').value;
    const confirmPassword = $('confirmPassword').value;
    if (newPassword.length < 8) {
      showError('Пароль должен быть минимум 8 символов.');
      return;
    }
    if (newPassword !== confirmPassword) {
      showError('Пароли не совпадают.');
      return;
    }

    const btn = $('resetSubmit');
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Сброс…';

    try {
      const r = await fetch(`${window.API}/api/password-reset/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      });
      if (r.ok) {
        // Any session token in localStorage was bound to the old
        // token_version; the confirm bumped tv, so the token is dead.
        // Clear it so the next /index.html load shows the login screen.
        try { localStorage.removeItem('token'); } catch (_) {}
        showOk('Пароль успешно сброшен. Перенаправляем на вход…');
        setTimeout(() => { window.location.href = 'index.html'; }, 1500);
        return;
      }
      let detail = 'Не удалось сбросить пароль.';
      try {
        const data = await r.json();
        if (data && data.detail) {
          detail = Array.isArray(data.detail)
            ? data.detail.map((d) => d.msg || 'Ошибка валидации').join('; ')
            : data.detail;
        }
      } catch (_) {}
      showError(detail);
    } catch (_) {
      showError('Нет связи с сервером. Попробуйте позже.');
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!getToken()) {
      showError('Ссылка повреждена — токен не найден. Запросите новую.');
      $('resetSubmit').disabled = true;
    }
    $('resetForm').addEventListener('submit', submit);
  });
})();

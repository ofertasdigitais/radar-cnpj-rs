(() => {
  const body = document.body;
  const tabs = [...document.querySelectorAll('[data-auth-tab]')];
  const forms = [...document.querySelectorAll('.auth-form')];

  function setView(view, updateUrl = true) {
    if (view === 'register' && body.dataset.registration !== 'enabled') view = 'login';
    body.dataset.authView = view;
    tabs.forEach(tab => {
      const active = tab.dataset.authTab === view;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    forms.forEach(form => {
      const active = form.classList.contains(`auth-form-${view}`);
      form.querySelectorAll('input,button,select,textarea').forEach(field => { field.disabled = !active; });
    });
    if (updateUrl) history.replaceState(null, '', view === 'register' ? '/login?mode=register' : '/login');
  }

  tabs.forEach(tab => tab.addEventListener('click', () => setView(tab.dataset.authTab)));
  document.querySelectorAll('[data-password-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const input = button.previousElementSibling;
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      button.textContent = reveal ? 'OCULTAR' : 'VER';
      button.setAttribute('aria-label', reveal ? 'Ocultar senha' : 'Mostrar senha');
    });
  });

  const registerPassword = document.querySelector('.auth-form-register input[name="password"]');
  const strength = document.querySelector('.auth-strength');
  registerPassword?.addEventListener('input', () => {
    const value = registerPassword.value;
    const score = [value.length >= 10, /[A-Za-zÀ-ÿ]/.test(value), /\d/.test(value), /[^A-Za-zÀ-ÿ\d]/.test(value)].filter(Boolean).length;
    strength.dataset.score = String(score);
    strength.querySelector('em').textContent = score < 3 ? 'Use ao menos 10 caracteres, letras e números' : score === 3 ? 'Senha adequada' : 'Senha forte';
  });

  forms.forEach(form => form.addEventListener('submit', event => {
    if (!form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
      form.classList.add('auth-form-shake');
      setTimeout(() => form.classList.remove('auth-form-shake'), 420);
    }
  }));

  if (body.dataset.registration !== 'enabled') document.querySelector('[data-auth-tab="register"]')?.setAttribute('hidden', '');
  setView(body.dataset.authView || 'login', false);
})();

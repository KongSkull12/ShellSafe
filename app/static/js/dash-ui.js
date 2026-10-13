(function () {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* Stagger enter for dashboard page blocks */
    document.querySelectorAll('.dash-page > *, .dash-stagger > *').forEach(function (el, i) {
        el.classList.add('dash-anim');
        el.style.animationDelay = `${Math.min(i, 10) * 0.06 + 0.04}s`;
    });

    /* Confirm modal for destructive actions */
    const modalEl = document.getElementById('ssConfirmModal');
    if (!modalEl || typeof bootstrap === 'undefined') return;

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const titleEl = document.getElementById('ssConfirmTitle');
    const bodyEl = document.getElementById('ssConfirmBody');
    const confirmBtn = document.getElementById('ssConfirmBtn');
    let pendingForm = null;

    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (!form.hasAttribute('data-confirm')) return;
        event.preventDefault();
        pendingForm = form;
        if (titleEl) titleEl.textContent = form.getAttribute('data-confirm-title') || 'Confirm action';
        if (bodyEl) bodyEl.textContent = form.getAttribute('data-confirm') || 'Are you sure?';
        if (confirmBtn) {
            const danger = form.getAttribute('data-confirm-danger') === 'true';
            confirmBtn.className = danger ? 'btn ss-btn-danger' : 'btn ss-btn-primary';
            confirmBtn.textContent = form.getAttribute('data-confirm-action') || 'Confirm';
        }
        modal.show();
    });

    if (confirmBtn) {
        confirmBtn.addEventListener('click', function () {
            if (!pendingForm) return;
            const form = pendingForm;
            pendingForm = null;
            modal.hide();
            form.removeAttribute('data-confirm');
            form.submit();
        });
    }

    modalEl.addEventListener('hidden.bs.modal', function () {
        pendingForm = null;
    });

    if (reduceMotion) return;

    /* Soft ripple on primary buttons */
    document.addEventListener('click', function (event) {
        const btn = event.target.closest('.ss-btn-primary, .export-btn, .ss-auth-submit');
        if (!btn) return;
        btn.classList.remove('is-pressed');
        void btn.offsetWidth;
        btn.classList.add('is-pressed');
    });
})();

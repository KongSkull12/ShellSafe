/* Shell behaviour: entry stagger, drawer, confirm dialog, tabs, flash dismiss. */
(function () {
    'use strict';

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const cssMs = function (name, fallback) {
        return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || fallback;
    };

    /* Staggered entry for top-level page blocks (and chart grid tiles). */
    document.querySelectorAll('.enter').forEach(function (root) {
        let i = 0;
        Array.from(root.children).forEach(function (child) {
            child.style.setProperty('--i', Math.min(i++, 8));
        });
    });
    document.querySelectorAll('.chart-grid').forEach(function (grid) {
        grid.classList.add('enter');
        Array.from(grid.children).forEach(function (child, i) {
            child.style.setProperty('--i', 3 + Math.min(i, 6));
        });
    });

    /* Mobile navigation drawer */
    const drawer = document.getElementById('navDrawer');
    if (drawer && typeof drawer.showModal === 'function') {
        const closeDrawer = function () {
            if (!drawer.open) return;
            if (reduceMotion) { drawer.close(); return; }
            drawer.classList.add('is-closing');
            setTimeout(function () { drawer.classList.remove('is-closing'); drawer.close(); }, cssMs('--duration-fast', 250));
        };
        document.querySelectorAll('[data-open-drawer]').forEach(function (btn) {
            btn.addEventListener('click', function () { drawer.showModal(); });
        });
        drawer.querySelectorAll('[data-close-drawer]').forEach(function (btn) {
            btn.addEventListener('click', closeDrawer);
        });
        drawer.addEventListener('click', function (event) { if (event.target === drawer) closeDrawer(); });
        drawer.addEventListener('cancel', function (event) { event.preventDefault(); closeDrawer(); });
        window.matchMedia('(min-width: 1024px)').addEventListener('change', function (mq) {
            if (mq.matches && drawer.open) drawer.close();
        });
    }

    /* Confirm before destructive form submits: <form data-confirm="..."> */
    const dialog = document.getElementById('confirmDialog');
    let pendingForm = null;

    function openConfirm() {
        dialog.classList.remove('is-closing');
        dialog.showModal();
        requestAnimationFrame(function () { dialog.classList.add('is-open'); });
    }
    function closeConfirm(value) {
        dialog.classList.remove('is-open');
        dialog.classList.add('is-closing');
        setTimeout(function () {
            dialog.classList.remove('is-closing');
            dialog.close(value);
        }, reduceMotion ? 0 : cssMs('--modal-close-dur', 150));
    }

    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-confirm')) return;
        if (!dialog || typeof dialog.showModal !== 'function') {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
            return;
        }
        event.preventDefault();
        pendingForm = form;
        document.getElementById('confirmTitle').textContent = form.dataset.confirmTitle || 'Are you sure?';
        document.getElementById('confirmText').textContent = form.dataset.confirm;
        const ok = document.getElementById('confirmOk');
        ok.textContent = form.dataset.confirmAction || 'Confirm';
        ok.className = form.dataset.confirmDanger === 'true' ? 'btn btn-danger' : 'btn btn-primary';
        openConfirm();
    });
    if (dialog) {
        dialog.querySelectorAll('button[value]').forEach(function (btn) {
            btn.addEventListener('click', function (event) {
                event.preventDefault();
                closeConfirm(btn.value);
            });
        });
        dialog.addEventListener('cancel', function (event) { event.preventDefault(); closeConfirm('cancel'); });
        dialog.addEventListener('close', function () {
            const form = pendingForm;
            pendingForm = null;
            if (form && dialog.returnValue === 'confirm') {
                form.removeAttribute('data-confirm');
                form.submit();
            }
        });
    }

    /* Sliding indicator for a set of buttons: pill in .tabs, underline in .seg-tabs. */
    function slider(container, indicatorClass, selectedOf) {
        const buttons = Array.from(container.querySelectorAll('button'));
        if (!buttons.length) return null;
        const bar = document.createElement('span');
        bar.className = indicatorClass;
        bar.setAttribute('aria-hidden', 'true');
        container.appendChild(bar);
        container.classList.add('has-pill');
        function moveTo(btn, animate) {
            if (!btn) return;
            const x = btn.offsetLeft;
            if (!animate) {
                const prev = bar.style.transition;
                bar.style.transition = 'none';
                bar.style.transform = `translateX(${x}px)`;
                bar.style.width = `${btn.offsetWidth}px`;
                void bar.offsetWidth;
                bar.style.transition = prev;
            } else {
                bar.style.transform = `translateX(${x}px)`;
                bar.style.width = `${btn.offsetWidth}px`;
            }
        }
        const sync = function (animate) { moveTo(selectedOf(buttons), animate); };
        requestAnimationFrame(function () { sync(false); });
        window.addEventListener('resize', function () { sync(false); });
        if (document.fonts) document.fonts.ready.then(function () { sync(false); });
        return sync;
    }
    const selected = function (buttons) {
        return buttons.find(function (b) { return b.getAttribute('aria-selected') === 'true'; }) || buttons[0];
    };

    document.querySelectorAll('.tabs').forEach(function (bar) {
        const sync = slider(bar, 'tabs-pill', selected);
        if (!sync) return;
        bar.addEventListener('click', function (event) {
            if (event.target.closest('button')) requestAnimationFrame(function () { sync(true); });
        });
    });

    /* ARIA tabs: [role=tablist][data-tabs] with buttons[role=tab][aria-controls] */
    document.querySelectorAll('[role="tablist"][data-tabs]').forEach(function (list) {
        const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
        const sync = list.classList.contains('seg-tabs') ? slider(list, 'underline', selected) : null;
        function select(tab) {
            tabs.forEach(function (t) {
                const on = t === tab;
                t.setAttribute('aria-selected', on ? 'true' : 'false');
                t.tabIndex = on ? 0 : -1;
                const panel = document.getElementById(t.getAttribute('aria-controls'));
                if (panel) panel.hidden = !on;
            });
            if (sync) sync(true);
        }
        tabs.forEach(function (tab, i) {
            tab.addEventListener('click', function () { select(tab); });
            tab.addEventListener('keydown', function (event) {
                const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
                if (!step) return;
                const next = tabs[(i + step + tabs.length) % tabs.length];
                next.focus();
                select(next);
            });
        });
    });

    /* Flash dismiss */
    document.addEventListener('click', function (event) {
        const btn = event.target.closest('[data-dismiss-flash]');
        if (!btn) return;
        const flash = btn.closest('.flash');
        if (reduceMotion) { flash.remove(); return; }
        flash.classList.add('is-leaving');
        flash.addEventListener('animationend', function () { flash.remove(); }, { once: true });
    });

    /* Show/hide password */
    document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
        const input = document.getElementById(btn.getAttribute('aria-controls'));
        btn.addEventListener('click', function () {
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            btn.setAttribute('aria-pressed', show ? 'true' : 'false');
            btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            btn.querySelector('i').className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
        });
    });
})();

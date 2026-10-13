document.addEventListener('DOMContentLoaded', function () {
    const nav = document.querySelector('.ss-nav');
    if (nav) {
        const onScroll = function () {
            nav.classList.toggle('is-scrolled', window.scrollY > 12);
        };
        onScroll();
        window.addEventListener('scroll', onScroll, { passive: true });
    }

    document.addEventListener('click', function (event) {
        const btn = event.target.closest('.ss-btn-primary');
        if (!btn) return;
        btn.classList.remove('is-pressed');
        void btn.offsetWidth;
        btn.classList.add('is-pressed');
    });

    const revealItems = document.querySelectorAll(
        '.ss-reveal-stagger > *, .ss-sensor-rail > li, .ss-step, .ss-feature-item, .ss-team-member'
    );

    if (!revealItems.length) return;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        revealItems.forEach(function (el) { el.classList.add('is-visible', 'fade-in'); });
        return;
    }

    const observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            const siblings = el.parentElement
                ? Array.from(el.parentElement.children)
                : [];
            const index = Math.max(0, siblings.indexOf(el));
            el.style.transitionDelay = `${Math.min(index, 6) * 70}ms`;
            el.classList.add('is-visible', 'fade-in');
            observer.unobserve(el);
        });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

    revealItems.forEach(function (el) { observer.observe(el); });
});

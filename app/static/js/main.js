document.addEventListener("DOMContentLoaded", function() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in');
            }
        });
    });

    const targets = document.querySelectorAll('.team-card');
    targets.forEach(target => {
        observer.observe(target);
    });
});

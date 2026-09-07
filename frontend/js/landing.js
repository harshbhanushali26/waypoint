// Landing page only. Fades in each .reveal section as it enters the
// viewport. Purely cosmetic — no data, no API calls.

const revealEls = document.querySelectorAll('.reveal');

if ('IntersectionObserver' in window && revealEls.length) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in-view');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  revealEls.forEach(el => observer.observe(el));
} else {
  // No IntersectionObserver support — just show everything immediately.
  revealEls.forEach(el => el.classList.add('in-view'));
}
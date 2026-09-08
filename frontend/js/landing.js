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

document.getElementById('footer-year').textContent = new Date().getFullYear();


const dayTabs = document.querySelectorAll('.day-tab');
const dayPanels = document.querySelectorAll('.voyage-day-panel');

if (dayTabs.length) {
  dayTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const day = tab.dataset.day;

      // toggle active tab
      dayTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      // toggle active panel
      dayPanels.forEach(p => {
        p.classList.toggle('active', p.dataset.panel === day);
      });
    });
  });
}


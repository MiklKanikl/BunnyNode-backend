document.querySelectorAll('.sidebar a').forEach(link => {
    link.addEventListener('click', (e) => {
    const href = link.getAttribute('href');
    if (href && href.startsWith('#')) {
        e.preventDefault();
        const targetId = href.substring(1);
        const targetElement = document.getElementById(targetId);
        if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth' });
        if (window.innerWidth <= 768) {
            document.querySelector('.sidebar').classList.remove('open');
        }
        }
    }
    });
});
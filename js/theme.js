// Переключение светлой и тёмной темы. Раньше было встроено в index.html; вынесено в файл,
// чтобы Content-Security-Policy могла запретить встроенные скрипты (script-src 'self').

const themeToggle = document.getElementById('theme-toggle');
themeToggle.addEventListener('click', function () {
    document.body.classList.toggle('dark-mode');
    const icon = this.querySelector('i');

    if (document.body.classList.contains('dark-mode')) {
        icon.classList.replace('fa-moon', 'fa-sun');
        localStorage.setItem('darkMode', 'true');
    } else {
        icon.classList.replace('fa-sun', 'fa-moon');
        localStorage.setItem('darkMode', 'false');
    }

    // Обновляем стили карты
    document.getElementById('map').classList.toggle('dark-map');
});

// Проверяем сохранённую тему при загрузке
if (localStorage.getItem('darkMode') === 'true') {
    document.body.classList.add('dark-mode');
    document.getElementById('map').classList.add('dark-map');
    themeToggle.querySelector('i').classList.replace('fa-moon', 'fa-sun');
}

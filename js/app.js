// Конфигурация приложения
const config = {
    defaultYear: 2021,
    defaultMonth: 1,
    defaultLevel: 1,
    animationSpeed: 900, // Общая скорость анимации
    levelAnimationSpeed: 900, // Можно задать отдельную скорость для уровней
    yearsAnimationSpeed: 900, // Самая медленная анимация
    // maxConcentration: 0.1, // максимальное значение для цветовой шкалы
    substances: {
        hno3: {
            name: "HNO₃",
            fullName: "Азотная кислота",
            maxConcentration: 11.66,
            minConcentration: 0,
            colorScale: ['#00fff', '#ff0000'], // от зеленого к красному
            availableYears: [2010, 2021], // Диапазон годов
            availableLevels: 27 // Количество уровней
        },
        h2o: {
            name: "H₂O",
            fullName: "Вода",
            maxConcentration: 0.0067,
            minConcentration: 0.00000027,
            colorScale: ['#ffffff', '#0000ff' ], // от голубого к синему
            availableYears: [2022, 2023],
            availableLevels: 55
        },
        co: {
            name: "CO",
            fullName: "Угарный газ",
            maxConcentration: 0.000061,
            minConcentration: 0.000000004,
            colorScale: ['#ffffff', '#ff6600'], // желтый → оранжевый
            availableYears: [2022, 2023],
            availableLevels: 37
        },
        o3: {
            name: "O₃",
            fullName: "Озон",
            maxConcentration: 0.0000079,
            minConcentration: 0.000000028,
            colorScale: ['#ccccff', '#6600cc'], // светло-фиолетовый → темно-фиолетовый
            availableYears: [2023, 2023], // Только 2022 год
            availableLevels: 55
        }
    }
};

// Инициализация карты
const map = L.map('map', {
    preferCanvas: true,
    zoomControl: false,
}).setView([55.0, 60.0], 7);

// Добавляем контрол масштаба
L.control.zoom({
    position: 'bottomright'
}).addTo(map);

// ======================
// СЛОИ КАРТ
// ======================

// OpenStreetMap слои
const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
});

const osmHumanitarian = L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
});

// Группировка слоев
const baseLayers = {
    '<i class="fas fa-map-marked-alt"></i> OSM Стандарт': osmStandard, // Слой по умолчанию
    '<i class="fas fa-people-arrows"></i> OSM Гуманитарный': osmHumanitarian,
};

// Добавляем переключатель слоев
L.control.layers(baseLayers, null, {
    position: 'topleft',
    collapsed: true,
    autoZIndex: true
}).addTo(map);

// Устанавливаем слой по умолчанию
osmStandard.addTo(map);

// ======================
// ЗАГРУЗКА ДАННЫХ
// ======================

let appData = {};
let geoJsonData = {};
let currentMarkers = [];
let animationInterval = null; // Для анимации месяцев
let levelAnimationInterval = null; // Новая переменная для анимации уровней
let yearsAnimationInterval = null; // Новая переменная для анимации годов

// Загрузка данных HNO3
fetch('data/hno3_data.json')
    .then(response => {
        if (!response.ok) throw new Error('Ошибка загрузки данных');
        return response.json();
    })
    .then(data => {
        appData = data;
        initControls();
        updateMap();
    })
    .catch(error => {
        console.error('Ошибка:', error);
        showAlert('Ошибка загрузки данных. Пожалуйста, обновите страницу.', 'error');
    });

// Загрузка границ области
fetch('data/region.geojson')
    .then(response => {
        if (!response.ok) throw new Error('Ошибка загрузки GeoJSON');
        return response.json();
    })
    .then(data => {
        geoJsonData = data;
        L.geoJSON(data, {
            style: {
                color: '#8f7878',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.1
            }
        }).addTo(map);
    })
    .catch(error => {
        console.error('Ошибка GeoJSON:', error);
    });

// ======================
// ИНИЦИАЛИЗАЦИЯ ЭЛЕМЕНТОВ УПРАВЛЕНИЯ
// ======================

function initControls() {
    const substanceSelect = document.getElementById('substance');
    const yearSelect = document.getElementById('year');
    const monthSelect = document.getElementById('month');
    const levelSelect = document.getElementById('level');
    const animateBtn = document.getElementById('animate-btn');
    const animateLevelsBtn = document.getElementById('animate-levels-btn');
    const animateYearsBtn = document.getElementById('animate-years-btn');


    // Заполняем годы (2010-2022)
    for (let year = 2010; year <= 2023; year++) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        if (year === config.defaultYear) option.selected = true;
        yearSelect.appendChild(option);
    }

    // Заполняем месяцы (1-12)
    for (let month = 1; month <= 12; month++) {
        const option = document.createElement('option');
        option.value = month;
        option.textContent = new Date(2000, month - 1).toLocaleString('ru', { month: 'long' });
        if (month === config.defaultMonth) option.selected = true;
        monthSelect.appendChild(option);
    }

    // Заполняем уровни (1-27)
    for (let level = 1; level <= 55; level++) {
        const option = document.createElement('option');
        option.value = level;
        option.textContent = level;
        if (level === config.defaultLevel) option.selected = true;
        levelSelect.appendChild(option);
    }

    // Обработчик изменения вещества
    substanceSelect.addEventListener('change', function() {
        updateControlsForSubstance(this.value);
        updateMap();
    });

        // Останавливаем анимации при ручном изменении параметров
    yearSelect.addEventListener('change', function() {
        stopAllAnimations();
        updateMap();
    });
    
    monthSelect.addEventListener('change', function() {
        stopAllAnimations();
        updateMap();
    });
    
    levelSelect.addEventListener('change', function() {
        stopAllAnimations();
        updateMap();
    });

    // Инициализация для текущего вещества
    updateControlsForSubstance(substanceSelect.value);

    // Обработчики событий
    yearSelect.addEventListener('change', updateMap);
    monthSelect.addEventListener('change', updateMap);
    levelSelect.addEventListener('change', updateMap);
    animateBtn.addEventListener('click', toggleAnimation);
    animateLevelsBtn.addEventListener('click', toggleLevelAnimation);
    animateYearsBtn.addEventListener('click', toggleYearsAnimation);
    
    document.getElementById('substance').addEventListener('change', updateMap);
    document.getElementById('animate-levels-btn').addEventListener('click', toggleLevelAnimation);
    document.getElementById('animate-years-btn').addEventListener('click', toggleYearsAnimation);
    // Инициализация графика
    initChart();
}

function updateControlsForSubstance(substance) {
    const substanceConfig = config.substances[substance];
    const yearSelect = document.getElementById('year');
    const levelSelect = document.getElementById('level');

    // Обновляем годы
    yearSelect.innerHTML = '';
    for (let year = substanceConfig.availableYears[0]; year <= substanceConfig.availableYears[1]; year++) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        yearSelect.appendChild(option);
    }

    // Обновляем уровни
    levelSelect.innerHTML = '';
    for (let level = 1; level <= substanceConfig.availableLevels; level++) {
        const option = document.createElement('option');
        option.value = level;
        option.textContent = level;
        levelSelect.appendChild(option);
    }

    // Останавливаем все анимации при смене вещества
    stopAllAnimations();

    // Сбрасываем анимации при смене вещества
    if (animationInterval) toggleAnimation();
    if (levelAnimationInterval) toggleLevelAnimation();
    if (yearsAnimationInterval) toggleYearsAnimation();
}

// ======================
// ОБНОВЛЕНИЕ КАРТЫ
// ======================

function updateMap() {
    const substance = document.getElementById('substance').value;
    const year = parseInt(document.getElementById('year').value);
    const month = parseInt(document.getElementById('month').value);
    const level = parseInt(document.getElementById('level').value);
    const substanceConfig = config.substances[substance];

    // Проверка на соответствие допустимым значениям
    if (year < substanceConfig.availableYears[0] || year > substanceConfig.availableYears[1]) {
        showAlert(`Для ${substanceConfig.fullName} доступны только данные за ${substanceConfig.availableYears.join('-')} годы`, 'warning');
        return;
    }

    if (level < 1 || level > substanceConfig.availableLevels) {
        showAlert(`Для ${substanceConfig.fullName} доступно только ${substanceConfig.availableLevels} уровней`, 'warning');
        return;
    }

    // Очищаем предыдущие маркеры
    clearMarkers();

    // Загрузка данных для выбранного вещества
    fetch(`data/${substance}_data.json`)
        .then(response => {
            if (!response.ok) throw new Error(`Не удалось загрузить данные для ${substanceConfig.fullName}`);
            return response.json();
        })
        .then(data => {
            if (!data?.cities?.length) {
                throw new Error('Нет данных для отображения');
            }

            const cityNames = [];
            const concentrations = [];
            let maxValue = 0;

            // Обрабатываем данные для каждого города
            data.cities.forEach(city => {
                const record = city.data.find(d => 
                    d.year === year && 
                    d.month === month && 
                    d.level === level
                );

                if (record) {
                    const concentration = record.concentration;
                    cityNames.push(city.name);
                    concentrations.push(concentration);
                    
                    // Добавляем маркер на карту
                    const marker = L.circleMarker([city.coordinates[0], city.coordinates[1]], {
                        radius: calculateRadius(concentration, substanceConfig.maxConcentration),
                        fillColor: getColor(concentration, substanceConfig),
                        color: '#333',
                        weight: 1,
                        fillOpacity: 0.7
                    }).addTo(map);

                    marker.bindPopup(createPopupContent(city, concentration, substanceConfig));
                    currentMarkers.push(marker);

                    // Обновляем максимальное значение для графика
                    if (concentration > maxValue) maxValue = concentration;
                }
            });

            // Обновляем легенду и график
            updateLegend(substanceConfig);
            updateChart(cityNames, concentrations, substance, maxValue);

        })
        .catch(error => {
            console.error('Ошибка:', error);
            showAlert(error.message, 'error');
            
            // Очищаем график при ошибке
            if (chart) {
                chart.data.labels = [];
                chart.data.datasets = [];
                chart.update();
            }
        });
}

function addCityMarker(city, concentration, substance) {
    const substanceConfig = config.substances[substance];
    
    const marker = L.circleMarker([city.coordinates[0], city.coordinates[1]], {
        radius: calculateRadius(concentration, substanceConfig.maxConcentration),
        fillColor: getColor(concentration, substanceConfig),
        color: '#333',
        weight: 1,
        fillOpacity: 0.7
    }).addTo(map);
    
    marker.bindPopup(createPopupContent(city, concentration, substanceConfig));
    currentMarkers.push(marker);
}

// ======================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ======================

function calculateRadius(concentration, max) {
    return Math.max(8, Math.min(30, 15 + (concentration / max) * 50));
}

function getColor(concentration, substanceConfig) {
    const ratio = Math.min(concentration / substanceConfig.maxConcentration, 1);
    
    // Для веществ с двумя цветами в градиенте
    if (substanceConfig.colorScale && substanceConfig.colorScale.length === 2) {
        const [color1, color2] = substanceConfig.colorScale;
        return interpolateColor(color1, color2, ratio);
    }
    
    // Возвращаем первый цвет из массива или красный по умолчанию
    return substanceConfig.colorScale?.[0] || '#ff0000';
}

function interpolateColor(color1, color2, ratio) {
    const r = Math.round(parseInt(color1.substring(1,3), 16) * (1-ratio) + parseInt(color2.substring(1,3), 16) * ratio);
    const g = Math.round(parseInt(color1.substring(3,5), 16) * (1-ratio) + parseInt(color2.substring(3,5), 16) * ratio);
    const b = Math.round(parseInt(color1.substring(5,7), 16) * (1-ratio) + parseInt(color2.substring(5,7), 16) * ratio);
    return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

function createPopupContent(city, concentration, substanceConfig) {
    return `
        <div class="popup-content">
            <h3>${city.name}</h3>
            <p><strong>Вещество:</strong> ${substanceConfig.fullName}</p>
            <p><strong>Концентрация:</strong> ${concentration.toExponential(4)} ppm</p>
        </div>
    `;
}

function updateLegend(substanceConfig) {
    const legend = document.getElementById('concentration-legend');
    legend.innerHTML = `
        <h4><i class="fas fa-flask"></i> ${substanceConfig.fullName}</h4>
        <div class="legend-scale">
            <div class="legend-gradient" style="background: linear-gradient(to right, ${substanceConfig.colorScale.join(', ')});"></div>
            <div class="legend-labels">
                <span>${(substanceConfig.minConcentration).toFixed(9)}</span>
                <!-- <span>${(substanceConfig.maxConcentration/2).toFixed(2)}</span> -->
                <span>${substanceConfig.maxConcentration.toFixed(5)} ppm</span>
            </div>
        </div>
        <div class="legend-info">
            <i class="fas fa-info-circle"></i> ${getSubstanceInfo(substanceConfig.name)}
        </div>
    `;
}

function getSubstanceInfo(substance) {
    const info = {
        'HNO₃': 'Азотная кислота — один из загрязнителей атмосферы.',
        'H₂O': 'Водяной пар — основной пар в атмосфере, влияет на погоду и парниковый эффект.',
        'CO': 'Угарный газ — продукт сгорания, опасен для здоровья, влияет на баланс атмосферных газов.',
        'O₃': 'Озон — защищает от УФ на высоте, но вреден у поверхности.'
    };
    return info[substance] || '';
}

function clearMarkers() {
    currentMarkers.forEach(marker => map.removeLayer(marker));
    currentMarkers = [];
}

function showAlert(message, type = 'info') {
    const alert = L.control({ position: 'topcenter' });
    alert.onAdd = function() {
        this._div = L.DomUtil.create('div', `alert alert-${type}`);
        this._div.innerHTML = message;
        return this._div;
    };
    alert.addTo(map);
    setTimeout(() => alert.remove(), 5000);
}

// ======================
// АНИМАЦИЯ
// ======================

function toggleAnimation() {
    const btn = document.getElementById('animate-btn');
    const icon = btn.querySelector('i');
    
    if (animationInterval) {
        clearInterval(animationInterval);
        animationInterval = null;
        btn.innerHTML = '<i class="fas fa-play"></i> Анимировать по месяцам';
        return;
    }
    
    // Останавливаем другие анимации
    if (levelAnimationInterval) toggleLevelAnimation();
    if (yearsAnimationInterval) toggleYearsAnimation();
    
    btn.innerHTML = '<i class="fas fa-stop"></i> Остановить анимацию';
    
    // Начинаем с текущего выбранного месяца
    let month = parseInt(document.getElementById('month').value);
    const maxMonth = 12;
    
    animationInterval = setInterval(() => {
        document.getElementById('month').value = month;
        updateMap();
        
        month = month % maxMonth + 1;
    }, config.animationSpeed);
}

function toggleLevelAnimation() {
    const btn = document.getElementById('animate-levels-btn');
    const icon = btn.querySelector('i');
    
    if (levelAnimationInterval) {
        clearInterval(levelAnimationInterval);
        levelAnimationInterval = null;
        btn.innerHTML = '<i class="fas fa-layer-group"></i> Анимировать по уровням';
        return;
    }
    
    // Останавливаем другие анимации
    if (animationInterval) toggleAnimation();
    if (yearsAnimationInterval) toggleYearsAnimation();
    
    btn.innerHTML = '<i class="fas fa-stop"></i> Остановить анимацию';
    
    // Начинаем с текущего выбранного уровня
    const levelSelect = document.getElementById('level');
    let level = parseInt(levelSelect.value);
    const maxLevel = parseInt(levelSelect.options[levelSelect.options.length - 1].value);
    
    levelAnimationInterval = setInterval(() => {
        levelSelect.value = level;
        updateMap();
        
        if (level >= maxLevel) {
            level = 1;
        } else {
            level++;
        }
    }, config.levelAnimationSpeed);
}

function toggleYearsAnimation() {
    const btn = document.getElementById('animate-years-btn');
    const icon = btn.querySelector('i');
    
    if (yearsAnimationInterval) {
        clearInterval(yearsAnimationInterval);
        yearsAnimationInterval = null;
        btn.innerHTML = '<i class="fas fa-calendar-alt"></i> Анимировать по годам';
        return;
    }
    
    // Останавливаем другие анимации
    if (animationInterval) toggleAnimation();
    if (levelAnimationInterval) toggleLevelAnimation();
    
    btn.innerHTML = '<i class="fas fa-stop"></i> Остановить анимацию';
    
    // Начинаем с текущего выбранного года
    const yearSelect = document.getElementById('year');
    let year = parseInt(yearSelect.value);
    const minYear = parseInt(yearSelect.options[0].value);
    const maxYear = parseInt(yearSelect.options[yearSelect.options.length - 1].value);
    
    yearsAnimationInterval = setInterval(() => {
        yearSelect.value = year;
        updateMap();
        
        if (year >= maxYear) {
            year = minYear;
        } else {
            year++;
        }
    }, config.yearsAnimationSpeed);
}

function stopAllAnimations() {
    if (animationInterval) {
        const btn = document.getElementById('animate-btn');
        clearInterval(animationInterval);
        animationInterval = null;
        btn.innerHTML = '<i class="fas fa-play"></i> Анимировать по месяцам';
    }
    
    if (levelAnimationInterval) {
        const btn = document.getElementById('animate-levels-btn');
        clearInterval(levelAnimationInterval);
        levelAnimationInterval = null;
        btn.innerHTML = '<i class="fas fa-layer-group"></i> Анимировать по уровням';
    }
    
    if (yearsAnimationInterval) {
        const btn = document.getElementById('animate-years-btn');
        clearInterval(yearsAnimationInterval);
        yearsAnimationInterval = null;
        btn.innerHTML = '<i class="fas fa-calendar-alt"></i> Анимировать по годам';
    }
}

// ======================
// ГРАФИК (CHART.JS)
// ======================

let chart = null;

function initChart() {
    const ctx = document.getElementById('chart').getContext('2d');
    
    chart = new Chart(ctx, {
        type: 'bar',
        data: { 
            labels: [], 
            datasets: [] 
        },
        options: {
            responsive: false, // Отключаем адаптивность
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: { 
                        display: true, 
                        text: 'Концентрация (ppm)',
                        font: {
                            size: 12
                        }
                    },
                    ticks: {
                        font: {
                            size: 10
                        }
                    }
                },
                x: {
                    ticks: {
                        font: {
                            size: 10
                        },
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            },
            plugins: {
                legend: { 
                    display: false 
                },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.raw.toExponential(4)} ppm`
                    }
                }
            }
        }
    });
}

function updateChart(labels, data, substance) {
    if (!chart) return;
    
    const substanceConfig = config.substances[substance];
    
    chart.data.labels = labels;
    chart.data.datasets = [{
        label: substanceConfig.fullName,
        data: data,
        backgroundColor: data.map(c => getColor(c, substanceConfig)),
        borderColor: '#333',
        borderWidth: 1,
        barThickness: 15 // Фиксированная толщина столбцов
    }];
    
    // Фиксированные пределы для оси Y
    chart.options.scales.y.max = substanceConfig.maxConcentration * 1.1;
    chart.options.scales.y.min = 0;
    
    chart.update();
}

function updateChart(labels, data, substance) {
    if (!chart) return;
    
    const substanceConfig = config.substances[substance];
    
    chart.data.labels = labels;
    chart.data.datasets = [{
        label: `Концентрация ${substanceConfig.name}`,
        data: data,
        backgroundColor: data.map(c => getColor(c, substanceConfig)),
        borderColor: '#333',
        borderWidth: 1
    }];
    chart.update();
}

function highlightChart(cityName) {
    if (!chart) return;
    
    const index = chart.data.labels.indexOf(cityName);
    if (index >= 0) {
        chart.setActiveElements([{ datasetIndex: 0, index }]);
        chart.update();
    }
}

function resetChartHighlight() {
    if (chart) {
        chart.setActiveElements([]);
        chart.update();
    }
}

function centerMapOnCity(cityName) {
    const city = appData.cities.find(c => c.name === cityName);
    if (city) {
        map.flyTo(city.coordinates, 10, {
            duration: 1,
            easeLinearity: 0.25
        });
    }
}

// ======================
// ТЕМНАЯ ТЕМА
// ======================

// Инициализация при загрузке

    // Инициализация темы
    document.getElementById('theme-toggle').addEventListener('click', toggleDarkMode);
    updateThemeIcon();
    
    // Адаптация под мобильные устройства
    if (window.innerWidth < 768) {
        map.setView([55.0, 60.0], 6);
    }
function getAvailableSubstances() {
    return Object.keys(config.substances).filter(substance => {
        // Проверяем существование файла данных
        // В реальном приложении нужно делать AJAX-запрос
        return true; // Для демонстрации всегда возвращаем true
    });
}

// Автоматическое заполнение select
function initSubstanceSelector() {
    const select = document.getElementById('substance');
    select.innerHTML = ''; // Очищаем существующие варианты
    
    getAvailableSubstances().forEach(substanceKey => {
        const substance = config.substances[substanceKey];
        const option = document.createElement('option');
        option.value = substanceKey;
        option.textContent = `${substance.name} (${substance.fullName})`;
        select.appendChild(option);
    });
}

function validateData(data) {
    return data.cities.every(city => 
        Array.isArray(city.data) && 
        city.data.every(item => 
            typeof item.concentration === 'number'
        )
    );
}

// Вызовите эту функцию в initControls()
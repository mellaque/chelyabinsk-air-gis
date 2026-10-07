// Веб-ГИС мониторинга качества воздуха.
// Годы, уровни и единицы измерения читаются из файлов данных (формат: docs/data-format.md),
// поэтому при добавлении новых лет или веществ код менять не нужно.

const config = {
    defaultSubstance: 'hno3',
    animationSpeed: 900,
    noDataColor: '#9e9e9e',
    substances: {
        hno3: {
            name: 'HNO₃',
            fullName: 'Азотная кислота',
            info: 'Азотная кислота — продукт окисления оксидов азота, один из компонентов загрязнения атмосферы.',
            colorScale: ['#1a9850', '#fee08b', '#d73027'],
        },
        h2o: {
            name: 'H₂O',
            fullName: 'Водяной пар',
            info: 'Водяной пар — основной парниковый газ, влияет на погоду и климат.',
            colorScale: ['#deebf7', '#6baed6', '#08306b'],
        },
        co: {
            name: 'CO',
            fullName: 'Угарный газ',
            info: 'Угарный газ — продукт неполного сгорания топлива, индикатор переноса загрязнений.',
            colorScale: ['#fff5eb', '#fd8d3c', '#7f2704'],
        },
        o3: {
            name: 'O₃',
            fullName: 'Озон',
            info: 'Озон защищает от УФ-излучения в стратосфере, но вреден у поверхности.',
            colorScale: ['#efedf5', '#9e9ac8', '#3f007d'],
        },
    },
};

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

// ======================
// КАРТА
// ======================

const map = L.map('map', { preferCanvas: true, zoomControl: false }).setView([55.0, 60.0], 7);
L.control.zoom({ position: 'bottomright' }).addTo(map);

const osmAttribution = '&copy; <a href="https://www.openstreetmap.org/copyright">участники OpenStreetMap</a>';
const baseLayers = {
    '<i class="fas fa-map-marked-alt"></i> OSM Стандарт': L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: osmAttribution, maxZoom: 19 }),
    '<i class="fas fa-people-arrows"></i> OSM Гуманитарный': L.tileLayer(
        'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', { attribution: osmAttribution, maxZoom: 19 }),
};
L.control.layers(baseLayers, null, { position: 'topleft', collapsed: true }).addTo(map);
Object.values(baseLayers)[0].addTo(map);
map.attributionControl.addAttribution('Данные: NASA TROPESS, Aura MLS');

if (window.innerWidth < 768) map.setView([55.0, 60.0], 6);

// ======================
// СОСТОЯНИЕ
// ======================

const state = {
    data: null,          // загруженный файл текущего вещества
    substance: null,
    markers: [],
    animation: null,     // { timer, selectId, buttonId }
};
const dataCache = {};    // substance -> data
const scaleCache = {};   // `${substance}:${levelIndex}` -> {min, max}

const el = id => document.getElementById(id);

// ======================
// ЗАГРУЗКА ДАННЫХ
// ======================

async function loadSubstance(substance) {
    if (!dataCache[substance]) {
        const response = await fetch(`data/${substance}_data.json`);
        if (!response.ok) throw new Error(`Не удалось загрузить данные: ${substance}`);
        const data = await response.json();
        if (data.schema_version !== 2) throw new Error(`Неподдерживаемый формат данных: ${substance}`);
        dataCache[substance] = data;
    }
    return dataCache[substance];
}

fetch('data/region.geojson')
    .then(r => { if (!r.ok) throw new Error('Не удалось загрузить границы'); return r.json(); })
    .then(geojson => {
        L.geoJSON(geojson, {
            style: f => f.properties.admin_level === 4
                ? { color: '#5b4b4b', weight: 2.5, fillOpacity: 0.08 }
                : { color: '#8f7878', weight: 0.8, fillOpacity: 0.04 },
            onEachFeature: (f, layer) => {
                if (f.properties.admin_level !== 4 && f.properties.name) {
                    layer.bindTooltip(f.properties.name, { sticky: true, direction: 'top' });
                }
            },
        }).addTo(map);
    })
    .catch(err => console.error(err));

// ======================
// РАСЧЁТЫ
// ======================

function valueAt(city, yearIndex, month, levelIndex) {
    return city.values[yearIndex]?.[month - 1]?.[levelIndex] ?? null;
}

// Шкала цвета считается для выбранного уровня по всем годам, месяцам и городам,
// чтобы цвета были сопоставимы при анимации по времени.
function scaleFor(substance, data, levelIndex) {
    const key = `${substance}:${levelIndex}`;
    if (!scaleCache[key]) {
        let min = Infinity, max = -Infinity;
        for (const city of data.cities)
            for (const year of city.values)
                for (const month of year) {
                    const v = month[levelIndex];
                    if (v !== null && v !== undefined) { min = Math.min(min, v); max = Math.max(max, v); }
                }
        scaleCache[key] = Number.isFinite(min) ? { min, max } : null;
    }
    return scaleCache[key];
}

// Уровень по умолчанию — самый нижний, где почти нет пропусков
// (нижние уровни давления часто оказываются «под землёй»).
function defaultLevelIndex(data) {
    for (let li = 0; li < data.levels.length; li++) {
        let total = 0, present = 0;
        for (const city of data.cities)
            for (const year of city.values)
                for (const month of year) { total++; if (month[li] !== null) present++; }
        if (total && present / total >= 0.95) return li;
    }
    return 0;
}

function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function interpolate(colors, t) {
    t = Math.min(1, Math.max(0, t));
    const pos = t * (colors.length - 1);
    const i = Math.min(Math.floor(pos), colors.length - 2);
    const a = hexToRgb(colors[i]), b = hexToRgb(colors[i + 1]);
    const f = pos - i;
    const rgb = a.map((c, k) => Math.round(c + (b[k] - c) * f));
    return `rgb(${rgb.join(',')})`;
}

function ratio(value, scale) {
    if (!scale || scale.max === scale.min) return 0.5;
    return (value - scale.min) / (scale.max - scale.min);
}

function colorFor(value, scale, substanceConfig) {
    return value === null ? config.noDataColor : interpolate(substanceConfig.colorScale, ratio(value, scale));
}

function formatValue(v) {
    if (v === null) return '—';
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 0.001 || abs >= 100000)) return v.toExponential(2);
    return Number(v.toPrecision(4)).toLocaleString('ru-RU');
}

function levelLabel(level) {
    return level.pressure_hPa != null
        ? `Уровень ${level.level} — ${level.pressure_hPa} гПа`
        : `Уровень ${level.level}`;
}

// ======================
// ЭЛЕМЕНТЫ УПРАВЛЕНИЯ
// ======================

function fillSelect(select, items, selectedValue) {
    const previous = selectedValue ?? select.value;
    select.innerHTML = '';
    for (const { value, label } of items) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    }
    const values = items.map(i => String(i.value));
    select.value = values.includes(String(previous)) ? previous : values[values.length - 1];
}

function setupControlsFor(data, isFirstLoad) {
    fillSelect(el('year'), data.years.map(y => ({ value: y, label: y })));
    fillSelect(el('month'), data.months.map(m => ({ value: m, label: MONTHS[m - 1] })),
        isFirstLoad ? 1 : undefined);
    fillSelect(el('level'), data.levels.map((lv, i) => ({ value: i, label: levelLabel(lv) })),
        defaultLevelIndex(data));
}

async function selectSubstance(substance, isFirstLoad = false) {
    stopAnimation();
    try {
        const data = await loadSubstance(substance);
        state.data = data;
        state.substance = substance;
        setupControlsFor(data, isFirstLoad);
        updateInfoPanel();
        updateMap();
    } catch (err) {
        console.error(err);
        showAlert(err.message, 'error');
    }
}

function currentSelection() {
    const data = state.data;
    const year = parseInt(el('year').value, 10);
    return {
        data,
        substanceConfig: config.substances[state.substance],
        year,
        yearIndex: data.years.indexOf(year),
        month: parseInt(el('month').value, 10),
        levelIndex: parseInt(el('level').value, 10),
    };
}

// ======================
// ОТРИСОВКА
// ======================

function clearMarkers() {
    state.markers.forEach(m => map.removeLayer(m));
    state.markers = [];
}

function updateMap() {
    if (!state.data) return;
    const sel = currentSelection();
    const scale = scaleFor(state.substance, sel.data, sel.levelIndex);

    clearMarkers();
    const labels = [], values = [];

    for (const city of sel.data.cities) {
        const value = valueAt(city, sel.yearIndex, sel.month, sel.levelIndex);
        labels.push(city.name);
        values.push(value);

        const marker = L.circleMarker(city.coordinates, value === null
            ? { radius: 8, fillColor: config.noDataColor, color: '#555', weight: 1, dashArray: '3', fillOpacity: 0.5 }
            : { radius: 9 + 13 * ratio(value, scale), fillColor: colorFor(value, scale, sel.substanceConfig),
                color: '#333', weight: 1, fillOpacity: 0.8 }
        ).addTo(map);
        marker.bindPopup(popupContent(city, value, sel));
        state.markers.push(marker);
    }

    updateLegend(sel, scale);
    updateChart(labels, values, sel, scale);
}

function popupContent(city, value, sel) {
    const units = sel.data.units;
    const level = sel.data.levels[sel.levelIndex];
    const valueText = value === null
        ? '<span class="no-data">нет данных</span><br><small>Уровень ниже поверхности земли или значение отсутствует в источнике.</small>'
        : `${formatValue(value)} ${units}`;

    let cellNote = '';
    if (city.grid_cell) {
        const [lat, lon] = city.grid_cell;
        const shared = sel.data.cities
            .filter(c => c !== city && c.grid_cell && c.grid_cell[0] === lat && c.grid_cell[1] === lon)
            .map(c => c.name);
        cellNote = `<p class="popup-note">Ячейка сетки ${lat.toFixed(2)}° с.ш., ${lon.toFixed(2)}° в.д.`
            + (shared.length ? ` — общая с: ${shared.join(', ')}` : '') + '</p>';
    }

    return `
        <div class="popup-content">
            <h3>${city.name}</h3>
            <p><strong>${sel.substanceConfig.name}</strong> — ${sel.substanceConfig.fullName}</p>
            <p><strong>Концентрация:</strong> ${valueText}</p>
            <p><strong>Период:</strong> ${MONTHS[sel.month - 1]} ${sel.year}</p>
            <p><strong>${levelLabel(level)}</strong></p>
            ${cellNote}
        </div>`;
}

function updateLegend(sel, scale) {
    const units = sel.data.units;
    const gradient = sel.substanceConfig.colorScale.join(', ');
    el('concentration-legend').innerHTML = `
        <h4><i class="fas fa-flask"></i> ${sel.substanceConfig.name}, ${units}</h4>
        <div class="legend-gradient" style="background: linear-gradient(to right, ${gradient});"></div>
        <div class="legend-labels">
            <span>${scale ? formatValue(scale.min) : '—'}</span>
            <span>${scale ? formatValue(scale.max) : '—'}</span>
        </div>
        <div class="legend-nodata"><span class="swatch"></span> нет данных</div>
        <div class="legend-note">Шкала для выбранного уровня, все годы и месяцы</div>`;
}

function updateInfoPanel() {
    const data = state.data;
    const sc = config.substances[state.substance];
    const src = data.source || {};
    const doi = src.doi ? ` (<a href="https://doi.org/${src.doi}" target="_blank" rel="noopener">doi:${src.doi}</a>)` : '';
    const warning = data.quality === 'unverified'
        ? `<div class="quality-warning"><i class="fas fa-exclamation-triangle"></i> ${data.quality_note || 'Данные не проверены.'}</div>`
        : '';
    el('data-info').innerHTML = `
        ${warning}
        <p>${sc.info}</p>
        <p><strong>Единицы:</strong> ${data.units} (объёмная доля)</p>
        <p><strong>Источник:</strong> ${src.product || '—'}${doi}</p>
        <p><strong>Период:</strong> ${formatYears(data.years)}, уровней: ${data.levels.length}</p>`;
}

function formatYears(years) {
    const first = years[0], last = years[years.length - 1];
    return first === last ? String(first) : `${first}–${last}`;
}

// ======================
// ГРАФИК
// ======================

let chart = null;

function initChart() {
    chart = new Chart(el('chart').getContext('2d'), {
        type: 'bar',
        data: { labels: [], datasets: [] },
        options: {
            responsive: false,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: '' }, ticks: { font: { size: 10 } } },
                x: { ticks: { font: { size: 10 }, maxRotation: 45, minRotation: 45 } },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => ctx.raw === null ? 'нет данных' : `${formatValue(ctx.raw)} ${state.data.units}`,
                    },
                },
            },
        },
    });
}

function updateChart(labels, values, sel, scale) {
    if (!chart) return;
    chart.data.labels = labels;
    chart.data.datasets = [{
        data: values,
        backgroundColor: values.map(v => colorFor(v, scale, sel.substanceConfig)),
        borderColor: '#333',
        borderWidth: 1,
    }];
    chart.options.scales.y.title.text = `${sel.substanceConfig.name}, ${sel.data.units}`;
    chart.options.scales.y.suggestedMax = scale ? scale.max : undefined;
    chart.update();
}

// ======================
// АНИМАЦИЯ
// ======================

const ANIMATIONS = {
    'animate-years-btn': { selectId: 'year', label: '<i class="fas fa-calendar-alt"></i> Анимировать по годам' },
    'animate-btn': { selectId: 'month', label: '<i class="fas fa-play"></i> Анимировать по месяцам' },
    'animate-levels-btn': { selectId: 'level', label: '<i class="fas fa-layer-group"></i> Анимировать по уровням' },
};

function stopAnimation() {
    if (!state.animation) return;
    clearInterval(state.animation.timer);
    const btn = el(state.animation.buttonId);
    btn.innerHTML = ANIMATIONS[state.animation.buttonId].label;
    btn.classList.remove('running');
    state.animation = null;
}

function toggleAnimation(buttonId) {
    const wasRunning = state.animation?.buttonId === buttonId;
    stopAnimation();
    if (wasRunning) return;

    const select = el(ANIMATIONS[buttonId].selectId);
    const btn = el(buttonId);
    btn.innerHTML = '<i class="fas fa-stop"></i> Остановить анимацию';
    btn.classList.add('running');

    state.animation = {
        buttonId,
        timer: setInterval(() => {
            select.selectedIndex = (select.selectedIndex + 1) % select.options.length;
            updateMap();
        }, config.animationSpeed),
    };
}

// ======================
// УВЕДОМЛЕНИЯ
// ======================

function showAlert(message, type = 'info') {
    const box = document.createElement('div');
    box.className = `app-alert app-alert-${type}`;
    box.textContent = message;
    el('map').appendChild(box);
    setTimeout(() => box.remove(), 5000);
}

// ======================
// ЗАПУСК
// ======================

function init() {
    initChart();

    el('substance').addEventListener('change', e => selectSubstance(e.target.value));
    for (const id of ['year', 'month', 'level']) {
        el(id).addEventListener('change', () => { stopAnimation(); updateMap(); });
    }
    for (const buttonId of Object.keys(ANIMATIONS)) {
        el(buttonId).addEventListener('click', () => toggleAnimation(buttonId));
    }

    el('substance').value = config.defaultSubstance;
    selectSubstance(config.defaultSubstance, true);
}

init();

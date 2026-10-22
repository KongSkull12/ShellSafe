/* One trend chart per sensor, fed by live.js.
   ShellSafeTrend.seed(history, max) loads server-recorded samples once;
   ShellSafeTrend.mount(panel, { key, span, small }) draws one sensor. */
(function () {
    'use strict';

    const SENSORS = {
        temperature: { label: 'Temperature', unit: '°C', decimals: 1 },
        ph: { label: 'pH', unit: '', decimals: 2 },
        turbidity: { label: 'Turbidity', unit: 'NTU', decimals: 1 },
        orp: { label: 'ORP', unit: 'mV', decimals: 1 },
        ec: { label: 'EC', unit: 'µS/cm', decimals: 1 },
    };
    const KEYS = Object.keys(SENSORS);
    const LINE = '#2f5fe0';
    const BAND = 'rgba(34, 160, 90, 0.07)';
    const WARN = 'rgba(190, 120, 20, 0.55)';
    const GRID = '#eef0f3';
    const TICK = '#7a818c';
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const store = { samples: [], max: 240, listeners: [] };

    function timeLabel(epoch) {
        return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function seed(history, max) {
        store.max = Math.max(store.max, max || 0);
        if (store.samples.length || !Array.isArray(history)) return;
        store.samples = history.slice(-store.max);
    }

    function sampleFrom(payload) {
        if (!payload || payload.link?.state !== 'live') return null;
        const sample = { t: Date.now() / 1000 };
        let any = false;
        (payload.sensors || []).forEach(function (s) {
            sample[s.key] = s.state === 'live' ? s.value : null;
            if (sample[s.key] != null) any = true;
        });
        return any ? sample : null;
    }

    document.addEventListener('shellsafe:live', function (event) {
        const sample = sampleFrom(event.detail.payload);
        if (sample) {
            const last = store.samples[store.samples.length - 1];
            const same = last && KEYS.every(function (k) { return last[k] === sample[k]; });
            if (!same || sample.t - last.t >= 5) {
                store.samples.push(sample);
                if (store.samples.length > store.max) store.samples.shift();
            }
        }
        store.listeners.forEach(function (fn) { fn(event.detail.payload); });
    });

    // Shade the normal band and dash the warning limits behind the line.
    const bandPlugin = {
        id: 'shellsafeBand',
        beforeDatasetsDraw(chart, _args, opts) {
            const band = opts && opts.band;
            if (!band) return;
            const { ctx, chartArea, scales } = chart;
            const y = scales.y;
            ctx.save();
            if (band.min != null || band.max != null) {
                const top = band.max != null ? y.getPixelForValue(band.max) : chartArea.top;
                const bottom = band.min != null ? y.getPixelForValue(band.min) : chartArea.bottom;
                const t = Math.max(chartArea.top, Math.min(top, bottom));
                const b = Math.min(chartArea.bottom, Math.max(top, bottom));
                if (b > t) {
                    ctx.fillStyle = BAND;
                    ctx.fillRect(chartArea.left, t, chartArea.right - chartArea.left, b - t);
                }
            }
            ctx.strokeStyle = WARN;
            ctx.setLineDash([3, 4]);
            ctx.lineWidth = 1;
            [band.warnMin, band.warnMax].forEach(function (v) {
                if (v == null) return;
                const py = y.getPixelForValue(v);
                if (py < chartArea.top || py > chartArea.bottom) return;
                ctx.beginPath();
                ctx.moveTo(chartArea.left, py);
                ctx.lineTo(chartArea.right, py);
                ctx.stroke();
            });
            ctx.restore();
        },
    };

    // Vertical hairline under the cursor.
    const crosshairPlugin = {
        id: 'shellsafeCrosshair',
        afterDatasetsDraw(chart) {
            const active = chart.tooltip && chart.tooltip.getActiveElements();
            if (!active || !active.length) return;
            const x = active[0].element.x;
            const { ctx, chartArea } = chart;
            ctx.save();
            ctx.strokeStyle = '#c9ced6';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, chartArea.top);
            ctx.lineTo(x, chartArea.bottom);
            ctx.stroke();
            ctx.restore();
        },
    };

    function bandFor(payload, key) {
        const cfg = payload?.risk_assessment?.thresholds?.[key];
        if (!cfg) return null;
        return { min: cfg.normal_min, max: cfg.normal_max, warnMin: cfg.warning_min, warnMax: cfg.warning_max };
    }

    function fillGradient(ctx, area) {
        if (!area) return 'rgba(47, 95, 224, 0.08)';
        const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
        g.addColorStop(0, 'rgba(47, 95, 224, 0.16)');
        g.addColorStop(1, 'rgba(47, 95, 224, 0)');
        return g;
    }

    function mount(root, options) {
        if (!root || typeof Chart === 'undefined') return null;
        options = options || {};
        seed(options.history, options.maxPoints);

        const canvas = root.querySelector('canvas');
        const empty = root.querySelector('[data-trend-empty]');
        const caption = root.querySelector('[data-trend-caption]');
        const key = options.key || root.dataset.chart || 'temperature';
        const sensor = SENSORS[key];
        let span = options.span || 60;
        let drawn = false;

        const chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    data: [],
                    borderColor: LINE,
                    borderWidth: 1.75,
                    backgroundColor: function (c) { return fillGradient(c.chart.ctx, c.chart.chartArea); },
                    fill: 'start',
                    tension: 0.35,
                    cubicInterpolationMode: 'monotone',
                    spanGaps: false,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: LINE,
                    pointHoverBorderColor: '#fff',
                    pointHoverBorderWidth: 2,
                }],
            },
            plugins: [bandPlugin, crosshairPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                layout: { padding: { top: 4, right: 2 } },
                plugins: {
                    legend: { display: false },
                    shellsafeBand: { band: null },
                    tooltip: {
                        backgroundColor: '#ffffff',
                        borderColor: '#e3e6eb',
                        borderWidth: 1,
                        titleColor: '#7a818c',
                        bodyColor: '#171a20',
                        titleFont: { family: 'Geist', weight: '400', size: 11 },
                        bodyFont: { family: 'Geist', weight: '600', size: 13 },
                        padding: 8,
                        cornerRadius: 6,
                        displayColors: false,
                        caretSize: 0,
                        callbacks: {
                            label: function (ctx) {
                                return `${Number(ctx.parsed.y).toFixed(sensor.decimals)} ${sensor.unit}`.trim();
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        border: { color: GRID },
                        ticks: {
                            color: TICK, maxRotation: 0, autoSkip: true, autoSkipPadding: 16, maxTicksLimit: 4,
                            font: { family: 'Geist', size: 11 },
                            // Axis shows HH:MM; the tooltip keeps seconds.
                            callback: function (value) {
                                const label = this.getLabelForValue(value) || '';
                                return label.replace(/:\d{2}(?=\s|$)/, '');
                            },
                        },
                    },
                    y: {
                        position: 'right',
                        grid: { color: GRID, drawTicks: false },
                        border: { display: false },
                        ticks: { color: TICK, maxTicksLimit: 4, padding: 8, font: { family: 'Geist', size: 11 } },
                    },
                },
            },
        });

        function emptyMessage(payload, count) {
            if (count) return null;
            const s = (payload?.sensors || []).find(function (x) { return x.key === key; });
            const state = payload?.link?.state;
            if (state === 'offline') return ['Device offline', 'The trend resumes when the device reports again.'];
            if (state === 'checking') return ['Connecting', 'Waiting for the first fresh reading.'];
            if (state === 'nodata' || !payload) return ['No data yet', 'Nothing has reached Firebase from the device.'];
            if (s && s.uncalibrated) return ['Not calibrated', `The probe is reading (${s.display} V). Calibrate it on the device to see ${sensor.label} values here.`];
            if (s && s.state === 'unplugged') return ['Probe unplugged', `Reconnect the ${sensor.label.toLowerCase()} probe and readings will appear here.`];
            return ['Collecting readings', 'Points appear as the device reports, every few seconds.'];
        }

        // First paint draws the line in from left to right; later updates
        // just extend it, so a live feed doesn't keep re-animating.
        function drawIn() {
            if (reduceMotion) return;
            chart.options.animation = {
                x: { type: 'number', easing: 'easeOutCubic', duration: 600, from: NaN, delay: function (ctx) { return ctx.type === 'data' ? ctx.index * (600 / Math.max(1, span)) : 0; } },
                y: { duration: 0 },
            };
            chart.update();
            chart.options.animation = false;
        }

        function render(payload) {
            payload = payload || window.ShellSafeLive?.current;
            const rows = store.samples.slice(-span);
            const values = rows.map(function (r) { return r[key] == null ? null : r[key]; });
            const count = values.filter(function (v) { return v != null; }).length;
            chart.data.labels = rows.map(function (r) { return timeLabel(r.t); });
            chart.data.datasets[0].data = values;
            chart.options.plugins.shellsafeBand.band = count ? bandFor(payload, key) : null;
            if (!drawn && count) { drawn = true; drawIn(); } else { chart.update('none'); }

            const msg = emptyMessage(payload, count);
            if (empty) {
                empty.hidden = !msg;
                if (msg) empty.innerHTML = `<div><strong>${msg[0]}</strong>${msg[1]}</div>`;
            }
            if (caption) {
                const live = payload?.link?.state === 'live';
                caption.textContent = !count
                    ? 'No readings yet'
                    : live
                        ? `Last ${count} reading${count === 1 ? '' : 's'} · normal range shaded`
                        : `Earlier readings · device not reporting`;
            }
        }

        store.listeners.push(render);
        render();
        return { chart: chart, render: render, setSpan: function (n) { span = n; render(); } };
    }

    window.ShellSafeTrend = { mount: mount, store: store, SENSORS: SENSORS, timeLabel: timeLabel, seed: seed };
})();

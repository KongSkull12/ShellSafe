/* Live sensor state for every logged-in page.
   One connection (SSE, falling back to polling), one payload, and every
   element bound with data-* attributes is repainted from it. Pages listen for
   `shellsafe:live` to update their own charts or tables. */
(function () {
    'use strict';

    const body = document.body;
    const streamUrl = body.dataset.sensorStreamUrl;
    const pollUrl = body.dataset.sensorPollUrl;
    const POLL_MS = 5000;
    const STREAM_RETRY_MS = 30000;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let current = null;
    let stream = null;
    let pollTimer = null;
    let retryTimer = null;
    let serverReachable = true;

    const LINK_LABELS = { live: 'Live', offline: 'Offline', checking: 'Connecting', nodata: 'No data' };
    const RISK_ICONS = { normal: 'bi-check-lg', warning: 'bi-exclamation-lg', high: 'bi-exclamation-triangle' };

    /* ---------- motion helpers (transitions.dev) ---------- */

    const cssMs = function (name) {
        return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
    };

    // Number pop-in: only the digits that changed rise into place.
    function setDigits(group, str) {
        const prev = group.textContent.replace(/\s+/g, '');
        if (prev === str) return;
        if (reduceMotion || !/\d/.test(str) || !/\d/.test(prev)) {
            group.classList.remove('is-animating');
            group.textContent = str;
            return;
        }
        let same = 0;
        while (same < prev.length && same < str.length && prev[same] === str[same]) same++;
        group.classList.remove('is-animating');
        group.replaceChildren();
        const chars = str.split('');
        chars.forEach(function (ch, i) {
            const span = document.createElement('span');
            span.className = 't-digit';
            span.textContent = ch;
            if (i < same) span.dataset.same = '';
            if (i === chars.length - 2) span.dataset.stagger = '1';
            else if (i === chars.length - 1) span.dataset.stagger = '2';
            group.appendChild(span);
        });
        void group.offsetHeight;
        group.classList.add('is-animating');
        // Settle to plain text afterwards so a throttled or skipped animation
        // can never leave a reading half-drawn.
        clearTimeout(group._digitTimer);
        group._digitTimer = setTimeout(function () {
            group.classList.remove('is-animating');
            group.textContent = str;
        }, cssMs('--digit-dur') + cssMs('--digit-stagger') * 2 + 60);
    }

    // Soft swap: old text blurs out while the new one blurs in, in place.
    function softSwap(el, next) {
        const prev = el.dataset.text ?? el.textContent;
        if (prev === next) return;
        el.dataset.text = next;
        if (reduceMotion) { el.textContent = next; return; }
        clearTimeout(el._softTimer);
        el.classList.add('t-text-soft');
        const out = document.createElement('span');
        out.className = 't-text-soft-old';
        out.setAttribute('aria-hidden', 'true');
        out.textContent = prev;
        const inn = document.createElement('span');
        inn.className = 't-text-soft-new';
        inn.textContent = next;
        const w0 = el.getBoundingClientRect().width;
        el.classList.remove('is-swapping');
        el.replaceChildren(out, inn);
        const w1 = inn.getBoundingClientRect().width;
        el.style.width = w0 + 'px';
        void el.offsetWidth;
        el.classList.add('is-swapping');
        el.style.width = w1 + 'px';
        el._softTimer = setTimeout(function () {
            el.classList.remove('is-swapping', 't-text-soft');
            el.style.removeProperty('width');
            el.textContent = next;
        }, Math.max(cssMs('--text-soft-dur'), cssMs('--text-soft-resize-dur')) + 40);
    }

    /* ---------- formatting ---------- */

    function humanizeAge(seconds) {
        if (seconds == null || !Number.isFinite(seconds)) return null;
        const s = Math.max(0, Math.floor(seconds));
        if (s < 10) return 'just now';
        if (s < 60) return `${s} s ago`;
        const m = Math.floor(s / 60);
        if (m < 60) return `${m} min ago`;
        const h = Math.floor(m / 60);
        if (h < 48) return `${h} hr ago`;
        return `${Math.floor(h / 24)} days ago`;
    }

    function lastSeenText(payload) {
        const epoch = payload?.link?.last_seen_epoch;
        if (epoch) return humanizeAge(Date.now() / 1000 - epoch);
        const label = payload?.link?.last_update;
        return label && label !== 'unknown' ? label : null;
    }

    function stateText(s) {
        return s.state === 'live' ? (s.level_label || 'Live') : s.state_label;
    }

    function setAll(selector, fn) {
        document.querySelectorAll(selector).forEach(fn);
    }

    /* ---------- painters ---------- */

    function paintLink(payload) {
        const state = serverReachable ? (payload?.link?.state || 'nodata') : 'offline';
        const seen = lastSeenText(payload);
        setAll('[data-link-pill]', function (pill) {
            pill.dataset.state = state;
            const label = pill.querySelector('[data-link-label]');
            if (label) softSwap(label, serverReachable ? LINK_LABELS[state] || 'Offline' : 'Server unreachable');
        });
        setAll('[data-last-seen]', function (el) {
            el.textContent = state === 'live' ? 'updated just now' : (seen ? `last seen ${seen}` : 'never seen');
        });
        setAll('[data-live-count]', function (el) {
            el.textContent = state === 'live' ? String(payload?.link?.live_count ?? 0) : '0';
        });
    }

    function paintSensors(payload) {
        (payload.sensors || []).forEach(function (s) {
            const live = s.state === 'live';

            setAll(`[data-plate="${s.key}"]`, function (cell) {
                cell.dataset.state = s.state;
                cell.dataset.level = s.level || '';
                const num = cell.querySelector('[data-plate-num]');
                const unit = cell.querySelector('[data-plate-unit]');
                const state = cell.querySelector('[data-plate-state]');
                const last = cell.querySelector('[data-plate-last]');
                if (num) setDigits(num, live ? s.display : '—');
                if (unit) { unit.textContent = s.display_unit || ''; unit.hidden = !(live && s.display_unit); }
                if (state) {
                    state.dataset.state = s.state;
                    state.dataset.level = s.level || '';
                    softSwap(state, stateText(s));
                }
                if (last) last.textContent = s.last_display ? `last ${s.last_display} ${s.unit}`.trim() : '';
            });

            setAll(`[data-chart-now="${s.key}"]`, function (box) {
                box.dataset.state = s.state;
                const val = box.querySelector('[data-chart-val]');
                const unit = box.querySelector('[data-chart-unit]');
                const state = box.querySelector('[data-chart-state]');
                if (val) val.textContent = live ? s.display : '—';
                if (unit) { unit.textContent = s.display_unit || ''; unit.hidden = !(live && s.display_unit); }
                if (state) {
                    state.dataset.state = s.state;
                    state.dataset.level = s.level || '';
                    softSwap(state, stateText(s));
                }
            });

            setAll(`[data-sensor-row="${s.key}"]`, function (row) {
                const dot = row.querySelector('[data-sensor-state]');
                const reading = row.querySelector('[data-sensor-reading]');
                const signal = row.querySelector('[data-sensor-signal]');
                if (signal) {
                    const data = payload.sensor_data || {};
                    const volts = (data.probe_voltage || {})[s.key];
                    if (s.key === 'temperature') signal.textContent = data.ds18b20_count == null ? '—' : `${data.ds18b20_count} on bus`;
                    else signal.textContent = volts == null ? '—' : `${Number(volts).toFixed(3)} V`;
                }
                if (dot) { dot.dataset.state = s.state; dot.dataset.level = s.level || ''; softSwap(dot, s.state_label); }
                if (reading) reading.textContent = live ? `${s.display} ${s.unit}`.trim() : (s.last_display ? `last ${s.last_display} ${s.unit}`.trim() : '—');
            });
        });
    }

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function paintVerdict(risk) {
        if (!risk) return;
        setAll('[data-verdict]', function (box) {
            box.dataset.level = risk.overall_level;
            const icon = box.querySelector('[data-verdict-icon]');
            const label = box.querySelector('[data-verdict-label]');
            const msg = box.querySelector('[data-verdict-msg]');
            const scoreWrap = box.querySelector('[data-verdict-score-wrap]');
            const score = box.querySelector('[data-verdict-score]');
            const tags = box.querySelector('[data-verdict-tags]');
            if (icon) icon.className = `bi ${RISK_ICONS[risk.overall_level] || 'bi-dash-lg'}`;
            if (label) softSwap(label, risk.overall_label);
            if (msg) msg.textContent = risk.message;
            if (scoreWrap) scoreWrap.hidden = risk.overall_score == null;
            if (score && risk.overall_score != null) setDigits(score, String(Math.round(risk.overall_score)));
            if (tags) {
                tags.innerHTML = (risk.triggered || []).map(function (p) {
                    return `<span class="badge badge-${escapeHtml(p.level)}">${escapeHtml(p.name)} ${escapeHtml(p.display)}</span>`;
                }).join('');
            }
        });
    }

    function paintFields(payload) {
        const data = payload.sensor_data || {};
        setAll('[data-live-field]', function (el) {
            const value = data[el.dataset.liveField];
            el.textContent = value == null || value === '' ? (el.dataset.empty || '—') : String(value);
        });
    }

    function apply(payload) {
        if (!payload) return;
        const previous = current;
        current = payload;
        paintLink(payload);
        paintSensors(payload);
        paintVerdict(payload.risk_assessment);
        paintFields(payload);
        document.dispatchEvent(new CustomEvent('shellsafe:live', { detail: { payload: payload, previous: previous } }));
    }

    /* ---------- transport ---------- */

    async function pollOnce() {
        if (!pollUrl) return;
        try {
            const res = await fetch(pollUrl, { cache: 'no-store', headers: { Accept: 'application/json' } });
            if (res.redirected || !res.ok) throw new Error(`HTTP ${res.status}`);
            const payload = await res.json();
            serverReachable = true;
            apply(payload);
        } catch (err) {
            serverReachable = false;
            paintLink(current);
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollOnce();
        pollTimer = setInterval(pollOnce, POLL_MS);
    }

    function stopPolling() {
        clearInterval(pollTimer);
        pollTimer = null;
    }

    function closeStream() {
        if (stream) { stream.close(); stream = null; }
        clearTimeout(retryTimer);
        retryTimer = null;
    }

    function connect() {
        closeStream();
        if (!streamUrl || typeof EventSource === 'undefined') { startPolling(); return; }
        stream = new EventSource(streamUrl);
        stream.onmessage = function (event) {
            stopPolling();
            serverReachable = true;
            try { apply(JSON.parse(event.data)); } catch (err) { /* ignore malformed frame */ }
        };
        stream.onerror = function () {
            closeStream();
            startPolling();
            retryTimer = setTimeout(connect, STREAM_RETRY_MS);
        };
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            closeStream();
            stopPolling();
        } else {
            pollOnce();
            connect();
        }
    });

    // Keep "last seen 12 s ago" honest between server pushes.
    setInterval(function () { if (current) paintLink(current); }, 1000);

    window.ShellSafeLive = {
        get current() { return current; },
        refresh: pollOnce,
        humanizeAge: humanizeAge,
    };

    const initialEl = document.getElementById('liveInitial');
    if (initialEl) {
        try { current = JSON.parse(initialEl.textContent); } catch (err) { current = null; }
    }
    connect();
})();

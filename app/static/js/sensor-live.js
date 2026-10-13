(function () {
    const streamUrl = document.body.dataset.sensorStreamUrl;
    const pollUrl = document.body.dataset.sensorPollUrl;
    let lastTimestamp = null;
    let pollTimer = null;
    let streamSource = null;
    let dispatchTimer = null;
    let pendingPayload = null;
    const DISPATCH_DEBOUNCE_MS = 400;
    const POLL_INTERVAL_MS = 5000;

    function isConnected(flag, value) {
        if (flag === false) return false;
        return value != null;
    }

    function emit(payload) {
        document.dispatchEvent(new CustomEvent('sensor-data-update', { detail: payload }));

        const badge = document.getElementById('liveDataBadge');
        const hasData = Boolean(payload?.sensor_data);
        const isOnline = Boolean(payload?.is_online && hasData);
        if (badge) {
            badge.textContent = !hasData || !isOnline ? 'Offline' : 'Live';
            badge.classList.toggle('text-success', isOnline);
            badge.classList.toggle('text-danger', !isOnline);
        }
    }

    function queueDispatch(payload) {
        pendingPayload = payload;
        if (dispatchTimer) return;
        dispatchTimer = setTimeout(function () {
            dispatchTimer = null;
            const next = pendingPayload;
            pendingPayload = null;
            if (next) emit(next);
        }, DISPATCH_DEBOUNCE_MS);
    }

    function dispatchUpdate(payload) {
        const hasData = Boolean(payload?.sensor_data);
        const isOnline = Boolean(payload?.is_online && hasData);
        const data = payload?.sensor_data || {};
        const stateKey = hasData
            ? [
                data.temperature, data.ph, data.turbidity, data.orp, data.ec,
                data.temperature_connected, data.ph_connected, data.turbidity_connected,
                data.orp_connected, data.ec_connected, isOnline ? 1 : 0,
                data.gps_fix ? 1 : 0,
                data.latitude, data.longitude, data.satellites,
                data.last_update,
            ].join('|')
            : 'offline-no-data';

        if (stateKey === lastTimestamp && lastTimestamp !== null) {
            return;
        }
        lastTimestamp = stateKey;
        queueDispatch(payload);
    }

    function startPolling() {
        if (!pollUrl || pollTimer) return;

        const poll = async function () {
            try {
                const response = await fetch(pollUrl, { cache: 'no-store' });
                if (!response.ok) return;
                dispatchUpdate(await response.json());
            } catch (error) {
                console.error('Sensor poll failed', error);
            }
        };

        poll();
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function connectStream() {
        if (!streamUrl || typeof EventSource === 'undefined') {
            startPolling();
            return;
        }

        streamSource = new EventSource(streamUrl);

        streamSource.onmessage = function (event) {
            stopPolling();
            try {
                dispatchUpdate(JSON.parse(event.data));
            } catch (error) {
                console.error('Invalid sensor stream payload', error);
            }
        };

        streamSource.onerror = function () {
            if (streamSource) {
                streamSource.close();
                streamSource = null;
            }
            startPolling();
        };
    }

    // Pause updates when tab is hidden to reduce freeze risk.
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            stopPolling();
            if (streamSource) {
                streamSource.close();
                streamSource = null;
            }
        } else {
            lastTimestamp = null;
            connectStream();
        }
    });

    window.ShellSafeSensor = {
        formatTemperature(value, connected) {
            if (!isConnected(connected, value)) return 'Disconnected';
            return `${Number(value).toFixed(1)}°C`;
        },
        formatPh(value, connected) {
            if (!isConnected(connected, value)) return 'Disconnected';
            return Number(value).toFixed(2);
        },
        formatTurbidity(value, connected) {
            if (!isConnected(connected, value)) return 'Disconnected';
            return `${Number(value).toFixed(1)} NTU`;
        },
        formatOrp(value, connected) {
            if (!isConnected(connected, value)) return 'Disconnected';
            return `${Number(value).toFixed(1)} mV`;
        },
        formatEc(value, connected) {
            if (!isConnected(connected, value)) return 'Disconnected';
            return `${Number(value).toFixed(1)} µS/cm`;
        },
        updateSensorTable(statuses) {
            const tbody = document.getElementById('sensorStatusBody');
            if (!tbody || !statuses?.length) return;
            tbody.innerHTML = statuses.map(function (sensor) {
                return `
                    <tr>
                        <td class="ps-3 border-bottom">${sensor.name}</td>
                        <td class="border-bottom">
                            <span class="d-flex align-items-center">
                                <span class="rounded-circle bg-${sensor.status_class} me-2" style="width: 8px; height: 8px;"></span>
                                ${sensor.status}
                            </span>
                        </td>
                        <td class="border-bottom">${sensor.reading}</td>
                    </tr>
                `;
            }).join('');
        },
        updateDevicesPage(payload) {
            const data = payload?.sensor_data;
            const statuses = payload?.sensor_statuses || [];
            const online = Boolean(payload?.is_online && data);

            const temperatureReading = document.getElementById('temperatureReading');
            const turbidityReading = document.getElementById('turbidityReading');
            const phReading = document.getElementById('phReading');
            const orpReading = document.getElementById('orpReading');
            const ecReading = document.getElementById('ecReading');
            const phTableReading = document.getElementById('phTableReading');
            const tempTableReading = document.getElementById('tempTableReading');
            const lastUpdateText = document.getElementById('lastUpdateText');
            const lastUpdateTable = document.getElementById('lastUpdateTable');
            const deviceStatusText = document.getElementById('deviceStatusText');
            const deviceStatusTable = document.getElementById('deviceStatusTable');
            const onlineDevicesText = document.getElementById('onlineDevicesText');
            const onlineDot = document.getElementById('onlineDot');
            const signalStatusText = document.getElementById('signalStatusText');
            const signalIcon = document.getElementById('signalIcon');
            const deviceStatusBadge = document.getElementById('deviceStatusBadge');
            const deviceStatusBadgeDot = document.getElementById('deviceStatusBadgeDot');
            const deviceStatusBadgeText = document.getElementById('deviceStatusBadgeText');
            const deviceDataAlert = document.getElementById('deviceDataAlert');

            const setOnlineState = (isOnline) => {
                if (deviceStatusText) deviceStatusText.textContent = isOnline ? 'Online' : 'Offline';
                if (deviceStatusTable) deviceStatusTable.textContent = isOnline ? 'Online' : 'Offline';
                if (onlineDevicesText) onlineDevicesText.textContent = isOnline ? '1 online' : '0 online';
                if (signalStatusText) {
                    signalStatusText.textContent = isOnline ? 'Connected' : 'Offline';
                    signalStatusText.classList.toggle('text-success', isOnline);
                    signalStatusText.classList.toggle('text-secondary', !isOnline);
                }
                if (signalIcon) {
                    signalIcon.classList.toggle('text-success', isOnline);
                    signalIcon.classList.toggle('text-secondary', !isOnline);
                }
                if (onlineDot) {
                    onlineDot.classList.toggle('bg-success', isOnline);
                    onlineDot.classList.toggle('bg-secondary', !isOnline);
                }
                if (deviceStatusBadge) {
                    deviceStatusBadge.classList.toggle('ss-chip-ok', isOnline);
                }
                if (deviceStatusBadgeDot) {
                    deviceStatusBadgeDot.classList.toggle('bg-success', isOnline);
                    deviceStatusBadgeDot.classList.toggle('bg-secondary', !isOnline);
                }
                if (deviceStatusBadgeText) {
                    deviceStatusBadgeText.textContent = isOnline ? 'ONLINE' : 'OFFLINE';
                }
            };

            setOnlineState(online);

            if (deviceDataAlert) {
                if (!data) {
                    deviceDataAlert.className = 'alert ss-flash alert-warning';
                    deviceDataAlert.innerHTML = 'No live sensor data found in Firebase Realtime Database. Ensure your device is sending to <code>/device_data</code>.';
                } else if (!online) {
                    deviceDataAlert.className = 'alert ss-flash alert-warning';
                    deviceDataAlert.textContent = 'Device data is stale. The device is marked as offline until fresh readings arrive.';
                } else {
                    deviceDataAlert.className = 'alert ss-flash alert-success d-none';
                    deviceDataAlert.textContent = 'Device is online and sending live data.';
                }
            }

            if (!data) {
                const disconnected = 'Disconnected';
                if (temperatureReading) temperatureReading.textContent = disconnected;
                if (turbidityReading) turbidityReading.textContent = disconnected;
                if (phReading) phReading.textContent = disconnected;
                if (orpReading) orpReading.textContent = disconnected;
                if (ecReading) ecReading.textContent = disconnected;
                if (phTableReading) phTableReading.textContent = disconnected;
                if (tempTableReading) tempTableReading.textContent = disconnected;
                if (lastUpdateText) lastUpdateText.textContent = 'No data';
                if (lastUpdateTable) lastUpdateTable.textContent = 'No data';
                this.updateSensorTable(statuses);
                this.updateGpsPanel(null);
                return;
            }

            if (temperatureReading) temperatureReading.textContent = this.formatTemperature(data.temperature, data.temperature_connected);
            if (turbidityReading) turbidityReading.textContent = this.formatTurbidity(data.turbidity, data.turbidity_connected);
            if (phReading) phReading.textContent = this.formatPh(data.ph, data.ph_connected);
            if (orpReading) orpReading.textContent = this.formatOrp(data.orp, data.orp_connected);
            if (ecReading) ecReading.textContent = this.formatEc(data.ec, data.ec_connected);
            if (phTableReading) phTableReading.textContent = this.formatPh(data.ph, data.ph_connected);
            if (tempTableReading) tempTableReading.textContent = this.formatTemperature(data.temperature, data.temperature_connected);
            if (lastUpdateText) lastUpdateText.textContent = data.last_update || (online ? 'Live' : 'No data');
            if (lastUpdateTable) lastUpdateTable.textContent = data.last_update || (online ? 'Live' : 'No data');
            this.updateSensorTable(statuses);
            this.updateGpsPanel(data);
        },
        updateGpsPanel(data) {
            const gpsFix = Boolean(data?.gps_fix && data.latitude != null && data.longitude != null);
            const fmtCoord = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(6);
            const fmtOne = (v, unit) => (v == null || Number.isNaN(Number(v))) ? '—' : `${Number(v).toFixed(1)}${unit}`;

            const gpsFixStat = document.getElementById('gpsFixStat');
            const gpsStatusChip = document.getElementById('gpsStatusChip');
            const gpsLatitude = document.getElementById('gpsLatitude');
            const gpsLongitude = document.getElementById('gpsLongitude');
            const gpsAltitude = document.getElementById('gpsAltitude');
            const gpsSpeed = document.getElementById('gpsSpeed');
            const gpsSatellites = document.getElementById('gpsSatellites');
            const gpsAccuracy = document.getElementById('gpsAccuracy');
            const gpsMapsLink = document.getElementById('gpsMapsLink');
            const gpsMapHint = document.getElementById('gpsMapHint');

            if (gpsFixStat) gpsFixStat.textContent = gpsFix ? 'Fix' : 'No fix';
            if (gpsStatusChip) {
                gpsStatusChip.classList.toggle('ss-chip-ok', gpsFix);
                gpsStatusChip.textContent = gpsFix
                    ? 'Live fix'
                    : (data?.gps_enabled ? 'Searching…' : 'GPS off');
            }
            if (gpsLatitude) gpsLatitude.textContent = gpsFix ? fmtCoord(data.latitude) : '—';
            if (gpsLongitude) gpsLongitude.textContent = gpsFix ? fmtCoord(data.longitude) : '—';
            if (gpsAltitude) gpsAltitude.textContent = gpsFix ? fmtOne(data.altitude_m, ' m') : '—';
            if (gpsSpeed) gpsSpeed.textContent = gpsFix ? fmtOne(data.speed_kmh, ' km/h') : '—';
            if (gpsSatellites) gpsSatellites.textContent = gpsFix ? String(data.satellites || 0) : '—';
            if (gpsAccuracy) gpsAccuracy.textContent = gpsFix ? fmtOne(data.gps_accuracy_m, ' m') : '—';
            if (gpsMapsLink) {
                if (gpsFix && data.maps_url) {
                    gpsMapsLink.href = data.maps_url;
                    gpsMapsLink.classList.remove('disabled');
                } else {
                    gpsMapsLink.href = '#';
                    gpsMapsLink.classList.add('disabled');
                }
            }
            if (gpsMapHint) {
                gpsMapHint.textContent = gpsFix ? 'Exact device position' : 'Waiting for GNSS fix…';
            }

            if (typeof window.ShellSafeDeviceMap?.update === 'function') {
                window.ShellSafeDeviceMap.update(
                    gpsFix ? Number(data.latitude) : null,
                    gpsFix ? Number(data.longitude) : null
                );
            }
        }
    };

    connectStream();
})();

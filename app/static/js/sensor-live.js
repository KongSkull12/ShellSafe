(function () {
    const streamUrl = document.body.dataset.sensorStreamUrl;
    const pollUrl = document.body.dataset.sensorPollUrl;
    let lastTimestamp = null;
    let pollTimer = null;

    function dispatchUpdate(payload) {
        const timestamp = payload?.sensor_data?.timestamp;
        if (timestamp === lastTimestamp && lastTimestamp !== null) {
            return;
        }
        lastTimestamp = timestamp ?? null;
        document.dispatchEvent(new CustomEvent('sensor-data-update', { detail: payload }));

        const badge = document.getElementById('liveDataBadge');
        if (badge) {
            badge.textContent = 'Updated just now';
            badge.classList.add('text-success');
        }
    }

    function startPolling() {
        if (!pollUrl || pollTimer) {
            return;
        }

        const poll = async function () {
            try {
                const response = await fetch(pollUrl, { cache: 'no-store' });
                if (!response.ok) {
                    return;
                }
                dispatchUpdate(await response.json());
            } catch (error) {
                console.error('Sensor poll failed', error);
            }
        };

        poll();
        pollTimer = setInterval(poll, 2000);
    }

    function connectStream() {
        if (!streamUrl || typeof EventSource === 'undefined') {
            startPolling();
            return;
        }

        const source = new EventSource(streamUrl);

        source.onmessage = function (event) {
            try {
                dispatchUpdate(JSON.parse(event.data));
            } catch (error) {
                console.error('Invalid sensor stream payload', error);
            }
        };

        source.onerror = function () {
            source.close();
            startPolling();
        };
    }

    window.ShellSafeSensor = {
        formatTemperature(value) {
            return value != null ? `${Number(value).toFixed(1)}°C` : '—';
        },
        formatPh(value) {
            return value != null ? Number(value).toFixed(1) : '—';
        },
        formatTurbidity(value) {
            return value != null ? `${Number(value).toFixed(1)} NTU` : '—';
        },
        updateSensorTable(statuses) {
            const tbody = document.getElementById('sensorStatusBody');
            if (!tbody || !statuses?.length) {
                return;
            }

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
            if (!data) {
                return;
            }

            const temperatureReading = document.getElementById('temperatureReading');
            const turbidityReading = document.getElementById('turbidityReading');
            const phReading = document.getElementById('phReading');
            const tempTableReading = document.getElementById('tempTableReading');
            const lastUpdateText = document.getElementById('lastUpdateText');
            const lastUpdateTable = document.getElementById('lastUpdateTable');

            if (temperatureReading) {
                temperatureReading.textContent = this.formatTemperature(data.temperature);
            }
            if (turbidityReading) {
                turbidityReading.textContent = this.formatTurbidity(data.turbidity);
            }
            if (phReading) {
                phReading.textContent = this.formatPh(data.ph);
            }
            if (tempTableReading) {
                tempTableReading.textContent = this.formatTemperature(data.temperature);
            }
            if (lastUpdateText) {
                lastUpdateText.textContent = data.last_update || 'Live';
            }
            if (lastUpdateTable) {
                lastUpdateTable.textContent = data.last_update || 'Live';
            }

            this.updateSensorTable(statuses);
        }
    };

    connectStream();
})();

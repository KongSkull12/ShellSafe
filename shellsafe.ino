#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include <time.h>

// ================== PIN DEFINITIONS ==================
#define ONE_WIRE_BUS 2
#define PH_SENSOR_PIN 34
#define TURBIDITY_PIN 35
#define DO_SENSOR_PIN 32          // only used if ENABLE_DO_SENSOR is true
#define SALINITY_SENSOR_PIN 33    // only used if ENABLE_SALINITY_SENSOR is true

// Set to true ONLY when that sensor module is physically wired.
const bool ENABLE_DO_SENSOR = false;
const bool ENABLE_SALINITY_SENSOR = false;
const bool ENABLE_TURBIDITY_SENSOR = true;  // set false if turbidity module is not installed

const char* ssid = "reaper123";
const char* password = "R05122001r";

// ================== SENSOR SETUP ==================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
DeviceAddress tempSensorAddress;
bool tempSensorFound = false;

// ================== GLOBAL VARIABLES ==================
float currentTemperature = 0.0;
float currentPH = 0.0;
float currentTurbidity = 0.0;
float currentDissolvedOxygen = 0.0;
float currentSalinity = 0.0;
float lastPhVoltage = 0.0;
float lastTurbidityVoltage = 0.0;
float lastDoVoltage = 0.0;
float lastSalinityVoltage = 0.0;
unsigned long lastSensorRead = 0;
const unsigned long sensorReadInterval = 2000;

const long gmtOffset_sec = 8 * 3600;
const int daylightOffset_sec = 0;

const char* firebaseHost = "shellsafe-ac058-default-rtdb.firebaseio.com";
const char* firebaseAuth = "aPoy4nJ99iKkDPDHz4lcMM1ajqViXgUgsOPwYvxs";
const char* firebasePath = "/device_data.json";

// ================== CALIBRATION ==================
// --- Temperature (DS18B20) ---
// Fine-tune if you compare against a reference thermometer.
float tempOffsetC = 0.0f;

// --- pH (two-point calibration) ---
// Calibrated from your live reading: 2.322 V in water -> pH ~7.0 reference
// Re-test in pH 4.00 buffer and update phVoltageAt4 if you have calibration solutions.
float phVoltageAt7 = 2.322f;
float phVoltageAt4 = 2.145f;   // ~59 mV per pH unit below pH 7 (adjust after pH 4 buffer test)

// --- Turbidity ---
// Lower voltage than clear = higher turbidity on this probe.
// clear: voltage in clean/clear water (your probe: ~0.86-0.90 V)
// turbid: voltage in very muddy water (must be LOWER than clear)
float turbidityClearVoltage = 0.880f;   // clear water baseline (match printed raw V)
float turbidityTurbidVoltage = 0.720f;  // muddy water (~1000 NTU) - update after muddy test
float turbidityMaxNtu = 1000.0f;
const float TURBIDITY_ZERO_BAND = 0.050f;  // within 50 mV of clear = 0 NTU

bool turbiditySensorConnected = false;

// --- Dissolved oxygen (only used if sensor connected) ---
float doSaturationVoltage = 2.0f;
float doSaturationMgL = 8.0f;

// --- Salinity / EC (only used if sensor connected) ---
float ecCalibrationFactor = 1.0f;

const float SENSOR_MIN_VOLTAGE = 0.05f;
// Powered turbidity probe outputs roughly 0.5-1.0 V; unpowered/floating GPIO reads ~1.2-3.3 V.
const float TURBIDITY_MIN_VALID_V = 0.05f;
const float TURBIDITY_MAX_VALID_V = 1.02f;
const int ADC_SAMPLES = 64;
const float TEMP_INVALID = -127.0;
const float EMA_ALPHA = 0.30f;  // smoothing: lower = smoother, higher = faster response

float phEma = 7.0f;
float turbidityEma = 0.0f;
bool phEmaInit = false;
bool turbidityEmaInit = false;

// ================== ADC HELPERS ==================
void initAdc() {
  analogReadResolution(12);
#if defined(ESP32)
  analogSetPinAttenuation(PH_SENSOR_PIN, ADC_11db);
  analogSetPinAttenuation(TURBIDITY_PIN, ADC_11db);
  analogSetPinAttenuation(DO_SENSOR_PIN, ADC_11db);
  analogSetPinAttenuation(SALINITY_SENSOR_PIN, ADC_11db);
#endif
}

float readAdcAverage(int pin) {
  // Discard first reading after channel changes/noise settling.
  (void)analogRead(pin);
  delayMicroseconds(300);

  long total = 0;
  for (int i = 0; i < ADC_SAMPLES; i++) {
    total += analogRead(pin);
    delayMicroseconds(200);
  }
  return total / (float)ADC_SAMPLES;
}

float rawToVoltage(float raw) {
  return raw * (3.3f / 4095.0f);
}

float applyEma(float previous, float sample, bool& initialized) {
  if (!initialized) {
    initialized = true;
    return sample;
  }
  return (EMA_ALPHA * sample) + ((1.0f - EMA_ALPHA) * previous);
}

// ================== TEMPERATURE ==================
void printAddress(DeviceAddress deviceAddress) {
  for (uint8_t i = 0; i < 8; i++) {
    if (deviceAddress[i] < 16) Serial.print("0");
    Serial.print(deviceAddress[i], HEX);
  }
}

void initTemperatureSensor() {
  sensors.begin();
  sensors.setResolution(12);
  sensors.setWaitForConversion(true);

  int count = sensors.getDeviceCount();
  Serial.printf("DS18B20 devices found on GPIO %d: %d\n", ONE_WIRE_BUS, count);

  if (count == 0) {
    Serial.println("ERROR: No DS18B20 detected.");
    tempSensorFound = false;
    return;
  }

  if (!sensors.getAddress(tempSensorAddress, 0)) {
    Serial.println("ERROR: Could not read DS18B20 address.");
    tempSensorFound = false;
    return;
  }

  tempSensorFound = true;
  Serial.print("DS18B20 address: ");
  printAddress(tempSensorAddress);
  Serial.println();
}

float readTemperatureC() {
  if (!tempSensorFound) {
    int count = sensors.getDeviceCount();
    if (count > 0 && sensors.getAddress(tempSensorAddress, 0)) {
      tempSensorFound = true;
    } else {
      return TEMP_INVALID;
    }
  }

  if (!sensors.isConnected(tempSensorAddress)) {
    tempSensorFound = false;
    return TEMP_INVALID;
  }

  sensors.requestTemperatures();
  float tempC = sensors.getTempC(tempSensorAddress);

  if (tempC == DEVICE_DISCONNECTED_C || tempC == TEMP_INVALID) {
    tempSensorFound = false;
    return TEMP_INVALID;
  }

  return tempC + tempOffsetC;
}

// ================== pH ==================
float readPH() {
  float raw = readAdcAverage(PH_SENSOR_PIN);
  lastPhVoltage = rawToVoltage(raw);

  float voltageSpan = phVoltageAt7 - phVoltageAt4;
  if (fabs(voltageSpan) < 0.01f) {
    return constrain(phEma, 0.0f, 14.0f);
  }

  // Two-point linear calibration between pH 4 and pH 7 references.
  float pH = 4.0f + (lastPhVoltage - phVoltageAt4) * (3.0f / voltageSpan);
  pH = constrain(pH, 0.0f, 14.0f);
  phEma = applyEma(phEma, pH, phEmaInit);
  return phEma;
}

// ================== TURBIDITY ==================
bool isTurbidityVoltageInRange(float voltage) {
  return voltage >= TURBIDITY_MIN_VALID_V && voltage <= TURBIDITY_MAX_VALID_V;
}

bool isTurbidityClearVoltage(float voltage) {
  return voltage >= (turbidityClearVoltage - TURBIDITY_ZERO_BAND);
}

float voltageToTurbidityNtu(float voltage) {
  float voltageSpan = turbidityClearVoltage - turbidityTurbidVoltage;
  if (voltageSpan < 0.02f) {
    return 0.0f;
  }

  if (isTurbidityClearVoltage(voltage)) {
    return 0.0f;
  }

  // Lower voltage than clear baseline -> higher turbidity.
  float ntu = ((turbidityClearVoltage - voltage) / voltageSpan) * turbidityMaxNtu;
  return constrain(ntu, 0.0f, turbidityMaxNtu);
}

float readTurbidity() {
  if (!ENABLE_TURBIDITY_SENSOR) {
    lastTurbidityVoltage = 0.0f;
    turbiditySensorConnected = false;
    turbidityEmaInit = false;
    turbidityEma = 0.0f;
    return 0.0f;
  }

  float raw = readAdcAverage(TURBIDITY_PIN);
  lastTurbidityVoltage = rawToVoltage(raw);

  // Disconnected: open pin (~0 V) or unpowered floating pin (~1.2 V+ on GPIO 35).
  if (!isTurbidityVoltageInRange(lastTurbidityVoltage)) {
    turbiditySensorConnected = false;
    turbidityEmaInit = false;
    turbidityEma = 0.0f;
    return 0.0f;
  }

  turbiditySensorConnected = true;

  float ntuInstant = voltageToTurbidityNtu(lastTurbidityVoltage);

  // Snap to 0 in clear band — do not let old high EMA linger after leaving muddy water.
  if (ntuInstant <= 0.0f) {
    turbidityEma = 0.0f;
    turbidityEmaInit = true;
    return 0.0f;
  }

  turbidityEma = applyEma(turbidityEma, ntuInstant, turbidityEmaInit);
  return turbidityEma;
}

// ================== DO / SALINITY (optional hardware) ==================
float readDissolvedOxygen() {
  float raw = readAdcAverage(DO_SENSOR_PIN);
  lastDoVoltage = rawToVoltage(raw);

  if (lastDoVoltage < SENSOR_MIN_VOLTAGE) {
    return 0.0f;
  }

  float doMgL = (lastDoVoltage / doSaturationVoltage) * doSaturationMgL;

  if (currentTemperature != TEMP_INVALID && currentTemperature > 0.0f) {
    float tempFactor = 1.0f + 0.022f * (currentTemperature - 25.0f);
    doMgL = doMgL / tempFactor;
  }

  return constrain(doMgL, 0.0f, 20.0f);
}

float readSalinity() {
  float raw = readAdcAverage(SALINITY_SENSOR_PIN);
  lastSalinityVoltage = rawToVoltage(raw);

  if (lastSalinityVoltage < SENSOR_MIN_VOLTAGE) {
    return 0.0f;
  }

  float ecMicroSiemens = (133.42f * lastSalinityVoltage * lastSalinityVoltage * lastSalinityVoltage)
                       - (255.86f * lastSalinityVoltage * lastSalinityVoltage)
                       + (857.39f * lastSalinityVoltage);
  ecMicroSiemens *= ecCalibrationFactor;
  if (ecMicroSiemens < 0.0f) ecMicroSiemens = 0.0f;

  float salinityPpt = (ecMicroSiemens / 1000.0f) * 0.64f;
  return constrain(salinityPpt, 0.0f, 50.0f);
}

// ================== READ / SEND ==================
void readAllSensors() {
  currentTemperature = readTemperatureC();
  currentPH = readPH();
  currentTurbidity = readTurbidity();

  if (ENABLE_DO_SENSOR) {
    currentDissolvedOxygen = readDissolvedOxygen();
  } else {
    currentDissolvedOxygen = 0.0f;
    lastDoVoltage = 0.0f;
  }

  if (ENABLE_SALINITY_SENSOR) {
    currentSalinity = readSalinity();
  } else {
    currentSalinity = 0.0f;
    lastSalinityVoltage = 0.0f;
  }

  Serial.println("===== Sensor Readings =====");
  if (currentTemperature == TEMP_INVALID) {
    Serial.println("Temperature: SENSOR ERROR");
  } else {
    Serial.printf("Temperature: %.2f C\n", currentTemperature);
  }
  Serial.printf("pH: %.2f (raw %.3f V, cal 7V=%.3f 4V=%.3f)\n",
                currentPH, lastPhVoltage, phVoltageAt7, phVoltageAt4);
  if (!turbiditySensorConnected) {
    Serial.printf("Turbidity: NOT CONNECTED (raw %.3f V, valid range %.2f-%.2f V)\n",
                  lastTurbidityVoltage, TURBIDITY_MIN_VALID_V, TURBIDITY_MAX_VALID_V);
  } else {
    float turbidityInstant = voltageToTurbidityNtu(lastTurbidityVoltage);
    Serial.printf("Turbidity: %.1f NTU (raw %.3f V, instant %.1f, clear=%.3f turbid=%.3f)\n",
                  currentTurbidity, lastTurbidityVoltage, turbidityInstant,
                  turbidityClearVoltage, turbidityTurbidVoltage);
  }

  if (ENABLE_DO_SENSOR && lastDoVoltage >= SENSOR_MIN_VOLTAGE) {
    Serial.printf("Dissolved Oxygen: %.2f mg/L (%.3f V)\n", currentDissolvedOxygen, lastDoVoltage);
  }
  if (ENABLE_SALINITY_SENSOR && lastSalinityVoltage >= SENSOR_MIN_VOLTAGE) {
    Serial.printf("Salinity: %.1f ppt (%.3f V)\n", currentSalinity, lastSalinityVoltage);
  }
  Serial.println("===========================");
}

void syncTime() {
  configTime(gmtOffset_sec, daylightOffset_sec, "pool.ntp.org", "time.nist.gov");

  struct tm timeinfo;
  int attempts = 0;
  while (!getLocalTime(&timeinfo) && attempts < 20) {
    delay(500);
    attempts++;
  }
}

unsigned long getCurrentTimestamp() {
  time_t now = time(nullptr);
  if (now > 100000) {
    return (unsigned long)now;
  }
  return millis() / 1000UL;
}

bool sendDataToFirebase() {
  StaticJsonDocument<384> jsonDoc;

  if (currentTemperature == TEMP_INVALID) {
    jsonDoc["temperature"] = nullptr;
    jsonDoc["temperature_error"] = true;
  } else {
    jsonDoc["temperature"] = roundf(currentTemperature * 100.0f) / 100.0f;
  }

  jsonDoc["pH"] = roundf(currentPH * 100.0f) / 100.0f;
  if (turbiditySensorConnected) {
    jsonDoc["turbidity_NTU"] = roundf(currentTurbidity * 10.0f) / 10.0f;
  } else {
    jsonDoc["turbidity_NTU"] = nullptr;
  }
  jsonDoc["turbidity_valid"] = turbiditySensorConnected;
  jsonDoc["ph_voltage"] = roundf(lastPhVoltage * 1000.0f) / 1000.0f;
  jsonDoc["turbidity_voltage"] = roundf(lastTurbidityVoltage * 1000.0f) / 1000.0f;
  jsonDoc["timestamp"] = getCurrentTimestamp();
  jsonDoc["device"] = "ShellSafe_Monitor";
  jsonDoc["has_do_sensor"] = ENABLE_DO_SENSOR;
  jsonDoc["has_salinity_sensor"] = ENABLE_SALINITY_SENSOR;

  if (ENABLE_DO_SENSOR) {
    jsonDoc["dissolved_oxygen"] = roundf(currentDissolvedOxygen * 100.0f) / 100.0f;
    jsonDoc["do_voltage"] = roundf(lastDoVoltage * 1000.0f) / 1000.0f;
  }

  if (ENABLE_SALINITY_SENSOR) {
    jsonDoc["salinity"] = roundf(currentSalinity * 10.0f) / 10.0f;
    jsonDoc["salinity_voltage"] = roundf(lastSalinityVoltage * 1000.0f) / 1000.0f;
  }

  String jsonString;
  serializeJson(jsonDoc, jsonString);

  String url = String("https://") + firebaseHost + firebasePath + "?auth=" + firebaseAuth;

  HTTPClient http;
  http.setTimeout(10000);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  int httpResponseCode = http.PUT(jsonString);
  if (httpResponseCode > 0) {
    Serial.printf("Firebase PUT %d | %s\n", httpResponseCode, jsonString.c_str());
    http.end();
    return true;
  }

  Serial.printf("Firebase send failed: %d\n", httpResponseCode);
  Serial.println(http.getString());
  http.end();
  return false;
}

void readAndSend() {
  readAllSensors();

  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(1000);
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi offline. Skipping Firebase send.");
      return;
    }
  }

  Serial.println("Sending data to Firebase...");
  sendDataToFirebase();
}

void printCalibrationGuide() {
  Serial.println("\n--- Calibration Guide ---");
  Serial.println("pH:");
  Serial.println("  1) Rinse probe, place in pH 7.00 buffer for 2 min");
  Serial.println("  2) Set phVoltageAt7 to printed voltage");
  Serial.println("  3) Repeat in pH 4.00 buffer -> set phVoltageAt4");
  Serial.println("Turbidity:");
  Serial.println("  1) In CLEAR water -> set turbidityClearVoltage to printed raw V");
  Serial.println("  2) In MUDDY water -> set turbidityTurbidVoltage (must be lower than clear)");
  Serial.println("  3) Unpowered/floating pin reads >1.02 V -> NOT CONNECTED");
  Serial.println("  4) Or set ENABLE_TURBIDITY_SENSOR false if module is removed");
  Serial.println("Temperature:");
  Serial.println("  Adjust tempOffsetC if needed against a reference thermometer");
  Serial.println("-------------------------\n");
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\nShellSafe Algal Bloom System");
  Serial.println("============================");

  initAdc();
  initTemperatureSensor();
  printCalibrationGuide();

  WiFi.begin(ssid, password);
  int wifiAttempts = 0;
  while (WiFi.status() != WL_CONNECTED && wifiAttempts < 30) {
    delay(500);
    Serial.print(".");
    wifiAttempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nWiFi connected. IP: ");
    Serial.println(WiFi.localIP());
    syncTime();
  } else {
    Serial.println("\nWiFi connection failed.");
  }

  readAndSend();
  Serial.println("Streaming sensor data every 2 seconds.\n");
}

void loop() {
  unsigned long now = millis();
  if (now - lastSensorRead >= sensorReadInterval) {
    lastSensorRead = now;
    readAndSend();
  }
}

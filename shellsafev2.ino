#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include "DFRobot_EC.h"
#include <EEPROM.h>
#include <Preferences.h>
#include <math.h>
#include "secrets.h"   // WiFi, Firebase token, alert phone; copy secrets.h.example

// ============================================================
// SHELLSAFE
// ESP32-WROVER-E + LilyGO T-Call A7670 V1.0
// Built-in A7670: GSM / SMS + GNSS / GPS
// WiFi: Firebase RTDB (A7670 mobile data as backup)
// Sensors: DS18B20, pH, Turbidity, ORP, EC
// ============================================================

// ============================================================
// A7670 / TINY GSM
// ============================================================
#define TINY_GSM_MODEM_A7670
#define TINY_GSM_RX_BUFFER 1024
#include <TinyGsmClient.h>

#define BOARD_PWRKEY_PIN       4
#define MODEM_RX_PIN           25
#define MODEM_TX_PIN           26
#define MODEM_RESET_PIN        27
#define MODEM_DTR_PIN          14
#define MODEM_RING_PIN         13
#define MODEM_RESET_LEVEL      LOW
#define MODEM_BAUDRATE         115200

HardwareSerial SerialAT(1);
TinyGsm modem(SerialAT);

// ============================================================
// SENSOR PINS
// ============================================================
#define ONE_WIRE_BUS           2
#define PH_SENSOR_PIN          35
#define TURBIDITY_PIN          34
#define ORP_SENSOR_PIN         39
#define EC_SENSOR_PIN          32

// ============================================================
// ALERT THRESHOLDS
// ============================================================
const float ALERT_PH_MIN = 6.5f;
const float ALERT_PH_MAX = 8.5f;
const float ALERT_TURBIDITY_MAX = 50.0f;
const float ALERT_TEMP_MAX = 35.0f;
const float ALERT_ORP_MIN = 200.0f;
const float ALERT_EC_MAX = 2000.0f;

// ============================================================
// SMS CONFIG
// ============================================================
const char* senderSmsc = "";
const int MAX_ALERT_PHONES = 4;
String alertPhoneNumbers[MAX_ALERT_PHONES];
int alertPhoneCount = 0;
const char* firebaseSmsConfigPath = "/sms_config.json";
const char* firebaseSmsTestPath = "/sms_test.json";
unsigned long lastSmsPoll = 0;
const unsigned long smsPollInterval = 15000UL;
unsigned long lastSmsTime = 0;
const unsigned long smsCooldown = 60000UL;

// ============================================================
// WIFI / FIREBASE
// ============================================================
const char* firebaseHost = "shellsafe-ac058-default-rtdb.firebaseio.com";
const char* firebasePath = "/device_data.json";

// ============================================================
// CELLULAR DATA (A7670 LTE backup)
// WiFi is used whenever it is up. When WiFi drops, readings go to Firebase
// over the A7670's mobile data instead, at a slower rate to save load.
// APN: Smart/TNT "internet", Globe/TM "internet.globe.com.ph",
// DITO "internet.dito.ph".
// ============================================================
const char* cellularApn = "internet";
const unsigned long cellularPublishInterval = 30000UL;
const unsigned long cellularAttachRetryMs = 60000UL;
bool cellularDataReady = false;
unsigned long lastCellularAttach = 0;
unsigned long lastCellularPublish = 0;

// ============================================================
// READING LOG
// One compact reading per minute is appended under /readings. This is the
// stored history used by the Data history page and for training the
// bloom prediction models (see ml/README.md).
// ============================================================
const char* firebaseHistoryPath = "/readings.json";
const unsigned long historyInterval = 60000UL;
unsigned long lastHistoryPush = 0;

// ============================================================
// BATTERY
// The A7670 is powered straight from the LiPo, so AT+CBC reports the
// battery voltage with no extra wiring. On USB with no battery it reads the
// charger output (about 4.2 V, shown as 100%). If you wire a divider from
// the battery to a free ADC1 pin (GPIO33 or GPIO36), set the pin here and
// that reading is used instead.
// ============================================================
#define BATTERY_ADC_PIN        -1
const float BATTERY_DIVIDER_RATIO = 2.0f;   // 100k / 100k divider
const unsigned long batteryReadInterval = 30000UL;
unsigned long lastBatteryRead = 0;
float batteryVoltage = 0.0f;
int batteryPercent = -1;
const char* batterySource = "none";

// ============================================================
// PUBLISH STATS (shown on the Device page)
// ============================================================
unsigned long publishOk = 0;
unsigned long publishFail = 0;
unsigned long lastPublishDurationMs = 0;
const char* lastTransport = "none";

// ============================================================
// SENSOR OBJECTS
// ============================================================
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
DeviceAddress tempSensorAddress;
bool tempSensorFound = false;
int oneWireDeviceCount = 0;
const int TEMP_DROP_READS = 3;
int tempBadReads = 0;
DFRobot_EC ec;

// ============================================================
// SENSOR VALUES
// ============================================================
float currentTemperature = 0.0f;
float currentPH = 0.0f;
float currentTurbidity = 0.0f;
float currentORP = 0.0f;
float currentEC = 0.0f;

bool phConnected = false;
bool turbidityConnected = false;
bool orpConnected = false;
bool ecConnected = false;
bool ecDry = false;   // EC board present but probe out of the water

// ============================================================
// SENSOR VOLTAGES
// ============================================================
float lastPhVoltage = 0.0f;
float lastTurbidityVoltage = 0.0f;
float lastOrpVoltage = 0.0f;
float lastEcVoltage = 0.0f;

// ============================================================
// TIMERS
// ============================================================
unsigned long lastSensorRead = 0;
const unsigned long sensorReadInterval = 5000UL;
unsigned long lastGpsRead = 0;
const unsigned long gpsReadInterval = 5000UL;
unsigned long lastGsmCheck = 0;
const unsigned long gsmCheckInterval = 30000UL;
unsigned long lastWiFiReconnect = 0;

// ============================================================
// A7670 STATUS
// ============================================================
bool modemInitialized = false;
bool simReady = false;
bool gsmNetworkRegistered = false;
int gsmSignalQuality = 0;
String modemName = "";
String modemInfo = "";

// ============================================================
// GPS / GNSS
// ============================================================
bool gpsSupported = true;
bool gpsEnabled = false;
bool gpsFix = false;
unsigned long lastGpsFixMs = 0;
bool testPending = false;
unsigned long testStartedMs = 0;
const unsigned long TEST_GPS_WAIT_MS = 120000UL;
String buildAlertMessage(bool test);
void readGPS();
String createGPSMessage();
String alertLines();
String lastSmsError;
const int SMS_SERVICE_PREFERENCE = 2;
void smsDiagnostics();
void handleSerialCommands();
bool deliverSMS(const String& phone, const String& message);
void ensureFallbackPhone();
void printProbeSignals();
void handleCalibrationCommand(String cmd);

float gpsLatitude = 0.0f;
float gpsLongitude = 0.0f;
float gpsAltitudeM = 0.0f;
float gpsSpeedKmh = 0.0f;
float gpsAccuracyM = 0.0f;
int gpsSatellites = 0;
String gpsUtcIso = "";
int gpsYear = 0;
int gpsMonth = 0;
int gpsDay = 0;
int gpsHour = 0;
int gpsMinute = 0;
int gpsSecond = 0;

// ============================================================
// PROBE DETECTION
// The A7670 shares this board, and its RF bursts put tens of millivolts
// of noise on the ESP32 ADC. A probe is therefore judged on the median of
// several averages with a tolerant spread limit, and with hysteresis: it
// connects after PROBE_CONNECT_READS good checks and only drops after
// PROBE_DROP_READS bad ones, so a single noisy sample no longer resets it.
// ============================================================
const float PROBE_MAX_SPREAD_V = 0.12f;   // floating pins wander far more
const float ADC_SATURATED_V = 3.20f;      // ESP32 ADC tops out near 3.3 V
const int PROBE_CONNECT_READS = 2;
const int PROBE_DROP_READS = 3;

struct ProbeState
{
    const char* name;
    int pin;
    float minV;          // below this the pin is treated as having no sensor
    int goodCount;
    int badCount;
    bool connected;
    float voltage;       // median of the last check
    float spread;        // max - min across the last check
    const char* reason;
};

ProbeState phProbe        = {"pH",        PH_SENSOR_PIN,  0.30f, 0, 0, false, 0.0f, 0.0f, "not read yet"};
ProbeState turbidityProbe = {"Turbidity", TURBIDITY_PIN,  0.20f, 0, 0, false, 0.0f, 0.0f, "not read yet"};
ProbeState orpProbe       = {"ORP",       ORP_SENSOR_PIN, 0.10f, 0, 0, false, 0.0f, 0.0f, "not read yet"};
ProbeState ecProbe        = {"EC",        EC_SENSOR_PIN,  0.05f, 0, 0, false, 0.0f, 0.0f, "not read yet"};

// ============================================================
// CALIBRATION
// Defaults below are placeholders. Each probe is calibrated on the
// device with reference solutions using serial commands (type CAL HELP),
// and the result is saved in flash so it survives restarts. Readings
// from an uncalibrated probe are still published, but flagged, and never
// trigger SMS alerts.
// ============================================================
Preferences calPrefs;

float tempOffsetC = 0.0f;

// pH: two-point line through (phVoltageAt7, 7.0) and (phVoltageAt2, phAt2).
float phVoltageAt7 = 2.322f;
float phVoltageAt2 = 2.145f;
float phAt2 = 4.0f;
bool phCal7 = false;
bool phCal2 = false;

// Turbidity: clean water sets 0 NTU; voltage falls as water gets cloudier.
// Without a second standard the slope assumes a 12% drop = 1000 NTU,
// the same ratio the original constants used.
float turbidityClearVoltage = 0.966f;
float turbidityVoltsPerNtu = 0.116f / 1000.0f;
float turbidityMaxNtu = 1000.0f;
const float TURBIDITY_ZERO_BAND = 0.030f;
bool turbidityCalibrated = false;

// ORP: pin millivolts plus an offset set from a reference solution.
float orpCalibrationOffset = 0.0f;
bool orpCalibrated = false;

// EC: dry-probe zero voltage is subtracted first, then a multiplier set
// from a conductivity standard is applied.
float ecZeroVoltage = 0.0f;
float ecCalibrationK = 1.0f;
bool ecCalibrated = false;

bool phCalibrated() { return phCal7 && phCal2; }

// ============================================================
// ADC
// ============================================================
void initAdc()
{
    analogReadResolution(12);
    analogSetPinAttenuation(PH_SENSOR_PIN, ADC_11db);
    analogSetPinAttenuation(TURBIDITY_PIN, ADC_11db);
    analogSetPinAttenuation(ORP_SENSOR_PIN, ADC_11db);
    analogSetPinAttenuation(EC_SENSOR_PIN, ADC_11db);
#if BATTERY_ADC_PIN >= 0
    analogSetPinAttenuation(BATTERY_ADC_PIN, ADC_11db);
#endif
}

float readAdcAverage(int pin)
{
    (void)analogRead(pin);
    delayMicroseconds(300);
    uint32_t total = 0;
    const int samples = 64;
    for (int i = 0; i < samples; i++)
    {
        total += analogRead(pin);
        delayMicroseconds(200);
    }
    return (float)total / samples;
}

float rawToVoltage(float raw)
{
    return raw * (3.3f / 4095.0f);
}

// Returns true when this check's reading is usable; p.connected carries
// the debounced state.
bool updateProbe(ProbeState& p)
{
    float v[5];
    for (int i = 0; i < 5; i++)
    {
        v[i] = rawToVoltage(readAdcAverage(p.pin));
        delay(15);
    }
    for (int i = 1; i < 5; i++)
    {
        float key = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; }
        v[j + 1] = key;
    }
    p.voltage = v[2];
    p.spread = v[4] - v[0];

    bool good = false;
    if (p.voltage < p.minV)
        p.reason = "no signal - pin near 0 V (check VCC/GND/signal wires)";
    else if (p.voltage >= ADC_SATURATED_V)
        p.reason = "saturated >3.2 V - sensor output too high, add a voltage divider";
    else if (p.spread > PROBE_MAX_SPREAD_V)
        p.reason = "unstable - floating pin or loose wire";
    else
    {
        p.reason = "ok";
        good = true;
    }

    if (good)
    {
        p.badCount = 0;
        if (p.goodCount < PROBE_CONNECT_READS) p.goodCount++;
        if (p.goodCount >= PROBE_CONNECT_READS) p.connected = true;
    }
    else
    {
        p.goodCount = 0;
        if (p.badCount < PROBE_DROP_READS) p.badCount++;
        if (p.badCount >= PROBE_DROP_READS) p.connected = false;
    }
    return good;
}

// ============================================================
// A7670 POWER / RESET
// ============================================================
void modemPulsePwrKey()
{
    pinMode(BOARD_PWRKEY_PIN, OUTPUT);
    digitalWrite(BOARD_PWRKEY_PIN, LOW);
    delay(100);
    digitalWrite(BOARD_PWRKEY_PIN, HIGH);
    delay(1000);
    digitalWrite(BOARD_PWRKEY_PIN, LOW);
}

void modemHardwareReset()
{
    pinMode(MODEM_RESET_PIN, OUTPUT);
    digitalWrite(MODEM_RESET_PIN, !MODEM_RESET_LEVEL);
    delay(100);
    digitalWrite(MODEM_RESET_PIN, MODEM_RESET_LEVEL);
    delay(2600);
    digitalWrite(MODEM_RESET_PIN, !MODEM_RESET_LEVEL);
}

bool modemWaitForAT(uint8_t maxRounds = 2)
{
    for (uint8_t round = 0; round < maxRounds; round++)
    {
        int retry = 0;
        while (retry++ < 25)
        {
            if (modem.testAT(1000))
            {
                return true;
            }
            Serial.print(".");
            if (retry % 12 == 0)
            {
                Serial.println();
                Serial.println("Re-pulsing A7670 PWRKEY...");
                modemPulsePwrKey();
            }
        }
        Serial.println();
        Serial.println("A7670 AT timeout.");
        Serial.println("Resetting modem...");
        modemHardwareReset();
        delay(1000);
        modemPulsePwrKey();
        delay(4000);
    }
    return false;
}

bool checkGsmNetwork()
{
    if (!modemInitialized)
    {
        gsmNetworkRegistered = false;
        return false;
    }
    gsmNetworkRegistered = modem.isNetworkConnected();
    if (gsmNetworkRegistered)
    {
        gsmSignalQuality = modem.getSignalQuality();
        return true;
    }
    return false;
}

// ============================================================
// INIT A7670
// ============================================================
void initA7670()
{
    Serial.println();
    Serial.println("========================================");
    Serial.println("INITIALIZING BUILT-IN A7670");
    Serial.println("GSM/SMS + GNSS/GPS");
    Serial.println("T-Call A7670 V1.0");
    Serial.println("========================================");

    SerialAT.begin(MODEM_BAUDRATE, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);
    delay(200);

    pinMode(MODEM_DTR_PIN, OUTPUT);
    digitalWrite(MODEM_DTR_PIN, LOW);
    pinMode(MODEM_RING_PIN, INPUT_PULLUP);

    modemHardwareReset();
    delay(500);
    modemPulsePwrKey();
    Serial.println("Waiting for A7670 boot...");
    delay(5000);

    if (!modemWaitForAT())
    {
        Serial.println();
        Serial.println("FATAL: A7670 NOT RESPONDING");
        Serial.println("Check modem power and V1.0 pin mapping.");
        modemInitialized = false;
        return;
    }

    Serial.println();
    Serial.println("A7670 AT communication OK.");

    if (!modem.init())
    {
        Serial.println("WARNING: modem.init() returned false.");
        Serial.println("Continuing because AT communication works.");
    }
    modemInitialized = true;

    modemName = modem.getModemName();
    modemInfo = modem.getModemInfo();
    Serial.println();
    Serial.println("---------- MODEM ----------");
    Serial.print("Name: ");
    Serial.println(modemName);
    Serial.print("Info: ");
    Serial.println(modemInfo);

    modem.sendAT("+SIMCOMATI");
    String simcomInfo = "";
    int simcomResult = modem.waitResponse(5000L, simcomInfo);
    if (simcomResult == 1)
    {
        Serial.println("SIMCOMATI:");
        Serial.println(simcomInfo);
    }

    String modelUpper = modemName + " " + modemInfo;
    modelUpper.toUpperCase();
    if (modelUpper.indexOf("A7670G-LLSE") >= 0 ||
        modelUpper.indexOf("A7670G-LABE") >= 0 ||
        modelUpper.indexOf("A7670E-LASE") >= 0)
    {
        gpsSupported = false;
        Serial.println();
        Serial.println("WARNING:");
        Serial.println("Detected modem variant may not");
        Serial.println("contain built-in GNSS.");
    }
    else
    {
        gpsSupported = true;
    }

    Serial.println();
    Serial.println("Checking SIM card...");
    SimStatus simStatus = modem.getSimStatus();
    if (simStatus == SIM_READY)
    {
        simReady = true;
        Serial.println("SIM CARD: READY");
    }
    else
    {
        simReady = false;
        Serial.print("SIM CARD NOT READY. Status=");
        Serial.println((int)simStatus);
    }

    if (simReady)
    {
        Serial.println();
        Serial.println("Waiting for cellular network...");
        if (modem.waitForNetwork(60000L))
        {
            gsmNetworkRegistered = true;
            Serial.println("CELLULAR NETWORK: REGISTERED");
            gsmSignalQuality = modem.getSignalQuality();
            Serial.print("Signal quality: ");
            Serial.println(gsmSignalQuality);
        }
        else
        {
            gsmNetworkRegistered = false;
            Serial.println("CELLULAR NETWORK: NOT REGISTERED");
        }
    }

    Serial.println("---------------------------");
    Serial.println("A7670 initialization complete.");
}

// ============================================================
// INIT GNSS
// ============================================================
void initGPS()
{
    Serial.println();
    Serial.println("========================================");
    Serial.println("INITIALIZING A7670 GNSS");
    Serial.println("========================================");

    if (!modemInitialized)
    {
        Serial.println("GNSS ERROR: A7670 unavailable.");
        gpsEnabled = false;
        return;
    }
    if (!gpsSupported)
    {
        Serial.println("GNSS ERROR:");
        Serial.println("Installed A7670 variant may not support GNSS.");
        gpsEnabled = false;
        return;
    }

    modem.sendAT("+CGNSSPWR=0");
    modem.waitResponse(5000L);
    delay(1000);

    Serial.println("Powering GNSS ON...");
    modem.sendAT("+CGNSSPWR=1");
    int result = modem.waitResponse(10000L);

    if (result != 1)
    {
        Serial.println("CGNSSPWR command failed.");
        Serial.println("Trying TinyGSM enableGPS()...");
        if (!modem.enableGPS())
        {
            Serial.println("GNSS ENABLE FAILED.");
            gpsEnabled = false;
            return;
        }
    }
    delay(2000);

    modem.sendAT("+CGNSSMODE=1");
    modem.waitResponse(5000L);

    gpsEnabled = true;
    gpsFix = false;
    Serial.println("GNSS ENABLED.");
    Serial.println("Connect the GNSS antenna.");
    Serial.println("Place the device outdoors.");
    Serial.println("Cold start can take several minutes.");
    Serial.println("========================================");
}

// ============================================================
// READ GPS
// ============================================================
void readGPS()
{
    if (!modemInitialized || !gpsEnabled || !gpsSupported)
    {
        gpsFix = false;
        return;
    }

    uint8_t fixMode = 0;
    float latitude = 0.0f;
    float longitude = 0.0f;
    float speed = 0.0f;
    float altitude = 0.0f;
    int visibleSatellites = 0;
    int usedSatellites = 0;
    float accuracy = 0.0f;
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;

    bool success = modem.getGPS(
        &fixMode, &latitude, &longitude, &speed, &altitude,
        &visibleSatellites, &usedSatellites, &accuracy,
        &year, &month, &day, &hour, &minute, &second
    );

    if (success && fabs(latitude) > 0.00001f && fabs(longitude) > 0.00001f)
    {
        gpsFix = true;
        lastGpsFixMs = millis();

        if (year >= 2020 && month >= 1 && month <= 12 && day >= 1 && day <= 31)
        {
            char utcBuf[32];
            snprintf(utcBuf, sizeof(utcBuf),
                     "%04d-%02d-%02dT%02d:%02d:%02dZ",
                     year, month, day, hour, minute, second);
            gpsUtcIso = utcBuf;
            gpsYear = year;
            gpsMonth = month;
            gpsDay = day;
            gpsHour = hour;
            gpsMinute = minute;
            gpsSecond = second;
        }

        gpsLatitude = latitude;
        gpsLongitude = longitude;
        gpsAltitudeM = altitude;
        gpsSpeedKmh = speed;
        gpsAccuracyM = accuracy;
        gpsSatellites = usedSatellites > 0 ? usedSatellites : visibleSatellites;

        Serial.println();
        Serial.println("========== GPS FIX ==========");
        Serial.print("Latitude   : ");
        Serial.println(gpsLatitude, 6);
        Serial.print("Longitude  : ");
        Serial.println(gpsLongitude, 6);
        Serial.print("Altitude   : ");
        Serial.print(gpsAltitudeM, 1);
        Serial.println(" m");
        Serial.print("Speed      : ");
        Serial.print(gpsSpeedKmh, 1);
        Serial.println(" km/h");
        Serial.print("Satellites : ");
        Serial.println(gpsSatellites);
        Serial.print("Accuracy   : ");
        Serial.print(gpsAccuracyM, 1);
        Serial.println(" (library dilution metric; not meters)");
        Serial.printf("UTC         : %04d-%02d-%02d %02d:%02d:%02d\n",
                      year, month, day, hour, minute, second);
        Serial.print("Google Maps : https://maps.google.com/?q=");
        Serial.print(gpsLatitude, 6);
        Serial.print(",");
        Serial.println(gpsLongitude, 6);
        Serial.println("=============================");
    }
    else
    {
        gpsFix = false;
        Serial.println();
        Serial.println("GPS: SEARCHING FOR SATELLITES...");

        modem.sendAT("+CGNSSINFO");
        String gnssResponse = "";
        modem.waitResponse(3000L, gnssResponse);
        if (gnssResponse.length() > 0)
        {
            Serial.print("GNSS response: ");
            Serial.println(gnssResponse);
        }
    }
}

// ============================================================
// SMS
// ============================================================
bool sendSMS(String message)
{
    if (lastSmsTime && millis() - lastSmsTime < smsCooldown) return false;
    lastSmsTime = millis();

    ensureFallbackPhone();
    bool all = true;
    for (int i = 0; i < alertPhoneCount; ++i)
    {
        if (!deliverSMS(alertPhoneNumbers[i], message)) all = false;
        if (i + 1 < alertPhoneCount) delay(2200);
    }
    return all && alertPhoneCount > 0;
}

String firebaseUrl(const char* path)
{
    return String("https://") + firebaseHost + path + "?auth=" + firebaseAuth;
}

bool firebaseHttpGet(const char* path, String& body)
{
    if (WiFi.status() != WL_CONNECTED) return false;
    HTTPClient http;
    http.setTimeout(10000);
    http.begin(firebaseUrl(path));
    int code = http.GET();
    if (code > 0) body = http.getString();
    http.end();
    return code >= 200 && code < 300;
}

bool firebaseHttpPut(const char* path, const String& body)
{
    if (WiFi.status() != WL_CONNECTED) return false;
    HTTPClient http;
    http.setTimeout(10000);
    http.begin(firebaseUrl(path));
    http.addHeader("Content-Type", "application/json");
    int code = http.PUT(body);
    http.end();
    return code >= 200 && code < 300;
}

void ensureFallbackPhone()
{
    if (alertPhoneCount > 0) return;
    alertPhoneNumbers[0] = String(alertPhoneNumber);
    alertPhoneCount = 1;
}

void loadSmsPhones(const String& body)
{
    StaticJsonDocument<768> doc;
    if (deserializeJson(doc, body)) return;
    JsonArray phones = doc["phones"].as<JsonArray>();
    if (phones.isNull()) return;
    alertPhoneCount = 0;
    for (JsonVariant value : phones)
    {
        if (alertPhoneCount >= MAX_ALERT_PHONES) break;
        const char* phone = value.as<const char*>();
        if (phone == nullptr || phone[0] == '\0') continue;
        alertPhoneNumbers[alertPhoneCount++] = String(phone);
    }
    Serial.print("SMS recipients from /sms_config: ");
    Serial.println(alertPhoneCount);
}

String normalizeSmsNumber(String phone)
{
    phone.trim();
    phone.replace(" ", "");
    phone.replace("-", "");
    if (phone.startsWith("09") && phone.length() == 11)
        phone = "+63" + phone.substring(1);
    if (phone.startsWith("63") && phone.length() == 12)
        phone = "+" + phone;
    if (!phone.startsWith("+") || phone.length() < 9 || phone.length() > 16)
        return "";
    for (unsigned int i = 1; i < phone.length(); ++i)
        if (!isDigit(phone[i])) return "";
    return phone;
}

String modemCommand(const String& command, uint32_t timeoutMs)
{
    while (SerialAT.available()) SerialAT.read();
    SerialAT.println(command);
    String response;
    unsigned long start = millis();
    while (millis() - start < timeoutMs)
    {
        while (SerialAT.available()) response += (char)SerialAT.read();
        if (response.indexOf("\r\nOK") >= 0 ||
            response.indexOf("\nOK") >= 0 ||
            response.indexOf("ERROR") >= 0)
            break;
        delay(10);
    }
    return response;
}

bool modemWaitToken(const char* token, uint32_t timeoutMs, String& response)
{
    unsigned long start = millis();
    while (millis() - start < timeoutMs)
    {
        while (SerialAT.available()) response += (char)SerialAT.read();
        if (response.indexOf(token) >= 0) return true;
        if (response.indexOf("ERROR") >= 0) return false;
        delay(10);
    }
    return false;
}

void configureSmsCenter()
{
    Serial.println(modemCommand("AT+CSCA?", 3000));
    if (strlen(senderSmsc))
    {
        Serial.println(modemCommand(
            String("AT+CSCA=\"") + senderSmsc + "\",145", 3000));
    }
}

void smsDiagnostics()
{
    const char* queries[] = {
        "AT+CPIN?", "AT+CSQ", "AT+COPS?", "AT+CREG?",
        "AT+CGREG?", "AT+CEREG?", "AT+CGSMS?", "AT+CSMS?", "AT+CSCA?"
    };
    Serial.println("--- SMS DIAGNOSTICS ---");
    for (const char* query : queries)
    {
        Serial.println(query);
        Serial.println(modemCommand(query, 3000));
    }
}

void handleSerialCommands()
{
    static String line;
    while (Serial.available())
    {
        char ch = (char)Serial.read();
        if (ch == '\r') continue;
        if (ch == '\n')
        {
            line.trim();
            if (line == "DIAG") smsDiagnostics();
            else if (line == "PROBES") printProbeSignals();
            else if (line.startsWith("CAL") || line.startsWith("cal")) handleCalibrationCommand(line.substring(3));
            else if (line.startsWith("AT") && modemInitialized) Serial.println(modemCommand(line, 10000));
            else if (line == "PLAIN")
            {
                ensureFallbackPhone();
                sendSMS("ShellSafe TEST ONLY: short SMS diagnostic.");
            }
            line = "";
        }
        else if (line.length() < 48) line += ch;
    }
}

String smsHexByte(uint8_t value)
{
    const char* hex = "0123456789ABCDEF";
    String out;
    out += hex[value >> 4];
    out += hex[value & 15];
    return out;
}

String gsm7Safe(const String& input)
{
    String out;
    for (unsigned int i = 0; i < input.length(); ++i)
    {
        uint8_t c = (uint8_t)input[i];
        if (c == '\r') continue;
        if (c == '\n' || (c >= 32 && c <= 126 &&
            c != '@' && c != '$' && c != '[' && c != ']' &&
            c != '{' && c != '}' && c != '\\' && c != '^' &&
            c != '~' && c != '|' && c != '`'))
            out += (char)c;
        else
            out += '?';
    }
    return out;
}

String makeSmsPdu(const String& dial, const String& text)
{
    String digits = dial.substring(1);
    String pdu = "000100" + smsHexByte(digits.length()) + "91";
    if (digits.length() % 2) digits += 'F';
    for (unsigned int i = 0; i < digits.length(); i += 2)
    {
        pdu += digits[i + 1];
        pdu += digits[i];
    }
    pdu += "0000" + smsHexByte((uint8_t)text.length());
    uint32_t bits = 0;
    int count = 0;
    for (unsigned int i = 0; i < text.length(); ++i)
    {
        uint8_t septet = (text[i] == '\n') ? 10 : (uint8_t)text[i];
        bits |= (uint32_t)(septet & 0x7F) << count;
        count += 7;
        while (count >= 8)
        {
            pdu += smsHexByte((uint8_t)(bits & 0xFF));
            bits >>= 8;
            count -= 8;
        }
    }
    if (count > 0) pdu += smsHexByte((uint8_t)(bits & 0xFF));
    return pdu;
}

String compactSmsMessage(const String& input)
{
    String safe = gsm7Safe(input);
    if (safe.length() <= 160) return safe;
    int mapAt = safe.indexOf("https://maps.google.com/?q=");
    if (mapAt < 0)
    {
        Serial.println("SMS too long without map URL; truncating to 160 characters.");
        return safe.substring(0, 160);
    }
    String url = safe.substring(mapAt);
    int newline = url.indexOf('\n');
    if (newline >= 0) url = url.substring(0, newline);
    String header = safe.substring(0, mapAt);
    const String separator = "\nGPS: ";
    int budget = 160 - (int)separator.length() - (int)url.length();
    if (budget < 0) return "";
    if ((int)header.length() > budget)
    {
        header = header.substring(0, budget);
        int lastLine = header.lastIndexOf('\n');
        if (lastLine > 12) header = header.substring(0, lastLine);
    }
    header.trim();
    return header + separator + url;
}

bool deliverSMS(const String& phone, const String& message)
{
    lastSmsError = "";
    if (!modemInitialized) { lastSmsError = "Modem offline"; return false; }

    simReady = modem.getSimStatus() == SIM_READY;
    if (!simReady || !modem.isNetworkConnected())
    {
        lastSmsError = "SIM not ready or network not registered";
        return false;
    }

    String dial = normalizeSmsNumber(phone);
    if (!dial.length()) { lastSmsError = "Invalid SMS recipient"; return false; }

    String payload = compactSmsMessage(message);
    if (!payload.length())
    {
        lastSmsError = "SMS payload is empty after compacting";
        return false;
    }

    bool resumeGnss = gpsEnabled;
    if (resumeGnss)
    {
        modemCommand("AT+CGNSSPWR=0", 3000);
        delay(400);
    }

    configureSmsCenter();
    modemCommand("AT+CMGF=1", 5000);
    modemCommand("AT+CSCS=\"GSM\"", 5000);
    modemCommand("AT+CSMP=17,167,0,0", 5000);

    auto sendTextSms = [&](const String& target) -> bool {
        while (SerialAT.available()) SerialAT.read();
        SerialAT.print("AT+CMGS=\"");
        SerialAT.print(target);
        SerialAT.println("\"");

        String prompt;
        if (!modemWaitToken(">", 15000, prompt))
        {
            SerialAT.write(27);
            lastSmsError = "No CMGS prompt: " + prompt;
            return false;
        }

        SerialAT.print(payload);
        SerialAT.write(26);
        SerialAT.flush();

        String response;
        unsigned long started = millis();
        bool ok = false;
        while (millis() - started < 90000UL)
        {
            while (SerialAT.available()) response += (char)SerialAT.read();
            if (response.indexOf("ERROR") >= 0) break;
            if (response.indexOf("+CMGS:") >= 0 &&
                response.indexOf("\r\nOK\r\n") >= 0) { ok = true; break; }
            delay(10);
        }
        Serial.println(response);
        if (!ok)
        {
            lastSmsError = response.length() ? response : "Submission timeout; acceptance unknown";
            lastSmsError.trim();
            return false;
        }
        return true;
    };

    Serial.println("Submitting single TEXT SMS to " + dial);
    Serial.println(payload);

    bool sent = sendTextSms(dial);
    if (!sent && dial.startsWith("+"))
    {
        String noPlus = dial.substring(1);
        Serial.println("Retrying SMS using no-plus format: " + noPlus);
        sent = sendTextSms(noPlus);
    }

    if (resumeGnss)
    {
        modemCommand("AT+CGNSSPWR=1", 5000);
        delay(300);
    }

    if (sent)
    {
        Serial.println("SMS accepted by network; handset delivery NOT confirmed.");
        return true;
    }

    Serial.println("SMS NOT confirmed submitted. Do not blindly retry.");
    return false;
}

void reportSmsTest(const char* status, const char* detail, int recipientCount)
{
    StaticJsonDocument<2048> doc;
    doc["requested"] = false;
    doc["status"] = status;
    doc["detail"] = detail;
    doc["recipient_count"] = recipientCount;
    doc["modem_error"] = lastSmsError;
    doc["delivery_confirmed"] = false;
    doc["completed_at"] = gpsUtcIso.length() ? gpsUtcIso : String(millis() / 1000UL);
    String body;
    serializeJson(doc, body);
    if (firebaseHttpPut(firebaseSmsTestPath, body))
    {
        Serial.print("SMS test status: ");
        Serial.println(status);
    }
    else
    {
        Serial.println("Failed to write /sms_test status.");
    }
}

void pollSmsTest()
{
    if (WiFi.status() != WL_CONNECTED) return;

    String body;
    if (firebaseHttpGet(firebaseSmsConfigPath, body)) loadSmsPhones(body);
    ensureFallbackPhone();

    if (!testPending)
    {
        if (!firebaseHttpGet(firebaseSmsTestPath, body)) return;
        StaticJsonDocument<768> doc;
        if (deserializeJson(doc, body) || !doc["requested"].as<bool>()) return;

        reportSmsTest("waiting_gps", "Waiting up to 120 seconds for fresh GPS coordinates.", 0);

        String verify;
        if (!firebaseHttpGet(firebaseSmsTestPath, verify)) return;
        StaticJsonDocument<768> claimed;
        if (deserializeJson(claimed, verify) || claimed["requested"].as<bool>() ||
            String(claimed["status"] | "") != "waiting_gps") return;

        lastSmsError = "";
        testPending = true;
        testStartedMs = millis();
    }

    readGPS();

    if (!gpsFix || millis() - lastGpsFixMs > 30000UL)
    {
        if (millis() - testStartedMs < TEST_GPS_WAIT_MS) return;
        reportSmsTest("failed", "No fresh GPS fix. Move outdoors and request the test again.", 0);
        testPending = false;
        return;
    }

    String message = buildAlertMessage(true);
    int accepted = 0;
    String errors;
    for (int i = 0; i < alertPhoneCount; ++i)
    {
        if (deliverSMS(alertPhoneNumbers[i], message)) ++accepted;
        else { errors += "Recipient " + String(i + 1) + ": " + lastSmsError + "\n"; }
    }
    lastSmsError = errors;
    lastSmsTime = millis();
    testPending = false;

    String detail = String(accepted) + " of " + String(alertPhoneCount) +
                    " recipients accepted. Phone delivery unconfirmed.";
    if (errors.length()) detail += " Error: " + errors;

    reportSmsTest(
        accepted == alertPhoneCount && accepted > 0 ? "submitted" :
        accepted > 0 ? "partial" : "failed",
        detail.c_str(), accepted);
}

// ============================================================
// TEMPERATURE
// ============================================================
// The DS18B20 needs its DATA line held high between pulses, normally by a
// 4.7k resistor to 3.3 V. The ESP32's internal pull-up (about 45k) is also
// turned on as a backup: weaker, but enough for one sensor on a short
// cable, so a missing or loose resistor no longer hides the reading.
// OneWire's begin() sets the pin to plain INPUT, so this runs after it.
void startTempBus()
{
    sensors.begin();
    pinMode(ONE_WIRE_BUS, INPUT_PULLUP);
    delay(5);
    if (sensors.getDeviceCount() == 0)
        sensors.begin();   // search again now that the line is pulled up
}

float readTemperatureC()
{
    if (!tempSensorFound)
    {
        startTempBus();
        oneWireDeviceCount = sensors.getDeviceCount();
        if (oneWireDeviceCount > 0 &&
            sensors.getAddress(tempSensorAddress, 0))
        {
            tempSensorFound = true;
        }
        else
        {
            return -127.0f;
        }
    }
    // One corrupted 1-Wire read (modem RF noise, long or loose wire) no
    // longer drops the sensor: each read is retried once, the last good
    // value is kept, and it only counts as disconnected after
    // TEMP_DROP_READS bad reads in a row. 85.0 C is the DS18B20's power-on
    // value, which means the read happened during a brown-out.
    for (int attempt = 0; attempt < 2; attempt++)
    {
        sensors.requestTemperatures();
        float temperature = sensors.getTempC(tempSensorAddress);
        if (temperature != DEVICE_DISCONNECTED_C && temperature != 85.0f)
        {
            tempBadReads = 0;
            return temperature + tempOffsetC;
        }
        delay(50);
    }
    if (++tempBadReads >= TEMP_DROP_READS)
    {
        tempSensorFound = false;
        tempBadReads = 0;
        return -127.0f;
    }
    return currentTemperature;
}

// ============================================================
// CONVERSIONS
// ============================================================
float phFromVoltage(float v)
{
    float span = phVoltageAt7 - phVoltageAt2;
    if (fabs(span) < 0.01f) return 7.0f;
    float pH = 7.0f + (v - phVoltageAt7) * ((7.0f - phAt2) / span);
    return constrain(pH, 0.0f, 14.0f);
}

float turbidityFromVoltage(float v)
{
    if (v >= turbidityClearVoltage - TURBIDITY_ZERO_BAND) return 0.0f;
    if (turbidityVoltsPerNtu <= 0.0f) return 0.0f;
    float ntu = (turbidityClearVoltage - v) / turbidityVoltsPerNtu;
    return constrain(ntu, 0.0f, turbidityMaxNtu);
}

float orpFromVoltage(float v)
{
    return v * 1000.0f + orpCalibrationOffset;
}

// Uncorrected EC in uS/cm (before ecCalibrationK), after removing the
// dry-probe zero voltage.
float ecFromVoltage(float v)
{
    float net = v - ecZeroVoltage;
    if (net <= 0.0f) return 0.0f;
    float tempForEC = (tempSensorFound && currentTemperature > 0)
                      ? currentTemperature : 25.0f;
    return ec.readEC(net * 1000.0f, tempForEC) * 1000.0f;   // DFRobot_EC returns mS/cm.
}

// ============================================================
// CALIBRATION STORAGE + SERIAL COMMANDS
// ============================================================
void loadCalibration()
{
    calPrefs.begin("shellsafe-cal", true);
    tempOffsetC = calPrefs.getFloat("t_off", tempOffsetC);
    phCal7 = calPrefs.getBool("ph7", false);
    phCal2 = calPrefs.getBool("ph2", false);
    phVoltageAt7 = calPrefs.getFloat("ph_v7", phVoltageAt7);
    phVoltageAt2 = calPrefs.getFloat("ph_v2", phVoltageAt2);
    phAt2 = calPrefs.getFloat("ph_p2", phAt2);
    turbidityCalibrated = calPrefs.getBool("turb", false);
    turbidityClearVoltage = calPrefs.getFloat("turb_v0", turbidityClearVoltage);
    turbidityVoltsPerNtu = calPrefs.getFloat("turb_vpn", turbidityVoltsPerNtu);
    orpCalibrated = calPrefs.getBool("orp", false);
    orpCalibrationOffset = calPrefs.getFloat("orp_off", orpCalibrationOffset);
    ecCalibrated = calPrefs.getBool("ec", false);
    ecCalibrationK = calPrefs.getFloat("ec_k", ecCalibrationK);
    ecZeroVoltage = calPrefs.getFloat("ec_v0", ecZeroVoltage);
    calPrefs.end();
}

void saveCalibration()
{
    calPrefs.begin("shellsafe-cal", false);
    calPrefs.putFloat("t_off", tempOffsetC);
    calPrefs.putBool("ph7", phCal7);
    calPrefs.putBool("ph2", phCal2);
    calPrefs.putFloat("ph_v7", phVoltageAt7);
    calPrefs.putFloat("ph_v2", phVoltageAt2);
    calPrefs.putFloat("ph_p2", phAt2);
    calPrefs.putBool("turb", turbidityCalibrated);
    calPrefs.putFloat("turb_v0", turbidityClearVoltage);
    calPrefs.putFloat("turb_vpn", turbidityVoltsPerNtu);
    calPrefs.putBool("orp", orpCalibrated);
    calPrefs.putFloat("orp_off", orpCalibrationOffset);
    calPrefs.putBool("ec", ecCalibrated);
    calPrefs.putFloat("ec_k", ecCalibrationK);
    calPrefs.putFloat("ec_v0", ecZeroVoltage);
    calPrefs.end();
}

void printCalibration()
{
    Serial.println("------------- CALIBRATION -------------");
    Serial.printf("pH        : %s  pH7 at %.3f V, pH%.2f at %.3f V\n",
                  phCalibrated() ? "CALIBRATED" : (phCal7 || phCal2 ? "HALF (needs 2nd buffer)" : "NOT CALIBRATED"),
                  phVoltageAt7, phAt2, phVoltageAt2);
    Serial.printf("Turbidity : %s  clear %.3f V, %.6f V/NTU\n",
                  turbidityCalibrated ? "CALIBRATED" : "NOT CALIBRATED",
                  turbidityClearVoltage, turbidityVoltsPerNtu);
    Serial.printf("ORP       : %s  offset %.1f mV\n",
                  orpCalibrated ? "CALIBRATED" : "NOT CALIBRATED", orpCalibrationOffset);
    Serial.printf("EC        : %s  K %.4f, dry zero %.3f V\n",
                  ecCalibrated ? "CALIBRATED" : "NOT CALIBRATED", ecCalibrationK, ecZeroVoltage);
    Serial.printf("Temp      : offset %.2f C\n", tempOffsetC);
    Serial.println("---------------------------------------");
}

void printCalibrationHelp()
{
    Serial.println("Calibration commands (probe in the solution, wait 1-2 min first):");
    Serial.println("  CAL PH7          probe in pH 7.00 buffer");
    Serial.println("  CAL PH4          probe in pH 4.00 buffer  (or CAL PH10)");
    Serial.println("  CAL TURB0        turbidity probe in clean water (0 NTU)");
    Serial.println("  CAL TURB <ntu>   optional: in a known turbidity standard");
    Serial.println("  CAL ORP <mV>     in ORP reference solution, e.g. CAL ORP 256");
    Serial.println("  CAL EC0          EC probe rinsed, dried and held in AIR (sets zero)");
    Serial.println("  CAL EC <uS/cm>   in conductivity standard, e.g. CAL EC 12880");
    Serial.println("  CAL TEMP <C>     next to a trusted thermometer");
    Serial.println("  CAL SHOW         show saved calibration");
    Serial.println("  CAL RESET        forget all calibration");
}

// Averages several fresh, stable checks of one probe. Returns false if the
// probe is not giving a usable signal right now.
bool sampleProbeVoltage(ProbeState& p, float& volts)
{
    float sum = 0.0f;
    int good = 0;
    for (int i = 0; i < 6; i++)
    {
        if (updateProbe(p)) { sum += p.voltage; good++; }
        delay(100);
    }
    if (good < 4)
    {
        Serial.print("CAL FAILED: ");
        Serial.print(p.name);
        Serial.print(" signal not stable (");
        Serial.print(p.reason);
        Serial.println(")");
        return false;
    }
    volts = sum / good;
    return true;
}

// Median voltage on a pin regardless of the connected floor; used for zero
// points where a near-0 V reading is the expected answer.
bool sampleRawVoltage(int pin, float& volts)
{
    float v[7];
    for (int i = 0; i < 7; i++)
    {
        v[i] = rawToVoltage(readAdcAverage(pin));
        delay(60);
    }
    for (int i = 1; i < 7; i++)
    {
        float key = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; }
        v[j + 1] = key;
    }
    if (v[6] - v[0] > PROBE_MAX_SPREAD_V)
    {
        Serial.println("CAL FAILED: signal not steady. Wait for the reading to settle and try again.");
        return false;
    }
    volts = v[3];
    return true;
}

void handleCalibrationCommand(String cmd)
{
    cmd.trim();
    cmd.toUpperCase();
    String arg = "";
    int space = cmd.indexOf(' ');
    String what = space < 0 ? cmd : cmd.substring(0, space);
    if (space >= 0) { arg = cmd.substring(space + 1); arg.trim(); }
    float value = arg.toFloat();
    float v = 0.0f;

    if (what == "HELP" || what == "") { printCalibrationHelp(); return; }
    if (what == "SHOW") { printCalibration(); return; }
    if (what == "RESET")
    {
        calPrefs.begin("shellsafe-cal", false);
        calPrefs.clear();
        calPrefs.end();
        Serial.println("Calibration cleared. Restarting...");
        delay(500);
        ESP.restart();
        return;
    }

    if (what == "PH7")
    {
        if (!sampleProbeVoltage(phProbe, v)) return;
        phVoltageAt7 = v;
        phCal7 = true;
    }
    else if (what == "PH4" || what == "PH10")
    {
        if (!sampleProbeVoltage(phProbe, v)) return;
        if (phCal7 && fabs(v - phVoltageAt7) < 0.02f)
        {
            Serial.println("CAL FAILED: same voltage as pH 7 buffer. Is the probe really in the second buffer?");
            return;
        }
        phVoltageAt2 = v;
        phAt2 = what == "PH4" ? 4.0f : 10.0f;
        phCal2 = true;
    }
    else if (what == "TURB0")
    {
        if (!sampleProbeVoltage(turbidityProbe, v)) return;
        turbidityClearVoltage = v;
        turbidityVoltsPerNtu = (v * 0.12f) / 1000.0f;   // keep the default ratio until a standard is used
        turbidityCalibrated = true;
    }
    else if (what == "TURB")
    {
        if (!turbidityCalibrated) { Serial.println("CAL FAILED: run CAL TURB0 in clean water first."); return; }
        if (value <= 0.0f) { Serial.println("Usage: CAL TURB <ntu of the standard>"); return; }
        if (!sampleProbeVoltage(turbidityProbe, v)) return;
        float drop = turbidityClearVoltage - v;
        if (drop < 0.01f) { Serial.println("CAL FAILED: no voltage drop versus clean water."); return; }
        turbidityVoltsPerNtu = drop / value;
    }
    else if (what == "ORP")
    {
        if (arg.length() == 0) { Serial.println("Usage: CAL ORP <mV of the reference solution>"); return; }
        if (!sampleProbeVoltage(orpProbe, v)) return;
        orpCalibrationOffset = value - v * 1000.0f;
        orpCalibrated = true;
    }
    else if (what == "EC0")
    {
        if (!sampleRawVoltage(EC_SENSOR_PIN, v)) return;
        ecZeroVoltage = v;
        Serial.printf("EC dry zero set to %.3f V.\n", v);
        if (ecCalibrated)
            Serial.println("Now put the probe back in the standard and run CAL EC <uS/cm> again.");
    }
    else if (what == "EC")
    {
        if (value <= 0.0f) { Serial.println("Usage: CAL EC <uS/cm of the standard>, e.g. CAL EC 1413"); return; }
        if (!sampleProbeVoltage(ecProbe, v)) return;
        float raw = ecFromVoltage(v);
        if (raw <= 0.0f) { Serial.println("CAL FAILED: EC reading is zero."); return; }
        ecCalibrationK = value / raw;
        ecCalibrated = true;
    }
    else if (what == "TEMP")
    {
        if (arg.length() == 0 || !tempSensorFound) { Serial.println("CAL FAILED: needs CAL TEMP <C> and a detected DS18B20."); return; }
        float raw = readTemperatureC() - tempOffsetC;
        tempOffsetC = value - raw;
    }
    else
    {
        printCalibrationHelp();
        return;
    }

    saveCalibration();
    Serial.print("Saved. ");
    printCalibration();
}

// ============================================================
// PH  (with consecutive-read debounce)
// ============================================================
float readPH()
{
    bool good = updateProbe(phProbe);
    phConnected = phProbe.connected;
    if (!phConnected) return 0.0f;
    if (!good) return currentPH;   // keep last value through a noisy check
    lastPhVoltage = phProbe.voltage;

    return phFromVoltage(lastPhVoltage);
}

// ============================================================
// TURBIDITY  (with consecutive-read debounce)
// ============================================================
float readTurbidity()
{
    bool good = updateProbe(turbidityProbe);
    turbidityConnected = turbidityProbe.connected;
    if (!turbidityConnected) return 0.0f;
    if (!good) return currentTurbidity;
    lastTurbidityVoltage = turbidityProbe.voltage;

    return turbidityFromVoltage(lastTurbidityVoltage);
}

// ============================================================
// ORP  (with consecutive-read debounce — fixes false 444 mV)
// ============================================================
float readORP()
{
    bool good = updateProbe(orpProbe);
    orpConnected = orpProbe.connected;
    if (!orpConnected) return 0.0f;
    if (!good) return currentORP;
    lastOrpVoltage = orpProbe.voltage;

    return orpFromVoltage(lastOrpVoltage);
}

// ============================================================
// EC  (with consecutive-read debounce — fixes false 4680 uS/cm)
// ============================================================
// A dry EC probe outputs about 0 V, the same as an unplugged board. The
// pin's internal pull-up tells them apart: the EC board's output holds the
// pin low, while a loose signal wire floats up to 3.3 V.
bool ecBoardHoldsPinLow()
{
    pinMode(EC_SENSOR_PIN, INPUT_PULLUP);
    delay(2);
    int highs = 0;
    for (int i = 0; i < 8; i++)
    {
        highs += digitalRead(EC_SENSOR_PIN);
        delayMicroseconds(200);
    }
    pinMode(EC_SENSOR_PIN, INPUT);   // pull-up off before the next analog read
    analogSetPinAttenuation(EC_SENSOR_PIN, ADC_11db);
    return highs <= 2;
}

float readEC()
{
    bool good = updateProbe(ecProbe);
    ecDry = false;
    if (!good && ecProbe.voltage < ecProbe.minV && ecProbe.spread <= PROBE_MAX_SPREAD_V)
    {
        if (ecBoardHoldsPinLow())
        {
            // Board present, probe out of the water: report 0, not disconnected.
            ecDry = true;
            ecProbe.badCount = 0;
            ecProbe.goodCount = PROBE_CONNECT_READS;
            ecProbe.connected = true;
            ecProbe.reason = "dry - probe out of the water (0 uS/cm)";
            ecConnected = true;
            lastEcVoltage = ecProbe.voltage;
            return 0.0f;
        }
        ecProbe.reason = "no signal - EC wire not reaching GPIO32 (pin floats high)";
    }
    ecConnected = ecProbe.connected;
    if (!ecConnected) return 0.0f;
    if (!good) return currentEC;
    lastEcVoltage = ecProbe.voltage;

    return ecFromVoltage(lastEcVoltage) * ecCalibrationK;
}

// ============================================================
// MESSAGE / ALERT
// ============================================================
String createGPSMessage()
{
    if (!gpsFix || millis() - lastGpsFixMs > 30000UL)
        return "\nGPS unavailable";
    return "\nLat " + String(gpsLatitude, 6) +
           "\nLon " + String(gpsLongitude, 6);
}

String alertLines()
{
    String alertMsg = "";

    if (phConnected && phCalibrated() && (currentPH < ALERT_PH_MIN || currentPH > ALERT_PH_MAX))
    {
        alertMsg += " pH=";
        alertMsg += String(currentPH, 2);
    }
    if (turbidityConnected && turbidityCalibrated && currentTurbidity > ALERT_TURBIDITY_MAX)
    {
        alertMsg += " Turb=";
        alertMsg += String(currentTurbidity, 1);
        alertMsg += "NTU";
    }
    if (tempSensorFound && currentTemperature > ALERT_TEMP_MAX)
    {
        alertMsg += " Temp=";
        alertMsg += String(currentTemperature, 1);
        alertMsg += "C";
    }
    if (orpConnected && orpCalibrated && currentORP < ALERT_ORP_MIN)
    {
        alertMsg += " ORP=";
        alertMsg += String(currentORP, 1);
        alertMsg += "mV";
    }
    if (ecConnected && ecCalibrated && currentEC > ALERT_EC_MAX)
    {
        alertMsg += " EC=";
        alertMsg += String(currentEC, 1);
        alertMsg += "uS/cm";
    }
    return alertMsg;
}

String alertTimestamp()
{
    if (gpsYear < 2020) return "Time unavailable";

    int year = gpsYear;
    int month = gpsMonth;
    int day = gpsDay;
    int hour = gpsHour + 8;   // Philippines UTC+8

    if (hour >= 24)
    {
        hour -= 24;
        day++;
        const int daysInMonth[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
        int dim = daysInMonth[month];
        bool leap = (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0));
        if (month == 2 && leap) dim = 29;
        if (day > dim) { day = 1; month++; if (month > 12) { month = 1; year++; } }
    }

    const char* meridiem = (hour >= 12) ? "PM" : "AM";
    int hour12 = hour % 12;
    if (hour12 == 0) hour12 = 12;

    char buf[32];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %d:%02d:%02d %s",
             year, month, day, hour12, gpsMinute, gpsSecond, meridiem);
    return String(buf);
}

String buildAlertMessage(bool test)
{
    String lines = alertLines();
    String message = test ? "ShellSafe TEST" : "ShellSafe ALERT";
    message += "\n";
    message += alertTimestamp();
    if (lines.length()) message += lines;
    else if (test) message += " pH=9.30";
    message += createGPSMessage();
    return message;
}

void checkAlerts()
{
    if (!alertLines().length()) return;
    if (lastSmsTime && millis() - lastSmsTime < smsCooldown) return;

    readGPS();
    if (!gpsFix || millis() - lastGpsFixMs > 30000UL)
    {
        Serial.println("Alert is waiting for a GPS fix before sending SMS.");
        return;
    }
    sendSMS(buildAlertMessage(false));
}

// ============================================================
// FIREBASE
// ============================================================
void sendDataToFirebase()
{
    // On mobile data, publish every cellularPublishInterval instead of
    // every sensor read.
    bool onWifi = WiFi.status() == WL_CONNECTED;
    if (!onWifi && lastCellularPublish &&
        millis() - lastCellularPublish < cellularPublishInterval)
        return;

    StaticJsonDocument<2048> jsonDoc;

    if (tempSensorFound)
        jsonDoc["temperature"] = roundf(currentTemperature * 100.0f) / 100.0f;
    else
        jsonDoc["temperature"] = "Disconnected";

    if (phConnected)
        jsonDoc["pH"] = roundf(currentPH * 100.0f) / 100.0f;
    else
        jsonDoc["pH"] = "Disconnected";

    if (turbidityConnected)
        jsonDoc["turbidity_NTU"] = roundf(currentTurbidity * 10.0f) / 10.0f;
    else
        jsonDoc["turbidity_NTU"] = "Disconnected";

    if (orpConnected)
        jsonDoc["ORP_mV"] = roundf(currentORP * 10.0f) / 10.0f;
    else
        jsonDoc["ORP_mV"] = "Disconnected";

    if (ecConnected)
        jsonDoc["EC_uS_cm"] = roundf(currentEC * 10.0f) / 10.0f;
    else
        jsonDoc["EC_uS_cm"] = "Disconnected";

    JsonObject probeV = jsonDoc.createNestedObject("probe_voltage");
    probeV["ph"] = roundf(phProbe.voltage * 1000.0f) / 1000.0f;
    probeV["turbidity"] = roundf(turbidityProbe.voltage * 1000.0f) / 1000.0f;
    probeV["orp"] = roundf(orpProbe.voltage * 1000.0f) / 1000.0f;
    probeV["ec"] = roundf(ecProbe.voltage * 1000.0f) / 1000.0f;
    jsonDoc["ec_dry"] = ecDry;
    jsonDoc["ds18b20_count"] = oneWireDeviceCount;
    JsonObject cal = jsonDoc.createNestedObject("calibrated");
    cal["temperature"] = true;   // DS18B20 is factory calibrated
    cal["ph"] = phCalibrated();
    cal["turbidity"] = turbidityCalibrated;
    cal["orp"] = orpCalibrated;
    cal["ec"] = ecCalibrated;

    jsonDoc["a7670_initialized"] = modemInitialized;
    jsonDoc["a7670_model"] = modemName;
    jsonDoc["sim_ready"] = simReady;
    jsonDoc["gsm_network"] = gsmNetworkRegistered;
    jsonDoc["gsm_signal"] = gsmSignalQuality;

    jsonDoc["gps_supported"] = gpsSupported;
    jsonDoc["gps_enabled"] = gpsEnabled;
    jsonDoc["gps_fix"] = gpsFix;

    if (gpsFix)
    {
        jsonDoc["latitude"] = gpsLatitude;
        jsonDoc["longitude"] = gpsLongitude;
        jsonDoc["altitude_m"] = roundf(gpsAltitudeM * 10.0f) / 10.0f;
        jsonDoc["speed_kmh"] = roundf(gpsSpeedKmh * 10.0f) / 10.0f;
        jsonDoc["gps_accuracy_m"] = roundf(gpsAccuracyM * 10.0f) / 10.0f;
        jsonDoc["satellites"] = gpsSatellites;

        String mapsURL = "https://maps.google.com/?q=";
        mapsURL += String(gpsLatitude, 6);
        mapsURL += ",";
        mapsURL += String(gpsLongitude, 6);
        jsonDoc["maps_url"] = mapsURL;
    }
    else
    {
        jsonDoc["satellites"] = 0;
    }

    // Power and performance, for the Device page.
    if (batteryPercent >= 0)
    {
        jsonDoc["battery_pct"] = batteryPercent;
        jsonDoc["battery_v"] = roundf(batteryVoltage * 100.0f) / 100.0f;
    }
    jsonDoc["battery_source"] = batterySource;
    jsonDoc["transport"] = onWifi ? "wifi" : "cellular";
    jsonDoc["cellular_data"] = cellularDataReady;
    jsonDoc["publish_interval_s"] = (onWifi ? sensorReadInterval : cellularPublishInterval) / 1000UL;
    if (onWifi) jsonDoc["wifi_rssi"] = WiFi.RSSI();
    jsonDoc["free_heap"] = ESP.getFreeHeap();
    jsonDoc["min_free_heap"] = ESP.getMinFreeHeap();
    jsonDoc["publish_ok"] = publishOk;
    jsonDoc["publish_fail"] = publishFail;
    jsonDoc["publish_ms"] = lastPublishDurationMs;

    jsonDoc["uptime_seconds"] = millis() / 1000UL;
    // Firebase fills this with its own clock on write, so the dashboard can
    // tell a live device from an old snapshot without relying on GPS time.
    JsonObject serverTs = jsonDoc.createNestedObject("server_ts");
    serverTs[".sv"] = "timestamp";
    if (gpsUtcIso.length() > 0) jsonDoc["timestamp"] = gpsUtcIso;
    jsonDoc["device"] = "ShellSafe_TCall_A7670_V1";

    String jsonString;
    serializeJson(jsonDoc, jsonString);

    firebaseSend(firebasePath, jsonString, true);
    if (!onWifi) lastCellularPublish = millis();
}

// ============================================================
// READING LOG (/readings, one per minute)
// ============================================================
void pushReadingLog()
{
    if (!tempSensorFound && !phConnected && !turbidityConnected && !orpConnected && !ecConnected)
        return;

    StaticJsonDocument<768> doc;
    JsonObject ts = doc.createNestedObject("t");
    ts[".sv"] = "timestamp";
    if (tempSensorFound) doc["temperature"] = roundf(currentTemperature * 100.0f) / 100.0f;
    if (phConnected) doc["ph"] = roundf(currentPH * 100.0f) / 100.0f;
    if (turbidityConnected) doc["turbidity"] = roundf(currentTurbidity * 10.0f) / 10.0f;
    if (orpConnected) doc["orp"] = roundf(currentORP * 10.0f) / 10.0f;
    // A dry probe's 0 is not a water reading; leave it out of the training log.
    if (ecConnected && !ecDry) doc["ec"] = roundf(currentEC * 10.0f) / 10.0f;

    JsonObject cal = doc.createNestedObject("cal");
    cal["ph"] = phCalibrated();
    cal["turbidity"] = turbidityCalibrated;
    cal["orp"] = orpCalibrated;
    cal["ec"] = ecCalibrated;

    if (batteryPercent >= 0) doc["battery_pct"] = batteryPercent;
    if (gpsFix)
    {
        doc["lat"] = serialized(String(gpsLatitude, 6));
        doc["lon"] = serialized(String(gpsLongitude, 6));
    }
    doc["via"] = WiFi.status() == WL_CONNECTED ? "wifi" : "cellular";

    String body;
    serializeJson(doc, body);
    firebaseSend(firebaseHistoryPath, body, false);
}

// ============================================================
// FIREBASE TRANSPORT: WiFi first, A7670 mobile data as backup
// ============================================================

// Attaches the A7670 to mobile data (PDP context 1). Retries at most once
// per cellularAttachRetryMs so a dead SIM does not stall the loop.
bool cellularAttach()
{
    if (cellularDataReady) return true;
    if (!modemInitialized || !simReady || !gsmNetworkRegistered) return false;
    if (lastCellularAttach && millis() - lastCellularAttach < cellularAttachRetryMs) return false;
    lastCellularAttach = millis();

    Serial.print("Cellular data: attaching, APN ");
    Serial.println(cellularApn);
    modemCommand(String("AT+CGDCONT=1,\"IP\",\"") + cellularApn + "\"", 5000);
    String r = modemCommand("AT+CGACT=1,1", 30000);
    cellularDataReady = r.indexOf("OK") >= 0;
    if (cellularDataReady) Serial.println("Cellular data: CONNECTED");
    else Serial.println("Cellular data: FAILED " + r);
    return cellularDataReady;
}

// POSTs JSON over the A7670's built-in HTTPS client. Returns the HTTP
// status, or -1 when the modem did not complete the request. Firebase
// treats the POST as a PUT when replace is set (method override).
int cellularHttpPost(String url, const String& body, bool replace)
{
    if (replace) url += "&x-http-method-override=PUT";

    modemCommand("AT+HTTPTERM", 2000);
    String r = modemCommand("AT+HTTPINIT", 10000);
    if (r.indexOf("OK") < 0)
    {
        Serial.println("Cellular HTTPINIT failed: " + r);
        return -1;
    }
    modemCommand("AT+CSSLCFG=\"sslversion\",0,4", 3000);
    modemCommand("AT+CSSLCFG=\"enableSNI\",0,1", 3000);
    modemCommand("AT+HTTPPARA=\"SSLCFG\",0", 3000);
    modemCommand("AT+HTTPPARA=\"URL\",\"" + url + "\"", 5000);
    modemCommand("AT+HTTPPARA=\"CONTENT\",\"application/json\"", 3000);
    if (replace) modemCommand("AT+HTTPPARA=\"USERDATA\",\"X-HTTP-Method-Override: PUT\"", 3000);

    int status = -1;
    String resp;
    while (SerialAT.available()) SerialAT.read();
    SerialAT.println("AT+HTTPDATA=" + String(body.length()) + ",10000");
    if (modemWaitToken("DOWNLOAD", 10000, resp))
    {
        SerialAT.print(body);
        resp = "";
        if (modemWaitToken("OK", 15000, resp))
        {
            while (SerialAT.available()) SerialAT.read();
            SerialAT.println("AT+HTTPACTION=1");
            resp = "";
            if (modemWaitToken("+HTTPACTION:", 60000, resp))
            {
                // Read the rest of the line: +HTTPACTION: 1,<status>,<length>
                int at = resp.indexOf("+HTTPACTION:");
                unsigned long started = millis();
                while (resp.indexOf('\n', at) < 0 && millis() - started < 3000)
                {
                    while (SerialAT.available()) resp += (char)SerialAT.read();
                    delay(5);
                }
                int comma = resp.indexOf(',', at);
                if (comma >= 0) status = resp.substring(comma + 1).toInt();
            }
        }
    }
    if (status < 0) Serial.println("Cellular HTTP failed: " + resp);
    modemCommand("AT+HTTPTERM", 2000);
    return status;
}

// replace=true overwrites the node (PUT), false appends a child (POST).
bool firebaseSend(const char* path, const String& body, bool replace)
{
    unsigned long started = millis();
    int code = -1;
    if (WiFi.status() == WL_CONNECTED)
    {
        lastTransport = "wifi";
        HTTPClient http;
        http.setTimeout(10000);
        http.begin(firebaseUrl(path));
        http.addHeader("Content-Type", "application/json");
        code = replace ? http.PUT(body) : http.POST(body);
        http.end();
    }
    else if (cellularAttach())
    {
        lastTransport = "cellular";
        code = cellularHttpPost(firebaseUrl(path), body, replace);
        if (code < 0) cellularDataReady = false;   // re-attach on the next try
    }
    else
    {
        lastTransport = "none";
        Serial.println("Firebase skipped: no WiFi and no cellular data.");
        return false;
    }

    lastPublishDurationMs = millis() - started;
    bool ok = code >= 200 && code < 300;
    if (ok) publishOk++;
    else publishFail++;
    Serial.printf("Firebase %s via %s: %d (%lu ms)\n",
                  replace ? "PUT" : "POST", lastTransport, code, lastPublishDurationMs);
    return ok;
}

// ============================================================
// BATTERY
// ============================================================

// Single-cell LiPo voltage to charge, interpolated between these points.
int batteryPercentFromVoltage(float v)
{
    static const float volts[] = {3.30f, 3.50f, 3.60f, 3.70f, 3.75f, 3.80f, 3.85f, 3.90f, 4.00f, 4.10f, 4.20f};
    static const int pct[]     = {0,     5,     10,    20,    30,    40,    50,    60,    75,    90,    100};
    const int n = sizeof(pct) / sizeof(pct[0]);
    if (v <= volts[0]) return 0;
    if (v >= volts[n - 1]) return 100;
    for (int i = 1; i < n; i++)
    {
        if (v <= volts[i])
            return (int)roundf(pct[i - 1] + (v - volts[i - 1]) * (pct[i] - pct[i - 1]) / (volts[i] - volts[i - 1]));
    }
    return 100;
}

void readBattery()
{
    float v = 0.0f;
#if BATTERY_ADC_PIN >= 0
    v = rawToVoltage(readAdcAverage(BATTERY_ADC_PIN)) * BATTERY_DIVIDER_RATIO;
    batterySource = "adc";
#else
    if (!modemInitialized) return;
    String r = modemCommand("AT+CBC", 3000);   // +CBC: 3.950V
    int at = r.indexOf("+CBC:");
    if (at < 0) return;
    int end = r.indexOf('\n', at);
    String field = r.substring(at + 5, end > 0 ? end : r.length());
    int comma = field.lastIndexOf(',');
    if (comma >= 0) field = field.substring(comma + 1);
    field.trim();
    v = field.toFloat();
    if (v > 100.0f) v /= 1000.0f;   // some firmware reports millivolts
    batterySource = "modem";
#endif
    if (v < 2.5f || v > 5.0f)
    {
        batteryPercent = -1;
        return;
    }
    batteryVoltage = v;
    batteryPercent = batteryPercentFromVoltage(v);
}

// ============================================================
// PROBE SIGNALS (wiring diagnostics)
// ============================================================
void printProbeLine(const ProbeState& p)
{
    char line[48];
    snprintf(line, sizeof(line), "%-10s GPIO%-2d %.3f V  +/-%.3f  ",
             p.name, p.pin, p.voltage, p.spread / 2.0f);
    Serial.print(line);
    Serial.println(p.reason);
}

void printProbeSignals()
{
    Serial.println("------------- PROBE SIGNALS ------------");
    Serial.print("Temp DS18B20 GPIO");
    Serial.print(ONE_WIRE_BUS);
    Serial.print(" devices: ");
    Serial.print(oneWireDeviceCount);
    if (tempSensorFound) Serial.println("  ok");
    else Serial.println("  none - check DATA wire and 4.7k pull-up DATA->3.3V");
    printProbeLine(phProbe);
    printProbeLine(turbidityProbe);
    printProbeLine(orpProbe);
    printProbeLine(ecProbe);
}

// ============================================================
// READ ALL SENSORS
// ============================================================
void readAllSensors()
{
    currentTemperature = readTemperatureC();
    currentPH = readPH();
    currentTurbidity = readTurbidity();
    currentORP = readORP();
    currentEC = readEC();

    Serial.println();
    Serial.println("========================================");
    Serial.println("          SHELLSAFE READINGS");
    Serial.println("========================================");

    Serial.print("Temperature : ");
    if (tempSensorFound) { Serial.print(currentTemperature, 2); Serial.println(" C"); }
    else Serial.println("DISCONNECTED");

    Serial.print("pH          : ");
    if (phConnected) { Serial.print(currentPH, 2); Serial.println(phCalibrated() ? "" : "  (NOT CALIBRATED)"); }
    else Serial.println("DISCONNECTED");

    Serial.print("Turbidity   : ");
    if (turbidityConnected) { Serial.print(currentTurbidity, 1); Serial.println(turbidityCalibrated ? " NTU" : " NTU  (NOT CALIBRATED)"); }
    else Serial.println("DISCONNECTED");

    Serial.print("ORP         : ");
    if (orpConnected) { Serial.print(currentORP, 1); Serial.println(orpCalibrated ? " mV" : " mV  (NOT CALIBRATED)"); }
    else Serial.println("DISCONNECTED");

    Serial.print("EC          : ");
    if (ecConnected && ecDry) Serial.println("0.0 uS/cm  (probe dry / in air)");
    else if (ecConnected) { Serial.print(currentEC, 1); Serial.println(ecCalibrated ? " uS/cm" : " uS/cm  (NOT CALIBRATED)"); }
    else Serial.println("DISCONNECTED");

    printProbeSignals();

    Serial.println("----------------------------------------");
    Serial.print("A7670      : ");
    Serial.println(modemInitialized ? "ONLINE" : "OFFLINE");
    Serial.print("SIM         : ");
    Serial.println(simReady ? "READY" : "NOT READY");
    Serial.print("GSM Network : ");
    Serial.println(gsmNetworkRegistered ? "REGISTERED" : "NOT REGISTERED");
    Serial.print("GSM Signal  : ");
    Serial.println(gsmSignalQuality);

    Serial.print("GPS         : ");
    if (gpsFix)
    {
        Serial.print(gpsLatitude, 6);
        Serial.print(", ");
        Serial.println(gpsLongitude, 6);
        Serial.print("Satellites  : ");
        Serial.println(gpsSatellites);
    }
    else if (!gpsSupported) Serial.println("NOT SUPPORTED");
    else if (!modemInitialized) Serial.println("MODEM OFFLINE");
    else if (!gpsEnabled) Serial.println("DISABLED");
    else Serial.println("SEARCHING...");

    Serial.print("Battery     : ");
    if (batteryPercent >= 0) Serial.printf("%d%% (%.2f V, %s)\n", batteryPercent, batteryVoltage, batterySource);
    else Serial.println("UNKNOWN");
    Serial.print("Data link   : ");
    if (WiFi.status() == WL_CONNECTED) Serial.printf("WiFi (%d dBm)\n", WiFi.RSSI());
    else if (cellularDataReady) Serial.println("CELLULAR (A7670)");
    else Serial.println("NONE");

    Serial.println("========================================");

    checkAlerts();
}

// ============================================================
// WIFI
// ============================================================
void connectWiFi()
{
    Serial.println();
    Serial.print("Connecting WiFi: ");
    Serial.println(ssid);
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20)
    {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.println("WiFi CONNECTED.");
        Serial.print("IP: ");
        Serial.println(WiFi.localIP());
    }
    else
    {
        Serial.println("WiFi connection failed.");
        Serial.println("Sensors, GSM and GPS will continue.");
    }
}

// ============================================================
// SETUP
// ============================================================
void setup()
{
    Serial.begin(115200);
    delay(1500);

    Serial.println();
    Serial.println("########################################");
    Serial.println("#                                      #");
    Serial.println("#          SHELLSAFE SYSTEM            #");
    Serial.println("#                                      #");
    Serial.println("# ESP32-WROVER-E T-CALL A7670 V1.0    #");
    Serial.println("# Firmware: v5 (LTE backup, battery)   #");
    Serial.println("#                                      #");
    Serial.println("# A7670 = SMS + GPS + LTE backup       #");
    Serial.println("# WiFi  = Firebase (primary)           #");
    Serial.println("#                                      #");
    Serial.println("########################################");

    initAdc();

    startTempBus();
    sensors.setResolution(12);
    sensors.setWaitForConversion(true);

    oneWireDeviceCount = sensors.getDeviceCount();
    if (oneWireDeviceCount > 0 &&
        sensors.getAddress(tempSensorAddress, 0))
    {
        tempSensorFound = true;
        Serial.println("DS18B20: DETECTED");
    }
    else
    {
        tempSensorFound = false;
        Serial.println("DS18B20: NOT DETECTED");
    }

    EEPROM.begin(32);
    ec.begin();
    loadCalibration();
    printCalibration();
    Serial.println("Type CAL HELP in the Serial Monitor to calibrate probes.");

    initA7670();
    initGPS();
    connectWiFi();

    Serial.println();
    Serial.println("========================================");
    Serial.println("SYSTEM INITIALIZATION COMPLETE");
    Serial.println("========================================");
    Serial.print("A7670      : ");
    Serial.println(modemInitialized ? "READY" : "FAILED");
    Serial.print("SIM         : ");
    Serial.println(simReady ? "READY" : "NOT READY");
    Serial.print("GSM Network : ");
    Serial.println(gsmNetworkRegistered ? "REGISTERED" : "NOT REGISTERED");
    Serial.print("GNSS        : ");
    Serial.println(gpsEnabled ? "ENABLED" : "NOT AVAILABLE");
    Serial.print("WiFi        : ");
    Serial.println(WiFi.status() == WL_CONNECTED ? "CONNECTED" : "OFFLINE");
    Serial.println("========================================");

    readBattery();

    lastGpsRead = millis();
    lastSensorRead = millis();
    lastGsmCheck = millis();
    lastBatteryRead = millis();

    pollSmsTest();
}

// ============================================================
// LOOP
// ============================================================
void loop()
{
    handleSerialCommands();
    unsigned long now = millis();

    if (now - lastGpsRead >= gpsReadInterval)
    {
        lastGpsRead = now;
        readGPS();
    }

    if (now - lastGsmCheck >= gsmCheckInterval)
    {
        lastGsmCheck = now;
        if (modemInitialized)
        {
            gsmNetworkRegistered = modem.isNetworkConnected();
            gsmSignalQuality = modem.getSignalQuality();
            if (!gsmNetworkRegistered) cellularDataReady = false;
            Serial.print("A7670 GSM: ");
            Serial.print(gsmNetworkRegistered ? "REGISTERED" : "NOT REGISTERED");
            Serial.print(" | Signal: ");
            Serial.println(gsmSignalQuality);
        }
        pollSmsTest();
    }

    if (now - lastSensorRead >= sensorReadInterval)
    {
        lastSensorRead = now;
        lastGpsRead = now;

        readGPS();
        readAllSensors();
        sendDataToFirebase();

        if (now - lastHistoryPush >= historyInterval)
        {
            lastHistoryPush = now;
            pushReadingLog();
        }
    }

    if (now - lastBatteryRead >= batteryReadInterval)
    {
        lastBatteryRead = now;
        readBattery();
    }

    if (WiFi.status() != WL_CONNECTED && now - lastWiFiReconnect >= 30000UL)
    {
        lastWiFiReconnect = now;
        Serial.println("Attempting WiFi reconnect...");
        WiFi.disconnect();
        WiFi.begin(ssid, password);
    }

    delay(10);
}
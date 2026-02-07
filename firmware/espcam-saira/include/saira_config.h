#pragma once

// Build-time configuration.
// Values come from .env via tools/load_dotenv.py (PlatformIO extra_scripts).
// All macros have safe defaults so the project still builds without .env.

#ifndef SAIRA_WIFI_SSID
#define SAIRA_WIFI_SSID "Tenda_A05E38"
#endif

#ifndef SAIRA_WIFI_PASSWORD
#define SAIRA_WIFI_PASSWORD ""
#endif

#ifndef SAIRA_SERVER_BASE
#define SAIRA_SERVER_BASE "http://example.invalid"
#endif

#ifndef SAIRA_IP_CAM_URL
#define SAIRA_IP_CAM_URL "http://192.168.0.142:80/snap.jpg"
#endif

#ifndef SAIRA_IP_CAM_USER
#define SAIRA_IP_CAM_USER "admin"
#endif

#ifndef SAIRA_IP_CAM_PASS
#define SAIRA_IP_CAM_PASS "admin"
#endif

#ifndef SAIRA_TIMER_DELAY_MS
#define SAIRA_TIMER_DELAY_MS 30000
#endif

#ifndef SAIRA_TLS_INSECURE
#define SAIRA_TLS_INSECURE 1
#endif

// OTA over HTTP(S) (device pulls updates)
#ifndef SAIRA_OTA_ENABLED
#define SAIRA_OTA_ENABLED 0
#endif

#ifndef SAIRA_OTA_MANIFEST_URL
// If empty, firmware will default to SAIRA_SERVER_BASE + "/ota/manifest.txt"
#define SAIRA_OTA_MANIFEST_URL ""
#endif

#ifndef SAIRA_OTA_CURRENT_VERSION
#define SAIRA_OTA_CURRENT_VERSION "dev"
#endif

#ifndef SAIRA_OTA_CHECK_INTERVAL_MS
#define SAIRA_OTA_CHECK_INTERVAL_MS 600000
#endif

#ifndef SAIRA_OTA_ADMIN_TOKEN
// Optional token sent as X-Admin-Token header (if your manifest requires it)
#define SAIRA_OTA_ADMIN_TOKEN ""
#endif

#ifndef SAIRA_DEVICE_ID
#define SAIRA_DEVICE_ID "esp32"
#endif

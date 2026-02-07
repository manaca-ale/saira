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


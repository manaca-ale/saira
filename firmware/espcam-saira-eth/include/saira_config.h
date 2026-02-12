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

// Network mode
#ifndef SAIRA_USE_ETHERNET
// 0 = Wi-Fi (default), 1 = native ESP32 Ethernet (RMII PHY)
#define SAIRA_USE_ETHERNET 0
#endif

// Ethernet PHY config (used when SAIRA_USE_ETHERNET=1)
#ifndef SAIRA_ETH_ADDR
#define SAIRA_ETH_ADDR 0
#endif

#ifndef SAIRA_ETH_POWER_PIN
#define SAIRA_ETH_POWER_PIN -1
#endif

#ifndef SAIRA_ETH_MDC_PIN
#define SAIRA_ETH_MDC_PIN 23
#endif

#ifndef SAIRA_ETH_MDIO_PIN
#define SAIRA_ETH_MDIO_PIN 18
#endif

#ifndef SAIRA_ETH_TYPE
// 0 = ETH_PHY_LAN8720
#define SAIRA_ETH_TYPE 0
#endif

#ifndef SAIRA_ETH_CLK_MODE
// 0 = ETH_CLOCK_GPIO0_IN
#define SAIRA_ETH_CLK_MODE 0
#endif

#ifndef SAIRA_ETH_WIFI_DUAL_MODE
// 1 = keep Ethernet (camera LAN) and Wi-Fi (internet/OTA) active in parallel.
#define SAIRA_ETH_WIFI_DUAL_MODE 1
#endif

#ifndef SAIRA_ETH_WIFI_FALLBACK
// 1 = when Ethernet is unavailable, allow Wi-Fi fallback to keep OTA alive.
#define SAIRA_ETH_WIFI_FALLBACK 1
#endif

#ifndef SAIRA_ETH_RETRY_INTERVAL_MS
// Interval between Ethernet re-init attempts when disconnected.
#define SAIRA_ETH_RETRY_INTERVAL_MS 10000
#endif

#ifndef SAIRA_WIFI_RETRY_INTERVAL_MS
// Interval between Wi-Fi reconnect attempts in fallback mode.
#define SAIRA_WIFI_RETRY_INTERVAL_MS 15000
#endif

// Remote debug heartbeat via /status (for headless/remote devices)
#ifndef SAIRA_REMOTE_DEBUG_ENABLED
#define SAIRA_REMOTE_DEBUG_ENABLED 1
#endif

#ifndef SAIRA_REMOTE_DEBUG_INTERVAL_MS
#define SAIRA_REMOTE_DEBUG_INTERVAL_MS 60000
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

// Remote config (device pulls updates)
#ifndef SAIRA_REMOTE_CONFIG_ENABLED
#define SAIRA_REMOTE_CONFIG_ENABLED 0
#endif

#ifndef SAIRA_REMOTE_CONFIG_URL
// If empty, defaults to SAIRA_SERVER_BASE + "/device/" + SAIRA_DEVICE_ID + "/config.txt"
#define SAIRA_REMOTE_CONFIG_URL ""
#endif

#ifndef SAIRA_REMOTE_CONFIG_CHECK_INTERVAL_MS
#define SAIRA_REMOTE_CONFIG_CHECK_INTERVAL_MS 60000
#endif

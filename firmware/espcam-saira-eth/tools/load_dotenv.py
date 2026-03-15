import os

Import("env")  # PlatformIO build environment


def _parse_dotenv(path):
    items = {}
    if not os.path.isfile(path):
        return items

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            # Allow quoted values in .env (strip one layer).
            if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                v = v[1:-1]
            items[k] = v
    return items


def _as_define_value(v, force_string=False):
    vv = v.strip()
    if force_string:
        esc = vv.replace("\\", "\\\\").replace('"', '\\"')
        return f'\\\"{esc}\\\"'

    low = vv.lower()
    if low in ("true", "yes", "on"):
        return "1"
    if low in ("false", "no", "off"):
        return "0"
    # int?
    if vv.isdigit():
        return vv

    # String literal for -D: we must keep quotes all the way to the compiler.
    # Using escaped quotes ensures the preprocessor expands to a valid C string:
    #   -DSAIRA_WIFI_SSID=\\\"MyWifi\\\"  -> SAIRA_WIFI_SSID expands to "MyWifi"
    esc = vv.replace("\\", "\\\\").replace('"', '\\"')
    return f'\\\"{esc}\\\"'


project_dir = env.subst("$PROJECT_DIR")
dotenv_path = os.path.join(project_dir, ".env")
cfg = _parse_dotenv(dotenv_path)

mapping = {
    "WIFI_SSID": "SAIRA_WIFI_SSID",
    "WIFI_PASSWORD": "SAIRA_WIFI_PASSWORD",
    "SERVER_BASE": "SAIRA_SERVER_BASE",
    "IP_CAM_URL": "SAIRA_IP_CAM_URL",
    "IP_CAM_USER": "SAIRA_IP_CAM_USER",
    "IP_CAM_PASS": "SAIRA_IP_CAM_PASS",
    "TIMER_DELAY_MS": "SAIRA_TIMER_DELAY_MS",
    "TLS_INSECURE": "SAIRA_TLS_INSECURE",
    "USE_ETHERNET": "SAIRA_USE_ETHERNET",
    "ETH_ADDR": "SAIRA_ETH_ADDR",
    "ETH_POWER_PIN": "SAIRA_ETH_POWER_PIN",
    "ETH_MDC_PIN": "SAIRA_ETH_MDC_PIN",
    "ETH_MDIO_PIN": "SAIRA_ETH_MDIO_PIN",
    "ETH_TYPE": "SAIRA_ETH_TYPE",
    "ETH_CLK_MODE": "SAIRA_ETH_CLK_MODE",
    "ETH_WIFI_DUAL_MODE": "SAIRA_ETH_WIFI_DUAL_MODE",
    "ETH_WIFI_FALLBACK": "SAIRA_ETH_WIFI_FALLBACK",
    "ETH_RETRY_INTERVAL_MS": "SAIRA_ETH_RETRY_INTERVAL_MS",
    "WIFI_RETRY_INTERVAL_MS": "SAIRA_WIFI_RETRY_INTERVAL_MS",
    "REMOTE_DEBUG_ENABLED": "SAIRA_REMOTE_DEBUG_ENABLED",
    "REMOTE_DEBUG_INTERVAL_MS": "SAIRA_REMOTE_DEBUG_INTERVAL_MS",
    "DEVICE_ID": "SAIRA_DEVICE_ID",
    "OTA_ENABLED": "SAIRA_OTA_ENABLED",
    "OTA_MANIFEST_URL": "SAIRA_OTA_MANIFEST_URL",
    "OTA_CURRENT_VERSION": "SAIRA_OTA_CURRENT_VERSION",
    "OTA_CHECK_INTERVAL_MS": "SAIRA_OTA_CHECK_INTERVAL_MS",
    "OTA_ADMIN_TOKEN": "SAIRA_OTA_ADMIN_TOKEN",
    "REMOTE_CONFIG_ENABLED": "SAIRA_REMOTE_CONFIG_ENABLED",
    "REMOTE_CONFIG_URL": "SAIRA_REMOTE_CONFIG_URL",
    "REMOTE_CONFIG_CHECK_INTERVAL_MS": "SAIRA_REMOTE_CONFIG_CHECK_INTERVAL_MS",
}

defines = []
numeric_keys = {
    "TIMER_DELAY_MS",
    "TLS_INSECURE",
    "USE_ETHERNET",
    "ETH_ADDR",
    "ETH_POWER_PIN",
    "ETH_MDC_PIN",
    "ETH_MDIO_PIN",
    "ETH_TYPE",
    "ETH_CLK_MODE",
    "ETH_WIFI_DUAL_MODE",
    "ETH_WIFI_FALLBACK",
    "ETH_RETRY_INTERVAL_MS",
    "WIFI_RETRY_INTERVAL_MS",
    "REMOTE_DEBUG_ENABLED",
    "REMOTE_DEBUG_INTERVAL_MS",
    "OTA_ENABLED",
    "OTA_CHECK_INTERVAL_MS",
    "REMOTE_CONFIG_ENABLED",
    "REMOTE_CONFIG_CHECK_INTERVAL_MS",
}
for src_key, dst_key in mapping.items():
    if src_key not in cfg:
        continue
    defines.append((dst_key, _as_define_value(cfg[src_key], force_string=(src_key not in numeric_keys))))

if defines:
    env.Append(CPPDEFINES=defines)

"""Constants for ElOverblik Data."""

from zoneinfo import ZoneInfo

DOMAIN = "eloverblik_data"
CONF_TOKEN = "refresh_token"
CONF_METERS = "metering_points"
CONF_HISTORY = "history_start"
CONF_ALL_HISTORY = "all_history"
CONF_POLL = "poll_hours"
DENMARK = ZoneInfo("Europe/Copenhagen")
API_URL = "https://api.eloverblik.dk/customerapi/api"
PLATFORMS = ["sensor", "binary_sensor", "button"]
METADATA_FIELDS = (
    "meterNumber",
    "typeOfMP",
    "balanceSupplierName",
    "gridOperatorName",
    "settlementMethod",
    "estimatedAnnualVolume",
    "energyTimeSeriesMeasureUnit",
    "powerLimitKW",
    "powerLimitKWDecimal",
    "powerLimitA",
    "mpCapacity",
)

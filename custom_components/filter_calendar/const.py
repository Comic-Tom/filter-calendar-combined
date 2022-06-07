"""Constants for integration_blueprint."""

# Base component constants
NAME = "Filter Calendar"
DOMAIN = "filter_calendar"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"
ISSUE_URL = "https://github.com/abates/filter-calendar/issues"

# Icons
ICON = "mdi:calendar"

# Configuration and options
CONF_ENABLED = "enabled"
CONF_TRACKING_CALENDAR = "tracking_calendar"
CONF_FILTER = "filter"
ATTR_TRACKING_CALENDAR = "tracking"
ATTR_FILTER = "filter"

# Defaults
DEFAULT_NAME = DOMAIN


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

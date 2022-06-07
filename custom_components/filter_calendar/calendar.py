"""Calendar entity for the FilterCalendar integration"""

from datetime import datetime, timedelta
import logging

from homeassistant.helpers.typing import ConfigType
from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_NAME
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_platforms,
)
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

import voluptuous as vol

from .const import (
    ATTR_TRACKING_CALENDAR,
    ATTR_FILTER,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


ENTITY_ID_FORMAT = "calendar.{}"

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_TRACKING_CALENDAR): str,
        vol.Required(ATTR_FILTER): str,
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    # pylint: disable=unused-argument
    discovery_info,
):
    """Set up the filter calendar platform."""

    calendar_filter = Filter(config[ATTR_FILTER])
    sensor = FilterCalendar(
        hass, config[ATTR_NAME], config[ATTR_TRACKING_CALENDAR], calendar_filter
    )
    async_add_entities([sensor])


class Filter:
    """Filter to match upstream calendar events."""

    def __init__(self, filter_spec):
        self.filter = filter_spec

    def __call__(self, event: CalendarEntity) -> bool:
        for check in [event.summary, event.description, event.location]:
            if check is not None and self.filter in check:
                return True
        return False


class FilterCalendar(CalendarEntity):
    """Base class for calendar event entities."""

    def __init__(
        self, hass: HomeAssistant, name: str, tracking_calendar_id, filter_spec
    ):
        self.hass = hass
        self._entity_registry: EntityRegistry = None
        self._name = name
        self.tracking_calendar_id = tracking_calendar_id
        self._tracking_calendar: CalendarEntity = None
        self._events = []
        self.filter = filter_spec

    @property
    def event(self) -> CalendarEvent:
        """Return the next upcoming event."""
        if self._events:
            return self._events[0]
        return None

    async def _get_tracking_calendar(self):
        """Get the tracking calendar entity"""

        if self._tracking_calendar is None:
            entity_id = f"calendar.{self.tracking_calendar_id}"
            _LOGGER.debug("Looking for tracking calendar %s", entity_id)
            entry = self._entity_registry.async_get(entity_id)
            if entry:
                for platform in async_get_platforms(self.hass, entry.platform):
                    if entity_id in platform.entities:
                        if platform.entities[entity_id].available:
                            self._tracking_calendar = platform.entities[entity_id]
                        else:
                            _LOGGER.debug(
                                "Found %s, but it is not yet ready", entity_id
                            )
                        return self._tracking_calendar
                _LOGGER.warning(
                    "Failed to find tracking calendar with id %s", entity_id
                )
        return self._tracking_calendar

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Periodically update the local state"""
        _LOGGER.debug("Updating %s", self.unique_id)
        cal = await self._get_tracking_calendar()
        if cal:
            self._events = await self.async_get_events(self.hass, None, None)

    async def async_added_to_hass(self):
        self._entity_registry = entity_registry.async_get(self.hass)
        await super().async_added_to_hass()

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        cal = await self._get_tracking_calendar()
        if cal:
            _LOGGER.debug("Pulling events from tracking calendar")
            return list(
                filter(
                    self.filter,
                    await self._tracking_calendar.async_get_events(
                        hass, start_date, end_date
                    ),
                )
            )
        return []

    @property
    def name(self):
        return self._name

"""Calendar entity for the FilterCalendar integration"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from cachetools import TTLCache, keys

from homeassistant.helpers.typing import ConfigType
from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_NAME, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry
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
        config[ATTR_NAME],
        config[ATTR_TRACKING_CALENDAR],
        calendar_filter,
    )

    async_add_entities([sensor])


class CalendarUnavailable(Exception):
    """Raised when a tracking calendar isn't available."""


class CalendarStore:
    """This class will manage looking up calendars and events."""

    hass: HomeAssistant

    _calendars: dict[str, CalendarEntity]

    _events_cache: TTLCache

    def __new__(cls, hass: HomeAssistant):
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
            cls._instance.hass = hass
            cls._instance._calendars: dict[str, CalendarEntity] = {}
            cls._instance._events_cache = TTLCache(
                maxsize=10,
                ttl=MIN_TIME_BETWEEN_UPDATES,
                timer=datetime.now,
            )
        return cls._instance

    async def async_get_events(
        self,
        entity_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        key = keys.hashkey(calendar=entity_id, start_date=start_date, end_date=end_date)
        try:
            events = self._events_cache[key]
            if asyncio.isfuture(events):
                return await events
            return events
        except KeyError:
            future = asyncio.Future()
            self._events_cache[key] = future
            try:
                cal = await self.async_get_calendar(entity_id)
                events = await cal.async_get_events(self.hass, start_date, end_date)
                future.set_result(events)
                self._events_cache[key] = events
                return events
            except CalendarUnavailable as ex:
                future.set_exception(ex)
                raise ex

    async def async_get_calendar(self, entity_id):
        """Retrieve a calendar from the store."""

        try:
            return self._calendars[entity_id]
        except KeyError:
            _LOGGER.debug("Looking for tracking calendar %s", entity_id)

            registry = entity_registry.async_get(self.hass)
            entry = registry.async_get(entity_id)
            calendar = None
            if entry:
                for platform in async_get_platforms(self.hass, entry.platform):
                    if entity_id in platform.entities:
                        if platform.entities[entity_id].available:
                            calendar = platform.entities[entity_id]
                            self._calendars[entity_id] = calendar
                            return calendar
                        _LOGGER.debug("Calendar %s is not yet ready", entity_id)
                        break
        _LOGGER.debug("Calendar %s is not available", entity_id)
        raise CalendarUnavailable()


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
        self,
        name: str,
        tracking_calendar_id: str,
        filter_spec,
    ):
        self._name = name
        if not tracking_calendar_id.startswith("calendar"):
            tracking_calendar_id = f"calendar.{tracking_calendar_id}"
        self._tracking_calendar_id = tracking_calendar_id

        self._filter = filter_spec
        self._events = None
        self._last_update: datetime = None

    @property
    def state(self) -> str | None:
        """Return the state of the calendar event."""
        if self._events is None:
            return STATE_UNAVAILABLE
        return super().state

    @property
    def event(self) -> CalendarEvent:
        """Return the next upcoming event."""
        if self._events:
            return self._events[0]
        return None

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Periodically update the local state"""
        _LOGGER.debug("Updating %s", self.entity_id)
        next_update = datetime.combine(
            datetime.now(timezone.utc),
            datetime.min.time(),
            timezone.utc,
        ) - timedelta(days=1)
        # Do a full update once a day
        if next_update != self._last_update:
            _LOGGER.debug(
                "Performing full update for %s (from %s to %s)",
                self.entity_id,
                self._last_update,
                next_update,
            )
            self._events = await self.async_get_events(self.hass, datetime.min, datetime.max)
        # Otherwise just look for events from yesterday forward
        else:
            _LOGGER.debug(
                "Performing incremental update (from %s) for %s",
                self._last_update,
                self.entity_id,
            )
            self._events = await self.async_get_events(
                self.hass, self._last_update, None
            )
        self._last_update = next_update

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        try:
            return list(
                filter(
                    self._filter,
                    await CalendarStore(hass).async_get_events(
                        self._tracking_calendar_id, start_date, end_date
                    ),
                )
            )
        except CalendarUnavailable:
            return None

    @property
    def name(self):
        return self._name

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timedelta
import logging
import re
import sys
from typing import Iterable

from cachetools import TTLCache, keys

from homeassistant.helpers.typing import ConfigType
from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_NAME
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_platforms,
)
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import Throttle, dt
import homeassistant.helpers.config_validation as cv

import voluptuous as vol

from .const import (
    ATTR_TRACKING_CALENDAR,
    ATTR_FILTER,
    ATTR_REGEX,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

ENTITY_ID_FORMAT = "calendar.{}"

# Update PLATFORM_SCHEMA to include custom options for work-related and excluded event types
PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_TRACKING_CALENDAR): str,
        vol.Required(ATTR_FILTER): str,
        vol.Optional(ATTR_REGEX, default=False): bool,
        vol.Optional('include_work_types', default=["Lunch", "One-on-One", "Inbound"]): [str],  # New option for work-related event types
        vol.Optional('exclude_types', default=["Public Holiday", "Annual Leave", "Personal Leave"]): [str],  # Excluded event types
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info,
):
    """Set up the filter calendar platform."""

    # Retrieve custom options for work-related and excluded event types
    include_work_types = config.get('include_work_types', ["Lunch", "One-on-One", "Inbound"])
    exclude_types = config.get('exclude_types', ["Public Holiday", "Annual Leave", "Personal Leave"])

    # Initialize the filter based on regex setting
    if config[ATTR_REGEX]:
        calendar_filter = RegexFilter(config[ATTR_FILTER], include_work_types=include_work_types, exclude_types=exclude_types)
    else:
        calendar_filter = AttrFilter(config[ATTR_FILTER], include_work_types=include_work_types, exclude_types=exclude_types)

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

    _lock = asyncio.Lock()

    _initialized = False

    def __new__(cls, hass: HomeAssistant):  # pylint:disable=unused-argument
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, hass):
        if self._initialized:
            return

        self.hass = hass
        self._calendars: dict[str, CalendarEntity] = {}
        self._events_cache = TTLCache(
            maxsize=10,
            ttl=MIN_TIME_BETWEEN_UPDATES,
            timer=datetime.now,
        )
        self._initialized = True

    async def async_get_events(
        self,
        entity_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        _LOGGER.info(
            "Getting events, cache size is %s ",
            sys.getsizeof(self._events_cache),
        )
        key = keys.hashkey(
            calendar=entity_id,
            start_date=start_date.replace(second=0, microsecond=0),
            end_date=end_date.replace(second=0, microsecond=0),
        )
        async with self._lock:
            if key in self._events_cache:
                events = self._events_cache[key]
                if asyncio.isfuture(events):
                    events = await events
                    self._events_cache[key] = events
                return events

        future = asyncio.Future()
        self._events_cache[key] = future

        try:
            cal = await self.async_get_calendar(entity_id)
            events = await cal.async_get_events(self.hass, start_date, end_date)
            future.set_result(events)
            return events
        except CalendarUnavailable as ex:
            future.set_exception(ex)
            raise ex

    async def async_get_calendar(self, entity_id):
        """Retrieve a calendar from the store."""

        try:
            return self._calendars[entity_id]
        except KeyError:
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


class Filter(ABC):
    """Filter to match upstream calendar events."""

    @abstractmethod
    def __init__(self, filter_spec, include_work_types, exclude_types):
        self.filter_spec = filter_spec
        self.include_work_types = include_work_types
        self.exclude_types = exclude_types

    @abstractmethod
    def search(self, event: CalendarEntity):
        pass

    @abstractmethod
    def match(self, search: str) -> bool:
        pass

    def __call__(self, event: CalendarEntity) -> bool:
        for search in self.search(event):
            if search is not None and self.match(search):
                return True
        return False


class AttrFilter(Filter):
    def __init__(
        self,
        filter_spec: str,
        include_work_types: list[str],
        exclude_types: list[str],
        attrs: list[str] = None,
    ):
        super().__init__(filter_spec, include_work_types, exclude_types)
        if attrs is None:
            attrs = ["summary", "description", "location"]
        self._attrs = attrs

    def search(self, event: CalendarEntity) -> list[str]:
        for attr in self._attrs:
            try:
                yield getattr(event, attr)
            except AttributeError:
                _LOGGER.error("CalendarEntity does not have an attribute '%s'", attr)

    def match(self, search: str) -> bool:
        """Check if the event matches the filter and treat 'lunch', 'one-on-one', and 'inbound' as work."""
        # If the event matches the 'work' categories, treat it as work
        if any(work_type in search for work_type in self.include_work_types):
            return True

        # If the event matches excluded types (e.g., Public Holiday), exclude it
        if any(exclude_type in search for exclude_type in self.exclude_types):
            return False

        # Match the filter spec in the event's attributes (if not excluded)
        return self.filter_spec in search


class RegexFilter(AttrFilter):
    def __init__(
        self,
        filter_spec: str,
        include_work_types: list[str],
        exclude_types: list[str],
        attrs=None,
    ):
        super().__init__(filter_spec, include_work_types, exclude_types, attrs)
        self.expression = re.compile(self.filter_spec)

    def match(self, search: str) -> bool:
        s = self.expression.search(search)
        if s is None:
            return False
        return True


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
        self._event = None

    @property
    def event(self) -> CalendarEvent:
        """Return the next upcoming event."""
        return self._event

    def format_event_time(self, event: CalendarEvent) -> str:
        """Format the event time to show work hours (1pm to 9pm, etc.)."""
        start_time = event.start
        end_time = event.end
        formatted_start_time = start_time.strftime("%I:%M %p")  # Example: 01:00 PM
        formatted_end_time = end_time.strftime("%I:%M %p")  # Example: 09:00 PM
        return f"{formatted_start_time} to {formatted_end_time}"

@Throttle(MIN_TIME_BETWEEN_UPDATES)
async def async_update(self):
    """Periodically update the local state"""
    now = dt.now()
    events = await self.async_get_events(self.hass, now, now + timedelta(weeks=26))

    # Combine events into one for the day
    filtered_events = [event for event in events if self._filter(event)]
    combined_events = self.combine_events(filtered_events)

    # If there are combined events, set the first one as the active event
    if combined_events:
        self._event = combined_events[0]
        # Format the event time for display
        self._event_time = self.format_event_time(self._event)

        # Explicitly set the state so the frontend can reflect the combined event
        self._attr_state = self._event.summary  # Set the summary as the state
        self._attr_start = self._event.start    # Set the start time for frontend display
        self._attr_end = self._event.end        # Set the end time for frontend display

        # Optionally, update other attributes to reflect the merged event data
        self._attr_extra_state_attributes = {
            "start_time": self._event.start,
            "end_time": self._event.end,
            "location": self._event.location,
            "description": self._event.description,
        }



    def combine_events(self, events: list[CalendarEvent]) -> list[CalendarEvent]:
        """Combine consecutive events of the same type into one event."""
        if not events:
            return []

        # Sort events by start time
        events.sort(key=lambda x: x.start)

        # Initialize the merged event variables
        merged_event_start = events[0].start
        merged_event_end = events[0].end
        merged_event_summary = events[0].summary
        events_combined = []

        for event in events[1:]:
            # If events overlap or are consecutive, combine them
            if event.start <= merged_event_end:
                merged_event_end = max(merged_event_end, event.end)
            else:
                # If no overlap, add the previous merged event
                events_combined.append(
                    CalendarEvent(
                        start=merged_event_start,
                        end=merged_event_end,
                        summary=merged_event_summary,
                    )
                )
                # Reset for the next event
                merged_event_start = event.start
                merged_event_end = event.end
                merged_event_summary = event.summary

        # Add the last combined event
        events_combined.append(
            CalendarEvent(
                start=merged_event_start,
                end=merged_event_end,
                summary=merged_event_summary,
            )
        )

        return events_combined
        
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Retrieve and filter events."""
        calendar_store = CalendarStore(self.hass)
        events = await calendar_store.async_get_events(
            self._tracking_calendar_id, start_date, end_date
        )
        filtered_events = [event for event in events if self._filter(event)]
        return filtered_events

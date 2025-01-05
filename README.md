# Filter Calendar Home Assistant Add-on

i needed a addon that would combine events to a single one to make a hours worked, this does not do everything i want... but at least the filtering works removing stuff and it at least give the outcome i like into its attributes so i could make a template to give me a " 1pm to 9pm tomorrow " for example ill also have that yaml in "template.ymal" for anyone to copy as well

Im not good at making documents so the following was made by chatgpt and tbh the code as well as there was also no docs with the og code i used

## Overview
The Filter Calendar add-on for Home Assistant allows you to create a virtual calendar that displays a curated set of events based on specific filters. This add-on is useful for combining and simplifying calendar views, focusing only on relevant events, or excluding unnecessary ones.

## Features
- Filter events from an existing calendar using keywords.
- Include or exclude specific types of events.
- Combine consecutive or overlapping events into a single event.
- Automatically update the filtered calendar periodically.

## Installation
1. Copy the `filter_calendar.py` file into your Home Assistant `custom_components` directory.
   - Path: `config/custom_components/filter_calendar/filter_calendar.py`
2. Restart Home Assistant.
3. Add the configuration below to your `configuration.yaml` file.

## Configuration
The Filter Calendar requires specific parameters to function correctly.

### Example Configuration
```yaml
calendar:
  - platform: filter_calendar
    name: "Work Calendar"
    tracking_calendar_id: "calendar.work"  # The calendar to filter events from
    filter: "Work"                         # Keyword to match events
    regex: false                            # Whether the filter uses regex
    include_work_types:
      - "Lunch"
      - "One-on-One"
      - "Inbound"                         # Event types to include
    exclude_types:
      - "Public Holiday"
      - "Annual Leave"
      - "Personal Leave"                  # Event types to exclude
```

### Parameters
| Parameter              | Type        | Description                                                                                  |
|------------------------|-------------|----------------------------------------------------------------------------------------------|
| `name`                | string      | The name of the filtered calendar (appears in Home Assistant).                              |
| `tracking_calendar_id` | string      | The ID of the calendar entity to filter events from.                                         |
| `filter`              | string      | A keyword to match events.                                                                  |
| `regex`               | boolean     | Whether the filter uses regex. Set to `true` for regex filtering or `false` for plain text. |
| `include_work_types`  | list[string]| A list of event types to include in the filtered calendar.                                   |
| `exclude_types`       | list[string]| A list of event types to exclude from the filtered calendar.                                 |

### Additional Notes
- Ensure the calendar entity you specify in `tracking_calendar_id` exists in Home Assistant.
- The `filter` parameter determines which events are matched and displayed.
- Use `regex: true` if you want to use advanced matching patterns (e.g., regular expressions).
- Events listed in `exclude_types` will be ignored even if they match the `filter` or `include_work_types` criteria.

## How It Works
1. The add-on retrieves events from the specified calendar.
2. Filters are applied to include only relevant events based on `filter`, `include_work_types`, and `exclude_types`.
3. Consecutive or overlapping events are combined into a single event.
4. The filtered events are displayed as a new virtual calendar entity in Home Assistant.

## Customization
### Adjusting Filters
You can modify the `filter`, `include_work_types`, and `exclude_types` parameters to fine-tune which events appear on your filtered calendar.

### Combining Events
Consecutive or overlapping events are automatically combined into a single event. This behavior is built into the platform and ensures the filtered calendar remains concise and organized.

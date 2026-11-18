"""Integration-owned native Lovelace dashboard; user dashboards are never edited."""

import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA, LovelaceData
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.json import cached_json_fragment, json_fragment
from homeassistant.helpers.translation import async_get_translations

from .const import CONF_DASHBOARD, DOMAIN, NAME
from .coordinator import Coordinator

URL_PATH = "el-overblik-ha"
DATA_KEY = f"{DOMAIN}_dashboard"
_LOGGER = logging.getLogger(__name__)


class Dashboard(LovelaceConfig):
    """Generate native cards on load using current registry IDs and streams."""

    def __init__(self, hass: HomeAssistant, labels: dict[str, str]) -> None:
        super().__init__(
            hass,
            URL_PATH,
            {
                "title": NAME,
                "mode": "yaml",
                "icon": "mdi:lightning-bolt",
                "show_in_sidebar": True,
                "require_admin": False,
            },
        )
        self.owners: dict[str, Coordinator] = {}
        self.labels = labels

    @property
    def mode(self) -> str:
        return "yaml"

    def text(self, key: str) -> str:
        return self.labels[f"component.{DOMAIN}.dashboard.{key}"]

    async def async_get_info(self) -> dict[str, Any]:
        return {"mode": self.mode, "views": len(self.build()["views"])}

    async def async_load(self, force: bool) -> dict[str, Any]:
        return self.build()

    async def async_json(self, force: bool) -> json_fragment:
        return cached_json_fragment(self.build())

    @callback
    def updated(self) -> None:
        self._config_updated()

    def heading(self, text: str, icon: str) -> dict[str, Any]:
        return {
            "type": "heading",
            "heading": text,
            "icon": icon,
            "heading_style": "title",
        }

    def markdown(self, content: str) -> dict[str, Any]:
        return {"type": "markdown", "content": content}

    def build(self) -> dict[str, Any]:
        registry = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        overview: list[dict[str, Any]] = [
            {
                "type": "grid",
                "column_span": 2,
                "cards": [
                    self.heading(NAME, "mdi:lightning-bolt"),
                    self.markdown(self.text("introduction")),
                ],
            }
        ]
        views: list[dict[str, Any]] = []
        for coordinator in self.owners.values():
            for meter, data in coordinator.states.items():
                device = devices.async_get_device_by_identifier(
                    (DOMAIN, meter), coordinator.entry.entry_id
                )
                name = (
                    device.name_by_user if device else None
                ) or f"{self.text('meter')} · {meter[-4:]}"
                entities: dict[str, str] = {}
                for registered in er.async_entries_for_config_entry(
                    registry, coordinator.entry.entry_id
                ):
                    if (
                        registered.unique_id.startswith(f"{meter}_")
                        and not registered.disabled
                    ):
                        entities[registered.unique_id[len(meter) + 1 :]] = (
                            registered.entity_id
                        )

                def tile(
                    key: str, entities: dict[str, str] = entities
                ) -> list[dict[str, Any]]:
                    if key not in entities:
                        return []
                    registered = registry.async_get(entities[key])
                    name = (
                        registered.name
                        if registered and registered.name
                        else self.text(key)
                    )
                    if key == "refresh":
                        return [
                            {
                                "type": "button",
                                "entity": entities[key],
                                "name": name,
                                "show_state": False,
                                "tap_action": {
                                    "action": "perform-action",
                                    "perform_action": "button.press",
                                    "target": {"entity_id": entities[key]},
                                },
                            }
                        ]
                    return [{"type": "tile", "entity": entities[key], "name": name}]

                path = f"meter-{meter[-4:]}-{coordinator.entry.entry_id[:6]}-{coordinator.meters.index(meter)}"
                cards = [self.heading(name, "mdi:meter-electric")]
                for key in (
                    "consumption_day",
                    "consumption_month",
                    "market_price",
                    "cheapest_hour",
                    "energy_cost",
                    "market_difference",
                ):
                    cards.extend(tile(key))
                if "consumption" in data.history.streams:
                    cards.append(
                        {
                            "type": "statistics-graph",
                            "title": self.text("consumption"),
                            "chart_type": "bar",
                            "period": "day",
                            "days_to_show": 14,
                            "stat_types": ["change"],
                            "entities": [
                                {
                                    "entity": f"{DOMAIN}:{meter}_consumption",
                                    "name": self.text("consumption"),
                                }
                            ],
                        }
                    )
                if "stale" in entities:
                    cards.append(
                        {
                            "type": "conditional",
                            "conditions": [
                                {"entity": entities["stale"], "state": "on"}
                            ],
                            "card": self.markdown(self.text("stale_warning")),
                        }
                    )
                cards.append(
                    {
                        "type": "button",
                        "name": self.text("details"),
                        "icon": "mdi:chart-box-outline",
                        "tap_action": {
                            "action": "navigate",
                            "navigation_path": f"/{URL_PATH}/{path}",
                        },
                    }
                )
                overview.append({"type": "grid", "column_span": 2, "cards": cards})
                energy_cards = [
                    self.heading(self.text("energy"), "mdi:chart-bar"),
                    self.markdown(self.text("delayed")),
                ]
                for direction in ("consumption", "production"):
                    for period, days, label in (
                        ("day", 30, "daily"),
                        ("month", 365, "monthly"),
                    ):
                        if direction in data.history.streams:
                            energy_cards.append(
                                {
                                    "type": "statistics-graph",
                                    "title": f"{self.text(direction)} · {self.text(label)}",
                                    "chart_type": "bar",
                                    "period": period,
                                    "days_to_show": days,
                                    "stat_types": ["change"],
                                    "entities": [
                                        {
                                            "entity": f"{DOMAIN}:{meter}_{direction}",
                                            "name": self.text(direction),
                                        }
                                    ],
                                }
                            )
                    for period in ("day", "month", "year"):
                        energy_cards.extend(tile(f"{direction}_{period}"))
                if not data.history.streams:
                    energy_cards.append(self.markdown(self.text("awaiting_history")))
                if "consumption_month" in entities:
                    entity = entities["consumption_month"]
                    energy_cards.append(
                        self.markdown(
                            self.text("coverage") + "\n\n"
                            f"{{{{ state_attr('{entity}', 'reported_hours') }}}} / "
                            f"{{{{ state_attr('{entity}', 'expected_hours') }}}} h\n\n"
                            f"{{{{ state_attr('{entity}', 'covered_through') or '—' }}}}"
                        )
                    )
                price_cards = [
                    self.heading(self.text("market"), "mdi:chart-timeline-variant"),
                    self.markdown(self.text("price_basis")),
                ]
                if "market_price" in entities:
                    price_cards.extend(tile("market_price"))
                    price_cards.extend(tile("cheapest_hour"))
                    cheap = entities.get("cheapest_hour")
                    if cheap:
                        price_cards.append(
                            self.markdown(
                                self.text("cheapest") + "\n\n"
                                f"{{% set start = state_attr('{cheap}', 'start') %}}"
                                f"{{% set end = state_attr('{cheap}', 'end') %}}"
                                "{% if start and end %}"
                                "{{ as_local(as_datetime(start)).strftime('%d/%m %H:%M %z') }} — "
                                "{{ as_local(as_datetime(end)).strftime('%H:%M %z') }}"
                                "{% else %}" + self.text("unpublished") + "{% endif %}"
                            )
                        )
                    for day in ("today", "tomorrow"):
                        price_cards.append(self.schedule(entities["market_price"], day))
                else:
                    price_cards.append(self.markdown(self.text("configure_prices")))
                cost_cards = [
                    self.heading(self.text("costs"), "mdi:cash-multiple"),
                    self.markdown(self.text("cost_basis")),
                ]
                for key in ("energy_cost", "market_cost", "market_difference"):
                    cost_cards.extend(tile(key))
                if "energy_cost" in entities:
                    entity = entities["energy_cost"]
                    cost_cards.append(
                        self.markdown(
                            "{% set reason = state_attr('"
                            + entity
                            + "', 'status') %}\n"
                            + "\n".join(
                                "{% "
                                + ("if" if i == 0 else "elif")
                                + f" reason == '{reason}' %}}"
                                + self.text(reason)
                                for i, reason in enumerate(
                                    (
                                        "configure_contract",
                                        "incomplete_energy",
                                        "outside_contract",
                                        "unsupported_period",
                                        "incomplete_prices",
                                        "ready",
                                    )
                                )
                            )
                            + "{% endif %}\n\n"
                            + self.text("comparison_period")
                            + "\n\n"
                            + f"{{{{ state_attr('{entity}', 'period_start') or '—' }}}} — "
                            + f"{{{{ state_attr('{entity}', 'period_end') or '—' }}}}\n\n"
                            + self.text("effective")
                            + ": "
                            + f"{{{{ state_attr('{entity}', 'effective') or '—' }}}}"
                        )
                    )
                else:
                    cost_cards.append(self.markdown(self.text("configure_prices")))
                health_cards = [self.heading(self.text("health"), "mdi:heart-pulse")]
                for key in (
                    "status",
                    "last_success",
                    "latest_measurement",
                    "stale",
                    "import_status",
                    "refresh",
                ):
                    health_cards.extend(tile(key))
                if "import_status" in entities:
                    entity = entities["import_status"]
                    health_cards.append(
                        self.markdown(
                            self.text("import_progress")
                            + "\n\n"
                            + f"{{{{ state_attr('{entity}', 'completed_through') or '—' }}}}"
                            + " / "
                            + f"{{{{ state_attr('{entity}', 'end') or '—' }}}}\n\n"
                            + self.text("import_failures")
                            + ": "
                            + f"{{{{ state_attr('{entity}', 'failed_meter_count') or 0 }}}}\n\n"
                            + f"{{{{ state_attr('{entity}', 'error') or '' }}}}"
                        )
                    )
                if "market_price" in entities:
                    entity = entities["market_price"]
                    health_cards.append(
                        self.markdown(
                            self.text("price_health")
                            + "\n\n"
                            + f"{{{{ state_attr('{entity}', 'fetched_at') or '—' }}}}\n\n"
                            + f"{{{{ state_attr('{entity}', 'latest_published_interval_end') or '—' }}}}\n\n"
                            + f"{{{{ state_attr('{entity}', 'market_error') or '' }}}}"
                        )
                    )
                views.append(
                    {
                        "title": name,
                        "path": path,
                        "type": "sections",
                        "max_columns": 2,
                        "subview": True,
                        "sections": [
                            {"type": "grid", "cards": section}
                            for section in (
                                energy_cards,
                                price_cards,
                                cost_cards,
                                health_cards,
                            )
                        ],
                    }
                )
        return {
            "title": NAME,
            "views": [
                {
                    "title": self.text("overview"),
                    "path": "overview",
                    "type": "sections",
                    "max_columns": 2,
                    "sections": overview,
                },
                *views,
            ],
        }

    def schedule(self, entity: str, day: str) -> dict[str, Any]:
        return self.markdown(
            f"### {self.text(day)}\n"
            f"{{% set day = state_attr('{entity}', '{day}') %}}"
            "{% if day and day.complete %}\n"
            + self.text("range")
            + ": {{ '%.3f' | format(day.minimum) }} / "
            "{{ '%.3f' | format(day.average) }} / {{ '%.3f' | format(day.maximum) }} DKK/kWh\n"
            "{% endif %}\n"
            + "<details><summary>"
            + self.text("schedule")
            + "</summary>\n\n"
            + "| "
            + self.text("time")
            + " | DKK/kWh |\n| --- | ---: |\n"
            "{% if day %}{% for interval in day.intervals %}"
            "| {{ as_local(as_datetime(interval.start)).strftime('%H:%M %z') }} "
            "| {{ '%.3f' | format(interval.price) }} |\n"
            "{% endfor %}{% endif %}\n"
            "{% if not day or not day.complete %}"
            + self.text("unpublished")
            + "{% endif %}"
            + "\n</details>"
        )


async def async_setup_dashboard(hass: HomeAssistant, coordinator: Coordinator) -> None:
    """Register only an owned URL; opt-out never touches unrelated dashboards."""
    if not coordinator.entry.options.get(CONF_DASHBOARD, True):
        return
    if LOVELACE_DATA not in hass.data:
        _LOGGER.info(
            "El-Overblik HA dashboard requires the Lovelace frontend; energy entities remain available"
        )
        return
    lovelace: LovelaceData = hass.data[LOVELACE_DATA]
    labels = await async_get_translations(
        hass, hass.config.language, "dashboard", {DOMAIN}
    )
    dashboard = hass.data.get(DATA_KEY)
    if dashboard is None:
        if URL_PATH in lovelace.dashboards or frontend.async_panel_exists(
            hass, URL_PATH
        ):
            _LOGGER.error(
                "Cannot create El-Overblik HA dashboard: URL /%s is already in use",
                URL_PATH,
            )
            return
        dashboard = Dashboard(hass, labels)
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=URL_PATH,
            sidebar_title=NAME,
            sidebar_icon="mdi:lightning-bolt",
            config={"mode": "yaml"},
            require_admin=False,
        )
        lovelace.dashboards[URL_PATH] = dashboard
        hass.data[DATA_KEY] = dashboard
    dashboard.owners[coordinator.entry.entry_id] = coordinator
    coordinator.entry.async_on_unload(coordinator.async_add_listener(dashboard.updated))

    @callback
    def registry_updated(event: Event[Any]) -> None:
        dashboard.updated()

    for event_type in (
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ):
        coordinator.entry.async_on_unload(
            hass.bus.async_listen(event_type, registry_updated)
        )
    dashboard.updated()

    @callback
    def remove() -> None:
        dashboard.owners.pop(coordinator.entry.entry_id, None)
        if not dashboard.owners:
            frontend.async_remove_panel(hass, URL_PATH)
            lovelace.dashboards.pop(URL_PATH, None)
            hass.data.pop(DATA_KEY, None)
        else:
            dashboard.updated()

    coordinator.entry.async_on_unload(remove)

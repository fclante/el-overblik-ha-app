# El-Overblik HA

A read-only custom integration for Denmark's [ElOverblik Customer API](https://docs.eloverblik.dk/en/docs/api/customer).

**Requires Home Assistant Core 2026.11.2 or newer.** Automated integration tests run against Core 2026.11.2, including its real recorder and entity registries. No separate Home Assistant OS app/add-on, MQTT broker, or external service is needed.

[Læs denne side på dansk](docs/da/README.md).

## Features

- Multiple explicitly selected metering points; one Home Assistant device per meter.
- Consumption and production history as hourly external statistics for the Energy dashboard.
- Latest reported interval, most recent complete day, and reported month/year energy summaries.
- Meter number, supplier, grid operator, settlement method, and available annual estimates/limits.
- Reported tariff schedules, subscriptions and fees; dated charge queries where the deployed API supports them.
- Last fetch/measurement timestamps, quality/coverage, import progress, and stale-data warnings.
- Resumable historical import, correction-aware statistics, reauthentication, and meter reconfiguration.
- Danish and English translations using Home Assistant's native language settings.

**This is delayed reporting, not a live meter reader.** Measurements may arrive several days late. A successful cloud request does not mean today's measurements are available.

## Install

### Home Assistant Marketplace

1. In Home Assistant, open **Settings > Marketplace > Add from link**.
2. Add `https://github.com/fclante/el-overblik-ha-app` and install **El-Overblik HA**.
3. Restart Home Assistant if prompted.
4. Open **Settings > Devices & services > Add integration > El-Overblik HA**.

Marketplace availability through **Add from link** does not mean this project has been accepted into a default catalog.

### Manual

Copy [`custom_components/eloverblik_data`](custom_components/eloverblik_data) to your Home Assistant configuration directory's `custom_components/eloverblik_data`, restart Home Assistant, and add the integration.

The display name is **El-Overblik HA**. The technical domain, storage keys, statistic IDs and archive filename retain `eloverblik_data` for compatibility with existing installations. Existing default entry titles are updated on setup; custom titles are preserved.

## Configure

In [ElOverblik](https://eloverblik.dk), create/activate a **Customer API refresh token** and ensure your metering points are already linked to your account.

Enter:

- **Refresh token**: the Customer API refresh token, not a temporary data-access token.
- **Metering-point IDs**: comma-separated 18-digit IDs, for example `001234567890123456,001234567890123457` (synthetic examples).

IDs remain strings, preserving leading zeros. Whitespace and duplicate IDs are normalized. The integration validates access and refuses overlapping meters across its own entries. It never creates or deletes ElOverblik meter relations.

Use **Reconfigure** to change meters or replace the token. Authentication failures also offer HA's reauthentication flow. Removed meters retain historical statistics and their integration-managed history cache.

### Language

Choose **Dansk** or **English** in your Home Assistant user profile's language settings. Integration forms, errors, repairs, entity translations, and action descriptions follow HA's native translation behavior. English is the fallback for other languages and missing translations.

There is deliberately no separate integration language switch. Persisted entity names follow HA's standard naming behavior; changing profile language does not recreate identities/statistics or overwrite custom entity names.

### Options

- Default history: the previous 12 calendar months at initial import.
- Choose an explicit history start date or **Import all available history**.
- API retention: previous five calendar years plus the current year, additionally limited by ownership/access and upstream availability.
- Refresh: every six hours by default, configurable from one to 24 hours.

History is imported in background chunks; setup does not wait for a complete backfill. Watch **Historical import** and **Data status**. An access-period error stops the affected import rather than silently skipping inaccessible dates. Select an authorized start date if necessary.

## Energy dashboard

After readings have been imported, select the appropriate **statistic**, not a summary sensor:

```text
eloverblik_data:<metering_point_id>_consumption
eloverblik_data:<metering_point_id>_production
```

Find these under HA's statistics tools and the Energy dashboard's source selectors.

- Use verified consumption meters as grid-consumption sources.
- Production is a distinct source-reported stream. Check your meter's purpose before selecting it as grid export or solar generation: production, grid export, inverter generation and self-consumption are **not interchangeable**.
- Child meters are not automatically added. Do not select overlapping parent/child sources or the same meter from another ElOverblik integration.
- Summary sensors are snapshots without a statistics state class. They intentionally do not feed a second energy total into recorder.
- Month/year summaries expose reported and expected hours, completeness, estimated hours, and coverage timestamps. Limited history is not presented as a complete calendar total.
- Missing/incomplete readings are not filled with zero. Unsupported coarse/profiled intervals are flagged rather than distributed into imaginary hourly values.

The integration does not modify your Energy dashboard configuration.

## Tariffs and costs

**No complete bill, current DKK/kWh total, VAT adjustment, or historical cost estimate is calculated in this release.** The current schema does not sufficiently establish all unit, billing-period, VAT, and charge-category semantics needed for safe arithmetic.

Instead, the integration exposes:

- Optional, disabled-by-default tariff entities identifying reported schedules.
- Optional subscriptions/fees showing their source-reported DKK price, with quantity, validity and native period metadata. These are not amounts assumed to be due now or converted into daily/monthly costs.
- `get_charges`: cached tariffs, source price arrays, subscriptions and fees.
- `get_charge_schedule`: dated charge links, factors, classifications and price intervals from the newer dated-charge endpoint.

**Live API finding:** the documented dated-charge endpoint returned HTTP 404 during an authorized read-only check. The action reports this limitation explicitly, and does not substitute today's charges for historical ones. Current charges and hourly energy were successfully retrieved and parsed.

`cost_status: unsupported_semantics` makes the calculation limitation explicit. Tariff entities do not assert that a source price is the currently applicable rate. Future schedules are available only when returned by ElOverblik.

Do not multiply old consumption by today's tariff or use a current-price entity to price delayed historical measurements. ElOverblik charges do not establish your complete spot-price/supplier contract. Cost estimation remains gated until source semantics can be verified; unknown components are never treated as zero.

## Actions

Actions return response data. In an automation/script, use `response_variable`. The entry ID is selectable in Developer Tools' action form.

### Import or reconcile history

```yaml
action: eloverblik_data.import_history
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  start: "2026-01-01"
  end: "2026-02-01"
response_variable: import_job
```

The end date is exclusive. Returns a job ID immediately; the import sensor reports completion/failure. One history job runs per entry. Use this action for corrections older than the automatic reconciliation horizon.

### Retrieve reported charges

```yaml
action: eloverblik_data.get_charges
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  metering_points:
    - "001234567890123456"
response_variable: reported_charges
```

Omit `metering_points` to include all configured meters. The response is a cached source snapshot, not an invoice.

### Retrieve dated charge information

```yaml
action: eloverblik_data.get_charge_schedule
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  metering_points:
    - "001234567890123456"
  start: "2026-11-01T00:00:00+01:00"
  end: "2026-11-02T00:00:00+01:00"
response_variable: charge_schedule
```

Use timezone-aware timestamps, at most 31 days, and at most 10 configured meters per request. Per-meter upstream errors remain explicit in the returned response.

## Reliability and privacy

- Metadata/charges refresh daily. Recent energy is checked on each poll.
- Normal polls revisit 14 days; weekly reconciliation revisits 90 days. Older corrections require the history action.
- API time-series requests use at most 31 days and batches of at most 10 meters.
- All entries share request spacing and token-exchange throttling. Access tokens are reused for almost 24 hours. HTTP 429/503 retries wait at least one minute and honor longer valid Retry-After values.
- Internally, readings use UTC; Danish calendar summaries use Europe/Copenhagen, including 23/25-hour DST days.
- Canonical hourly readings and import checkpoints are persisted with HA's storage helpers. Statistics are updated idempotently; earlier imports/corrections rebase later cumulative values.
- Your refresh token is stored in HA's normal config-entry storage, **not an independently encrypted vault**. Protect HA's configuration and backups.
- Meter history/cache also resides in HA's configuration storage. Removing the integration does not automatically erase historical statistics or per-meter history caches.
- Diagnostics export an allowlist of operational metadata, excluding tokens, full meter IDs, contact data and raw customer responses. Logs do not include credentials or raw response bodies.

## Troubleshooting

- **Invalid token:** ensure it is active and issued for Customer API. Create a replacement in ElOverblik and reauthenticate.
- **Meter access lost:** check meter relations and authorized dates in ElOverblik. The integration cannot grant access.
- **No current readings:** inspect latest measurement and completeness; delayed reporting is not necessarily a failure.
- **API unavailable/rate limited:** wait for the bounded retry cycle. Repeated refreshes do not accelerate upstream reporting.
- **Historical import failed:** inspect the import error and meter status; retry an authorized, narrower period.
- **Production mapping unclear:** verify the metering-point type/topology before configuring Energy sources.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, all validation commands, contribution guidance, and the release process. In brief, development requires Python 3.14.2+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run pytest -q
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components scripts
uv run python scripts/release.py check
```

Before preparing an archive, run `uv run python scripts/release.py build --output "$(mktemp -d)/eloverblik-dist"`. This is a local dry run: it validates versions and the archive without committing or contacting a network service.

Tests use synthetic API responses and do not require credentials, production meters, or live network access. Never commit tokens, full meter IDs, personal data, or raw customer responses.

## Community

This is an independent community integration; it is not affiliated with or endorsed by ElOverblik or Home Assistant. Please read the [Code of Conduct](CODE_OF_CONDUCT.md), [Contributing Guide](CONTRIBUTING.md), and [Security Policy](SECURITY.md) before participating. Issues and pull requests are welcome, but do not include tokens, full meter IDs, personal data, or unredacted API responses. **Do not report a security vulnerability in a public issue.** Private vulnerability reporting must be enabled before release; see the security policy for the current status.

This project is MIT-licensed, Copyright (c) 2026 fclante; see [LICENSE](LICENSE). See the [release process](docs/RELEASING.md) for automation, safeguards, and administrator prerequisites.

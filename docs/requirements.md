# Project: Home Climate Monitor

Implement a lightweight, self-hosted, mobile-first PWA for monitoring temperature and humidity throughout an apartment using inexpensive Bluetooth Low Energy (BLE) sensors.

The application must run entirely locally, without external cloud dependencies, and be deployable through Docker Compose in Portainer.

## 1. Technology stack

**Frontend**
- Vue 3 + TypeScript + Vite
- Apache ECharts + vue-echarts
- Tailwind CSS 4
- Vue Router
- vue-i18n (Czech and English)
- PWA with service worker

**Backend**
- Python + FastAPI
- Bleak for Bluetooth Low Energy communication
- Pydantic for configuration validation
- SQLite for application data and settings
- InfluxDB 3 Core for time-series measurements
- Web Push using VAPID

**Deployment**
- Docker Compose
- Two runtime containers: application and InfluxDB 3 Core
- Static frontend served by FastAPI
- Persistent Docker volumes
- Compatible with Debian 13, Intel N100, 16 GB RAM
- Deployable and manageable through Portainer
- No Redis, Celery, PostgreSQL or unnecessary services

Use `uv` for Python dependency management.

## 2. BLE sensor integration

The application will initially use five inexpensive CX0726B Bluetooth temperature/humidity sensors with LCD displays.

The communication protocol is not yet verified and may require reverse engineering.

Design a modular sensor integration layer that supports multiple BLE protocols.

Requirements:

- BLE device discovery and identification
- Support BLE advertisements and GATT communication
- Associate physical sensors with logical sensor IDs
- Store temperature and relative humidity
- Track the timestamp of the last received measurement
- Detect disconnected or inactive sensors
- Configurable sampling/storage interval, default 15 minutes
- Avoid unnecessarily frequent BLE connections to preserve battery life
- Automatically reconnect and recover from temporary errors
- Support future sensor models through additional drivers

Provide a diagnostic mode that logs raw BLE advertisements, manufacturer data, service data and GATT characteristics.

Do not invent or assume the CX0726B protocol. Implement the collector interface and diagnostics first, then finalize decoding using real captured data.

## 3. InfluxDB 3 Core

Use InfluxDB 3 Core for historical time-series data.

Store at minimum:

- Timestamp (UTC)
- Sensor ID
- Room ID at measurement time
- Temperature in °C
- Relative humidity in %
- Data source and optionally signal strength

Requirements:

- SQL-based querying
- Historical measurements
- Aggregations by hour, day, week and month
- Configurable time ranges
- Support historical comparisons between rooms
- Unlimited retention by default
- Preserve data during application upgrades
- Handle missing measurements correctly

Use the official InfluxDB 3 Python client where appropriate.

The application should distinguish between the measurement timestamp and ingestion timestamp when necessary.

## 4. SQLite application database

SQLite stores all application configuration and metadata.

Suggested entities:

- Users
- UserSettings
- Sensors
- Rooms
- Floorplans
- AlertRules
- AlertEvents
- PushSubscriptions

Do not store historical temperature measurements in SQLite.

Use database migrations and persistent storage.

## 5. Mobile-first PWA

The application should feel like a polished native mobile application.

Requirements:

- Responsive, mobile-first layout
- Installable PWA
- Light, dark and system theme
- Czech and English localization
- Bottom navigation on mobile
- Desktop-friendly responsive layout
- Fast loading and minimal resource consumption
- Offline application shell
- Clearly indicate when live measurements are unavailable
- HTTPS-compatible deployment
- Accessible controls and touch-friendly interactions

## 6. Main dashboard

The home screen displays:

- Current average apartment temperature
- Current average apartment humidity
- Number of active/available sensors
- Individual room temperature and humidity
- Last measurement timestamp
- Sensor availability
- Interactive apartment floorplan

Use a clean, modern design with excellent typography, spacing and subtle animations.

## 7. Interactive apartment floorplan

The apartment floorplan is one of the application's primary features.

Render it using SVG.

Each room is represented by a polygon and can have an arbitrary shape.

The floorplan must support two visualization modes:

**Temperature heatmap**
- Color each room according to its current temperature
- Cold rooms: blue
- Comfortable temperatures: green
- Warm rooms: yellow/orange
- Configurable color thresholds

**Humidity heatmap**
- Color each room according to relative humidity
- Low humidity: yellow
- Normal humidity: green
- High humidity: blue
- Configurable color thresholds

Each room displays its current measurement.

Clicking/tapping a room opens detailed statistics and historical charts.

Sensor locations should be visible as optional markers.

Do not attempt complex spatial interpolation. Each room uses a single color derived from its assigned sensor measurements.

Provide a historical timeline slider to visualize how the floorplan heatmap changed over time.

## 8. Floorplan mini editor

Implement a lightweight built-in floorplan editor using Vue 3 and native SVG.

The editor must be usable without modifying application source code.

Features:

- Create, rename and delete rooms
- Draw arbitrary room polygons
- Drag and edit polygon vertices
- Move and resize room geometry
- Grid overlay
- Snap to grid
- Configure dimensions in meters
- Place and move sensors
- Assign sensors to rooms
- Undo/redo
- Zoom and pan
- Touch support
- Save changes directly to SQLite

The editor and dashboard should reuse the same SVG rendering components.

The editor does not need advanced CAD capabilities.

## 9. Floorplan import/export

Support JSON import and export of floorplan definitions.

JSON should contain:

- Schema version
- Floorplan name
- Coordinate units
- Room definitions
- Room polygons
- Sensor positions
- Logical sensor assignments

Requirements:

- Versioned JSON schema
- Validate imports using Pydantic
- Preview changes before importing
- Atomic configuration updates
- Preserve existing measurement history
- Keep stable room and sensor IDs
- Export the complete current floorplan
- Support future schema migrations

Updating a floorplan must not require rebuilding or restarting the application.

## 10. Historical charts

Use Apache ECharts for all historical visualizations.

Required functionality:

- Temperature over time
- Humidity over time
- Compare multiple rooms
- Enable/disable individual data series
- Time ranges: 24 hours, 7 days, 30 days and custom
- Interactive tooltips
- Zooming and panning
- Minimum, maximum and average values
- Responsive charts optimized for mobile

Use efficient server-side aggregation for large time ranges.

## 11. Alert rules

Users can configure temperature and humidity monitoring rules.

Each rule contains:

- Room or sensor
- Measurement type
- Above/below threshold
- Minimum duration before triggering
- Hysteresis/reset threshold
- Enabled/disabled state

Examples:

- Notify when bedroom temperature exceeds 24 °C for 15 minutes
- Notify when pantry temperature exceeds 18 °C
- Notify when humidity exceeds 70 %
- Notify when a sensor has not reported for 30 minutes

Avoid repeated notifications while a condition remains active.

Maintain an alert history in SQLite.

## 12. Web Push notifications

Implement standards-based Web Push.

Requirements:

- VAPID authentication
- Push subscriptions stored in SQLite
- Multiple devices per user
- Per-device push enable/disable
- Background notifications when PWA is closed
- Notification permission management
- Subscription cleanup
- Test notification feature

Push delivery must not depend on the frontend being open.

No proprietary push-notification SaaS.

## 13. User settings

Provide a simple settings screen.

Settings include:

- Language: Czech / English
- Theme: Light / Dark / System
- Push notification preferences
- Temperature/humidity display preferences
- Heatmap color thresholds
- Sensor management
- Floorplan management
- Alert rules

Settings should persist in SQLite and synchronize across devices for authenticated users.

## 14. Future extensibility

Design the system so the following features can be added later without major architectural changes:

- Sleep-quality correlation analysis using smartwatch data
- Temperature and humidity correlations
- Fermentation temperature monitoring
- Additional BLE sensor models
- Historical CSV export
- Multiple floorplans
- Additional notification channels

Do not implement these future features unless required by the core architecture.

## 15. Docker and deployment

Provide a production-ready Docker Compose configuration suitable for Portainer.

Requirements:

- Multi-stage Docker build
- Build Vue frontend into static assets
- Serve frontend through FastAPI
- Persistent SQLite database
- Persistent InfluxDB 3 data
- BLE access through host BlueZ/D-Bus
- Environment-based configuration
- Health checks
- Automatic container restart
- Proper logging
- Non-hardcoded secrets
- Clear README deployment instructions

Use only two runtime containers unless an additional service is technically necessary.

Document Linux Bluetooth permissions and Docker device access.

Avoid privileged containers if possible.

## 16. Development requirements

- Clean, maintainable architecture
- Python type annotations
- TypeScript strict mode
- Ruff for Python linting and formatting
- ESLint for frontend
- Automated tests for critical logic
- API documentation through FastAPI OpenAPI
- Clear separation of BLE drivers, application services and persistence
- No unnecessary abstractions or enterprise-level complexity

## 17. Implementation approach

Work in logical stages:

1. Initialize project structure, Docker Compose, backend and frontend.
2. Implement SQLite models, migrations and settings.
3. Implement InfluxDB 3 integration.
4. Build the responsive Vue dashboard using realistic mock measurements.
5. Implement SVG floorplan renderer, heatmap and mini editor.
6. Implement floorplan JSON import/export.
7. Implement historical ECharts visualizations.
8. Implement BLE discovery, diagnostics and pluggable collector architecture.
9. Implement alert rules and Web Push.
10. Add tests, documentation and deployment validation.

Use mock sensor data during development so the application can be developed and tested before the physical devices arrive.

Prioritize a polished UI, reliability, low resource consumption and simplicity.

Before implementing, briefly review the proposed architecture, identify any important technical limitations and create a concise implementation plan. Then proceed with implementation without requiring confirmation for routine technical decisions.
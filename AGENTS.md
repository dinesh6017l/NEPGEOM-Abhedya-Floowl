# Agent Notes

## Fast setup
- Enter dev shell with `nix-shell` (Python + Flask deps + sqlite3 are provided).
- `shell.nix` asks `Would you like to run the website now?`; answer `n` to avoid auto-start.
- Run server with `python backend/server.py` (serves on `0.0.0.0:3000`, browse `http://localhost:3000`).

## Required local files
- Create `api/config.json` with `{"MAPBOX_KEY": "pk...."}`; without it, frontend shows token warning and map never initializes.
- `api/config.json` is gitignored; treat it as local-only config.
- `backend/database.sqlite` auto-creates on first import of `server.py` (line 453 calls `init_db()` at module load time); it is gitignored.

## Architecture that matters
- Single backend entrypoint: `backend/server.py` (Flask) also serves static `frontend/` via `/` and `/<path>`.
- Frontend is plain static files (`frontend/index.html`, `frontend/app.js`, `frontend/style.css`); no frontend package/tooling.
- Region river overlay path in `frontend/app.js`: selecting/editing a region triggers live ArcGIS river fetch (`POST /api/rivers` for bounds while editing, `GET /api/regions/<id>/rivers` for persisted regions), then renders GeoJSON lines in both Mapbox source and Three.js custom layer.
- ArcGIS query constants in `backend/server.py:18-19`: min span 0.06°, padding ratio 0.45 — these affect how much river data is fetched for small regions.
- `cache/` (root) and `backend/cache/` exist on disk; both are gitignored. `cache/` is used by `export-tif` and `simulate` endpoints to store generated GeoTIFFs and metadata.

## API contract (GeoJSON, not raw lng/lat)
- `GET /api/locations`, `GET /api/regions` return `FeatureCollection`.
- `POST /api/locations` accepts `{name, geometry: Point}` or legacy `{name, lng, lat}`.
- `POST /api/regions` and `PUT /api/regions/<id>` accept `{name, geometry: Polygon}` or bounds `{minLng,minLat,maxLng,maxLat}`.
- Rivers endpoints are live ArcGIS FeatureServer queries returning GeoJSON `LineString` features: `GET /api/regions/<id>/rivers` (saved region geometry) and `POST /api/rivers` (ad-hoc bounds/polygon). No file cache; no `/api/cache-status` endpoint.
- `POST /api/export-tif` accepts bounds `{minLng,minLat,maxLng,maxLat}`, downloads Mapbox satellite tiles, stitches them into a GeoTIFF (EPSG:4326, 3-band uint8), and saves to `cache/`. Frontend "Export TIF" button appears during region edit.
- `POST /api/simulate` accepts same bounds, downloads ArcGIS WorldElevation Terrain ImageServer tiles using `ARCGIS_API` from `api/config.json`, decodes them to elevation, and computes a normalized velocity field (u/v components via DEM gradient). Saves 2-band GeoTIFF + JSON metadata + depth grayscale PNG to `cache/`. Frontend "Run Simulation" button appears during region edit and overlays the depth PNG on the Mapbox GL map.

## Database schema
- `locations(id, name, geometry TEXT)` — geometry is GeoJSON `Point`.
- `region(id, name, geometry TEXT)` — geometry is GeoJSON `Polygon`.

## Verification
- No test/lint/typecheck config exists; verify behavior manually while server is running.
- Minimum regression pass: add/delete a location, create/update/delete a region, click a region to load rivers, then drag region edit handles and confirm river overlay updates dynamically.
- Focused DB checks:
  - `sqlite3 backend/database.sqlite 'select id,name,json_extract(geometry, "$.type") from locations;'`
  - `sqlite3 backend/database.sqlite 'select id,name,json_extract(geometry, "$.type") from region;'`

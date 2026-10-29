# Region map data schema

This folder contains a portable static region-map viewer. This project uses it
for California MeshCore regions generated from meshcore-settings. An organization
may copy `map.html`, publish an `index.json` beside it, and host each referenced
GeoJSON file locally or on a separate HTTPS origin.

`index.json` is the public authority for the map title and each region's
identity and coordination status. GeoJSON supplies geometry, coordinator data,
and optional descriptive/provenance data.

## `index.json`

The manifest must be a JSON object containing a `regions` array. Each region
item represents one map layer and must include `id` and `file`. Use a `name`
and `short_name` for every item; these are used for stable layer names, colors,
the legend, and popup content.

```json
{
  "title": "Example Mesh Region Map",
  "regions": [
    {
      "id": "example",
      "name": "Example Mesh Region",
      "short_name": "EXAMPLE",
      "region_type": "Regional",
      "coordination_status": "coordinated_external",
      "coordination_label": "Coordinated External Region",
      "file": "example.geojson"
    }
  ]
}
```

### Top-level fields

| Field | Required | Description |
| --- | --- | --- |
| `title` | Recommended | Map title shown in the browser tab and map key. |
| `regions` | Yes | Array of region-layer objects. |

### Region fields

| Field | Required | Description |
| --- | --- | --- |
| `id` | Yes | Stable, unique region identifier. It overrides every GeoJSON feature's `id`. |
| `name` | Recommended | Human-readable region name. |
| `short_name` | Recommended | Short region code shown on the map. |
| `region_type` | No | Boundary category shown in popups. |
| `optional` | No | When `true`, labels the layer as optional. It does not affect visibility. |
| `visible` | No | When `false`, a regular layer is hidden by default but available in the layer control. Defaults to `true`. Draft `subregion` layers are controlled by the SoCal view instead. |
| `legend` | No | When `false`, a regular layer is omitted from the map key. Defaults to `true`. Subregions appear in their own key while the SoCal view is open. |
| `overlay_group` | No | `region` marks a state-level region; `subregion` marks an area revealed by the SoCal drill-in. Omit for ordinary independent layers. |
| `proposed_code` | No | Suggested human-readable MeshCore scope name displayed for a region. It is not an assignment or radio configuration. |
| `area_code_hints` | No | Array of approximate telephone area-code mnemonics. They are neither geographic boundary definitions nor routing aliases. |
| `legacy_reference` | No | When `true`, a legacy reference appears in location results only when its layer is enabled. |
| `color` | No | Six-digit hexadecimal color (`#RRGGBB`) used for the region boundary and key. |
| `coordination_status` | Recommended | Public status controlling the badge and boundary style. If omitted, the viewer uses `extrapolated_external`. |
| `coordination_label` | No | Optional text for the status badge. The viewer supplies a standard label when omitted. |
| `file` | Yes | Local GeoJSON filename/path or an absolute `https://` GeoJSON URL. |

Use one of these stable values for `coordination_status`:

| Value | Meaning in this viewer |
| --- | --- |
| `official_new_england` | Official New England Mesh Region |
| `official_local` | Official region of the organization hosting the map |
| `political_boundaries` | Political Boundaries |
| `proposed` | Proposed Region |
| `coordinated_external` | Coordinated External Region |
| `extrapolated_external` | Suggested External Region |

Local `file` paths resolve relative to the region-map directory. Absolute URLs
allow a coordinator to operate their own GeoJSON endpoint:

```json
{
  "id": "ny",
  "name": "New York",
  "short_name": "NY",
  "coordination_status": "coordinated_external",
  "file": "https://nyme.sh/regions/nyc.geojson"
}
```

`index.json` is strict JSON, so do not add comments to it.

When a `socal` layer and `subregion` entries are present, the viewer opens in
the **Original** statewide view. Select **SoCal proposal** to highlight the revised
parent region, then click it to reveal subdivisions. **State view** or a click
outside SoCal returns to the statewide proposal. Set `visible: false` and `legend: false` on subdivision
entries for compatibility with generic viewers. A shared URL can include
`view=proposal` or `view=socal`, as well as the existing `lat`, `lng`, and
`z` parameters for an inspected location. The drill-in is disabled if the
manifest does not contain both the parent and subdivisions.

## GeoJSON files

Each `file` must return a GeoJSON `FeatureCollection` with a `features` array.
Polygon or multipolygon features are typical for regions. Point features are
used for local-area dots. For a one-region polygon file, `index.json` overrides
feature identity. For the `local-areas` point collection, each feature keeps its
own `id`.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "boundary_basis": "Coordinator-defined operating area",
        "coordinator": "mesh-coordinator",
        "notes": "Reviewed July 2026",
        "source": "Example Mesh regional coordinators"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-73.9, 42.7], [-73.2, 42.7], [-73.2, 43.1], [-73.9, 43.1], [-73.9, 42.7]]]
      }
    }
  ]
}
```

Feature properties such as `kind`, `boundary_basis`, `notes`, `draft`,
`source`, and `coordinator` may be included. The GeoJSON `coordinator` value is
authoritative and is shown as plain text in popups; the viewer ignores a
coordinator value in `index.json`. For other ordinary properties, the manifest
value wins when both sources provide one.

Do not use `coordination_status`, `coordination_label`, or
`coordination_notes` in GeoJSON to declare public status. The viewer discards
those fields and derives status only from `index.json`.

## Hosting on another website

An external host must serve the GeoJSON over HTTPS and allow the map site's
origin with CORS, for example:

```text
Access-Control-Allow-Origin: https://newenglandme.sh
```

`Access-Control-Allow-Origin: *` also works for public GeoJSON. The endpoint
must return a successful HTTP response and `application/geo+json` or
`application/json` is recommended. If CORS is missing or the endpoint is down,
the browser will block the request and the map will show a loading error.

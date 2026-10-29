# California MeshCore Region Map

Standalone Leaflet map of the California MeshCore region tree. It reuses the
[New England Mesh](https://newenglandme.sh/regions/map) region-map viewer and
builds polygons from the places in
[meshcore-settings](https://github.com/matkam/meshcore-settings).

The site is static HTML plus GeoJSON. Serve the `public/` folder locally, then
deploy that same folder later.

## Look at it locally

If `public/regions/` already contains `index.json` and GeoJSON files:

```bash
python3 -m http.server 8080 --directory public
```

Then open [http://localhost:8080/](http://localhost:8080/) or
[http://localhost:8080/regions/map.html](http://localhost:8080/regions/map.html).

Do not open `map.html` as a `file://` URL. The viewer fetches JSON, so it needs
an HTTP server.

## What is on the map

- **Region map** switches between **Original** and **SoCal proposal**. Original
  uses the region geometry and labels saved from upstream revision
  `85a26cfc2e39`. The proposal first shows the statewide map with the revised
  SoCal region highlighted. Click SoCal to reveal its 17 draft subdivisions;
  click outside SoCal or select **State view** to return to the statewide
  proposal. Select **Original** to compare the upstream boundaries. Links
  preserve the selected view and any clicked location.
- Hover or tap the three northern SoCal boundary segments to highlight each
  shared edge and read its terrain rationale. These are planning guides, not
  verified RF viewsheds.
- **Sampled Coverage** and **Sampled Topology** can be turned on independently.
  Both start off and remain selected when switching map views. The compressed,
  display-only coverage shapes show a generalized 927.875 MHz handheld
  prediction for selected sites, not the full network. The average ITM model includes
  terrain, vegetation, and structures for a five-foot outdoor receiver; its
  shapes summarize a grid of approximately 0.0067 degrees in five margin bands.
  Topology shows reported paths on that network, which are not necessarily
  direct RF links.
- **Other nested areas** that claim county outlines remain in the layer control,
  hidden until you turn them on. In the proposal, former SoCal county areas are
  labeled legacy references and appear in location results when enabled.
- **California** is an optional statewide overlay.

Hover over a visible region to see its broad-to-local region hierarchy; click
or tap the map for the same names and more detail. The displayed names are the
map's proposed or mapped scopes, not a live device configuration. Each level
is a separately defined scope; a message uses one selected level, as described
in MeshCore's
[region-filtering guidance](https://blog.meshcore.io/2026/01/20/region-filtering).
Clicking also lists region polygons that contain the point and reverse-geocodes
the place name. Layer selection and zoom remain available in both views.

## SoCal proposal and naming

The SoCal outline leaves San Luis Obispo and the Five Cities in Central Coast,
with Santa Maria and Nipomo on the SoCal side as a potential bridge. The coastal
transition crosses the low Nipomo Mesa corridor; inland it follows an
elevation-guided line near Newsom Ridge before joining the San Emigdio and
Tehachapi ranges, near Tejon Pass and Tehachapi Pass. Its continuation across
the northern Mojave toward the Avawatz and Clark ranges joins separate ranges.
The coastal gap and Mojave connections are not continuous ridgelines or
verified RF barriers. Neighboring Central Coast, Central Valley and Sierra
Nevada layers and affected legacy areas were adjusted to avoid overlaps; their
changed boundaries are draft too.

The 17 areas interpret an initial community sketch using population centers and
terrain. A 0.0125-degree grid used terrain-weighted paths between centers, then
the polygons were clipped to SoCal. Approximate population totals were checked
against the European Commission JRC [GHS-POP R2023A, 2020, 30 arc-second
grid](https://human-settlement.emergency.copernicus.eu/ghs_pop2023.php)
([DOI](https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE));
they are grid estimates, not census counts or optimization targets. These
polygons are a starting point for community review, not calculated RF coverage,
verified line of sight, or agreed operating regions. Repeater sites, antennas,
frequency, obstructions and traffic should inform revisions.
The revised Santa Maria and Nipomo estimate sums native 30-arc-second cells
whose centers fall inside that draft polygon.

The key proposes descriptive MeshCore names such as `socal-sfv`, `socal-sgv`
and `socal-oc`. Telephone area codes are approximate mnemonics, not boundaries
or routing aliases: 818 and 747 overlap, while 805/820 cover several proposed
regions. Exact scope names must be coordinated; `818` and `socal-sfv` are
different names, not interchangeable aliases. The displayed `region_chain`
describes a proposed configuration hierarchy, not a route string automatically
transmitted by the protocol.

Repeater operators need to coordinate the scopes they configure and forward.
The reference firmware defaults to 32 region entries, adjustable at build time;
check each device's capacity before adopting a full set of subdivisions. See
[`RegionMap.h`](https://github.com/meshcore-dev/MeshCore/blob/main/src/helpers/RegionMap.h).

In current MeshCore, names derive transport keys and scoped packets carry
fixed-size transport codes. The optional transport-code fields total four bytes,
so using `818` rather than `socal-sfv` does not reduce that packet header;
name length may still matter in configuration or messages that include it. See
the [packet format](https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md),
[region matching](https://github.com/meshcore-dev/MeshCore/blob/main/src/helpers/RegionMap.cpp),
and [transport-key calculation](https://github.com/meshcore-dev/MeshCore/blob/main/src/helpers/TransportKeyStore.cpp).

## Rebuild the data

The builder reads `meshcore-settings/data/regions.json` when that sibling repo
is present. Otherwise it uses the copy in `data/regions.json`.

```bash
cd region-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python build_census_boundaries.py
python build_regions.py
```

Census county files are downloaded once into `region-tools/`. Region GeoJSON is
written to `public/regions/`. By default, the builder reapplies the curated
SoCal draft from `data/socal-draft/` after generating the county-based layers;
edit those source files when revising the proposal so rebuilds preserve changes.
The northern boundary notes in `boundary-notes.geojson` should be updated when
their traced edges change.
Shared subregion fields live in `manifest.json`'s `subregion_defaults`; generated
JSON is compact. The Original comparison reuses unchanged GeoJSON files and
stores only changed files in `original-regions.json`. If another region changes,
save its original data there first; the snapshot test checks against the saved
upstream revision.
Before replacing files, the builder checks that the source tree's top-level
county assignments and affected nested outlines match the draft's saved
baseline. A custom tree that changes them needs revised geometries and baseline,
or `python build_regions.py --no-socal-draft` for county-based output. An
unrelated custom tree without a `socal` region is left unchanged.

To point at another tree:

```bash
python build_regions.py --regions /path/to/regions.json
```

Run the draft rebuild checks from the repository root after installing the
builder requirements:

```bash
python -m unittest discover -s tests
python region-tools/check_region_topology.py
```

The topology check uses Shapely to validate polygon geometry and verify that the
seven statewide areas cover California and the 17 subdivisions cover SoCal
without gaps or overlaps. It can also check a different output folder with
`--regions-dir /path/to/regions`.

## Deploy later

Host the contents of `public/` as a static site. GitHub Pages, Cloudflare
Pages, Netlify, or any object store with a public website will work. `public/`
already includes `.nojekyll` for GitHub Pages.

If this map and the GeoJSON files are on different origins, the GeoJSON host
must send CORS headers. See `public/regions/SCHEMA.md`.

#!/usr/bin/env node
/**
 * County-line guess for the Pacific Northwest hierarchy and the Utah / Idaho trees.
 *
 * Regional scopes tile each state. City scopes cover the counties of the
 * communities named in the tree. Counties the tree does not name stay on the
 * parent regional scope. Cross-border scopes (pdx's Clark County reach, inw,
 * palouse, salishmesh) overlap those tiles on purpose.
 */

import { execFile } from "node:child_process";
import { copyFile, mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { area } from "@turf/area";
import { feature, featureCollection } from "@turf/helpers";
import { pointOnFeature } from "@turf/point-on-feature";
import { simplify } from "@turf/simplify";
import { truncate } from "@turf/truncate";
import { union } from "@turf/union";
import { read as readShapefile } from "shapefile";

const execFileAsync = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CACHE = path.join(ROOT, "region-tools", "cache");
const CENSUS_YEAR = 2024;
const CENSUS_ZIP = `cb_${CENSUS_YEAR}_us_county_5m.zip`;
const CENSUS_URL = `https://www2.census.gov/geo/tiger/GENZ${CENSUS_YEAR}/shp/${CENSUS_ZIP}`;

const UTAH = "49";
const IDAHO = "16";
const WASHINGTON = "53";
const OREGON = "41";
const MONTANA = "30";
const BC = "BC";
const STATE_FP = { ut: UTAH, id: IDAHO, wa: WASHINGTON, or: OREGON, mt: MONTANA, bc: BC };
const US_STATES = new Set([UTAH, IDAHO, WASHINGTON, OREGON, MONTANA]);
const BC_GEOJSON = path.join(CACHE, "bc", "districts.geojson");
const BC_URL = "https://openmaps.gov.bc.ca/geo/pub/WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=pub:WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP&srsName=EPSG:4326&outputFormat=json";

const nodes = [
  backbone("imw", "Intermountain West", "Backbone scope above both state tags. Drawn as the two states together."),
  state("ut", "Utah", "imw", "#1f4b3a", "State scope. The five regional scopes below tile Utah."),
  state("id", "Idaho", "imw", "#1e3a5f", "State scope. Southwest, southern, and eastern Idaho follow the Intermountain tree. The panhandle follows the Pacific Northwest hierarchy."),
  alias("pnw-boi", "Pacific Northwest — Boise only", "boi", "In the Intermountain tree, Boise is the Idaho scope that also carries pnw."),

  region("n-ut", "Brigham City, Logan, Tremonton", "ut", "#3d7ea6", ["Box Elder", "Cache", "Rich"],
    "Box Elder and Cache counties hold Brigham City, Tremonton, and Logan. Rich County stays on n-ut as the rest of the northern tier."),
  region("wf", "Wasatch Front", "ut", "#7eae93", ["Weber", "Davis", "Salt Lake", "Utah", "Tooele"],
    "The urban corridor from Ogden through Utah County, plus Tooele County on the west desert. Ogden, Salt Lake, and Utah County have their own city scopes."),
  region("wb", "Wasatch Back: Park City, Heber, Vernal", "ut", "#c6a24a", ["Morgan", "Summit", "Wasatch", "Duchesne", "Uintah", "Daggett"],
    "Summit and Wasatch counties hold Park City and Heber. Duchesne, Uintah, and Daggett carry that scope across the Uinta Basin to Vernal. Morgan sits east of Ogden, behind the Wasatch."),
  region("c-ut", "Nephi, Moab, Beaver, Richfield", "ut", "#d4844a", ["Juab", "Sanpete", "Millard", "Sevier", "Beaver", "Piute", "Wayne", "Carbon", "Emery", "Grand", "San Juan"],
    "Juab, Sevier, Beaver, and Grand counties match the named towns. The counties between them, including Millard, Sanpete, Carbon, Emery, and San Juan, stay on c-ut."),
  region("s-ut", "Southern Utah", "ut", "#c45b6a", ["Iron", "Garfield", "Washington", "Kane"],
    "Southern Utah splits into Cedar City and St. George. Garfield and Kane counties are the eastern portion of those two scopes."),

  local("ogd", "Ogden, Layton, Bountiful, Plain City", "wf", "#1f8a5b", ["Weber", "Davis"],
    "Weber and Davis counties: Ogden, Plain City, Layton, and Bountiful."),
  local("slc", "Salt Lake City, Draper, West Jordan", "wf", "#2f62d6", ["Salt Lake"],
    "Salt Lake County, including Salt Lake City, West Jordan, and Draper."),
  local("utc", "Lehi, Provo, Santaquin", "wf", "#7a4ea3", ["Utah"],
    "Utah County, from Lehi through Provo to Santaquin."),
  local("ced", "Cedar City", "s-ut", "#d2543c", ["Iron", "Garfield"],
    "Iron County holds Cedar City. Garfield County (Panguitch and Bryce) is grouped here as the closest southern scope."),
  local("stg", "St. George", "s-ut", "#a8326a", ["Washington", "Kane"],
    "Washington County holds St. George. Kane County (Kanab) is grouped with it along the Arizona line."),

  region("sw-id", "Southwest Idaho", "id", "#6f93c4", ["Ada", "Canyon", "Gem", "Boise", "Payette", "Washington", "Adams", "Valley", "Elmore", "Owyhee"],
    "Southwest Idaho. Ada and Canyon counties are the Boise metro; Emmett, Payette, Weiser, McCall, Mountain Home, and the Owyhee desert stay on sw-id."),
  region("s-id", "Southern Idaho", "id", "#d4a24a", ["Blaine", "Camas", "Cassia", "Gooding", "Jerome", "Lincoln", "Minidoka", "Twin Falls"],
    "South-central Idaho: the Wood River valley and the Magic Valley."),
  region("e-id", "Eastern Idaho", "id", "#c4785a", ["Bannock", "Power", "Oneida", "Franklin", "Bear Lake", "Caribou", "Bingham", "Bonneville", "Jefferson", "Butte", "Clark", "Custer", "Lemhi", "Madison", "Fremont", "Teton"],
    "Eastern Idaho. The Snake River cities have their own scopes. Butte, Clark, Custer, and Lemhi counties stay on e-id."),
  local("boi", "Boise, Meridian, Nampa, Caldwell", "sw-id", "#1d4e89", ["Ada", "Canyon"],
    "Ada and Canyon counties: Boise, Meridian, Nampa, and Caldwell. This is the scope that also carries pnw.", ["pnw"]),
  local("twf", "Twin Falls, Gooding, Jerome, Mini-Cassia, Magic Valley", "s-id", "#e0a100", ["Twin Falls", "Gooding", "Jerome", "Lincoln", "Minidoka", "Cassia", "Camas"],
    "Magic Valley counties: Twin Falls, Gooding, Jerome, Lincoln, Minidoka, and Cassia, plus Camas County on the north edge."),
  local("sun", "Sun Valley, Blaine County", "s-id", "#e6b325", ["Blaine"],
    "Blaine County: Sun Valley, Ketchum, and Hailey."),
  local("pih", "Pocatello, Chubbuck, Malad, Soda Springs", "e-id", "#b86a2a", ["Bannock", "Power", "Oneida", "Franklin", "Bear Lake", "Caribou"],
    "Bannock, Oneida, and Caribou counties match Pocatello, Malad, and Soda Springs. Power, Franklin, and Bear Lake stay with them as the rest of the southeast corner."),
  local("ida", "Idaho Falls, Blackfoot", "e-id", "#e07a5f", ["Bonneville", "Bingham", "Jefferson"],
    "Bonneville and Bingham counties hold Idaho Falls and Blackfoot. Jefferson County (Rigby) stays with Idaho Falls."),
  local("mad", "Rexburg", "e-id", "#3f9a78", ["Madison", "Fremont", "Teton"],
    "Madison County holds Rexburg. Fremont and Teton counties (St. Anthony and Driggs) stay up-valley on mad."),

  region("cda", "Coeur d'Alene / N. Idaho panhandle", "id", "#2a9d8f", ["Boundary", "Bonner", "Kootenai", "Benewah", "Shoshone"],
    "From the Pacific Northwest hierarchy. Boundary, Bonner, Kootenai, Benewah, and Shoshone counties: Sandpoint, Coeur d'Alene, and the Silver Valley.", "pnw"),
  region("n-id", "Northern Idaho (Moscow, Lewiston, Clearwater)", "id", "#4f7d4a", ["Latah", "Nez Perce", "Lewis", "Clearwater", "Idaho"],
    "From the Pacific Northwest hierarchy. The Palouse and Clearwater are the local scope; Idaho County stays on n-id.", "pnw"),
  local("lws", "Lewiston / Moscow / Clearwater", "n-id", "#7cb342", ["Latah", "Nez Perce", "Lewis", "Clearwater"],
    "From the Pacific Northwest hierarchy. Latah, Nez Perce, Lewis, and Clearwater counties.", ["pnw"], "pnw"),
  campus("uofi", "University of Idaho, Moscow campus", "n-id", "#3d2a6d", 46.726, -117.013,
    "Campus-only scope from the Pacific Northwest hierarchy. Drawn as the Moscow campus, inside lws.", "pnw"),

  backbone("west", "Western US / SW Canada", "Root scope for this preview. Drawn as the Pacific Northwest scopes plus Utah and Idaho."),
  backbone("pnw", "Pacific Northwest", "Washington, Oregon, southern British Columbia, the Flathead, northern Idaho, and the Boise metro. Southern and eastern Idaho stay on imw except for Boise."),
  state("wa", "Washington", "pnw", "#1d3557", "State scope. Five regional scopes tile Washington."),
  state("or", "Oregon", "pnw", "#1b4332", "State scope. Portland, the Willamette, the coast, southern Oregon, and central Oregon tile the state."),
  state("bc", "British Columbia (southern)", "pnw", "#1a365d", "Southern coast only: the Lower Mainland and Vancouver Island. The interior and the north are outside this hierarchy."),
  region("mt", "Montana (partial)", "pnw", "#6b5b95", ["Flathead", "Lake", "Glacier", "Lincoln", "Sanders"],
    "Partial on purpose. Flathead, Lake, and Glacier counties are the Flathead Valley scope. Lincoln and Sanders stay on mt so the northwest corner is not left off the map.", "pnw"),
  local("fca", "Flathead Valley / Kalispell / Glacier", "mt", "#4a3f78", ["Flathead", "Lake", "Glacier"],
    "Flathead and Lake counties hold Kalispell and Flathead Lake. Glacier County stays with them for the park side of the valley.", [], "pnw"),

  region("w-wa", "Western Washington", "wa", "#3d6ea8", ["King", "Pierce", "Snohomish", "Thurston", "Kitsap", "Grays Harbor", "Pacific", "Clallam", "Jefferson", "Mason", "Island", "San Juan", "Skagit", "Whatcom"],
    "Puget Sound and the coast. The Olympic Peninsula, Hood Canal, Whidbey, and the San Juans stay on w-wa outside the named city scopes.", "pnw"),
  region("sw-wa", "Southwest Washington", "wa", "#2f8f6b", ["Lewis", "Cowlitz", "Clark", "Skamania", "Wahkiakum"],
    "Lewis and Cowlitz have city scopes. Clark, Skamania, and Wahkiakum stay on sw-wa. Clark County also sits inside the Portland metro outline.", "pnw"),
  region("c-wa", "Central Washington", "wa", "#c48a2a", ["Yakima", "Chelan", "Douglas", "Kittitas", "Grant", "Okanogan", "Klickitat"],
    "Yakima, Wenatchee, Ellensburg, and Ephrata have city scopes. Douglas County stays with Wenatchee. Okanogan and Klickitat stay on c-wa.", "pnw"),
  region("e-wa", "Eastern Washington", "wa", "#8d5a3b", ["Spokane", "Stevens", "Pend Oreille", "Ferry", "Lincoln", "Adams"],
    "Spokane and the counties north and west of it. The WSU Pullman tag is a campus dot here even though Pullman the city is in se-wa.", "pnw"),
  region("se-wa", "Southeastern Washington", "wa", "#b85c38", ["Walla Walla", "Columbia", "Whitman", "Asotin", "Garfield", "Benton", "Franklin"],
    "Walla Walla, the Palouse, and the Tri-Cities. Columbia County stays with Walla Walla.", "pnw"),

  local("sea", "Seattle / Tacoma / Bellevue", "w-wa", "#1d4e89", ["King", "Pierce", "Snohomish"],
    "King, Pierce, and Snohomish counties.", [], "pnw"),
  local("oly", "Olympia / Lacey / Tumwater", "w-wa", "#3d7ea6", ["Thurston"],
    "Thurston County.", [], "pnw"),
  local("kit", "Kitsap / Bremerton / Silverdale", "w-wa", "#5b4b8a", ["Kitsap"],
    "Kitsap County.", [], "pnw"),
  local("grh", "Grays Harbor / WA coast", "w-wa", "#2a9d8f", ["Grays Harbor", "Pacific"],
    "Grays Harbor and Pacific counties, the outer coast south of the Olympic Peninsula.", [], "pnw"),
  local("bvs", "Skagit Valley / Mount Vernon / Anacortes", "w-wa", "#3f8f4a", ["Skagit"],
    "Skagit County.", [], "pnw"),
  local("bli", "Bellingham / Whatcom County", "w-wa", "#1f7a4d", ["Whatcom"],
    "Whatcom County.", [], "pnw"),
  local("cls", "Centralia / Chehalis", "sw-wa", "#6aaa3a", ["Lewis"],
    "Lewis County.", [], "pnw"),
  local("kls", "Kelso / Longview", "sw-wa", "#7cb342", ["Cowlitz"],
    "Cowlitz County.", [], "pnw"),
  local("ykm", "Yakima", "c-wa", "#e0a100", ["Yakima"],
    "Yakima County.", [], "pnw"),
  local("eat", "Wenatchee", "c-wa", "#d4844a", ["Chelan", "Douglas"],
    "Chelan County holds Wenatchee. Douglas County stays with it for East Wenatchee.", [], "pnw"),
  local("eln", "Ellensburg", "c-wa", "#c46b2f", ["Kittitas"],
    "Kittitas County.", [], "pnw"),
  local("eph", "Ephrata", "c-wa", "#b8860b", ["Grant"],
    "Grant County. Ephrata is the named seat; Moses Lake is in the same county.", [], "pnw"),
  local("geg", "Spokane metro", "e-wa", "#8b3a3a", ["Spokane"],
    "Spokane County.", [], "pnw"),
  campus("wsu", "WSU Pullman campus", "e-wa", "#981e32", 46.7319, -117.166,
    "Campus-only tag. The dot is the Pullman campus. The city around it is puw, under se-wa.", "pnw"),
  local("alw", "Walla Walla", "se-wa", "#c45b6a", ["Walla Walla", "Columbia"],
    "Walla Walla County. Columbia County (Dayton) stays with it.", [], "pnw"),
  local("puw", "Pullman (Whitman, Asotin, Garfield)", "se-wa", "#7a4ea3", ["Whitman", "Asotin", "Garfield"],
    "The Washington side of the Palouse.", [], "pnw"),
  local("psc", "Tri-Cities / Pasco / Kennewick / Richland", "se-wa", "#d2543c", ["Benton", "Franklin"],
    "Benton and Franklin counties.", [], "pnw"),

  region("pdx", "Portland metro (OR + Clark County WA)", "or", "#1a5276", ["Multnomah", "Washington", "Clackamas", "Columbia"],
    "Multnomah, Washington, Clackamas, and Columbia counties, plus Clark County, Washington. Clark also remains inside sw-wa.", "pnw"),
  region("wv", "Willamette Valley", "or", "#2e7d4f", ["Yamhill", "Marion", "Polk", "Benton", "Linn", "Lane"],
    "The valley from Yamhill County through Lane County. Lane includes the Florence side of the coast range.", "pnw"),
  region("s-or", "Southern Oregon", "or", "#b85c38", ["Jackson", "Josephine", "Douglas", "Klamath", "Lake"],
    "Medford, Grants Pass, Roseburg, and Klamath Falls. Lake County stays on s-or.", "pnw"),
  region("coast-or", "Oregon Coast", "or", "#3d7ea8", ["Clatsop", "Tillamook", "Lincoln", "Coos", "Curry"],
    "The coast counties. Curry County, south of Coos Bay, stays on coast-or.", "pnw"),
  region("c-or", "Central Oregon", "or", "#c47b2b", ["Deschutes", "Jefferson", "Crook", "Wheeler", "Grant", "Harney", "Malheur", "Baker", "Union", "Wallowa", "Umatilla", "Morrow", "Gilliam", "Sherman", "Wasco", "Hood River"],
    "Bend, Pendleton, and Baker City have city scopes. The rest of the interior, the Columbia Plateau, and the gorge counties stay on c-or.", "pnw"),
  local("mmv", "McMinnville / Yamhill", "wv", "#6aaa3a", ["Yamhill"],
    "Yamhill County.", [], "pnw"),
  local("sle", "Salem / Keizer", "wv", "#2f8f6b", ["Marion", "Polk"],
    "Marion and Polk counties.", [], "pnw"),
  local("cvo", "Corvallis / Albany", "wv", "#3f6f4a", ["Benton", "Linn"],
    "Benton and Linn counties.", [], "pnw"),
  local("eug", "Eugene / Springfield", "wv", "#1f6b4a", ["Lane"],
    "Lane County.", [], "pnw"),
  local("mfr", "Medford / Ashland", "s-or", "#d35f3b", ["Jackson", "Josephine"],
    "Jackson County holds Medford and Ashland. Josephine County (Grants Pass) stays with the Rogue Valley.", [], "pnw"),
  local("rbg", "Roseburg", "s-or", "#a85b3a", ["Douglas"],
    "Douglas County.", [], "pnw"),
  local("lmt", "Klamath Falls", "s-or", "#8d6a2f", ["Klamath"],
    "Klamath County.", [], "pnw"),
  local("ast", "Astoria / Seaside", "coast-or", "#2a6f8f", ["Clatsop"],
    "Clatsop County.", [], "pnw"),
  local("otk", "Tillamook", "coast-or", "#5aa0c4", ["Tillamook"],
    "Tillamook County.", [], "pnw"),
  local("onp", "Newport / Lincoln City", "coast-or", "#4a90b8", ["Lincoln"],
    "Lincoln County.", [], "pnw"),
  local("oth", "North Bend / Coos Bay", "coast-or", "#1f5f78", ["Coos"],
    "Coos County.", [], "pnw"),
  local("bend", "Bend / Redmond", "c-or", "#e07a3a", ["Deschutes"],
    "Deschutes County. The tag is bend, the short full name used in the hierarchy's quick reference.", [], "pnw"),
  local("pdt", "Pendleton", "c-or", "#c4922a", ["Umatilla"],
    "Umatilla County. Wallowa County operators are described as dual-carrying palouse on this tag; the county itself is drawn with palouse.", [], "pnw"),
  local("bke", "Baker City", "c-or", "#a67c52", ["Baker"],
    "Baker County.", [], "pnw"),

  region("swbc", "Southwest BC / Lower Mainland", "bc", "#2a6f8f", ["Metro Vancouver Regional District", "Fraser Valley Regional District"],
    "Metro Vancouver and the Fraser Valley regional districts.", "pnw"),
  region("vanisle", "Vancouver Island", "bc", "#2f7d4f", ["Capital Regional District", "Cowichan Valley Regional District", "Regional District of Nanaimo", "Regional District of Alberni-Clayoquot", "Comox Valley Regional District"],
    "The island regional districts from the Capital through Comox and the west coast. Mount Waddington and Strathcona also sit with the island, but their official boundaries take in large mainland inlets, so they stay outside this outline.", "pnw"),
  local("southisland", "South Vancouver Island / Victoria", "vanisle", "#1f5c3a", ["Capital Regional District"],
    "Capital Regional District, including Victoria and the southern Gulf Islands.", [], "pnw"),

  overlay("inw", "Inland Northwest", "pnw", "#6b3a5a",
    ["Spokane", "Boundary", "Bonner", "Kootenai", "Benewah", "Shoshone"],
    "Cross-border scope for Spokane and the Idaho panhandle. It overlaps geg and cda."),
  overlay("palouse", "Palouse", "pnw", "#5c6b2f",
    ["Whitman", "Asotin", "Garfield", "Latah", "Nez Perce", "Lewis", "Clearwater", "Wallowa"],
    "Cross-border scope for the Washington Palouse, the Moscow–Lewiston–Clearwater corridor, and Wallowa County."),
  overlay("salishmesh", "Salish Sea / Gulf Islands", "bc", "#3d8ea6", [],
    "A generalized outline of the Gulf Islands between Vancouver Island and the mainland. It overlaps vanisle and the edge of the Lower Mainland.")
];

function backbone(id, name, note) {
  return { id, code: id, name, kind: "backbone", parent: null, color: "#607080", counties: [], note, source: "intermountain" };
}
function state(id, name, parent, color, note) {
  return { id, code: id, name, kind: "state", parent, color, counties: [], note, source: "intermountain" };
}
function alias(id, name, highlight, note) {
  return { id, code: id, name, kind: "alias", parent: null, highlight, color: "#1a4a7a", counties: [], note, source: "intermountain" };
}
function region(id, name, parent, color, counties, note, source = "intermountain") {
  return { id, code: id, name, kind: "region", parent, color, counties, note, source };
}
function local(id, name, parent, color, counties, note, also = [], source = "intermountain") {
  return { id, code: id, name, kind: "local", parent, color, counties, note, also, source };
}
function campus(id, name, parent, color, lat, lon, note, source = "intermountain") {
  return { id, code: id, name, kind: "campus", parent, color, counties: [], lat, lon, note, source };
}
function overlay(id, name, parent, color, counties, note) {
  return { id, code: id, name, kind: "overlay", parent, color, counties, note, source: "pnw", also: [] };
}

const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));

byId.imw.parent = "west";
byId.pnw.parent = "west";
byId.cda.also = ["pnw"];
byId["n-id"].also = ["pnw"];
byId.pdx.extra = [{ fp: WASHINGTON, names: ["Clark"] }];
byId.salishmesh.ring = [
  [-123.62, 48.72], [-123.28, 48.72], [-123.18, 49.02],
  [-123.52, 49.22], [-123.86, 49.16], [-123.78, 48.88], [-123.62, 48.72]
];

byId.ut.counties = ["n-ut", "wf", "wb", "c-ut", "s-ut"].flatMap((id) => byId[id].counties);
byId.id.counties = ["cda", "n-id", "sw-id", "s-id", "e-id"].flatMap((id) => byId[id].counties);
byId.wa.counties = ["w-wa", "sw-wa", "c-wa", "e-wa", "se-wa"].flatMap((id) => byId[id].counties);
byId.or.counties = ["pdx", "wv", "s-or", "coast-or", "c-or"].flatMap((id) => byId[id].counties);
byId.bc.counties = ["swbc", "vanisle"].flatMap((id) => byId[id].counties);
byId.imw.parts = [
  { fp: UTAH, names: byId.ut.counties },
  { fp: IDAHO, names: byId.id.counties }
];
byId.inw.parts = [
  { fp: WASHINGTON, names: ["Spokane"] },
  { fp: IDAHO, names: ["Boundary", "Bonner", "Kootenai", "Benewah", "Shoshone"] }
];
byId.palouse.parts = [
  { fp: WASHINGTON, names: ["Whitman", "Asotin", "Garfield"] },
  { fp: IDAHO, names: ["Latah", "Nez Perce", "Lewis", "Clearwater"] },
  { fp: OREGON, names: ["Wallowa"] }
];
byId.pnw.parts = [
  { fp: WASHINGTON, names: byId.wa.counties },
  { fp: OREGON, names: byId.or.counties },
  { fp: BC, names: byId.bc.counties },
  { fp: MONTANA, names: byId.mt.counties },
  { fp: IDAHO, names: [...byId.cda.counties, ...byId["n-id"].counties, ...byId.boi.counties] }
];
byId.west.parts = [
  ...byId.pnw.parts,
  { fp: UTAH, names: byId.ut.counties },
  { fp: IDAHO, names: byId.id.counties }
];

function assertPartition(label, expectedIds) {
  const seen = new Map();
  for (const id of expectedIds) {
    for (const name of byId[id].counties) {
      if (seen.has(name)) throw new Error(`${label} county ${name} is in both ${seen.get(name)} and ${id}`);
      seen.set(name, id);
    }
  }
  return seen;
}

const utahPieces = assertPartition("Utah", ["n-ut", "wf", "wb", "c-ut", "s-ut"]);
const idahoPieces = assertPartition("Idaho", ["cda", "n-id", "sw-id", "s-id", "e-id"]);
const washingtonPieces = assertPartition("Washington", ["w-wa", "sw-wa", "c-wa", "e-wa", "se-wa"]);
const oregonPieces = assertPartition("Oregon", ["pdx", "wv", "s-or", "coast-or", "c-or"]);

function childCounties(parentId) {
  return nodes.filter((node) => node.parent === parentId && node.kind === "local").flatMap((node) => node.counties);
}

function gapCounties(parentId) {
  const covered = new Set(childCounties(parentId));
  return byId[parentId].counties.filter((name) => !covered.has(name));
}

async function ensureBcDistricts() {
  try {
    await readFile(BC_GEOJSON);
  } catch {
    await mkdir(path.dirname(BC_GEOJSON), { recursive: true });
    const response = await fetch(BC_URL, { headers: { "User-Agent": "meshcore-region-map" } });
    if (!response.ok) throw new Error(`BC boundary download failed: ${response.status}`);
    await writeFile(BC_GEOJSON, Buffer.from(await response.arrayBuffer()));
  }
  return JSON.parse(await readFile(BC_GEOJSON, "utf8"));
}

async function ensureUsCounties() {
  const legacy = path.join(CACHE, `cb_${CENSUS_YEAR}_us_county_5m.shp`);
  try {
    await readFile(legacy);
    return legacy;
  } catch {
    return ensureZip(CENSUS_URL, CENSUS_ZIP, path.join(CACHE, "us"));
  }
}

async function ensureZip(url, filename, destDir) {
  await mkdir(destDir, { recursive: true });
  const zipPath = path.join(destDir, filename);
  try {
    await readFile(zipPath);
  } catch {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Download failed: ${response.status} ${url}`);
    await writeFile(zipPath, Buffer.from(await response.arrayBuffer()));
  }
  const existing = await findShp(destDir);
  if (!existing) await execFileAsync("unzip", ["-o", zipPath, "-d", destDir]);
  const shpPath = await findShp(destDir);
  if (!shpPath) throw new Error(`No shapefile in ${destDir}`);
  return shpPath;
}

async function findShp(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const nested = await findShp(full);
      if (nested) return nested;
    } else if (entry.name.endsWith(".shp")) return full;
  }
  return null;
}

function frameOf(node) {
  let current = node;
  while (current) {
    if (STATE_FP[current.id]) return STATE_FP[current.id];
    current = current.parent ? byId[current.parent] : null;
  }
  return null;
}

function groupsFor(node) {
  if (node.parts) return node.parts;
  const fp = frameOf(node);
  if (!fp) throw new Error(`No geography frame for ${node.id}`);
  const groups = [{ fp, names: node.counties }];
  if (node.extra) groups.push(...node.extra);
  return groups;
}

function dissolve(features) {
  const cleaned = features.map((item) => truncate(item, { precision: 4, coordinates: 2 }));
  const merged = cleaned.length === 1 ? cleaned[0] : union(featureCollection(cleaned));
  if (!merged) throw new Error("Union produced no geometry");
  return truncate(merged, { precision: 4, coordinates: 2 });
}

function labelPoint(geometryFeature) {
  const point = pointOnFeature(geometryFeature);
  return point.geometry.coordinates.map((value) => Number(value.toFixed(4)));
}

async function main() {
  const usShp = await ensureUsCounties();
  const bcCollection = await ensureBcDistricts();
  const usCollection = await readShapefile(usShp, usShp.replace(/\.shp$/, ".dbf"));
  const areas = new Map();
  for (const item of usCollection.features) {
    const state = item.properties.STATEFP;
    if (!US_STATES.has(state)) continue;
    areas.set(`${state}:${item.properties.NAME}`, feature(item.geometry, { name: item.properties.NAME, state }));
  }
  const bcNames = [];
  for (const item of bcCollection.features) {
    const name = item.properties.ADMIN_AREA_NAME;
    const simplified = simplify(feature(item.geometry), { tolerance: 0.012, highQuality: false, mutate: false });
    bcNames.push(name);
    areas.set(`${BC}:${name}`, truncate(simplified, { precision: 4, coordinates: 2 }));
  }

  function take(fp, names) {
    return names.map((name) => {
      const found = areas.get(`${fp}:${name}`);
      if (!found) {
        const hint = fp === BC ? ` BC names include: ${bcNames.sort().join(", ")}` : "";
        throw new Error(`Missing ${fp} area ${name}.${hint}`);
      }
      return found;
    });
  }

  function checkState(state, assigned) {
    const actual = [...areas.keys()].filter((key) => key.startsWith(`${state}:`)).map((key) => key.slice(state.length + 1)).sort();
    const used = [...assigned.keys()].sort();
    const missing = actual.filter((name) => !assigned.has(name));
    const extra = used.filter((name) => !actual.includes(name));
    if (missing.length || extra.length) {
      throw new Error(`County mismatch for ${state}. Missing: ${missing.join(", ") || "none"}. Extra: ${extra.join(", ") || "none"}.`);
    }
  }
  checkState(UTAH, utahPieces);
  checkState(IDAHO, idahoPieces);
  checkState(WASHINGTON, washingtonPieces);
  checkState(OREGON, oregonPieces);
  take(MONTANA, byId.mt.counties);
  take(BC, byId.bc.counties);

  const features = [];
  for (const node of nodes) {
    if (node.kind === "alias") continue;
    if (node.kind === "campus") {
      features.push(feature(
        { type: "Point", coordinates: [node.lon, node.lat] },
        baseProps(node, null)
      ));
      continue;
    }
    const geometry = node.ring
      ? feature({ type: "Polygon", coordinates: [node.ring] })
      : dissolve(groupsFor(node).flatMap((group) => take(group.fp, group.names)));
    const gapNames = node.kind === "region" && !node.parts ? gapCounties(node.id) : [];
    const gapLabel = gapNames.length && gapNames.length < node.counties.length
      ? labelPoint(dissolve(take(frameOf(node), gapNames)))
      : null;
    features.push(feature(geometry.geometry, baseProps(node, {
      area: Math.round(area(geometry)),
      label: labelPoint(geometry),
      gapLabel,
      gapCounties: gapNames
    })));
  }

  const pnwCards = [
    {
      id: "wa",
      title: "Washington",
      rows: rows([
        ["west", 0], ["pnw", 1], ["wa", 2],
        ["w-wa", 3], ["sea", 4], ["oly", 4], ["kit", 4], ["grh", 4], ["bvs", 4], ["bli", 4],
        ["sw-wa", 3], ["cls", 4], ["kls", 4],
        ["c-wa", 3], ["ykm", 4], ["eat", 4], ["eln", 4], ["eph", 4],
        ["e-wa", 3], ["geg", 4], ["wsu", 4],
        ["se-wa", 3], ["alw", 4], ["puw", 4], ["psc", 4]
      ])
    },
    {
      id: "or",
      title: "Oregon",
      rows: rows([
        ["or", 1],
        ["pdx", 2],
        ["wv", 2], ["mmv", 3], ["sle", 3], ["cvo", 3], ["eug", 3],
        ["s-or", 2], ["mfr", 3], ["rbg", 3], ["lmt", 3],
        ["coast-or", 2], ["ast", 3], ["otk", 3], ["onp", 3], ["oth", 3],
        ["c-or", 2], ["bend", 3], ["pdt", 3], ["bke", 3]
      ])
    },
    {
      id: "north",
      title: "British Columbia, Montana, cross-border",
      rows: rows([
        ["bc", 1], ["swbc", 2], ["vanisle", 2], ["southisland", 3], ["salishmesh", 2],
        ["mt", 1], ["fca", 2],
        ["inw", 1], ["palouse", 1]
      ])
    },
    {
      id: "id",
      title: "Idaho scopes in this hierarchy",
      rows: rows([
        ["id", 1], ["n-id", 2], ["lws", 3], ["uofi", 3], ["cda", 2], ["boi", 2]
      ])
    }
  ];
  const imwCards = [
    {
      id: "ut",
      title: "Utah",
      rows: rows([
        ["imw", 0], ["ut", 1],
        ["wf", 2], ["ogd", 3], ["slc", 3], ["utc", 3],
        ["wb", 2], ["n-ut", 2], ["c-ut", 2],
        ["s-ut", 2], ["ced", 3], ["stg", 3]
      ])
    },
    {
      id: "id",
      title: "Idaho",
      rows: rows([
        ["pnw-boi", 0], ["imw", 0], ["id", 1],
        ["sw-id", 2], ["boi", 3],
        ["s-id", 2], ["twf", 3], ["sun", 3],
        ["e-id", 2], ["pih", 3], ["ida", 3], ["mad", 3]
      ]),
      extraHeading: "Panhandle and Palouse, from the Pacific Northwest hierarchy",
      extraRows: rows([
        ["n-id", 2], ["lws", 3], ["uofi", 3],
        ["cda", 2]
      ])
    }
  ];

  const pnwMap = await exportMap(features, {
    dir: path.join(ROOT, "public", "pnw"),
    href: "/pnw",
    title: "Pacific Northwest",
    summary: "County-line guess for the Pacific Northwest hierarchy. Regional scopes tile Washington and Oregon. City scopes cover the named communities. Southern British Columbia is the Lower Mainland and Vancouver Island, Montana is the northwest corner, and Idaho shows the panhandle, Lewis-Clark, Coeur d'Alene, and Boise.",
    source: "https://gessaman.com/meshcore/regions/#proposed-region-hierarchy",
    cards: pnwCards,
    parents: { id: "pnw", boi: "id" },
    notes: {
      west: "Root scope on this map. Drawn as the Pacific Northwest coverage: Washington, Oregon, southern British Columbia, the Flathead, northern Idaho, and Boise.",
      id: "Idaho scopes named in the Pacific Northwest hierarchy: Coeur d'Alene, the panhandle, Lewis-Clark, and Boise. The rest of Idaho is on the Intermountain West map."
    },
    geometries: {
      west: ["pnw"],
      id: ["cda", "n-id", "boi"]
    }
  });
  const imwMap = await exportMap(features, {
    dir: path.join(ROOT, "public", "imw"),
    href: "/imw",
    title: "Intermountain West",
    summary: "County-line guess for the Utah and Idaho trees. Regional scopes tile each state. City scopes cover the named communities. The panhandle names come from the Pacific Northwest hierarchy. Boise is the Idaho scope that also carries pnw.",
    cards: imwCards,
    parents: { imw: null },
    notes: {},
    geometries: {}
  });
  await writeCatalog([pnwMap, imwMap]);
  const preview = path.join(ROOT, "region-tools", "preview-map.html");
  await copyFile(preview, path.join(ROOT, "public", "pnw", "index.html"));
  await copyFile(preview, path.join(ROOT, "public", "imw", "index.html"));
}

function rows(pairs) {
  return pairs.map(([id, depth]) => ({ id, depth }));
}

function chainIds(id) {
  const chain = [];
  let current = byId[id];
  while (current) {
    chain.push(current.id);
    current = current.parent ? byId[current.parent] : null;
  }
  return chain.reverse();
}

function cardIds(cards) {
  return [...new Set(cards.flatMap((card) => [...card.rows, ...(card.extraRows ?? [])].map((row) => row.id)))];
}

async function exportMap(features, spec) {
  const ids = cardIds(spec.cards);
  const idSet = new Set(ids);
  const parentOverrides = spec.parents ?? {};
  const noteOverrides = spec.notes ?? {};

  function parentOf(id) {
    if (Object.prototype.hasOwnProperty.call(parentOverrides, id)) return parentOverrides[id];
    const parent = byId[id].parent;
    return parent && idSet.has(parent) ? parent : null;
  }

  function countiesOf(id) {
    const sources = spec.geometries?.[id];
    if (!sources) return byId[id].counties;
    return [...new Set(sources.flatMap((sourceId) => byId[sourceId].counties ?? []))];
  }

  function chainOf(id) {
    const chain = [];
    let current = id;
    const seen = new Set();
    while (current && idSet.has(current) && !seen.has(current)) {
      seen.add(current);
      chain.push(current);
      current = parentOf(current);
    }
    return chain.reverse();
  }

  const featureById = new Map(
    features
      .filter((item) => idSet.has(item.properties.id))
      .map((item) => [item.properties.id, structuredClone(item)])
  );

  for (const [id, sourceIds] of Object.entries(spec.geometries ?? {})) {
    const pieces = sourceIds.map((sourceId) => featureById.get(sourceId)).filter(Boolean);
    const target = featureById.get(id);
    if (!target || !pieces.length) continue;
    const dissolved = pieces.length === 1 ? pieces[0] : union(featureCollection(pieces));
    target.geometry = structuredClone(dissolved.geometry);
    target.properties.area = Math.round(area(dissolved));
    target.properties.label = labelPoint(dissolved);
  }

  const exportedFeatures = [...featureById.values()].map((item) => {
    item.properties.parent = parentOf(item.properties.id);
    item.properties.chain = chainOf(item.properties.id);
    item.properties.counties = countiesOf(item.properties.id);
    if (noteOverrides[item.properties.id]) item.properties.note = noteOverrides[item.properties.id];
    return item;
  });

  const exportedNodes = Object.fromEntries(ids.map((id) => {
    const node = byId[id];
    return [id, {
      id: node.id,
      code: node.code,
      name: node.name,
      kind: node.kind,
      parent: parentOf(id),
      color: node.color,
      note: noteOverrides[id] ?? node.note,
      source: node.source,
      counties: countiesOf(id),
      also: node.also ?? [],
      highlight: node.highlight ?? null,
      chain: chainOf(id)
    }];
  }));

  const tree = {
    title: spec.title,
    summary: spec.summary,
    source: spec.source ?? null,
    cards: spec.cards,
    nodes: exportedNodes
  };

  await mkdir(spec.dir, { recursive: true });
  await writeFile(path.join(spec.dir, "tree.json"), `${JSON.stringify(tree)}\n`);
  await writeFile(path.join(spec.dir, "regions.geojson"), `${JSON.stringify(featureCollection(exportedFeatures))}\n`);
  console.log(`Wrote ${exportedFeatures.length} features to ${path.relative(ROOT, spec.dir)}`);
  return {
    id: path.basename(spec.dir),
    href: spec.href,
    title: spec.title,
    summary: spec.summary,
    groups: spec.cards.map((card) => ({
      title: card.title,
      note: card.extraHeading ?? null,
      rows: [...card.rows, ...(card.extraRows ?? [])].map((row) => ({
        id: row.id,
        code: exportedNodes[row.id].code,
        name: exportedNodes[row.id].name,
        depth: row.depth,
        kind: exportedNodes[row.id].kind
      }))
    }))
  };
}

function californiaGroups(regionTree, index) {
  const levels = regionTree.levels || [];
  const root = regionTree.root || [];
  const rows = [];

  root.forEach((token, depth) => {
    rows.push({
      id: token.code,
      code: token.code,
      name: token.name,
      depth,
      kind: "root"
    });
  });

  function walk(place, depthBelowRoot) {
    const level = levels[depthBelowRoot];
    rows.push({
      id: place.code,
      code: place.code,
      name: place.name,
      depth: root.length + depthBelowRoot,
      kind: place.kind || (level ? level.name : "place")
    });
    for (const child of place.children || []) walk(child, depthBelowRoot + 1);
  }
  for (const place of regionTree.places || []) walk(place, 0);

  const socalIndex = rows.findIndex((row) => row.id === "socal");
  const draftSubregions = (index?.regions || []).filter((entry) => entry.overlay_group === "subregion");
  if (socalIndex >= 0 && draftSubregions.length) {
    const socalDepth = rows[socalIndex].depth;
    let insertAt = socalIndex + 1;
    while (insertAt < rows.length && rows[insertAt].depth > socalDepth) insertAt += 1;
    rows.splice(
      insertAt,
      0,
      ...draftSubregions.map((entry) => ({
        id: entry.id,
        code: entry.proposed_code || entry.id,
        name: entry.name,
        depth: socalDepth + 1,
        kind: "draft subregion"
      }))
    );
  }

  return [{
    title: "meshcore-settings tree",
    note: "From matkam/meshcore-settings data/regions.yaml. Root tokens prefix every chain. Draft SoCal subregions sit under Southern California after the county references.",
    rows
  }];
}

async function writeCatalog(maps) {
  const index = JSON.parse(await readFile(path.join(ROOT, "public", "regions", "index.json"), "utf8"));
  const regionTree = JSON.parse(await readFile(path.join(ROOT, "data", "regions.json"), "utf8"));
  const catalog = {
    title: "WC Mesh region maps",
    maps: [
      {
        id: "california",
        href: "/california",
        title: "California",
        summary: regionTree.description || index.notes,
        source: "https://github.com/matkam/meshcore-settings/blob/main/data/regions.yaml",
        groups: californiaGroups(regionTree, index)
      },
      ...maps
    ]
  };
  await writeFile(path.join(ROOT, "public", "catalog.json"), `${JSON.stringify(catalog, null, 2)}\n`);
  const count = catalog.maps.reduce((sum, map) => sum + map.groups.reduce((inner, group) => inner + group.rows.length, 0), 0);
  console.log(`Wrote ${count} catalog rows to public/catalog.json`);
}

function baseProps(node, extra) {
  return {
    id: node.id,
    code: node.code,
    name: node.name,
    kind: node.kind,
    parent: node.parent,
    color: node.color,
    note: node.note,
    source: node.source,
    counties: node.counties,
    also: node.also ?? [],
    chain: chainIds(node.id),
    ...extra
  };
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

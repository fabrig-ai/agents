# Peer artifact content pins

2026-10-29 read-only hashes, modes and link metadata from hetzner3 and hel8.
Only the six versioned artifact paths in versions.toml are eligible. Claude's
versions directory was listed: h3 has only the binaries 2.1.310/311/312;
hel8 has only 2.1.302/312. No Claude authentication/config or Codex state is
part of a seed. Codex includes only the named standalone release, not manager
install.lock/history, other releases, authentication or sessions.

| Item | h3 | hel8 | Content agreement / source |
|---|---|---|---|
| nextest 0.9.148 | 53470cfc9b5cbcd96780db2d348700d76af962467503791f1f8a8824d8967e5c | 9c05bd3c7c5da1286b193873f12b37db386485fa483d8fa0554e68a53d9df550 (0.9.137) | different versions; only h3 has the pinned version |
| Claude 2.1.312 | 4f4178ce41d83e23341ebfbaecdbcf8ea6bf7baea0690025abe49eeec3a5d01d | same | agree; h3 preferred |
| Forgejo 17.0.0 | 5a3b07e124ed70b4e46ee3939515f003bd3cc85352257a9a4607a527251042ca | same | agree; h3 preferred |
| runner 13.2.0 | fadaec897f5e6641c363f87ecaf75f866f99c81b7097ec6b433e4c48123fcad1 | same | agree; h3 preferred |
| Codex 0.162.1 standalone | codex.sha256: 44 files, 11 directories, 1 symlink | pinned standalone release absent | h3 only |
| Chromium 147.0.7727.101 | chromium.sha256 (canonical) | different launcher/extensions | h3 only; hel8 excluded |

Chromium has 49 files, 42 directories, one symlink on each peer. All binary
and resource files agree except these two text files:

| File | h3 SHA256 / mode | hel8 SHA256 / mode |
|---|---|---|
| bin/chromium | bd85bf00571aeda9573b75107beb07e1be4fd926068755251058a737e465f7bc / 0775 | c525606b47b76026e93bd7281864e1968b2c5e30239a522498f263098f817dd0 / 0755 |
| etc/chromium.d/extensions | 18bb41255c4a8ece31d7f1d464034157738995822cbb2da413546f3c8023f872 / 0644 | 16af7aa8968c328434526b4c06d8e542571e1600d90d2cedd0349516c96be21b / 0644 |

h3's launcher/config selects the bundle's config/extensions and CHROME_WRAPPER;
hel8's launcher sources /etc/chromium.d and uses system extensions/wrapper.
Builders run browser tests, so h3's tree is canonical in chromium.sha256;
hel8's manifest is removed. Chromium's seed_hosts allowlist contains only h3.
hel8's own copy gets a version-only warning during --check and is never
reinstalled by normal runs. A matching pin is always required for explicit
provisioning; hel8's older nextest will also be refused as a fallback.

## Manifest format

`SHA256  relative/path` is a regular file checksum; `mode OCTAL  relative/path`
pins its mode. `directory OCTAL  relative/path` includes the root `.` and empty
directories. `symlink OCTAL  ["relative/path", "target"]` pins a link without
following it. Exactly one record per node and one mode per regular file is
required. All parents must be listed directories. Absolute/escaping links,
hard links, special files, missing/extra/duplicate entries and privileged modes
are refused. A partial archive cannot be installed.

Only explicit --provision checks these content pins/transfers artifacts.
It first checks local contents without running the tool. Matching files/trees
and links require no writes/SSH; missing links alone are repaired locally.
SSH uses BatchMode, StrictHostKeyChecking=yes and UpdateHostKeys=no. A small
Python standard-library tar exporter opens only explicitly pinned paths through
no-follow directory descriptors; it never recursively archives a parent tree or
opens unlisted files. The receiver streams to private staging, checks tar
headers, every hash, link and mode, then promotes a sibling and recreates links.
No copied program is run before verification. A failed peer can fall back to
another declared seed only if its contents match the exact same pins.
Only seed=true hosts allowed by an optional seed_hosts list are eligible,
and a host never transfers from itself. Chromium allows only hetzner3.

URL remains optional. For a single file it must serve the raw binary whose
SHA256 is the same content pin. A tree URL must serve a tar with the exact pinned
members and declare its archive SHA256 in versions.toml as well; both archive
SHA256 and the full tree manifest are verified. No unverified URL is invented.
A future approved URL takes precedence over peers; verification failure refuses
installation. Source labels above record the survey, not permanent availability.

Direct admin SSH to hel8 lacked trust in this environment, so the read-only
comparison used h3's already trusted SSH connection to hel8. No trust was added
or relaxed. Bootstrap users must arrange their own direct seed access first.

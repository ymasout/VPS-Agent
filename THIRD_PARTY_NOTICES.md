# Third-party notices

VPS Agent depends on third-party packages. Those packages remain under their
own licenses and are not relicensed by this repository's project licenses.
The source-distribution workflow publishes the exact dependency inventory as
`dependency-licenses.json` for every checked revision.

The current dependency graph includes the following less-common licenses:

- `argparse` is available under `Python-2.0`.
  <https://docs.python.org/3/license.html>
- `jackspeak`, `minimatch`, `minipass`, `package-json-from-dist`, and
  `path-scurry` are available under `BlueOak-1.0.0`.
  <https://blueoakcouncil.org/license/1.0.0>
- The language registry data distributed by `language-subtag-registry` is
  available under `ODC-By-1.0` and requires attribution.
  <https://opendatacommons.org/licenses/by/1-0/>

Package names and versions can change. Treat the generated inventory as the
authoritative per-build list and update this notice whenever the policy gate
reports a newly introduced notice-bearing license.

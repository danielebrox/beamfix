# Contributing to BeamFix

Bug reports, reproducible examples and suggestions are welcome. Use English
for project discussions, documentation and program messages. Remove personal
information from diagnostic reports before sharing them.

## Code contributions and licensing

Please open an issue to discuss substantial changes before writing a pull
request. The public project uses GPL-3.0-only. The maintainer also wants to
preserve the option of offering a separately licensed commercial edition.

For now, **third-party copyrightable contributions must not be merged until
an explicit separate written agreement has settled the necessary rights**,
including a non-exclusive right to distribute and sublicense the contribution
under other licenses, including proprietary commercial terms. This applies to
code, documentation and artwork. Contributors retain their copyright unless a
separate agreement explicitly says otherwise.

Opening an issue or pull request does not transfer copyright or automatically
grant commercial relicensing rights. No contributor agreement is implemented
by this document. Discuss the terms with the maintainer before acceptance;
until an agreement exists, code contributions remain pending. Do not submit
material you are not entitled to contribute, and identify third-party material
and its license explicitly.

## Development checks

Use Python 3.11 or later. Run:

```sh
python -m unittest discover -s tests -v
python scripts/build_release.py
python scripts/check_release.py
```

See the README for the isolated D-Bus integration test requirements. Do not
change real display configuration as part of an automated test. Keep the CLI
usable independently of the graphical interface and preserve explicit user
approval and independent recovery for display trials.

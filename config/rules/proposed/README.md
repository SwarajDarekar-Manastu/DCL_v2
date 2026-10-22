# Proposed operator rules (status: PROPOSED, not applied)

Rules drafted by S5 from stream configs and the team's own analysis workbooks, for an SME to
confirm. Lead ruling 2026-10-22: a proposed rule is **never applied by Route C** until an SME
confirms it in the Review UI or the user confirms it in writing; the confirmation turns it into
an operator rule (exported to `config/rules/*.yaml` at the top level). Nothing loads files from
this `proposed/` folder.

Each file is a valid `RulesFile` (`backend/review/rules.py`), so a confirmed rule can be moved to
`config/rules/` unchanged. Content is names, quantities, units and sensor ranges only; no measured
values. The `y*` columns of LabJack LJStreamM files are already scaled by the logger (the
`Scaling=` line of `LJStreamM.cfg`), so the rules carry no further scaling.

| File | Scope (Graph folder id) | Allowlist entry |
|------|-------------------------|-----------------|
| `inj10_cold_flow_channel_map.yaml` | `01RDWVU4ZUFFI75KMFFJEJNIOEECPJM6RB` | E1, Pressure |
| `inj14_flow_test_channel_map.yaml` | `01RDWVU42EH7Y5QREJ4JG2L4QNOWGWUFOJ` | E2 |
| `tp07_firing_channel_map.yaml` | `01RDWVU47SDGRHEBHJIFE3334CSLOVPSL4` | E3, Pressure |

Points for the SME:
- Ambient condition is `UNKNOWN`: gauge-to-absolute conversion needs the test-cell ambient.
- TP7 `y4` has a broken logger scaling (`y=e*`, constant 0); it is left unmapped, so Route C keeps
  a UNIT_AMBIGUITY case open until the SME decides (for example mark the channel unused).
- TP7 `y6` (thrust) reads a constant offset near -28 N and fails the 0-200 N bound; the
  cold-flow chamber channels read about -30 bar and fail the 0-150 bar bound. The rules map them
  honestly; the bounds cases stay open for the SME (golden behaviour cases expect that halt).

# Examples

Pipeline files made with the plugin. Open one in the panel (*Open…*) or run it with DisSCube directly.

| File | Grid | Variables | Run |
|---|---|---|---|
| `brasil_2200m_seats.toml` | Brazil, 2,200 m on the BDC SM tiles, 2491 x 2421 cells | `dist_seats`: distance to the nearest of the 5,570 municipal seats of IBGE (metres) | downloads one small zip from the ANA catalogue; ran with DisSCube 0.6.0 from the panel in QGIS 4.0.1 (Flatpak) |

```bash
disscube run brasil_2200m_seats.toml --workspace data/brasil_2200m --output data/brasil_2200m.tif
```

The files are checked in the tests (`tests/test_examples.py`): the plugin reads them without problems, writes them back
with the same content, and DisSCube accepts them (`disscube validate`).

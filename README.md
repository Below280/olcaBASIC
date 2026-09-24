# olcaBASIC

```
            ___  _     ____    _    ____    _    ____  _  ____
           / _ \| |   / ___|  / \  | __ )  / \  / ___|| |/ ___|
          | | | | |  | |     / _ \ |  _ \ / _ \ \___ \| | |
          | |_| | |__| |___ / ___ \| |_) / ___ \ ___) | | |___
           \___/|_____\____/_/   \_\____/_/   \_\____/|_|\____|
```

**A simplified language to control openLCA, borrowing heavily from
the BASIC programming language (1964)**

olcaBASIC lets LCA practitioners build models, run calculations, and
analyse results without writing Python. It connects to openLCA via the
IPC server and translates simple, readable commands into the full power
of the openLCA calculation engine.

## Quick start

```
pip install olcabasic
```

Start the IPC server in openLCA (Tools > Developer Tools > IPC Server),
then:

```
olcabasic
```

```
olcaBASIC v0.1.0
Connected to openLCA on port 8080 (ecoinvent 3.10)
Ready.

> PRINT PROCESSES("electricity", "", "GB")
  electricity production, wind, 1-3MW | GB
  electricity production, natural gas | GB
  ...

> PRINT METHODS("ReCiPe")
  ReCiPe 2016 Midpoint (H)
  ReCiPe 2016 Endpoint (H)

> CALCULATE "My System" USING "ReCiPe 2016 Midpoint (H)"
  Climate change:    247.3 kg CO2-eq
  Ozone depletion:   3.21e-6 kg CFC-11-eq
  ...
```

## Write programs

Save as `mymodel.baslca` and run with `olcabasic run mymodel.baslca`:

```basic
REM Concrete block EPD model

LET cement_mass = 300
LET water_cement_ratio = 0.45
LET mixing_energy = 12

FLOW "Concrete block", m3, PRODUCT

BRIDGE "BRIDGE | Cement | kg", kg
  FOLDER "00: Concrete/Bridges"
  PROVIDER "cement production, Portland | GB"
END BRIDGE

PROCESS "A1: Raw materials" LOCATION "GB"
  FOLDER "00: Concrete/A1"
  OUTPUT "Concrete block", 1, m3, PRODUCT
  INPUT "BRIDGE | Cement | kg", cement_mass, kg
  INPUT "BRIDGE | Sand | kg", 800, kg
  INPUT "BRIDGE | UK grid | kWh", mixing_energy, kWh
END PROCESS

SYSTEM "A1: Raw materials"
CALCULATE "A1: Raw materials" USING "EN15804+A2 (EF 3.1)"
PRINT RESULTS

SENSITIVITY ON "A1: Raw materials" USING "EN15804+A2 (EF 3.1)" BY 20%
  VARY cement_mass
  VARY mixing_energy
END SENSITIVITY

SCENARIO "Baseline"
END SCENARIO

SCENARIO "Low cement"
  LET cement_mass = 240
END SCENARIO

RUN SCENARIOS ON "A1: Raw materials" USING "EN15804+A2 (EF 3.1)"
SAVE RESULTS "scenarios.csv"
```

## Why?

This exists to make LCA easy to do programmatically. 

There was no sensible reason why we made this. 

## Requirements

- openLCA 2.x with IPC server running (port 8080)
- Python 3.10+
- `b280-olca-mcp` (installed automatically)

## Licence

MPL-2.0

## Links

- [Language specification](./olcaBASIC_Language_Specification_v1.md)
- [B280 openLCA MCP](https://github.com/Below280/B280-olca-MCP)
- [B280 Python IPC tools](https://github.com/Below280/openLCA-IPC-tools-python)
- [Below280](https://below280.com)

*Built by Below280. openLCA is developed by GreenDelta.*
*BASIC was created by Kemeny and Kurtz at Dartmouth College, 1964.*

# Probar SYSTEM-ENGINEERING en otra computadora

La rama `integrate-shema-ai` está publicada en GitHub con los 3 defectos
corregidos. Esta guía sirve para verificarla desde cualquier otra máquina.

En los comandos siguientes, `<repo>` es la ruta donde clonaste el repositorio y
`<proyecto>` el directorio de un proyecto gestionado que ya exista en esa máquina.

## 1. Bajar la rama

```powershell
cd <repo>\SYSTEM-ENGINEERING
git fetch origin --tags --prune
git switch integrate-shema-ai
git log --oneline -3
```

## 2. Probar los 3 defectos corregidos

### Defecto 1 — `se orchestrate` y `se memory` en proyectos externos

```powershell
# Crea una carpeta temporal fuera del repositorio
mkdir C:\tmp\prueba-se
cd C:\tmp\prueba-se

# PROJECT.json mínimo válido
# Luego:
python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py orchestrate create --project C:\tmp\prueba-se --name wf-prueba --nodes nodes.json --edges edges.json
# Esperado: "PASS: created workflow at C:\tmp\prueba-se\workflows\WF-0001.json"

python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py orchestrate execute --project C:\tmp\prueba-se --workflow WF-0001 --dry-run
# Esperado: "Status: DRY_RUN"

python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py memory add --project C:\tmp\prueba-se --type discovery --content '{"topic":"x","detail":"y"}'
# Esperado: "PASS: created MEM-0001"

python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py memory search --project C:\tmp\prueba-se --query "y"
# Esperado: "Returned: 1" y MEM-0001
```

> Todo esto escribe solo en `C:\tmp\prueba-se\`, nunca en el repositorio.

### Defecto 2 — Gates ya no pasan en vacío

```powershell
python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project <proyecto> --gate G3
python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project <proyecto> --gate G4
python <repo>\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project <proyecto> --gate G5
# Esperado: "Gate result: FAIL" (antes G4 pasaba en vacío)
```

### Defecto 3 — `release_master --check` detecta desync de versión/tag

```powershell
python <repo>\SYSTEM-ENGINEERING\SCRIPTS\release_master.py --check --ci
# Esperado: "Release check: OPERATIONAL" (exit 3, advierte pero no bloquea)
```

## 3. Validar que nada se rompió

```powershell
cd <repo>\SYSTEM-ENGINEERING
python TESTS\run_tests.py                           # Esperado: "OK", exit 0
python SCRIPTS\se.py validate                       # Esperado: "VALIDATE: PASS"
python SCRIPTS\se.py doctor                         # Esperado: "FAIL=0"
python SCRIPTS\release_master.py --check --offline  # Esperado: PASS
```

## 4. Estado de la rama

La rama `integrate-shema-ai` está publicada y su pull request pasa CI en
`ubuntu-latest`, `windows-latest` y el smoke del bootstrap en Windows. `main` no
se toca hasta que el pull request se mergee.

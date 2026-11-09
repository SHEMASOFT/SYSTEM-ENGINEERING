# Probar SYSTEM-ENGINEERING en otra computadora

La rama `integrate-shema-ai` ya está en GitHub con los 3 defectos corregidos. Esta guía sirve para verificar desde cualquier otra compu.

## 1. Bajar la rama

```powershell
cd <ruta>\SYSTEM-ENGINEERING
git fetch origin --tags --prune
git switch integrate-shema-ai
git log --oneline -3
```

Debe mostrar `1c277bd` (o superior) como HEAD.

## 2. Probar los 3 defectos corregidos

### Defecto 1 — `se orchestrate` y `se memory` en proyectos externos

```powershell
# Crea una carpeta temporal (NO D:\PERMISOS)
mkdir C:\tmp\prueba-se
cd C:\tmp\prueba-se

# PROJECT.json mínimo válido
# Luego:
python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py orchestrate create --project C:\tmp\prueba-se --name wf-prueba --nodes nodes.json --edges edges.json
# Esperado: "PASS: created workflow at C:\tmp\prueba-se\workflows\WF-0001.json"

python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py orchestrate execute --project C:\tmp\prueba-se --workflow WF-0001 --dry-run
# Esperado: "Status: DRY_RUN"

python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py memory add --project C:\tmp\prueba-se --type discovery --content '{"topic":"x","detail":"y"}'
# Esperado: "PASS: created MEM-0001"

python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py memory search --project C:\tmp\prueba-se --query "y"
# Esperado: "Returned: 1" y MEM-0001
```

> Todo esto escribe solo en `C:\tmp\prueba-se\`, nunca en `D:\PERMISOS`.

### Defecto 2 — Gates ya no pasan en vacío (D:\PERMISOS, solo lectura)

```powershell
python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project D:\PERMISOS --gate G3
python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project D:\PERMISOS --gate G4
python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\se.py gate --project D:\PERMISOS --gate G5
# Esperado: "Gate result: FAIL" (antes G4 pasaba en vacío)
```

### Defecto 3 — `release_master --check` detecta desync de versión/tag

```powershell
python D:\servidor-ia\SYSTEM-ENGINEERING\SCRIPTS\release_master.py --check --ci
# Esperado: "Release check: OPERATIONAL" (exit 3, advierte pero no bloquea)
```

## 3. Validar que nada se rompió

```powershell
cd D:\servidor-ia\SYSTEM-ENGINEERING
python TESTS\run_tests.py          # Esperado: "Ran 1469 tests ... OK", exit 0
python SCRIPTS\se.py validate      # Esperado: "VALIDATE: PASS"
python SCRIPTS\se.py doctor        # Esperado: "PASS=21 WARN=0 FAIL=0"
python SCRIPTS\release_master.py --check --offline  # Esperado: PASS
```

## 4. Conflicto esperado

La rama `integrate-shema-ai` y `p3-complete` tocan ambas `SCRIPTS/se_core/commands.py`. Cuando abras el PR a `main` desde GitHub, puede haber conflicto ahí. Resuélvelo a mano; no fuerces push.

## Estado de GitHub

```
origin/integrate-shema-ai:
1c277bd rebase coverage baseline after integrate-shema-ai merge
3636c95 Merge p3-complete into integrate-shema-ai
710f4a2 fix: resolve external project paths, validate gate records and compare release tags
...
```

`main` no se tocó. Todo quedó en la rama.

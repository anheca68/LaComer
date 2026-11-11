"""Salvaguardas del despliegue al NAS: la base productiva nunca se toca."""

import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "desplegar_nas.sh"


def _codigo_sin_comentarios() -> str:
    return "\n".join(
        linea for linea in SCRIPT.read_text().splitlines() if not linea.lstrip().startswith("#")
    )


def test_script_tiene_sintaxis_valida():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_script_no_usa_comandos_que_borran_la_base():
    codigo = _codigo_sin_comentarios()
    for peligroso in ("down -v", "down --volumes", "volume rm", "volume prune",
                      "system prune", "--pull", "--delete-excluded", "bd_volumen.py importar"):
        assert peligroso not in codigo, f"El despliegue no debe usar '{peligroso}'"


def test_rsync_protege_datos_secretos_y_bases():
    codigo = SCRIPT.read_text()
    for exclusion in ("/data/", "/.env", "*.db", "*.sqlite3", "/.git/"):
        assert f"--exclude={exclusion}" in codigo or f"--exclude='{exclusion}'" in codigo


def test_respalda_antes_de_actualizar_el_codigo():
    codigo = _codigo_sin_comentarios()
    respaldo = codigo.index("bd_volumen.py respaldar")
    assert respaldo < codigo.index("rsync -a --delete $EXCL_REMOTO")
    assert respaldo < codigo.index("$DC build")


def test_repositorio_no_versiona_bases_ni_secretos():
    archivos = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    prohibido = re.compile(r"(\.db|\.sqlite3?|\.db-(wal|shm|journal))$|(^|/)\.env$|^data/|^backups/")
    assert [a for a in archivos if prohibido.search(a)] == []

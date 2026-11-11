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
                      "system prune", "--pull", "--delete-excluded", "--reemplazar", "rm -rf data"):
        assert peligroso not in codigo, f"El despliegue no debe usar '{peligroso}'"


def test_rsync_protege_datos_secretos_y_bases():
    codigo = SCRIPT.read_text()
    for exclusion in ("/data/", "/procesados/", "/.env", "*.db", "*.sqlite3", "*.pdf",
                      "*.csv", "*.bak", "*.tar.gz", "/_backup_*/", "/.git/",
                      "/backend/backups/", "/backend/procesados/", "/backend/resultados/"):
        assert f"--exclude={exclusion}" in codigo or f"--exclude='{exclusion}'" in codigo


def test_respalda_antes_de_actualizar_el_codigo():
    codigo = _codigo_sin_comentarios()
    respaldo = codigo.index("bd_volumen.py respaldar")
    assert respaldo < codigo.index("rsync -a --delete $EXCL_REMOTO")
    assert respaldo < codigo.index("$DC build")


def test_migracion_copia_la_base_antes_de_tocar_el_codigo():
    codigo = _codigo_sin_comentarios()
    copia = codigo.index("cp -p data/despensa.db data/backups/")
    assert copia < codigo.index("rsync -a --delete $EXCL_REMOTO")
    assert copia < codigo.index("bd_volumen.py importar")
    # El original nunca se borra: solo se renombra tras confirmar que la app responde.
    assert "rm data/despensa.db" not in codigo and "rm -f data/despensa.db" not in codigo
    assert codigo.index("/health") < codigo.index("mv data/despensa.db data/despensa.db.migrada")


def test_repositorio_no_versiona_bases_ni_secretos():
    archivos = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    prohibido = re.compile(r"(\.db|\.sqlite3?|\.db-(wal|shm|journal))$|(^|/)\.env$|^data/|^backups/")
    assert [a for a in archivos if prohibido.search(a)] == []

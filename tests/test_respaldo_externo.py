"""Salvaguardas del respaldo al disco externo del NAS."""

import os
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "respaldo_externo.sh"


def _codigo() -> str:
    return "\n".join(
        l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#")
    )


def _ejecutar(tmp_path, montajes: str, *args):
    app = tmp_path / "app"
    (app / "data" / "backups").mkdir(parents=True)
    (app / "data" / "backups" / "despensa_backup_1.db").write_text("bd")
    destino = tmp_path / "externo"
    destino.mkdir()
    archivo_montajes = tmp_path / "mounts"
    archivo_montajes.write_text(montajes.format(destino=destino.resolve()))
    env = dict(os.environ, APP_DIR=str(app), DESTINO_RAIZ=str(destino),
               ARCHIVO_MONTAJES=str(archivo_montajes))
    r = subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)
    return r, destino


def test_sintaxis_valida():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


def test_nunca_borra_en_el_disco_externo_ni_copia_secretos():
    codigo = _codigo()
    for peligroso in ("--delete", "rm -rf", "rm -f", "down -v", "volume rm", ".env"):
        assert peligroso not in codigo, f"El respaldo no debe usar '{peligroso}'"


def test_verifica_el_disco_antes_de_copiar():
    codigo = _codigo()
    copia = codigo.index('$COPIAR "$APP_DIR/data/"')
    assert codigo.index("ARCHIVO_MONTAJES") < copia
    assert codigo.index('"$DISP_DESTINO" != "$DISP_APP"') < copia


def test_se_detiene_si_el_disco_no_esta_montado(tmp_path):
    r, destino = _ejecutar(tmp_path, "/dev/disk1 / apfs rw 0 0\n", "--simular")
    assert r.returncode != 0
    assert "no está en un disco montado" in r.stdout
    assert list(destino.iterdir()) == []


def test_se_detiene_si_el_destino_esta_en_el_mismo_disco(tmp_path):
    # El destino "parece" montado, pero df dice que es el mismo disco que la app.
    r, destino = _ejecutar(tmp_path, "/dev/sdc2 {destino} exfat rw 0 0\n")
    assert r.returncode != 0
    assert "mismo disco que la app" in r.stdout
    assert list(destino.iterdir()) == []

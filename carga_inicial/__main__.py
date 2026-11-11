"""Levanta la herramienta de carga inicial: ``python -m carga_inicial``."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga inicial del histórico de LaComer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    print(f"Carga inicial disponible en http://{args.host}:{args.port}/importar")
    uvicorn.run("carga_inicial.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

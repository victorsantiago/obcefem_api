"""Baixa os CSVs da ANM, processa e grava em dados_processados/ (parquet + meta.json).

É o que alimenta a API no modo pré-processado (Vercel/serverless). Rodado todo dia pelo
GitHub Actions (.github/workflows/atualizar-dados.yml), mas também pode ser rodado à mão:

    python scripts/gerar_dados.py

Só reescreve os arquivos se o conteúdo da ANM mudou (assim o Git não registra commits vazios).
Código de saída: 0 = ok (com ou sem mudança), 1 = falha.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["CFEM_MODO"] = "servidor"                       # aqui sempre baixa e processa
os.environ.setdefault("CFEM_PASTA_CACHE", str(RAIZ / "cache"))

from app import config  # noqa: E402
from app.repositorio import Repositorio, salvar_pre_processado  # noqa: E402


def main() -> int:
    repo = Repositorio()
    resultado = repo.atualizar()
    if resultado["status"] == "erro" or not repo.pronto:
        print(f"Falha ao processar: {resultado.get('erro')}", file=sys.stderr)
        return 1
    if resultado.get("falhas_download"):
        print(f"Portal da ANM indisponível para {resultado['falhas_download']}; nada foi publicado.", file=sys.stderr)
        return 1
    destino = config.PASTA_PRE_PROCESSADO
    gravou = salvar_pre_processado(repo.dados, destino)
    print(f"Versão {repo.dados.versao}: {'dados novos gravados em' if gravou else 'sem mudanças em'} {destino}")
    for nome, info in resultado.get("arquivos", {}).items():
        print(f"  {nome}: origem={info['origem']} conteudo_mudou={info['conteudo_mudou']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

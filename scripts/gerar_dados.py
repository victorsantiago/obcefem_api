"""Atualização diária: baixa o CSV do período corrente (2022–2026) e a autuação, processa e grava em
dados_processados/ (parquet + meta.json). O histórico 2002–2021 fica em dados_processados/historico/
e não é tocado aqui (ver scripts/gerar_historico.py).

Rodado todo dia pelo GitHub Actions (.github/workflows/atualizar-dados.yml), ou à mão:

    python scripts/gerar_dados.py
    python scripts/gerar_dados.py --forcar      # publica mesmo se a trava de segurança disparar

Trava de segurança: se algum ano já encerrado (ex.: 2022–2025) perder mais de 2% do valor em relação
ao que está publicado, ou a região perder registros nesses anos, nada é gravado. Isso protege o site
de um arquivo incompleto no portal da ANM.

Só reescreve os arquivos se o conteúdo mudou (assim o Git não registra commits vazios).
Código de saída: 0 = ok (com ou sem mudança), 1 = falha ou trava acionada.
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["CFEM_MODO"] = "servidor"                       # aqui sempre baixa e processa
os.environ.setdefault("CFEM_PASTA_CACHE", str(RAIZ / "cache"))

from app import config  # noqa: E402
from app.repositorio import Repositorio, salvar_pre_processado  # noqa: E402

QUEDA_MAXIMA = 0.02


def checar_contra_publicado(novo, pasta) -> list[str]:
    """Compara os anos encerrados do arquivo novo com a versão publicada."""
    arq_nac, arq_reg = pasta / "nacional_arrecadacao.parquet", pasta / "regiao_arrecadacao.parquet"
    if not arq_nac.exists():
        return []
    ultimo_ano = novo.cobertura["ultimo_ano"]
    antes_nac = pd.read_parquet(arq_nac, columns=["Ano", "Valor"]).groupby("Ano")["Valor"].sum()
    agora_nac = novo.nacional["arrecadacao"].groupby("Ano")["Valor"].sum()
    antes_reg = pd.read_parquet(arq_reg, columns=["Ano"])["Ano"].value_counts()
    agora_reg = novo.regiao["arrecadacao"]["Ano"].value_counts()
    problemas = []
    for ano in sorted(a for a in antes_nac.index if a < ultimo_ano):
        v0, v1 = float(antes_nac.get(ano, 0)), float(agora_nac.get(ano, 0))
        if v0 > 0 and v1 < v0 * (1 - QUEDA_MAXIMA):
            problemas.append(f"{ano}: arrecadação nacional caiu de R$ {v0/1e9:.2f} bi para R$ {v1/1e9:.2f} bi")
        r0, r1 = int(antes_reg.get(ano, 0)), int(agora_reg.get(ano, 0))
        if r1 < r0:
            problemas.append(f"{ano}: a região tinha {r0} registros e agora tem {r1}")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="publica mesmo se a trava de segurança disparar")
    args = ap.parse_args()

    repo = Repositorio()
    resultado = repo.atualizar()
    if resultado["status"] == "erro" or not repo.pronto:
        print(f"Falha ao processar: {resultado.get('erro')}", file=sys.stderr)
        return 1
    if resultado.get("falhas_download"):
        print(f"Portal da ANM indisponível para {resultado['falhas_download']}; nada foi publicado.", file=sys.stderr)
        return 1
    for nome, info in resultado.get("arquivos", {}).items():
        print(f"  {nome}: origem={info['origem']} conteudo_mudou={info['conteudo_mudou']}")

    novo = repo.dados_sem_historico               # só o período corrente: é o que vai para o Git
    destino = config.PASTA_PRE_PROCESSADO
    problemas = checar_contra_publicado(novo, destino)
    if problemas:
        texto = "Trava de segurança: o arquivo novo da ANM parece incompleto.\n" + "\n".join(f"- {p}" for p in problemas)
        print(texto, file=sys.stderr)
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("## " + texto + "\n\nNada foi publicado. O site continua com a versão anterior.\n")
        if not args.forcar:
            return 1
    gravou = salvar_pre_processado(novo, destino)
    print(f"Versão {novo.versao}: {'dados novos gravados em' if gravou else 'sem mudanças em'} {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

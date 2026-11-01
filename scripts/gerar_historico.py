"""Gera o histórico da arrecadação (2002–2021) UMA vez e grava em dados_processados/historico/.

Os arquivos de períodos encerrados da ANM não mudam, então não entram na atualização diária.
Rode pelo GitHub Actions (workflow "Gerar histórico da ANM") ou à mão:

    python scripts/gerar_historico.py            # baixa do portal da ANM
    python scripts/gerar_historico.py --forcar   # grava mesmo se a verificação apontar problema

Antes de gravar, confere se cada ano tem os 12 meses e se nenhum mês tem bem menos registros
que os outros (sinal de arquivo incompleto no portal). Se algo estiver errado, não grava nada.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["CFEM_MODO"] = "servidor"
os.environ.setdefault("CFEM_PASTA_CACHE", str(RAIZ / "cache"))
os.environ.setdefault("CFEM_REBAIXAR_HISTORICOS_A_CADA_DIAS", "0")

from app import config  # noqa: E402
from app.dominio import CHAVES_REGIAO, FOCO_NORM, UF_ALVO  # noqa: E402
from app.fonte import obter_arquivo  # noqa: E402
from app.leitura import preparar_arrecadacao, preparar_autuacao  # noqa: E402
from app.repositorio import pasta_historico  # noqa: E402

RE_PERIODO = re.compile(r"_(\d{4})_(\d{4})\.csv$", re.IGNORECASE)
LIMIAR_MES = 0.35   # um mês com menos de 35% da mediana de registros/mês do próprio ano é suspeito


def anos_esperados(nomes):
    anos = set()
    for nome in nomes:
        m = RE_PERIODO.search(nome)
        if not m:
            raise SystemExit(f"Nome sem período (AAAA_AAAA): {nome}")
        anos.update(range(int(m.group(1)), int(m.group(2)) + 1))
    return sorted(anos)


def verificar(nacional, anos):
    """Lista de problemas encontrados (vazia = tudo certo)."""
    problemas = []
    cont = nacional.groupby(["Ano", "Mes"]).size()
    for ano in anos:
        if ano not in cont.index.get_level_values(0):
            problemas.append(f"{ano}: nenhum registro")
            continue
        meses = cont.loc[ano]
        faltando = sorted(set(range(1, 13)) - set(int(m) for m in meses.index))
        if faltando:
            problemas.append(f"{ano}: faltam os meses {faltando}")
        mediana = float(meses.median())
        fracos = [int(m) for m, n in meses.items() if n < LIMIAR_MES * mediana]
        if fracos:
            problemas.append(f"{ano}: meses com poucos registros {fracos} (mediana do ano: {mediana:.0f})")
    return problemas


def totais_por_ano(nacional, regiao):
    tot = {}
    br = nacional.groupby("Ano")["Valor"].sum()
    pa = nacional[nacional["UF"].eq(UF_ALVO)].groupby("Ano")["Valor"].sum()
    rc = nacional[nacional["Chave"].isin(CHAVES_REGIAO)].groupby("Ano")["Valor"].sum()
    foco = nacional[nacional["Chave"].isin({f"{UF_ALVO}|{m}" for m in FOCO_NORM})].groupby("Ano")["Valor"].sum()
    for ano in br.index:
        tot[str(int(ano))] = {"brasil": round(float(br.get(ano, 0)), 2), "para": round(float(pa.get(ano, 0)), 2),
                              "regiao_carajas": round(float(rc.get(ano, 0)), 2),
                              "canaa_parauapebas": round(float(foco.get(ano, 0)), 2),
                              "linhas_regiao": int((regiao["Ano"] == ano).sum())}
    return tot


def resumo_markdown(meta, problemas):
    br = lambda v: f"R$ {v / 1e6:,.1f} mi".replace(",", "X").replace(".", ",").replace("X", ".")
    linhas = [f"## Histórico da CFEM {meta['ano_inicio']}–{meta['ano_fim']}", ""]
    if problemas:
        linhas += ["**Problemas encontrados (nada foi gravado):**", ""] + [f"- {p}" for p in problemas] + [""]
    linhas += ["| Ano | Brasil | Pará | Região de Carajás | Canaã + Parauapebas |", "|---|---:|---:|---:|---:|"]
    for ano, t in meta["totais_por_ano"].items():
        linhas.append(f"| {ano} | {br(t['brasil'])} | {br(t['para'])} | {br(t['regiao_carajas'])} | {br(t['canaa_parauapebas'])} |")
    return "\n".join(linhas) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="grava mesmo se a verificação apontar problemas")
    args = ap.parse_args()

    nomes = config.ARQUIVOS_HISTORICOS
    anos = anos_esperados(nomes)
    fontes = [obter_arquivo(n) for n in nomes]
    for f in fontes:
        print(f"{f.nome}: {f.tamanho_bytes / 1e6:.1f} MB ({f.origem}, {f.last_modified})")

    nomes_por_doc = {}
    if config.ARQUIVO_AUTUACAO:           # nomes das empresas para identificar os CNPJs
        _, _, nomes_por_doc = preparar_autuacao(obter_arquivo(config.ARQUIVO_AUTUACAO).caminho)
    regiao, nacional, _ = preparar_arrecadacao([f.caminho for f in fontes], nomes_por_doc)
    regiao = regiao[regiao["Ano"].between(anos[0], anos[-1])]
    nacional = nacional[nacional["Ano"].between(anos[0], anos[-1])]

    problemas = verificar(nacional, anos)
    versao = hashlib.sha1("\n".join(sorted(f.assinatura() for f in fontes)).encode()).hexdigest()[:12]
    meta = {"versao": versao, "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ano_inicio": anos[0], "ano_fim": anos[-1], "fontes": [f.como_dict() for f in fontes],
            "totais_por_ano": totais_por_ano(nacional, regiao), "problemas_ignorados": problemas if args.forcar else []}

    texto = resumo_markdown(meta, problemas)
    print(texto)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto)

    if problemas and not args.forcar:
        print("Arquivos da ANM parecem incompletos; nada foi gravado. Tente outro dia ou use --forcar.", file=sys.stderr)
        return 1

    pasta = pasta_historico()
    pasta.mkdir(parents=True, exist_ok=True)
    regiao.to_parquet(pasta / "regiao_arrecadacao.parquet", index=False)
    nacional.to_parquet(pasta / "nacional_arrecadacao.parquet", index=False)
    (pasta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"Histórico gravado em {pasta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

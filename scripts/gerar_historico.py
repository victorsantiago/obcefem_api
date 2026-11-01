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

import pandas as pd

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

# Tamanhos dos arquivos de períodos encerrados numa publicação completa da ANM (31/10/2026).
# Períodos encerrados não deveriam encolher: abaixo de 90% disso, o arquivo provavelmente está incompleto.
# (Em 01/11/2026 o portal publicou versões com 30–80% desses tamanhos e só ~30% dos valores.)
TAMANHO_REFERENCIA = {
    "CFEM_Arrecadacao_2002_2006.csv": 25_844_614,
    "CFEM_Arrecadacao_2007_2011.csv": 48_650_700,
    "CFEM_Arrecadacao_2012_2016.csv": 66_880_907,
    "CFEM_Arrecadacao_2017_2021.csv": 84_063_006,
}
# Totais anuais oficiais conhecidos (Brasil) para conferência: a CFEM de 2021 passou de R$ 10,2 bi.
REFERENCIA_OFICIAL = {2021: 10.2e9}
TOLERANCIA_OFICIAL = 0.85     # aceita até 15% abaixo da referência


def checar_tamanhos(fontes):
    problemas = []
    for f in fontes:
        ref = TAMANHO_REFERENCIA.get(f.nome)
        if ref and f.tamanho_bytes < 0.9 * ref:
            problemas.append(f"{f.nome}: {f.tamanho_bytes / 1e6:.1f} MB, bem menor que os {ref / 1e6:.1f} MB "
                             f"de uma publicação completa")
    return problemas


def checar_valores(nacional):
    """Compara com totais oficiais e com o primeiro ano do período corrente já publicado."""
    problemas = []
    por_ano = nacional.groupby("Ano")["Valor"].sum()
    for ano, ref in REFERENCIA_OFICIAL.items():
        if ano in por_ano.index and por_ano[ano] < TOLERANCIA_OFICIAL * ref:
            problemas.append(f"{ano}: total nacional de R$ {por_ano[ano] / 1e9:.2f} bi, mas o oficial passa de "
                             f"R$ {ref / 1e9:.1f} bi")
    publicado = config.PASTA_PRE_PROCESSADO / "nacional_arrecadacao.parquet"
    if publicado.exists() and len(por_ano):
        atual = pd.read_parquet(publicado, columns=["Ano", "Valor"]).groupby("Ano")["Valor"].sum()
        ultimo, seguinte = int(por_ano.index.max()), int(por_ano.index.max()) + 1
        if seguinte in atual.index and por_ano[ultimo] < 0.5 * atual[seguinte]:
            problemas.append(f"{ultimo}: R$ {por_ano[ultimo] / 1e9:.2f} bi, menos da metade dos "
                             f"R$ {atual[seguinte] / 1e9:.2f} bi publicados para {seguinte}")
    return problemas


def anos_esperados(nomes):
    anos = set()
    for nome in nomes:
        m = RE_PERIODO.search(nome)
        if not m:
            raise SystemExit(f"Nome sem período (AAAA_AAAA): {nome}")
        anos.update(range(int(m.group(1)), int(m.group(2)) + 1))
    return sorted(anos)


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


LIMIAR_INICIO = 0.05   # meses com menos de 5% da mediana mensal, antes do início real, são registros isolados


def inicio_da_serie(cont):
    """Primeiro (ano, mês) com volume de registros compatível com a série. Meses anteriores com
    volume ínfimo são registros isolados (ex.: uma guia com ano 2002 de um processo de 2007)."""
    corte = LIMIAR_INICIO * float(cont.median())
    for (ano, mes), n in cont.items():
        if n >= corte:
            return int(ano), int(mes)
    return tuple(int(x) for x in cont.index[0])


def verificar(nacional, anos, fim_primeiro_arquivo=None):
    """Devolve (problemas, inicio). Os meses ANTES do primeiro mês com dados são o começo da série
    da ANM (não é erro); a partir dele, todos os meses de todos os anos precisam estar presentes."""
    problemas = []
    cont = nacional.groupby(["Ano", "Mes"]).size().sort_index()
    if cont.empty:
        return ["nenhum registro em nenhum arquivo"], None
    inicio = inicio_da_serie(cont)
    if fim_primeiro_arquivo is not None and inicio[0] > fim_primeiro_arquivo:
        problemas.append(f"o primeiro arquivo não tem nenhum registro (a série só começa em {inicio[0]})")
    for ano in anos:
        if ano < inicio[0]:
            continue
        if ano not in cont.index.get_level_values(0):
            problemas.append(f"{ano}: nenhum registro")
            continue
        meses = cont.loc[ano]
        esperados = set(range(inicio[1] if ano == inicio[0] else 1, 13))
        faltando = sorted(esperados - set(int(m) for m in meses.index))
        if faltando:
            problemas.append(f"{ano}: faltam os meses {faltando}")
        mediana = float(meses.median())
        fracos = [int(m) for m, n in meses.items() if n < LIMIAR_MES * mediana]
        if fracos:
            problemas.append(f"{ano}: meses com poucos registros {fracos} (mediana do ano: {mediana:.0f})")
    return problemas, inicio


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
    linhas = [f"## Histórico da CFEM {meta['ano_inicio']}–{meta['ano_fim']}", "",
              f"A série da ANM começa em {MESES[meta['mes_inicio'] - 1]}/{meta['ano_inicio']}.", ""]
    desc = meta.get("registros_isolados_descartados") or {}
    if desc.get("linhas_agregadas"):
        valor = f"R$ {desc['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        linhas += [f"Registros isolados antes do início, deixados de fora: {', '.join(desc['meses'])} ({valor} no total).", ""]
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

    fim_primeiro = int(RE_PERIODO.search(nomes[0]).group(2))
    problemas, inicio = verificar(nacional, anos, fim_primeiro)
    problemas = checar_tamanhos(fontes) + checar_valores(nacional) + problemas
    inicio = inicio or (anos[0], 1)

    # registros isolados antes do início real da série ficam de fora (e são informados no resumo)
    chave = nacional["Ano"].astype(int) * 100 + nacional["Mes"].astype(int)
    antes = chave < inicio[0] * 100 + inicio[1]
    descartados = {"linhas_agregadas": int(antes.sum()), "valor": round(float(nacional.loc[antes, "Valor"].sum()), 2),
                   "meses": sorted({f"{MESES[m - 1]}/{a}" for a, m in nacional.loc[antes, ["Ano", "Mes"]].astype(int).itertuples(index=False)})}
    nacional = nacional[~antes]
    chave_r = regiao["Ano"].astype(int) * 100 + regiao["Mes"].astype(int)
    regiao = regiao[chave_r >= inicio[0] * 100 + inicio[1]]
    versao = hashlib.sha1("\n".join(sorted(f.assinatura() for f in fontes)).encode()).hexdigest()[:12]
    meta = {"versao": versao, "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ano_inicio": inicio[0], "mes_inicio": inicio[1], "ano_fim": anos[-1], "fontes": [f.como_dict() for f in fontes],
            "totais_por_ano": totais_por_ano(nacional, regiao), "problemas_ignorados": problemas if args.forcar else [],
            "registros_isolados_descartados": descartados}

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

"""Análise da distribuição: para onde vai a CFEM arrecadada, pela repartição definida em lei.

Estimativa = valor arrecadado (base de arrecadação da ANM) × percentual de cada destino na regra
vigente no ano (ou na regra atual, se o filtro `regra=atual`). Ver REGRAS_DISTRIBUICAO em dominio.py.

O arquivo CFEM_Distribuicao.csv da ANM (repasse efetivamente creditado) não entra aqui: em 01/11/2026
ele estava incompleto (cerca de 15% da cota municipal esperada em 2023–2025) e não traz a parcela da União.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import replace

import pandas as pd

from app import analises, config
from app.analises import ESCOPOS, Filtros, _lista, _num, _pct, _vezes, descricao_media, filtrar, info_anos
from app.dominio import (CORES, DEMAIS, DESTINOS, FOCO, PARCELAS_UNIAO, REGRA_ATUAL, REGRAS_DISTRIBUICAO, SOMA_FOCO,
                         UF_ALVO, norm, regra_do_ano)
from app.repositorio import Dados

BASE = "arrecadacao"
SELECAO = "Municípios selecionados da região"


# ============================================================================ percentuais
def fracoes(anos, modo: str) -> pd.DataFrame:
    """Fração (0–1) de cada destino e de cada parcela da União, por ano."""
    linhas = {}
    for a in anos:
        r = regra_do_ano(int(a), modo)
        linha = {k: v / 100 for k, v in r["destinos"].items()}
        linha.update({f"uniao_{k}": v / 100 for k, v in r["uniao"].items()})
        linha["regra"] = r["id"]
        linhas[int(a)] = linha
    return pd.DataFrame.from_dict(linhas, orient="index")


COLS_DESTINO = list(DESTINOS)
COLS_UNIAO = [f"uniao_{k}" for k in PARCELAS_UNIAO]


def _com_destinos(d: pd.DataFrame, modo: str) -> pd.DataFrame:
    """Acrescenta às linhas (com Ano e Valor) uma coluna em R$ para cada destino e parcela da União."""
    if d.empty:
        return d.assign(**{c: 0.0 for c in COLS_DESTINO + COLS_UNIAO})
    fr = fracoes(sorted(d["Ano"].dropna().unique()), modo)
    ano = d["Ano"].astype(int)
    novas = {c: d["Valor"].to_numpy() * ano.map(fr[c]).to_numpy(dtype=float) for c in COLS_DESTINO + COLS_UNIAO}
    return d.assign(**novas)


def _soma_destinos(d: pd.DataFrame) -> dict:
    gerado = float(d["Valor"].sum())
    dest = {c: float(d[c].sum()) for c in COLS_DESTINO}
    uniao = {c.removeprefix("uniao_"): float(d[c].sum()) for c in COLS_UNIAO}
    return {"gerado": gerado, "destinos": dest, "uniao": uniao,
            "percentuais": {c: _pct(v, gerado) for c, v in dest.items()}}


# ============================================================================ dados "convertidos" para um destino
# Mesmo formato dos Dados originais, mas com Valor = parcela do destino. Assim as funções de analises.py
# (comparação com médias, ranking, tabela resumo…) servem também para a cota municipal, estadual etc.
_derivados: OrderedDict = OrderedDict()
_trava_derivados = threading.Lock()


def dados_destino(dados: Dados, destino: str, modo: str) -> Dados:
    chave = (dados.versao, destino, modo)
    with _trava_derivados:
        if chave in _derivados:
            _derivados.move_to_end(chave)
            return _derivados[chave]

    def converter(df: pd.DataFrame) -> pd.DataFrame:
        fr = fracoes(sorted(df["Ano"].dropna().unique()), modo)[destino]
        fator = df["Ano"].map(fr).astype(float).fillna(0.0)
        return df.assign(Valor=df["Valor"] * fator)

    novo = replace(dados, versao=f"{dados.versao}|{destino}|{modo}",
                   regiao={BASE: converter(dados.regiao[BASE])}, nacional={BASE: converter(dados.nacional[BASE])})
    with _trava_derivados:
        _derivados[chave] = novo
        while len(_derivados) > 8:
            _derivados.popitem(last=False)
    return novo


def _f(f: Filtros) -> Filtros:
    return f if f.base == BASE else replace(f, base=BASE)


# ============================================================================ textos
def regras() -> dict:
    return {
        "destinos": [{"id": k, "nome": v, "cor": CORES[k]} for k, v in DESTINOS.items()],
        "parcelas_uniao": [{"id": k, "nome": v} for k, v in PARCELAS_UNIAO.items()],
        "regras": REGRAS_DISTRIBUICAO,
        "regra_atual": REGRA_ATUAL["id"],
        "uso_dos_recursos": ("Os recursos originados da CFEM não poderão ser aplicados pelos entes beneficiários em "
                             "pagamento de dívidas ou no quadro permanente de pessoal da União, dos Estados, Distrito "
                             "Federal e dos Municípios e sim aplicadas em projetos, que direta ou indiretamente revertam "
                             "em prol da comunidade local, na forma de melhoria da infraestrutura, da qualidade "
                             "ambiental, da saúde e educação."),
        "fonte_regra": "Agência Nacional de Mineração (nota sobre a distribuição da CFEM) e Lei 13.540/2017.",
    }


def notas(dados: Dados, f: Filtros) -> list[str]:
    f = _f(f)
    n = ["Estimativa: valor arrecadado × percentual de cada destino na lei. Não é o valor efetivamente creditado "
         "pela ANM, que pode sair em outro mês, ser retificado ou, no caso dos afetados, seguir critérios próprios."]
    if f.regra == "atual":
        if f.ano_inicio <= 2017:
            n.append("A regra atual (60/15/15/10) foi aplicada também aos anos anteriores a 2018, como simulação.")
    elif f.ano_inicio <= 2017:
        n.append("Até 2017 a divisão era 65% para o município, 23% para o estado e 12% para a União, sem cota para "
                 "municípios afetados. A regra atual vale a partir de 2018.")
    n.append("A cota dos municípios afetados não fica necessariamente na região: a ANM a reparte entre municípios "
             "cortados por ferrovias, portos, dutos ou com estruturas de mineração, inclusive de outros estados.")
    n.extend(analises.notas(dados, f)[1:])     # ano parcial, início da série, valores nominais
    return n


# ============================================================================ visualizações
def indicadores(dados: Dados, f: Filtros) -> dict:
    f = _f(f)
    d = _com_destinos(filtrar(dados, f), f.regra)
    por = {m: _soma_destinos(d[d["Municipio"] == m]) for m in FOCO}
    soma = _soma_destinos(d[d["Municipio"].isin(FOCO)])
    regiao = _soma_destinos(d)
    dm = dados_destino(dados, "municipio", f.regra)
    ref = analises.medias_referencia(dm, f, por_ano=False)
    medias = []
    for escopo, rotulo in ESCOPOS:
        media = ref[escopo]["Media"].iat[0]
        medias.append({"escopo": escopo, "nome": rotulo, "cor": CORES[rotulo], "valor_medio": _num(media),
                       "municipios": int(ref[escopo]["Municipios"].iat[0]),
                       "vezes": {m: _vezes(por[m]["destinos"]["municipio"], media) for m in FOCO}})
    regras_usadas = sorted(set(fracoes(f.anos, f.regra)["regra"]))
    return {
        "foco": [{"municipio": m, "cor": CORES[m], **por[m]} for m in FOCO],
        "foco_soma": {"nome": SOMA_FOCO, **soma},
        "regiao": {"nome": SELECAO, "municipios": len(f.municipios), **regiao},
        "medias_cota_municipal": medias,
        "descricao_media": descricao_media(f),
        "regras_no_periodo": regras_usadas,
        "regra_mista": len(regras_usadas) > 1,
    }


def fluxo(dados: Dados, f: Filtros) -> dict:
    """Origem (município onde a CFEM foi gerada) -> destinos -> parcelas da União. Para o diagrama de Sankey."""
    f = _f(f)
    d = _com_destinos(filtrar(dados, f), f.regra)
    origens = []
    for grupo in [*FOCO, DEMAIS]:
        sub = d[d["Grupo"] == grupo]
        if grupo == DEMAIS and sub.empty:
            continue
        origens.append({"nome": grupo, "cor": CORES[grupo], **_soma_destinos(sub)})
    return {"origens": origens, "destinos": [{"id": k, "nome": v, "cor": CORES[k]} for k, v in DESTINOS.items()],
            "parcelas_uniao": [{"id": k, "nome": v} for k, v in PARCELAS_UNIAO.items()],
            "total": _soma_destinos(d)}


def destinos_anual(dados: Dados, f: Filtros) -> dict:
    f = _f(f)
    d = _com_destinos(filtrar(dados, f), f.regra)
    fr = fracoes(f.anos, f.regra)

    def por_ano(sub: pd.DataFrame) -> dict:
        g = sub.groupby("Ano")[["Valor", *COLS_DESTINO]].sum().reindex(f.anos, fill_value=0).astype(float)
        return {"gerado": _lista(g["Valor"]), "destinos": {c: _lista(g[c]) for c in COLS_DESTINO}}

    origens = [{"id": "soma", "nome": SOMA_FOCO, **por_ano(d[d["Municipio"].isin(FOCO)])}]
    origens += [{"id": m, "nome": m, **por_ano(d[d["Municipio"] == m])} for m in FOCO]
    origens.append({"id": "regiao", "nome": SELECAO, **por_ano(d)})
    return {"anos": info_anos(dados, f), "regra_por_ano": fr["regra"].tolist(),
            "destinos": [{"id": k, "nome": v, "cor": CORES[k]} for k, v in DESTINOS.items()],
            "origens": origens}


def _nacional_filtrado(dados: Dados, f: Filtros) -> pd.DataFrame:
    n = dados.nacional[BASE]
    m = n["Ano"].between(f.ano_inicio, f.ano_fim) & n["Mes"].between(f.mes_inicio, f.mes_fim)
    if f.substancias:
        m &= n[f.col_substancia].isin(f.substancias)
    if f.tipo_titular != "Todos":
        m &= n["TipoPessoa"].eq(f.tipo_titular)
    return n[m]


def peso_nos_repasses(dados: Dados, f: Filtros) -> dict:
    """Quanto da cota estadual do Pará e das parcelas nacionais (União e afetados) vem de Parauapebas e Canaã."""
    f = _f(f)
    n = _com_destinos(_nacional_filtrado(dados, f), f.regra)
    chave = {m: f"{UF_ALVO}|{norm(m)}" for m in FOCO}
    pa = n[n["UF"] == UF_ALVO]

    def ano(sub, col):
        return sub.groupby("Ano")[col].sum().reindex(f.anos, fill_value=0).astype(float)

    est_pa, afet_br, uniao_br = ano(pa, "estado"), ano(n, "afetados"), ano(n, "uniao")
    ger_pa, ger_br = ano(pa, "Valor"), ano(n, "Valor")
    series = []
    grupos = {**{m: [chave[m]] for m in FOCO}, SOMA_FOCO: list(chave.values())}
    for nome, chaves in grupos.items():
        sub = n[n["Chave"].isin(chaves)]
        s_est, s_afet, s_uniao, s_ger = ano(sub, "estado"), ano(sub, "afetados"), ano(sub, "uniao"), ano(sub, "Valor")
        series.append({
            "nome": nome, "cor": CORES[nome],
            "cota_estadual": _lista(s_est), "pct_cota_estadual_pa": [_pct(a, b) for a, b in zip(s_est, est_pa)],
            "afetados": _lista(s_afet), "pct_afetados_br": [_pct(a, b) for a, b in zip(s_afet, afet_br)],
            "uniao": _lista(s_uniao), "pct_uniao_br": [_pct(a, b) for a, b in zip(s_uniao, uniao_br)],
            "pct_arrecadacao_pa": [_pct(a, b) for a, b in zip(s_ger, ger_pa)],
            "pct_arrecadacao_br": [_pct(a, b) for a, b in zip(s_ger, ger_br)],
            "periodo": {"pct_cota_estadual_pa": _pct(s_est.sum(), est_pa.sum()),
                        "pct_afetados_br": _pct(s_afet.sum(), afet_br.sum()),
                        "pct_uniao_br": _pct(s_uniao.sum(), uniao_br.sum())},
        })
    return {"anos": info_anos(dados, f), "series": series,
            "totais": {"cota_estadual_pa": _lista(est_pa), "afetados_br": _lista(afet_br), "uniao_br": _lista(uniao_br)},
            "observacao": ("Cota estadual: parte dos 15% (23% até 2017) que o Governo do Pará recebe, gerada em cada "
                           "município. Afetados e União: parte das parcelas nacionais, gerada em cada município.")}


def tabela_destinos(dados: Dados, f: Filtros) -> dict:
    f = _f(f)
    d = _com_destinos(filtrar(dados, f), f.regra)
    g = d.groupby("Municipio")[["Valor", *COLS_DESTINO]].sum().reindex(list(f.municipios), fill_value=0).astype(float)
    g = g.sort_values("Valor", ascending=False)
    linhas = [{"tipo": "municipio", "nome": m, "foco": m in FOCO, "gerado": float(r["Valor"]),
               "destinos": {c: float(r[c]) for c in COLS_DESTINO}} for m, r in g.iterrows()]
    linhas.append({"tipo": "total", "nome": "Total dos municípios selecionados", "foco": False,
                   "gerado": float(g["Valor"].sum()), "destinos": {c: float(g[c].sum()) for c in COLS_DESTINO}})
    ref = {"gerado": analises.medias_referencia(dados, f, por_ano=False)}
    for c in COLS_DESTINO:
        ref[c] = analises.medias_referencia(dados_destino(dados, c, f.regra), f, por_ano=False)
    for e, rot in ESCOPOS:
        linhas.append({"tipo": "media", "escopo": e, "nome": rot, "foco": False,
                       "gerado": _num(ref["gerado"][e]["Media"].iat[0]),
                       "destinos": {c: _num(ref[c][e]["Media"].iat[0]) for c in COLS_DESTINO},
                       "municipios": int(ref["gerado"][e]["Municipios"].iat[0])})
    return {"linhas": linhas, "destinos": [{"id": k, "nome": v, "cor": CORES[k]} for k, v in DESTINOS.items()],
            "descricao_media": descricao_media(f)}


# Cota municipal estimada: reaproveita as visualizações da arrecadação sobre os dados convertidos
def _da_cota_municipal(nome: str):
    def func(dados: Dados, f: Filtros):
        f = _f(f)
        return analises.calcular(nome, dados_destino(dados, "municipio", f.regra), f)
    func.__name__ = nome
    return func


VISUALIZACOES = {
    "indicadores": indicadores,
    "fluxo": fluxo,
    "destinos_anual": destinos_anual,
    "comparacao_medias": _da_cota_municipal("comparacao_medias"),
    "peso_nos_repasses": peso_nos_repasses,
    "ranking": _da_cota_municipal("ranking"),
    "tabela_destinos": tabela_destinos,
    "tabela_resumo": _da_cota_municipal("tabela_resumo"),
}


def painel(dados: Dados, f: Filtros) -> dict:
    return {nome: calcular(nome, dados, f) for nome in VISUALIZACOES}


_cache: OrderedDict = OrderedDict()
_trava_cache = threading.Lock()


def calcular(nome: str, dados: Dados, f: Filtros):
    f = _f(f)
    chave = (dados.versao, nome, f)
    with _trava_cache:
        if chave in _cache:
            _cache.move_to_end(chave)
            return _cache[chave]
    resultado = painel(dados, f) if nome == "painel" else VISUALIZACOES[nome](dados, f)
    with _trava_cache:
        _cache[chave] = resultado
        while len(_cache) > config.CACHE_RESPOSTAS:
            _cache.popitem(last=False)
    return resultado


def exportar(dados: Dados, f: Filtros) -> pd.DataFrame:
    """Município × ano × destino (R$), para o CSV."""
    f = _f(f)
    d = _com_destinos(filtrar(dados, f), f.regra)
    g = d.groupby(["Municipio", "Ano"])[["Valor", *COLS_DESTINO, *COLS_UNIAO]].sum().reset_index()
    g["Regra"] = g["Ano"].map(fracoes(f.anos, f.regra)["regra"])
    nomes = {"Valor": "Arrecadado", **{c: DESTINOS[c] for c in COLS_DESTINO},
             **{f"uniao_{k}": f"União - {v}" for k, v in PARCELAS_UNIAO.items()}}
    return g.rename(columns=nomes)

"""Funções que geram os dados de cada visualização (port do painel do Colab).

Todas recebem (dados, filtros) e devolvem estruturas prontas para JSON:
valores em R$ (float, sem arredondamento de exibição), percentuais de 0 a 100 e
None onde não há valor (ex.: média sem municípios).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from app import config
from app.dominio import (BASES, CHAVES_REGIAO, CORES, DEMAIS, FOCO, MESES_ABREV, N_MUNICIPIOS, REF_BR, REF_PA, REF_RC,
                         REGIAO_CARAJAS, SOMA_FOCO)
from app.repositorio import Dados

# Médias de referência, da mais próxima para a mais ampla: região de Carajás, Pará e Brasil
ESCOPOS = (("RC", REF_RC), ("PA", REF_PA), ("BR", REF_BR))


# ============================================================================ filtros
@dataclass(frozen=True)
class Filtros:
    base: str = "arrecadacao"
    ano_inicio: int = 2022
    ano_fim: int = 2026
    mes_inicio: int = 1
    mes_fim: int = 12
    substancias: tuple[str, ...] = ()
    agrupar_substancias: bool = True
    tipo_titular: str = "Todos"
    municipios: tuple[str, ...] = tuple(REGIAO_CARAJAS)
    denominador: str = "com_registro"          # "com_registro" | "todos"
    excluir_foco_das_medias: bool = False
    top_n: int = 10
    regra: str = "vigente"                     # distribuição: "vigente" (lei de cada ano) | "atual" (regra de hoje)

    def como_dict(self) -> dict:
        d = asdict(self)
        d["substancias"] = list(self.substancias)
        d["municipios"] = list(self.municipios)
        return d

    @property
    def anos(self) -> list[int]:
        return list(range(self.ano_inicio, self.ano_fim + 1))

    @property
    def col_substancia(self) -> str:
        return "SubstanciaGrupo" if self.agrupar_substancias else "Substancia"


# ============================================================================ utilitários
def _num(x):
    """Converte para float JSON-safe (NaN/None -> None)."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return float(x)


def _lista(valores) -> list:
    return [_num(v) for v in valores]


def _pct(parte, todo):
    return None if not todo else float(parte) / float(todo) * 100


def _vezes(a, b):
    a, b = _num(a), _num(b)
    return None if a is None or b is None or b <= 0 else a / b


def ano_parcial(dados: Dados, f: Filtros, ano: int) -> bool:
    cob = dados.cobertura
    return (f.base == "arrecadacao" and ano == cob["ultimo_ano"] and cob["ano_parcial"]
            and f.mes_fim > cob["ultimo_mes_completo"])


def inicio_parcial(dados: Dados, f: Filtros, ano: int) -> bool:
    """Primeiro ano da série que não começa em janeiro (ex.: a série da ANM começa em mai/2003)."""
    cob = dados.cobertura
    return (f.base == "arrecadacao" and ano == cob.get("primeiro_ano")
            and cob.get("primeiro_mes", 1) > f.mes_inicio)


def info_anos(dados: Dados, f: Filtros) -> list[dict]:
    saida = []
    for a in f.anos:
        if inicio_parcial(dados, f, a):
            rotulo = f"{a} (desde {MESES_ABREV[dados.cobertura['primeiro_mes'] - 1]})"
        elif ano_parcial(dados, f, a):
            rotulo = f"{a} (parcial)"
        else:
            rotulo = str(a)
        saida.append({"ano": a, "rotulo": rotulo, "parcial": rotulo != str(a)})
    return saida


def descricao_media(f: Filtros) -> str:
    base = ("todos os municípios (Região de Integração do Carajás 12, PA 144 e Brasil 5.570)" if f.denominador == "todos"
            else "municípios com registro no período")
    return f"média = total ÷ {base}" + (", sem Canaã e Parauapebas" if f.excluir_foco_das_medias else "")


def notas(dados: Dados, f: Filtros) -> list[str]:
    n = []
    cob = dados.cobertura
    if f.base == "arrecadacao":
        n.append("Valor recolhido pelas mineradoras referente à produção do município; não é o repasse à prefeitura "
                 "(a cota do município produtor é 60%, Lei 13.540/2017).")
        if cob["ano_parcial"] and f.ano_fim >= cob["ultimo_ano"] and f.mes_fim > cob["ultimo_mes_completo"]:
            mes = MESES_ABREV[max(cob["ultimo_mes_completo"], 1) - 1]
            n.append(f"{cob['ultimo_ano']} é parcial: o volume de registros só é completo até {mes}. "
                     f"Para comparar com outros anos use mes_fim={max(cob['ultimo_mes_completo'], 1)}.")
        if f.ano_inicio <= cob.get("primeiro_ano", 0) and cob.get("primeiro_mes", 1) > f.mes_inicio:
            n.append(f"A série da ANM começa em {MESES_ABREV[cob['primeiro_mes'] - 1]}/{cob['primeiro_ano']}; "
                     f"{cob['primeiro_ano']} não tem os meses anteriores.")
    else:
        n.append("Autuação = valor do auto de cobrança como a ANM publica hoje; a ANM atualiza esse valor ao longo do tempo (não é valor pago). "
                 "Ano = ano do processo de cobrança (AnoPublicação falta em ~1/3 das linhas).")
        n.append("A base de autuações da ANM tem poucos autos recentes: a maior parte é de 2009 a 2014. "
                 "Anos sem barra não têm autos publicados para o município; não é falha do painel.")
    n.append("Valores nominais (sem correção monetária).")
    return n


# ============================================================================ filtragem
def filtrar(dados: Dados, f: Filtros) -> pd.DataFrame:
    d = dados.regiao[f.base]
    m = d["Ano"].between(f.ano_inicio, f.ano_fim) & d["Municipio"].isin(f.municipios)
    if f.base == "arrecadacao":
        m &= d["Mes"].between(f.mes_inicio, f.mes_fim)
    if f.substancias:
        m &= d[f.col_substancia].isin(f.substancias)
    if f.tipo_titular != "Todos":
        m &= d["TipoPessoa"].eq(f.tipo_titular)
    d = d.loc[m].copy()
    d["SubstanciaExib"] = d[f.col_substancia]
    return d


def medias_referencia(dados: Dados, f: Filtros, por_ano: bool = True) -> dict[str, pd.DataFrame]:
    """Valor médio por município (Pará e Brasil) com os mesmos filtros de período, substância e titular.
    A média da região usa sempre os 12 municípios de Carajás (não depende do filtro de municípios).
    Retorna {"RC"|"PA"|"BR": DataFrame[Total, Municipios, Media]} indexado por ano (ou 'periodo')."""
    n = dados.nacional[f.base]
    m = n["Ano"].between(f.ano_inicio, f.ano_fim)
    if f.base == "arrecadacao":
        m &= n["Mes"].between(f.mes_inicio, f.mes_fim)
    if f.substancias:
        m &= n[f.col_substancia].isin(f.substancias)
    if f.tipo_titular != "Todos":
        m &= n["TipoPessoa"].eq(f.tipo_titular)
    if f.excluir_foco_das_medias:
        m &= ~n["EhFoco"].astype(bool)
    n = n[m]
    saida = {}
    for escopo, _ in ESCOPOS:
        if escopo == "RC":
            sub = n[n["Chave"].isin(CHAVES_REGIAO)]
        elif escopo == "PA":
            sub = n[n["UF"].eq("PA")]
        else:
            sub = n
        if por_ano:
            total = sub.groupby("Ano")["Valor"].sum().reindex(f.anos, fill_value=0)
            qtd = sub[sub["Valor"] > 0].groupby("Ano")["Chave"].nunique().reindex(f.anos, fill_value=0)
        else:
            total = pd.Series({"periodo": sub["Valor"].sum()})
            qtd = pd.Series({"periodo": sub.loc[sub["Valor"] > 0, "Chave"].nunique()})
        if f.denominador == "todos":
            qtd = pd.Series(N_MUNICIPIOS[escopo] - (2 if f.excluir_foco_das_medias else 0), index=total.index)
        tab = pd.DataFrame({"Total": total.astype(float), "Municipios": qtd.astype(float)})
        tab["Media"] = tab["Total"] / tab["Municipios"].replace(0, np.nan)
        saida[escopo] = tab
    return saida


def _por_ano_grupo(d: pd.DataFrame, f: Filtros) -> pd.DataFrame:
    g = d.groupby(["Ano", "Grupo"])["Valor"].sum().unstack(fill_value=0).reindex(f.anos, fill_value=0)
    for grupo in [*FOCO, DEMAIS]:
        if grupo not in g:
            g[grupo] = 0.0
    return g[[*FOCO, DEMAIS]].astype(float)


# ============================================================================ visualizações
def indicadores(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    total = float(d["Valor"].sum())
    por = d.groupby("Municipio")["Valor"].sum()
    soma = float(sum(por.get(m, 0) for m in FOCO))
    ref = medias_referencia(dados, f, por_ano=False)
    medias = []
    for escopo, rotulo in ESCOPOS:
        media = ref[escopo]["Media"].iat[0]
        medias.append({
            "escopo": escopo, "nome": rotulo, "cor": CORES[rotulo],
            "valor_medio": _num(media), "total": _num(ref[escopo]["Total"].iat[0]),
            "municipios": int(ref[escopo]["Municipios"].iat[0]),
            "vezes": {m: _vezes(por.get(m, 0), media) for m in FOCO},
        })
    return {
        "total_regiao": total,
        "municipios_selecionados": len(f.municipios),
        "foco": [{"municipio": m, "cor": CORES[m], "valor": float(por.get(m, 0)),
                  "participacao_regiao_pct": _pct(por.get(m, 0), total)} for m in FOCO],
        "foco_soma": {"nome": SOMA_FOCO, "valor": soma, "participacao_regiao_pct": _pct(soma, total)},
        "medias": medias,
        "descricao_media": descricao_media(f),
        "registros": int(len(d)),
    }


def evolucao_anual(dados: Dados, f: Filtros) -> dict:
    g = _por_ano_grupo(filtrar(dados, f), f)
    tot = g.sum(axis=1)
    return {
        "anos": info_anos(dados, f),
        "series": [{"nome": grupo, "cor": CORES[grupo], "valores": _lista(g[grupo]),
                    "participacao_pct": [_pct(v, t) for v, t in zip(g[grupo], tot)]} for grupo in g.columns],
        "totais": _lista(tot),
    }


def comparacao_medias(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    ref = medias_referencia(dados, f)
    ref_p = medias_referencia(dados, f, por_ano=False)
    foco = {m: d[d["Municipio"] == m].groupby("Ano")["Valor"].sum().reindex(f.anos, fill_value=0).astype(float)
            for m in FOCO}
    return {
        "anos": info_anos(dados, f),
        "descricao_media": descricao_media(f),
        "municipios": [{"nome": m, "cor": CORES[m], "valores": _lista(s),
                        "vezes_media_rc": [_vezes(v, a) for v, a in zip(s, ref["RC"]["Media"])],
                        "vezes_media_pa": [_vezes(v, a) for v, a in zip(s, ref["PA"]["Media"])],
                        "vezes_media_br": [_vezes(v, b) for v, b in zip(s, ref["BR"]["Media"])]}
                       for m, s in foco.items()],
        "medias": [{"escopo": e, "nome": rot, "cor": CORES[rot], "valor_medio": _lista(ref[e]["Media"]),
                    "total": _lista(ref[e]["Total"]), "municipios": [int(x) for x in ref[e]["Municipios"]]}
                   for e, rot in ESCOPOS],
        "periodo": {
            "rotulo": f"{f.ano_inicio}–{f.ano_fim}",
            "municipios": [{"nome": m, "valor": float(s.sum()),
                            "vezes_media_rc": _vezes(s.sum(), ref_p["RC"]["Media"].iat[0]),
                            "vezes_media_pa": _vezes(s.sum(), ref_p["PA"]["Media"].iat[0]),
                            "vezes_media_br": _vezes(s.sum(), ref_p["BR"]["Media"].iat[0])} for m, s in foco.items()],
            "medias": [{"escopo": e, "nome": rot, "valor_medio": _num(ref_p[e]["Media"].iat[0]),
                        "total": _num(ref_p[e]["Total"].iat[0]), "municipios": int(ref_p[e]["Municipios"].iat[0])}
                       for e, rot in ESCOPOS],
        },
    }


def participacao(dados: Dados, f: Filtros) -> dict:
    g = _por_ano_grupo(filtrar(dados, f), f)
    tot = g.sum(axis=1)
    series = {m: g[m] for m in FOCO}
    series[SOMA_FOCO] = g[FOCO].sum(axis=1)
    return {
        "anos": info_anos(dados, f),
        "series": [{"nome": nome, "cor": CORES[nome], "valores": _lista(s),
                    "participacao_pct": [_pct(v, t) for v, t in zip(s, tot)]} for nome, s in series.items()],
        "totais_regiao": _lista(tot),
    }


def ranking(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    s = d.groupby("Municipio")["Valor"].sum().reindex(list(f.municipios), fill_value=0).sort_values(ascending=False)
    total = float(s.sum())
    ref = medias_referencia(dados, f, por_ano=False)
    return {
        "itens": [{"posicao": i + 1, "municipio": m, "valor": float(v), "participacao_pct": _pct(v, total),
                   "foco": m in FOCO, "sem_registros": bool(v <= 0), "cor": CORES.get(m, CORES["contexto"])}
                  for i, (m, v) in enumerate(s.items())],
        "total": total,
        "medias_periodo": [{"escopo": e, "nome": rot, "cor": CORES[rot], "valor_medio": _num(ref[e]["Media"].iat[0]),
                            "municipios": int(ref[e]["Municipios"].iat[0])} for e, rot in ESCOPOS],
        "descricao_media": descricao_media(f),
    }


def serie_mensal(dados: Dados, f: Filtros) -> dict:
    if f.base != "arrecadacao":
        raise ValueError("A série mensal só existe para a base de arrecadação (autuações não têm mês).")
    d = filtrar(dados, f).dropna(subset=["Mes"])
    if d.empty:
        return {"meses": [], "series": [], "incompleto_a_partir_de": None}
    d["Data"] = pd.to_datetime(dict(year=d["Ano"].astype(int), month=d["Mes"].astype(int), day=1))
    idx = pd.date_range(d["Data"].min(), d["Data"].max(), freq="MS")
    g = d.groupby(["Data", "Grupo"])["Valor"].sum().unstack(fill_value=0).reindex(idx, fill_value=0)
    cob = dados.cobertura
    inicio_incompleto = None
    if cob["ano_parcial"]:
        ts = pd.Timestamp(cob["ultimo_ano"], 1, 1) + pd.DateOffset(months=cob["ultimo_mes_completo"])
        if ts <= idx.max():
            inicio_incompleto = ts.strftime("%Y-%m")
    return {
        "meses": [x.strftime("%Y-%m") for x in idx],
        "series": [{"nome": grupo, "cor": CORES[grupo], "valores": _lista(g[grupo]) if grupo in g else [0.0] * len(idx)}
                   for grupo in [*FOCO, DEMAIS]],
        "incompleto_a_partir_de": inicio_incompleto,
    }


def substancias(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    if d.empty:
        return {"categorias": [], "series": [], "totais": []}
    tot = d.groupby("SubstanciaExib")["Valor"].sum().nlargest(f.top_n)
    g = (d[d["SubstanciaExib"].isin(tot.index)].groupby(["SubstanciaExib", "Grupo"])["Valor"].sum()
         .unstack(fill_value=0).reindex(tot.index).fillna(0))
    return {
        "categorias": tot.index.tolist(),
        "totais": _lista(tot),
        "series": [{"nome": grupo, "cor": CORES[grupo], "valores": _lista(g[grupo]) if grupo in g else [0.0] * len(tot)}
                   for grupo in [*FOCO, DEMAIS]],
    }


def mapa_calor(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    p = (d.pivot_table(index="Municipio", columns="Ano", values="Valor", aggfunc="sum")
         .reindex(index=list(f.municipios), columns=f.anos).fillna(0))
    p = p.loc[p.sum(axis=1).sort_values(ascending=False).index]
    return {
        "anos": info_anos(dados, f),
        "municipios": p.index.tolist(),
        "valores": [_lista(linha) for linha in p.values],
        "totais_municipio": _lista(p.sum(axis=1)),
        "minimo_positivo": _num(p.values[p.values > 0].min()) if (p.values > 0).any() else None,
        "maximo": _num(p.values.max()) if p.size else None,
    }


def titulares(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    foco = d[d["Municipio"].isin(FOCO)]
    if foco.empty:
        return {"itens": [], "total_foco": 0.0}
    t = foco.groupby(["Titular", "Municipio"])["Valor"].sum().unstack(fill_value=0).reindex(columns=FOCO, fill_value=0)
    t["Total"] = t.sum(axis=1)
    total = float(t["Total"].sum())
    t = t.sort_values("Total", ascending=False).head(f.top_n)
    return {
        "itens": [{"titular": nome, "valores": {m: float(row[m]) for m in FOCO}, "total": float(row["Total"]),
                   "participacao_foco_pct": _pct(row["Total"], total)} for nome, row in t.iterrows()],
        "total_foco": total,
        "observacao": "Na arrecadação, o nome vem da base de autuações quando o CNPJ aparece lá; senão, só o CNPJ.",
    }


def tabela_resumo(dados: Dados, f: Filtros) -> dict:
    d = filtrar(dados, f)
    p = (d.pivot_table(index="Municipio", columns="Ano", values="Valor", aggfunc="sum")
         .reindex(index=list(f.municipios), columns=f.anos).fillna(0))
    p["Total"] = p.sum(axis=1)
    total = float(p["Total"].sum())
    p = p.sort_values("Total", ascending=False)
    ref = medias_referencia(dados, f)
    ref_p = medias_referencia(dados, f, por_ano=False)
    linhas = [{"tipo": "municipio", "nome": m, "foco": m in FOCO, "valores": _lista(row[f.anos]),
               "total": float(row["Total"]), "participacao_pct": _pct(row["Total"], total)} for m, row in p.iterrows()]
    linhas.append({"tipo": "total", "nome": "Total da região", "foco": False, "valores": _lista(p[f.anos].sum()),
                   "total": total, "participacao_pct": 100.0 if total else None})
    for e, rot in ESCOPOS:
        linhas.append({"tipo": "media", "escopo": e, "nome": rot, "foco": False, "valores": _lista(ref[e]["Media"]),
                       "total": _num(ref_p[e]["Media"].iat[0]), "participacao_pct": None,
                       "municipios": [int(x) for x in ref[e]["Municipios"]]})
    return {"anos": info_anos(dados, f), "linhas": linhas, "descricao_media": descricao_media(f),
            "observacao": "Nas linhas de média, 'total' é a média do período inteiro (não a soma das médias anuais)."}


VISUALIZACOES = {
    "indicadores": indicadores,
    "evolucao_anual": evolucao_anual,
    "comparacao_medias": comparacao_medias,
    "participacao": participacao,
    "ranking": ranking,
    "serie_mensal": serie_mensal,
    "substancias": substancias,
    "mapa_calor": mapa_calor,
    "titulares": titulares,
    "tabela_resumo": tabela_resumo,
}


def painel(dados: Dados, f: Filtros) -> dict:
    """Todas as visualizações numa chamada só (série mensal = None para autuações)."""
    saida = {}
    for nome, func in VISUALIZACOES.items():
        if nome == "serie_mensal" and f.base != "arrecadacao":
            saida[nome] = None
        else:
            saida[nome] = calcular(nome, dados, f)
    return saida


# ============================================================================ cache de respostas
_cache: OrderedDict = OrderedDict()
_trava_cache = threading.Lock()


def calcular(nome: str, dados: Dados, f: Filtros):
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


def metadados(dados: Dados) -> dict:
    bases = {}
    for base, df in dados.regiao.items():
        bases[base] = {
            "descricao": BASES[base],
            "ano_min": int(df["Ano"].min()), "ano_max": int(df["Ano"].max()),
            "tem_mes": base == "arrecadacao",
            "substancias_agrupadas": dados.substancias[base]["agrupadas"],
            "substancias_originais": dados.substancias[base]["originais"],
            "registros_regiao": int(len(df)),
            "municipios_sem_registro": [m for m in REGIAO_CARAJAS if m not in set(df["Municipio"])],
        }
    return {
        "versao_dados": dados.versao,
        "carregado_em": dados.carregado_em,
        "bases": bases,
        "regiao_carajas": REGIAO_CARAJAS,
        "foco": FOCO,
        "cores": CORES,
        "cobertura_arrecadacao": dados.cobertura,
        "n_municipios_ibge": N_MUNICIPIOS,
        "fontes": dados.fontes,
    }

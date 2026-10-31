"""Leitura e limpeza dos CSVs da ANM (mesma lógica do notebook do Colab, com leitura em blocos).

Saídas de cada base:
- regiao:   linhas detalhadas dos 12 municípios da região de Carajás (UF = PA)
- nacional: soma por ano/mês/UF/município/substância/tipo de titular, para todo o Brasil
            (é o que alimenta as médias do Pará e do Brasil)
"""
from __future__ import annotations

import logging
import re
from datetime import date

import numpy as np
import pandas as pd

from app import config
from app.dominio import DEMAIS, FOCO, FOCO_NORM, MAPA_MUN, UF_ALVO, norm

log = logging.getLogger("cfem.leitura")

RE_MINERIO = re.compile(r"^MIN[EÉ]RIO\s+(DE\s+)?", flags=re.IGNORECASE)


# ----------------------------------------------------------------------------- utilitários
def detectar_formato(caminho: str) -> tuple[str, str]:
    """Codificação (UTF-8 ou Windows-1252) e separador (; ou ,). O dicionário da ANM diz ';',
    mas o arquivo de arrecadação 2022–2026 usa ','."""
    with open(caminho, "rb") as f:
        amostra = f.read(500_000)
    amostra = amostra[: amostra.rfind(b"\n") + 1] or amostra
    try:
        amostra.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "cp1252"
    cab = amostra.splitlines()[0].decode(enc, errors="replace")
    sep = ";" if cab.count(";") > cab.count(",") else ","
    return enc, sep


def ler_em_blocos(caminho: str):
    enc, sep = detectar_formato(caminho)
    leitor = pd.read_csv(caminho, sep=sep, encoding=enc, dtype=str, encoding_errors="replace",
                         chunksize=config.LINHAS_POR_BLOCO)
    for bloco in leitor:
        bloco.columns = [norm(c).replace(" ", "") for c in bloco.columns]
        yield bloco


def para_numero(s: pd.Series) -> pd.Series:
    """'1.234,56' | '1234,56' | '1234.56' -> float."""
    s = s.astype(str).str.strip()
    com_virgula = s.str.contains(",", regex=False)
    s = s.where(~com_virgula, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def grupo_substancia(s) -> str:
    """'MINÉRIO DE FERRO' -> 'FERRO' (para somar com quem declarou só 'FERRO')."""
    return RE_MINERIO.sub("", str(s).strip()).strip() or str(s)


def formatar_doc(doc) -> str:
    d = re.sub(r"\D", "", str(doc))
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return str(doc)


def ano_cobranca(serie: pd.Series) -> pd.Series:
    """Ano do processo de cobrança ('950751/2026' -> 2026); descarta códigos como 8888/9999."""
    return (pd.to_numeric(serie.str.extract(r"/(\d{4})")[0], errors="coerce")
            .where(lambda x: x.between(1990, date.today().year)).astype("Int64"))


class _CacheNomes(dict):
    def __missing__(self, chave):
        self[chave] = v = norm(chave)
        return v


def _municipios_norm(serie: pd.Series, cache: _CacheNomes) -> pd.Series:
    return serie.map(lambda m: cache[m] if isinstance(m, str) else "")


def _agregar_nacional(bloco, ano, mes, tipo, valor, mun_norm) -> pd.DataFrame:
    uf = bloco["UF"].fillna("").str.strip().str.upper()
    nac = pd.DataFrame({"Ano": ano, "Mes": mes, "UF": uf, "Chave": uf + "|" + mun_norm,
                        "Substancia": bloco["SUBSTANCIA"].fillna("").str.strip(), "TipoPessoa": tipo,
                        "EhFoco": uf.eq(UF_ALVO) & mun_norm.isin(FOCO_NORM), "Valor": valor})
    nac = nac[mun_norm.ne("") & nac["Valor"].notna() & nac["Ano"].notna()]
    return (nac.groupby(["Ano", "Mes", "UF", "Chave", "Substancia", "TipoPessoa", "EhFoco"], dropna=False)["Valor"]
               .sum().reset_index())


def _finalizar_nacional(partes: list[pd.DataFrame]) -> pd.DataFrame:
    nac = pd.concat(partes, ignore_index=True)
    nac = (nac.groupby(["Ano", "Mes", "UF", "Chave", "Substancia", "TipoPessoa", "EhFoco"], dropna=False)["Valor"]
              .sum().reset_index())
    nac["SubstanciaGrupo"] = nac["Substancia"].map({x: grupo_substancia(x) for x in nac["Substancia"].unique()})
    nac["Ano"] = nac["Ano"].astype("Int64")
    nac["Mes"] = nac["Mes"].astype("Int64")
    return nac


def _complementar_regiao(df: pd.DataFrame) -> pd.DataFrame:
    df["SubstanciaGrupo"] = df["Substancia"].map(grupo_substancia)
    df["Grupo"] = np.where(df["Municipio"].isin(FOCO), df["Municipio"], DEMAIS)
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------- autuação
def preparar_autuacao(caminho: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Retorna (regiao, nacional, nomes_por_documento)."""
    cache = _CacheNomes()
    regiao, nacional, nomes = [], [], []
    for b in ler_em_blocos(caminho):
        mun = _municipios_norm(b["MUNICIPIO"], cache)
        uf = b["UF"].fillna("").str.strip().str.upper()
        ano = ano_cobranca(b["PROCESSOCOBRANCA"].fillna(""))
        tipo = b["TIPO_PF_PJ"].str.strip().replace({"J": "PJ", "F": "PF"})
        valor = para_numero(b["VALOR"])
        nacional.append(_agregar_nacional(b, ano, pd.Series(pd.NA, index=b.index, dtype="Int64"), tipo, valor, mun))
        nomes.append(pd.DataFrame({"doc": b["CPF_CNPJ"].fillna("").str.replace(r"\D", "", regex=True),
                                   "nome": b["NOMETITULAR"]}).dropna())
        m = uf.eq(UF_ALVO) & mun.isin(MAPA_MUN)
        if m.any():
            a = b[m]
            regiao.append(pd.DataFrame({
                "Ano": ano[m], "Mes": pd.Series(pd.NA, index=a.index, dtype="Int64"),
                "AnoPublicacao": pd.to_numeric(a["ANOPUBLICACAO"], errors="coerce").astype("Int64"),
                "Municipio": mun[m].map(MAPA_MUN),
                "Substancia": a["SUBSTANCIA"].str.strip(), "TipoPessoa": tipo[m],
                "Documento": a["CPF_CNPJ"].str.strip(), "Titular": a["NOMETITULAR"].str.strip(),
                "Processo": a["PROCESSOMINERARIO"].str.strip(),
                "ProcessoCobranca": a["PROCESSOCOBRANCA"].str.strip(),
                "NumeroAuto": a["NUMEROAUTO"], "Valor": valor[m],
            }))
    nomes_df = pd.concat(nomes, ignore_index=True)
    nomes_por_doc = nomes_df.groupby("doc")["nome"].agg(lambda s: s.mode().iat[0]).to_dict()
    reg = pd.concat(regiao, ignore_index=True) if regiao else pd.DataFrame()
    reg = reg[reg["Ano"].notna()] if len(reg) else reg
    return _complementar_regiao(reg), _finalizar_nacional(nacional), nomes_por_doc


# ----------------------------------------------------------------------------- arrecadação
def preparar_arrecadacao(caminhos: list[str], nomes_por_doc: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Retorna (regiao, nacional, cobertura)."""
    cache = _CacheNomes()
    regiao, nacional, contagens = [], [], []
    for caminho in caminhos:
        log.info("Lendo %s", caminho)
        for b in ler_em_blocos(caminho):
            mun = _municipios_norm(b["MUNICIPIO"], cache)
            uf = b["UF"].fillna("").str.strip().str.upper()
            ano = pd.to_numeric(b["ANO"], errors="coerce").astype("Int64")
            mes = pd.to_numeric(b["MES"], errors="coerce").astype("Int64")
            tipo = b["TIPO_PF_PJ"].fillna("").str.strip().replace({"-": "Não informado", "": "Não informado"})
            valor = para_numero(b["VALORRECOLHIDO"])
            contagens.append(pd.DataFrame({"Ano": ano, "Mes": mes}).value_counts())
            nacional.append(_agregar_nacional(b, ano, mes, tipo, valor, mun))
            m = uf.eq(UF_ALVO) & mun.isin(MAPA_MUN)
            if m.any():
                a = b[m]
                regiao.append(pd.DataFrame({
                    "Ano": ano[m], "Mes": mes[m], "Municipio": mun[m].map(MAPA_MUN),
                    "CodIBGE": a.get("CODIGOMUNICIPIO"),
                    "Substancia": a["SUBSTANCIA"].str.strip(), "TipoPessoa": tipo[m],
                    "Documento": a["CPF_CNPJ"].str.strip(),
                    "Processo": a["PROCESSO"].str.strip() + "/" + a["ANODOPROCESSO"].str.strip(),
                    "Quantidade": para_numero(a["QUANTIDADECOMERCIALIZADA"]),
                    "Unidade": a["UNIDADEDEMEDIDA"].str.strip(), "Valor": valor[m],
                }))
    reg = pd.concat(regiao, ignore_index=True)
    reg = reg[reg["Ano"].notna()]

    # Titular legível: nome (via base de autuações, quando o CNPJ aparece lá) + CNPJ formatado
    docs = reg[["Documento", "TipoPessoa"]].drop_duplicates()
    def _nome(row):
        doc = re.sub(r"\D", "", str(row["Documento"]))
        if row["TipoPessoa"] == "PF":
            return f"Pessoa física ({row['Documento']})"
        nome = nomes_por_doc.get(doc)
        return f"{nome} ({formatar_doc(doc)})" if nome else formatar_doc(row["Documento"])
    docs["Titular"] = docs.apply(_nome, axis=1)
    reg = reg.merge(docs, on=["Documento", "TipoPessoa"], how="left")

    cobertura = calcular_cobertura(pd.concat(contagens).groupby(level=[0, 1]).sum())
    return _complementar_regiao(reg), _finalizar_nacional(nacional), cobertura


def calcular_cobertura(cont: pd.Series) -> dict:
    """A ANM publica os meses mais recentes de forma incompleta. Um mês do último ano é considerado
    completo se tiver ao menos 50% da mediana de registros/mês dos anos anteriores."""
    cont = cont.dropna()
    anos = cont.index.get_level_values(0)
    ultimo_ano = int(anos.max())
    anteriores = cont[anos < ultimo_ano]
    ref = float(anteriores.median()) if len(anteriores) else 0.0
    meses_ult = cont.loc[ultimo_ano]
    completos = meses_ult[meses_ult >= 0.5 * ref].index if ref else meses_ult.index
    ultimo_completo = int(max(completos)) if len(completos) else 0
    return {
        "ultimo_ano": ultimo_ano,
        "ultimo_mes_com_registro": int(meses_ult.index.max()),
        "ultimo_mes_completo": ultimo_completo,
        "ano_parcial": ultimo_completo < 12,
        "registros_por_mes_ultimo_ano": {int(k): int(v) for k, v in meses_ult.sort_index().items()},
        "mediana_registros_mes_anos_anteriores": ref,
    }

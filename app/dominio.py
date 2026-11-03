"""Recorte geográfico e constantes de negócio (as mesmas do notebook do Colab)."""
import unicodedata

UF_ALVO = "PA"
FOCO = ["Parauapebas", "Canaã dos Carajás"]
REGIAO_CARAJAS = [
    "Bom Jesus do Tocantins", "Brejo Grande do Araguaia", "Canaã dos Carajás",
    "Curionópolis", "Eldorado do Carajás", "Marabá", "Palestina do Pará",
    "Parauapebas", "Piçarra", "São Domingos do Araguaia",
    "São Geraldo do Araguaia", "São João do Araguaia",
]
DEMAIS = "Demais municípios da região"
DEMAIS_PA = "Demais municípios do Pará"   # fora da região de Carajás (só no fluxo da distribuição)
SOMA_FOCO = "Canaã + Parauapebas"

# Total de municípios segundo o IBGE (usado quando a média é sobre "todos os municípios")
N_MUNICIPIOS = {"RC": 12, "PA": 144, "BR": 5570}   # RC = região de Carajás (os 12 da lista acima)

REF_RC = "Média dos municípios da região de Carajás"
REF_PA = "Média dos municípios do Pará"
REF_BR = "Média dos municípios do Brasil"

# Sugestão de cores para o front manter a mesma identidade do painel do Colab
CORES = {
    "Parauapebas": "#2a78d6",
    "Canaã dos Carajás": "#eb6834",
    DEMAIS: "#a3a29c",
    DEMAIS_PA: "#c9c8c2",
    SOMA_FOCO: "#3d3c39",
    REF_RC: "#6250d6",
    REF_PA: "#1baf7a",
    REF_BR: "#52514e",
    "contexto": "#c9c8c2",
}

BASES = {
    "arrecadacao": "Arrecadação da CFEM (valor recolhido pelas mineradoras)",
    "autuacao": "Autuações de CFEM (valor dos autos de cobrança, atualizado pela ANM)",
}

MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def norm(txt) -> str:
    """Maiúsculas, sem acentos e sem espaços duplicados (para casar nomes)."""
    if txt is None:
        return ""
    try:
        if txt != txt:  # NaN
            return ""
    except Exception:
        pass
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return " ".join(txt.upper().split())


MAPA_MUN = {norm(m): m for m in REGIAO_CARAJAS}
FOCO_NORM = {norm(m) for m in FOCO}

# Chaves "UF|MUNICÍPIO" (como na base nacional agregada) dos 12 municípios da região de Carajás
CHAVES_REGIAO = {f"{UF_ALVO}|{norm(m)}" for m in REGIAO_CARAJAS}

# ============================================================================ distribuição (repartição legal da CFEM)
# Destinos na ordem em que aparecem nos gráficos (a mesma da nota da ANM)
DESTINOS = {
    "municipio": "Município produtor",
    "estado": "Estado",
    "afetados": "Municípios afetados",
    "uniao": "União",
}
PARCELAS_UNIAO = {"anm": "ANM", "fndct": "FNDCT", "cetem": "CETEM", "ibama": "IBAMA"}

# Percentuais sobre o valor arrecadado. A regra vale para o ano de referência da arrecadação.
# - Até 2017: Lei 8.001/1990, art. 2º, § 2º (redação da Lei 9.993/2000) — 10% ao MME/DNPM, dos quais 2%
#   (0,2 ponto) iam ao IBAMA, e 2% ao FNDCT; não havia cota para municípios afetados.
# - Desde 2018: Lei 13.540/2017 (nota da ANM): 10% União (7% ANM, 1% FNDCT, 1,8% CETEM, 0,2% IBAMA),
#   15% estado, 60% município produtor e 15% municípios afetados.
REGRAS_DISTRIBUICAO = [
    {"id": "lei_9993_2000", "nome": "Lei 8.001/1990 (redação da Lei 9.993/2000)", "de": None, "ate": 2017,
     "destinos": {"municipio": 65.0, "estado": 23.0, "afetados": 0.0, "uniao": 12.0},
     "uniao": {"anm": 9.8, "fndct": 2.0, "cetem": 0.0, "ibama": 0.2},
     "observacao": "A parcela da ANM era do DNPM, que a antecedeu."},
    {"id": "lei_13540_2017", "nome": "Lei 13.540/2017", "de": 2018, "ate": None,
     "destinos": {"municipio": 60.0, "estado": 15.0, "afetados": 15.0, "uniao": 10.0},
     "uniao": {"anm": 7.0, "fndct": 1.0, "cetem": 1.8, "ibama": 0.2},
     "observacao": "Os repasses aos municípios afetados só começaram depois da regulamentação (Decreto 9.407/2018)."},
]
REGRA_ATUAL = REGRAS_DISTRIBUICAO[-1]


def regra_do_ano(ano: int, modo: str = "vigente") -> dict:
    """modo 'vigente' = a regra em vigor no ano; 'atual' = a regra de hoje aplicada a todos os anos."""
    if modo == "atual":
        return REGRA_ATUAL
    for r in REGRAS_DISTRIBUICAO:
        if (r["de"] is None or ano >= r["de"]) and (r["ate"] is None or ano <= r["ate"]):
            return r
    return REGRA_ATUAL


CORES.update({
    "municipio": "#0f8a72", "estado": "#b88400", "afetados": "#c0407a", "uniao": "#3d6fb0",
})

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
    SOMA_FOCO: "#3d3c39",
    REF_RC: "#6250d6",
    REF_PA: "#1baf7a",
    REF_BR: "#52514e",
    "contexto": "#c9c8c2",
}

BASES = {
    "arrecadacao": "Arrecadação da CFEM (valor recolhido pelas mineradoras)",
    "autuacao": "Autuações de CFEM (valor inicial dos autos de cobrança)",
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

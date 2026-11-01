"""Página de distribuição: a repartição estimada tem de fechar com a arrecadação e com a regra de cada ano."""
import pandas as pd
import pytest

V1 = "/api/v1"
D = f"{V1}/distribuicao"
ROTAS = ["indicadores", "fluxo", "destinos-anual", "comparacao-medias", "peso-nos-repasses", "ranking",
         "tabela-destinos", "tabela-resumo", "painel"]


def test_regras_somam_100():
    from app.dominio import REGRAS_DISTRIBUICAO, regra_do_ano
    for r in REGRAS_DISTRIBUICAO:
        assert sum(r["destinos"].values()) == pytest.approx(100)
        assert sum(r["uniao"].values()) == pytest.approx(r["destinos"]["uniao"])
    assert regra_do_ano(2017)["destinos"]["municipio"] == 65
    assert regra_do_ano(2018)["destinos"]["municipio"] == 60
    assert regra_do_ano(2005, "atual")["destinos"]["afetados"] == 15


def test_todas_as_rotas_respondem(cliente):
    assert cliente.get(f"{D}/regras").status_code == 200
    for rota in ROTAS:
        for params in [{}, {"regra": "atual", "substancias": ["FERRO"]}]:
            r = cliente.get(f"{D}/{rota}", params=params)
            assert r.status_code == 200, (rota, params, r.text[:300])
            assert {"filtros", "notas", "dados", "versao_dados"} <= set(r.json())
    assert cliente.get(f"{D}/indicadores", params={"regra": "outra"}).status_code == 422


def test_destinos_fecham_com_a_arrecadacao(cliente):
    arrec = {x["municipio"]: x["valor"] for x in cliente.get(f"{V1}/indicadores").json()["dados"]["foco"]}
    d = cliente.get(f"{D}/indicadores").json()["dados"]
    for f in d["foco"]:
        assert f["gerado"] == pytest.approx(arrec[f["municipio"]], rel=1e-12)
        assert sum(f["destinos"].values()) == pytest.approx(f["gerado"], rel=1e-12)
        assert sum(f["uniao"].values()) == pytest.approx(f["destinos"]["uniao"], rel=1e-12)
        # período padrão 2022–2026: só a regra atual
        assert f["percentuais"] == pytest.approx({"municipio": 60, "estado": 15, "afetados": 15, "uniao": 10})
    assert d["regras_no_periodo"] == ["lei_13540_2017"] and not d["regra_mista"]


def test_cota_municipal_e_60_por_cento_das_medias(cliente):
    a = cliente.get(f"{V1}/comparacao-medias").json()["dados"]
    c = cliente.get(f"{D}/comparacao-medias").json()["dados"]
    for ma, mc in zip(a["medias"], c["medias"]):
        assert mc["valor_medio"] == pytest.approx([v * 0.6 for v in ma["valor_medio"]], rel=1e-9)
        assert mc["municipios"] == ma["municipios"]
    # razão contra a média não muda: a mesma regra vale para todos os municípios
    assert c["periodo"]["municipios"][0]["vezes_media_pa"] == pytest.approx(a["periodo"]["municipios"][0]["vezes_media_pa"])


def _dados_sinteticos():
    """R$ 1.000 arrecadados em Parauapebas em 2017 e em 2018 (para testar a troca de regra sem os CSVs)."""
    from app.repositorio import Dados
    linhas = pd.DataFrame({"Ano": pd.array([2017, 2018], dtype="Int64"), "Mes": pd.array([6, 6], dtype="Int64"),
                           "Municipio": "Parauapebas", "Substancia": "FERRO", "SubstanciaGrupo": "FERRO",
                           "TipoPessoa": "PJ", "Grupo": "Parauapebas", "Valor": [1000.0, 1000.0]})
    nac = linhas.assign(UF="PA", Chave="PA|PARAUAPEBAS", EhFoco=True)[
        ["Ano", "Mes", "UF", "Chave", "Substancia", "TipoPessoa", "EhFoco", "Valor", "SubstanciaGrupo"]]
    cob = {"primeiro_ano": 2017, "primeiro_mes": 1, "ultimo_ano": 2018, "ultimo_mes_completo": 12, "ano_parcial": False}
    return Dados("teste", {"arrecadacao": linhas}, {"arrecadacao": nac}, cob, [], "agora")


def test_regra_vigente_em_cada_ano():
    """2017 segue a regra antiga (65/23/0/12) e 2018 a atual; com regra=atual, 2017 passa a 60/15/15/10."""
    from app import distribuicao
    from app.analises import Filtros
    dados = _dados_sinteticos()
    t = distribuicao.exportar(dados, Filtros(ano_inicio=2017, ano_fim=2018)).set_index("Ano")
    cols = ["Município produtor", "Estado", "Municípios afetados", "União"]
    assert t.loc[2017, cols].tolist() == pytest.approx([650, 230, 0, 120])
    assert t.loc[2018, cols].tolist() == pytest.approx([600, 150, 150, 100])
    assert t.loc[2017, "União - ANM"] == pytest.approx(98) and t.loc[2018, "União - CETEM"] == pytest.approx(18)
    t2 = distribuicao.exportar(dados, Filtros(ano_inicio=2017, ano_fim=2018, regra="atual")).set_index("Ano")
    assert t2.loc[2017, cols].tolist() == pytest.approx([600, 150, 150, 100])
    ind = distribuicao.indicadores(dados, Filtros(ano_inicio=2017, ano_fim=2018))
    assert ind["regra_mista"] and ind["foco_soma"]["destinos"]["municipio"] == pytest.approx(1250)


def test_peso_na_cota_estadual(cliente):
    d = cliente.get(f"{D}/peso-nos-repasses").json()["dados"]
    soma = next(s for s in d["series"] if s["nome"] == "Canaã + Parauapebas")
    # mesma regra para todos os municípios do Pará no ano -> participação na cota = participação na arrecadação
    assert soma["pct_cota_estadual_pa"] == pytest.approx(soma["pct_arrecadacao_pa"])
    assert 0 < soma["periodo"]["pct_cota_estadual_pa"] <= 100


def test_tabela_destinos(cliente):
    d = cliente.get(f"{D}/tabela-destinos").json()["dados"]
    total = next(l for l in d["linhas"] if l["tipo"] == "total")
    munis = [l for l in d["linhas"] if l["tipo"] == "municipio"]
    assert total["gerado"] == pytest.approx(sum(l["gerado"] for l in munis))
    rc = next(l for l in d["linhas"] if l.get("escopo") == "RC")
    assert rc["destinos"]["municipio"] == pytest.approx(rc["gerado"] * 0.6)

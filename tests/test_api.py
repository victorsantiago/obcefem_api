"""Testes de ponta a ponta da API. Os valores conferem com o painel do Colab
e com somas feitas direto no CSV de arrecadação 2022–2026 (versão de 30/10/2026)."""
import pytest

V1 = "/api/v1"


def test_saude_e_meta(cliente):
    s = cliente.get(f"{V1}/saude").json()
    assert s["pronto"] and s["estado"] == "pronto"
    m = cliente.get(f"{V1}/meta").json()
    assert set(m["bases"]) == {"arrecadacao", "autuacao"}
    assert "FERRO" in m["bases"]["arrecadacao"]["substancias_agrupadas"]
    assert "São Domingos do Araguaia" in m["bases"]["arrecadacao"]["municipios_sem_registro"]
    assert len(m["regiao_carajas"]) == 12


def test_todas_as_rotas_respondem(cliente):
    for rota in ["indicadores", "evolucao-anual", "comparacao-medias", "participacao", "ranking", "serie-mensal",
                 "substancias", "mapa-calor", "titulares", "tabela-resumo", "painel"]:
        for base in ["arrecadacao", "autuacao"]:
            r = cliente.get(f"{V1}/{rota}", params={"base": base})
            if rota == "serie-mensal" and base == "autuacao":
                assert r.status_code == 400
            else:
                assert r.status_code == 200, (rota, base, r.text[:300])
                corpo = r.json()
                assert {"filtros", "notas", "dados", "versao_dados"} <= set(corpo)


def test_indicadores_batem_com_o_csv(cliente):
    d = cliente.get(f"{V1}/indicadores").json()["dados"]
    assert d["total_regiao"] == pytest.approx(12_378_886_806.77, rel=1e-9)
    foco = {x["municipio"]: x for x in d["foco"]}
    assert foco["Parauapebas"]["valor"] == pytest.approx(5_478_602_757.45, rel=1e-9)
    assert foco["Canaã dos Carajás"]["valor"] == pytest.approx(5_390_963_149.20, rel=1e-9)
    medias = {x["escopo"]: x for x in d["medias"]}
    assert medias["PA"]["municipios"] == 85
    assert medias["PA"]["valor_medio"] == pytest.approx(159_568_238.0, rel=1e-6)
    assert medias["BR"]["municipios"] == 3277
    assert medias["PA"]["vezes"]["Parauapebas"] == pytest.approx(34.33, rel=1e-3)


def test_denominador_todos_e_exclusao_do_foco(cliente):
    d = cliente.get(f"{V1}/indicadores", params={"denominador": "todos", "excluir_foco_das_medias": True}).json()["dados"]
    medias = {x["escopo"]: x for x in d["medias"]}
    assert medias["PA"]["municipios"] == 142 and medias["BR"]["municipios"] == 5568
    assert medias["PA"]["valor_medio"] == pytest.approx(18_969_960, rel=1e-5)


def test_filtros_de_substancia_mes_e_municipio(cliente):
    p = {"substancias": ["minério de ferro"], "mes_fim": 6, "municipios": ["parauapebas", "MARABA"]}
    r = cliente.get(f"{V1}/ranking", params=p)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["filtros"]["substancias"] == ["FERRO"]
    assert [i["municipio"] for i in corpo["dados"]["itens"]] == ["Parauapebas", "Marabá"]
    medias = {m["escopo"]: m for m in corpo["dados"]["medias_periodo"]}
    assert medias["PA"]["municipios"] == 5
    assert medias["PA"]["valor_medio"] == pytest.approx(1_141_020_674.36, rel=1e-6)


def test_validacoes(cliente):
    assert cliente.get(f"{V1}/ranking", params={"municipios": "Belém"}).status_code == 422
    assert cliente.get(f"{V1}/ranking", params={"substancias": "KRIPTONITA"}).status_code == 422
    assert cliente.get(f"{V1}/ranking", params={"ano_inicio": 2025, "ano_fim": 2023}).status_code == 422


def test_ano_parcial_e_serie_mensal(cliente):
    ev = cliente.get(f"{V1}/evolucao-anual").json()
    ultimo = ev["dados"]["anos"][-1]
    assert ultimo["ano"] == 2026 and ultimo["parcial"] is True
    assert any("parcial" in n for n in ev["notas"])
    ev6 = cliente.get(f"{V1}/evolucao-anual", params={"mes_fim": 6}).json()
    assert ev6["dados"]["anos"][-1]["parcial"] is False
    sm = cliente.get(f"{V1}/serie-mensal").json()["dados"]
    assert sm["incompleto_a_partir_de"] == "2026-07"
    assert len(sm["meses"]) == len(sm["series"][0]["valores"])


def test_soma_das_series_igual_ao_total(cliente):
    d = cliente.get(f"{V1}/evolucao-anual").json()["dados"]
    for i, total in enumerate(d["totais"]):
        assert sum(s["valores"][i] for s in d["series"]) == pytest.approx(total)


def test_exportar_csv(cliente):
    r = cliente.get(f"{V1}/exportar.csv", params={"municipios": "Canaã dos Carajás"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    linhas = r.text.strip().splitlines()
    assert linhas[0].lstrip("﻿").startswith("Ano;Mes;Municipio")
    assert len(linhas) - 1 == 251


def test_admin_exige_token(cliente):
    assert cliente.post(f"{V1}/admin/atualizar").status_code == 401
    assert cliente.post(f"{V1}/admin/atualizar", headers={"X-Admin-Token": "segredo-teste"}).status_code == 202

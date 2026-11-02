"""Atualização diária: simula o comportamento real do portal da ANM, que regrava todos os arquivos todo dia.

Dia 1: primeira carga.
Dia 2: arquivos regravados com o MESMO conteúdo (data nova) -> baixa, percebe que é igual, não reprocessa.
Dia 3: arquivo de arrecadação com uma linha nova -> reprocessa e os números mudam.
"""
import functools
import http.server
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import agendador, config, fonte
from app.analises import Filtros, indicadores
from app.repositorio import Repositorio

DADOS = os.environ.get("CFEM_TESTE_DADOS", "./dados_teste")
ARR = "CFEM_Arrecadacao_2022_2026.csv"
AUT = "CFEM_Autuacao.csv"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass


@pytest.fixture()
def portal(tmp_path, monkeypatch):
    pasta = tmp_path / "portal"
    pasta.mkdir()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler, directory=str(pasta)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "PASTA_LOCAL", None)
    monkeypatch.setattr(config, "URL_BASE", f"http://127.0.0.1:{srv.server_address[1]}/")
    monkeypatch.setattr(config, "PASTA_CACHE", tmp_path / "cache")
    yield pasta
    srv.shutdown()


def _regravar(caminho):
    """Simula a ANM regravando o arquivo: mesmo conteúdo, data de modificação nova."""
    dados = caminho.read_bytes()
    time.sleep(1.1)
    caminho.write_bytes(dados)


@pytest.mark.skipif(not os.path.exists(os.path.join(DADOS, ARR)), reason="CSVs de teste ausentes")
def test_ciclo_diario(portal, monkeypatch):
    monkeypatch.setattr(config, "ARQUIVOS_ARRECADACAO", [ARR])
    monkeypatch.setattr(config, "ARQUIVO_AUTUACAO", AUT)
    shutil.copy(os.path.join(DADOS, ARR), portal / ARR)
    shutil.copy(os.path.join(DADOS, AUT), portal / AUT)
    repo = Repositorio()
    f = Filtros()

    r1 = repo.atualizar()                                   # dia 1
    assert r1["status"] == "atualizado"
    total1 = indicadores(repo.dados, f)["foco"][0]["valor"]   # Parauapebas

    _regravar(portal / ARR)
    _regravar(portal / AUT)
    r2 = repo.atualizar()                                   # dia 2: mesmo conteúdo
    assert r2["status"] == "sem_mudancas"
    assert r2["arquivos"][ARR] == {"origem": "anm", "conteudo_mudou": False}
    assert repo.dados.versao == r1["versao"]

    with open(portal / ARR, "a", encoding="cp1252", newline="") as arq:   # dia 3: guia nova
        arq.write('"2026","6","999999","2020","PJ","00000000000000","FERRO","PA","1505536","PARAUAPEBAS",'
                  '"1","t  ","1000,00","2026-06-30 10:00:00"\n')
    r3 = repo.atualizar()
    assert r3["status"] == "atualizado" and r3["versao"] != r1["versao"]
    assert r3["arquivos"][ARR]["conteudo_mudou"] is True
    assert indicadores(repo.dados, f)["foco"][0]["valor"] == pytest.approx(total1 + 1000)

    # Reinício do servidor no mesmo dia: carrega do cache processado, sem reprocessar
    repo2 = Repositorio()
    assert repo2.atualizar()["versao"] == r3["versao"]


def test_portal_fora_do_ar_mantem_dados_e_agenda_nova_tentativa(portal, monkeypatch):
    (portal / AUT).write_text('"A";"B"\n"1";"2"\n', encoding="cp1252")
    a1 = fonte.obter_arquivo(AUT)
    assert a1.origem == "anm"
    monkeypatch.setattr(config, "URL_BASE", "http://127.0.0.1:9/")
    a2 = fonte.obter_arquivo(AUT)
    assert a2.origem == "cache_falha_download" and a2.sha256 == a1.sha256
    assert agendador.precisa_nova_tentativa({"status": "sem_mudancas", "falhas_download": [AUT]})
    with pytest.raises(Exception):
        fonte.obter_arquivo("CFEM_Inexistente.csv")


def test_historico_nao_e_baixado_todo_dia(portal, monkeypatch):
    nome = "CFEM_Arrecadacao_2002_2006.csv"
    (portal / nome).write_text('"Ano"\n"2002"\n', encoding="cp1252")
    monkeypatch.setattr(config, "REBAIXAR_HISTORICOS_A_CADA_DIAS", 7)
    assert fonte.obter_arquivo(nome).origem == "anm"
    assert fonte.obter_arquivo(nome).origem == "cache_historico"     # nem consulta o portal
    assert fonte.eh_historico("CFEM_Arrecadacao_2022_2026.csv") is False
    monkeypatch.setattr(config, "REBAIXAR_HISTORICOS_A_CADA_DIAS", 0)
    _regravar(portal / nome)
    assert fonte.obter_arquivo(nome).origem == "anm"


def test_horario_agendado(monkeypatch):
    monkeypatch.setattr(config, "HORARIO_ATUALIZACAO", "07:30")
    monkeypatch.setattr(config, "FUSO_HORARIO", "America/Belem")
    # 07:00 em Belém (10:00 UTC) -> hoje 07:30 (10:30 UTC)
    agora = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    assert agendador.proxima_execucao(agora) == datetime(2026, 10, 31, 10, 30, tzinfo=timezone.utc)
    # 08:00 em Belém -> amanhã 07:30
    agora = datetime(2026, 10, 31, 11, 0, tzinfo=timezone.utc)
    assert agendador.proxima_execucao(agora) == datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(config, "HORARIO_ATUALIZACAO", "")
    monkeypatch.setattr(config, "ATUALIZAR_A_CADA_HORAS", 0)
    assert agendador.proxima_execucao(agora) is None
    monkeypatch.setattr(config, "ATUALIZAR_A_CADA_HORAS", 6)
    assert agendador.proxima_execucao(agora) == agora + timedelta(hours=6)


@pytest.mark.skipif(not os.path.exists(os.path.join(DADOS, ARR)), reason="CSVs de teste ausentes")
def test_modo_pre_processado_vercel(tmp_path, monkeypatch):
    """Gera dados_processados/ e lê de volta, como na Vercel (sem rede e sem gravar em disco)."""
    from app.repositorio import carregar_pre_processado, salvar_pre_processado
    monkeypatch.setattr(config, "PASTA_LOCAL", DADOS)
    monkeypatch.setattr(config, "PASTA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(config, "ARQUIVOS_ARRECADACAO", [ARR])
    monkeypatch.setattr(config, "ARQUIVO_AUTUACAO", AUT)
    origem = Repositorio()
    assert origem.atualizar()["status"] == "atualizado"
    destino = tmp_path / "dados_processados"
    assert salvar_pre_processado(origem.dados, destino) is True
    assert salvar_pre_processado(origem.dados, destino) is False      # mesma versão: não reescreve

    monkeypatch.setattr(config, "MODO", "pre_processado")
    monkeypatch.setattr(config, "PASTA_PRE_PROCESSADO", destino)
    vercel = Repositorio()
    vercel.garantir()
    assert vercel.pronto and vercel.dados.versao == origem.dados.versao
    f = Filtros()
    assert indicadores(vercel.dados, f) == indicadores(origem.dados, f)
    assert vercel.atualizar()["status"] == "erro"                       # não tenta baixar nada

    sem_dados = Repositorio()
    monkeypatch.setattr(config, "PASTA_PRE_PROCESSADO", tmp_path / "inexistente")
    sem_dados.garantir()
    assert not sem_dados.pronto and "gerar_dados.py" in sem_dados.ultimo_erro


def test_verificacao_do_historico_e_trava_diaria(tmp_path):
    """Arquivo incompleto (meses faltando) não passa na carga do histórico, e queda de valor
    em ano encerrado aciona a trava da atualização diária."""
    import importlib.util
    import pandas as pd

    def carregar(nome):
        spec = importlib.util.spec_from_file_location(nome, os.path.join(os.path.dirname(__file__), "..", "scripts", f"{nome}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    hist = carregar("gerar_historico")
    linhas = [{"Ano": a, "Mes": m, "Valor": 1.0} for a in (2019, 2020) for m in range(1, 13) for _ in range(40)]
    completo = pd.DataFrame(linhas)
    assert hist.verificar(completo, [2019, 2020]) == ([], (2019, 1))
    truncado = completo[~((completo["Ano"] == 2020) & (completo["Mes"] > 6))]
    assert any("2020: faltam os meses" in p for p in hist.verificar(truncado, [2019, 2020])[0])
    assert any("2021: nenhum registro" in p for p in hist.verificar(completo, [2019, 2020, 2021])[0])
    # série que começa no meio (como a da ANM, em mai/2003): o começo vazio não é erro
    tardio = completo[(completo["Ano"] > 2019) | (completo["Mes"] >= 5)]
    assert hist.verificar(tardio, [2018, 2019, 2020]) == ([], (2019, 5))
    # registro isolado antes do início real (caso real: uma guia de ago/2002 de um processo de 2007)
    isolado = pd.concat([tardio, pd.DataFrame([{"Ano": 2018, "Mes": 8, "Valor": 206.41}])])
    assert hist.verificar(isolado, [2018, 2019, 2020]) == ([], (2019, 5))
    # mas se o primeiro arquivo inteiro vier vazio, é erro
    assert hist.verificar(completo[completo["Ano"] == 2020], [2018, 2019, 2020], fim_primeiro_arquivo=2019)[0]

    diario = carregar("gerar_dados")
    pasta = tmp_path / "publicado"
    pasta.mkdir()
    pd.DataFrame({"Ano": [2023, 2024, 2025], "Valor": [100.0, 100.0, 50.0]}).to_parquet(pasta / "nacional_arrecadacao.parquet")
    pd.DataFrame({"Ano": [2023, 2024, 2025]}).to_parquet(pasta / "regiao_arrecadacao.parquet")

    class Novo:
        cobertura = {"ultimo_ano": 2025}
        def __init__(self, valores):
            self.nacional = {"arrecadacao": pd.DataFrame({"Ano": [2023, 2024, 2025], "Valor": valores})}
            self.regiao = {"arrecadacao": pd.DataFrame({"Ano": [2023, 2024, 2025]})}

    assert diario.checar_contra_publicado(Novo([100.0, 101.0, 10.0]), pasta) == []      # 2025 é o ano corrente
    problemas = diario.checar_contra_publicado(Novo([100.0, 60.0, 50.0]), pasta)
    assert len(problemas) == 1 and problemas[0].startswith("2024")


def test_historico_barra_publicacao_incompleta_da_anm(tmp_path, monkeypatch):
    """Caso real de 01/11/2026: arquivos menores e só ~30% dos valores."""
    import importlib.util
    import pandas as pd
    spec = importlib.util.spec_from_file_location("gh", os.path.join(os.path.dirname(__file__), "..", "scripts", "gerar_historico.py"))
    hist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hist)

    class F:
        def __init__(self, nome, tam):
            self.nome, self.tamanho_bytes = nome, tam
    assert hist.checar_tamanhos([F("CFEM_Arrecadacao_2017_2021.csv", 84_063_006)]) == []
    assert hist.checar_tamanhos([F("CFEM_Arrecadacao_2017_2021.csv", 30_121_381)])

    monkeypatch.setattr(config, "PASTA_PRE_PROCESSADO", tmp_path)
    pd.DataFrame({"Ano": [2022], "Valor": [7.02e9]}).to_parquet(tmp_path / "nacional_arrecadacao.parquet")
    bom = pd.DataFrame({"Ano": [2020, 2021], "Valor": [6.1e9, 10.3e9]})
    ruim = pd.DataFrame({"Ano": [2020, 2021], "Valor": [2.4e9, 2.94e9]})
    assert hist.checar_valores(bom) == []
    problemas = hist.checar_valores(ruim)
    assert any("oficial" in p for p in problemas) and any("2022" in p for p in problemas)


def test_codigos_de_saida_da_atualizacao_diaria(tmp_path, monkeypatch, capsys):
    """Trava = código 2 com aviso amarelo no Actions (não é erro); portal fora do ar = 1; tudo certo = 0."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gd", os.path.join(os.path.dirname(__file__), "..", "scripts", "gerar_dados.py"))
    diario = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diario)
    resumo = tmp_path / "resumo.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))
    monkeypatch.setattr(diario.config, "PASTA_PRE_PROCESSADO", tmp_path)
    monkeypatch.setattr(diario, "salvar_pre_processado", lambda novo, destino: True)

    class Repo:
        pronto = True
        falhas = []
        dados_sem_historico = type("N", (), {"versao": "abc"})()
        def atualizar(self):
            return {"status": "ok", "falhas_download": self.falhas,
                    "arquivos": {"CFEM_Arrecadacao_2022_2026.csv": {"origem": "anm", "conteudo_mudou": True, "tamanho_bytes": 28_906_852}}}

    monkeypatch.setattr(diario, "Repositorio", Repo)
    monkeypatch.setattr(sys, "argv", ["gerar_dados.py"])
    monkeypatch.setattr(diario, "checar_contra_publicado", lambda novo, pasta: ["2024: arrecadação nacional caiu"])
    assert diario.main() == 2
    assert "::warning" in capsys.readouterr().out
    assert "Nada foi publicado" in resumo.read_text() and "28.9 MB" in resumo.read_text()

    monkeypatch.setattr(sys, "argv", ["gerar_dados.py", "--forcar"])
    assert diario.main() == 0

    monkeypatch.setattr(sys, "argv", ["gerar_dados.py"])
    monkeypatch.setattr(diario, "checar_contra_publicado", lambda novo, pasta: [])
    assert diario.main() == 0
    Repo.falhas = ["CFEM_Arrecadacao_2022_2026.csv"]
    assert diario.main() == 1
    assert "Portal da ANM indisponível" in resumo.read_text()

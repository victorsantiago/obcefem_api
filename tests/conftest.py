"""Os testes usam CSVs locais. Aponte CFEM_TESTE_DADOS para uma pasta com
CFEM_Arrecadacao_2022_2026.csv e CFEM_Autuacao.csv (baixados de https://dadosabertos.anm.gov.br/CFEM/)."""
import os
import tempfile
import time

import pytest

PASTA_DADOS = os.environ.get("CFEM_TESTE_DADOS", "./dados_teste")
os.environ.setdefault("CFEM_PASTA_LOCAL", PASTA_DADOS)
os.environ.setdefault("CFEM_PASTA_CACHE", tempfile.mkdtemp(prefix="cfem_cache_"))
os.environ.setdefault("CFEM_ATUALIZAR_A_CADA_HORAS", "0")
os.environ.setdefault("CFEM_HORARIO_ATUALIZACAO", "")
os.environ.setdefault("CFEM_TOKEN_ADMIN", "segredo-teste")
# Os valores esperados nos testes são do arquivo 2022–2026; uma pasta vazia evita anexar o histórico
# 2003–2021 que estiver em dados_processados/historico.
os.environ.setdefault("CFEM_PASTA_PRE_PROCESSADO", tempfile.mkdtemp(prefix="cfem_pre_"))


@pytest.fixture(scope="session")
def cliente():
    if not os.path.exists(os.path.join(PASTA_DADOS, "CFEM_Arrecadacao_2022_2026.csv")):
        pytest.skip(f"CSVs de teste não encontrados em {PASTA_DADOS}")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        for _ in range(240):
            if c.get("/api/v1/saude").json()["pronto"]:
                break
            time.sleep(0.5)
        yield c

"""Configuração por variáveis de ambiente (ver .env.example)."""
import os
from pathlib import Path


def _lista(nome: str, padrao: list[str]) -> list[str]:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return [x.strip() for x in valor.split(",") if x.strip()]


# Portal de dados abertos da ANM
URL_BASE = os.getenv("CFEM_URL_BASE", "https://dadosabertos.anm.gov.br/CFEM/")

# Arquivos de arrecadação a carregar. Para a série histórica completa, acrescente
# CFEM_Arrecadacao_2002_2006.csv, ..._2007_2011.csv, ..._2012_2016.csv, ..._2017_2021.csv
ARQUIVOS_ARRECADACAO = _lista("CFEM_ARQUIVOS_ARRECADACAO", ["CFEM_Arrecadacao_2022_2026.csv"])

# Arquivo de autuações (deixe vazio para desativar)
ARQUIVO_AUTUACAO = os.getenv("CFEM_ARQUIVO_AUTUACAO", "CFEM_Autuacao.csv").strip()

# Onde guardar os CSVs baixados e os dados já processados (parquet)
PASTA_CACHE = Path(os.getenv("CFEM_PASTA_CACHE", "./cache"))

# Se definido, lê os CSVs desta pasta e NÃO baixa nada (útil em desenvolvimento/testes)
PASTA_LOCAL = os.getenv("CFEM_PASTA_LOCAL") or None

# Atualização diária em horário fixo. A ANM regrava os arquivos todo dia por volta das 6h (horário de Brasília);
# 07:30 dá margem. Deixe vazio para usar o intervalo em horas abaixo.
HORARIO_ATUALIZACAO = os.getenv("CFEM_HORARIO_ATUALIZACAO", "07:30").strip()
FUSO_HORARIO = os.getenv("CFEM_FUSO_HORARIO", "America/Belem")

# Alternativa ao horário fixo: verificar a cada N horas (0 desativa). Só vale se CFEM_HORARIO_ATUALIZACAO estiver vazio.
ATUALIZAR_A_CADA_HORAS = float(os.getenv("CFEM_ATUALIZAR_A_CADA_HORAS", "0"))

# Se o portal falhar, tenta de novo depois de N minutos (até o próximo horário agendado)
NOVA_TENTATIVA_MINUTOS = float(os.getenv("CFEM_NOVA_TENTATIVA_MINUTOS", "60"))

# Arquivos de períodos encerrados (ex.: ..._2017_2021.csv) quase não mudam, mas a ANM os regrava todo dia.
# Só são baixados de novo se a cópia local tiver mais de N dias (0 = baixar todo dia).
REBAIXAR_HISTORICOS_A_CADA_DIAS = float(os.getenv("CFEM_REBAIXAR_HISTORICOS_A_CADA_DIAS", "7"))

# Token exigido em POST /api/v1/admin/atualizar (header X-Admin-Token). Sem token, a rota fica desativada.
TOKEN_ADMIN = os.getenv("CFEM_TOKEN_ADMIN") or None

# Origens liberadas para o front (CORS)
CORS_ORIGENS = _lista("CFEM_CORS_ORIGENS", ["*"])

# Tempo máximo de download de cada CSV, em segundos
TIMEOUT_DOWNLOAD = float(os.getenv("CFEM_TIMEOUT_DOWNLOAD", "900"))

# Linhas por bloco na leitura dos CSVs grandes (controla o uso de memória)
LINHAS_POR_BLOCO = int(os.getenv("CFEM_LINHAS_POR_BLOCO", "250000"))

# Quantidade de respostas guardadas em memória (cache por combinação de filtros)
CACHE_RESPOSTAS = int(os.getenv("CFEM_CACHE_RESPOSTAS", "512"))

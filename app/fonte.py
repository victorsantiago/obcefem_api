"""Obtenção dos CSVs do portal da ANM, com cache local.

Como a ANM publica: todos os arquivos de https://dadosabertos.anm.gov.br/CFEM/ são regravados diariamente
(por volta das 6h), inclusive os de períodos encerrados. Por isso o Last-Modified/ETag muda todo dia mesmo
quando o conteúdo é igual. A API então:

- envia If-None-Match / If-Modified-Since (se algum dia o portal responder 304, nada é baixado);
- calcula o SHA-256 de cada arquivo: a "versão" dos dados depende do CONTEÚDO, não da data.
  Se o arquivo baixado for idêntico ao anterior, nada é reprocessado;
- arquivos de períodos encerrados (ex.: CFEM_Arrecadacao_2017_2021.csv) só são baixados de novo
  quando a cópia local tiver mais de CFEM_REBAIXAR_HISTORICOS_A_CADA_DIAS dias;
- se o download falhar e já existir cópia local, segue com ela (origem = "cache_falha_download").
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app import config

log = logging.getLogger("cfem.fonte")

RE_PERIODO = re.compile(r"_(\d{4})_(\d{4})\.csv$", re.IGNORECASE)


@dataclass
class ArquivoFonte:
    nome: str
    caminho: str
    origem: str          # "anm" | "cache" (304) | "cache_historico" | "cache_falha_download" | "local"
    url: str | None
    tamanho_bytes: int
    sha256: str
    last_modified: str | None
    etag: str | None
    baixado_em: str | None
    conteudo_mudou: bool | None = None   # em relação à cópia anterior (None = primeira vez/desconhecido)

    def assinatura(self) -> str:
        return f"{self.nome}|{self.sha256}"

    def como_dict(self) -> dict:
        d = asdict(self)
        d.pop("caminho")
        return d


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def eh_historico(nome: str, hoje: date | None = None) -> bool:
    """Arquivo de período encerrado (ano final anterior ao ano corrente)."""
    m = RE_PERIODO.search(nome)
    return bool(m) and int(m.group(2)) < (hoje or date.today()).year


def obter_arquivo(nome: str) -> ArquivoFonte:
    # Modo local: lê de uma pasta, sem rede
    if config.PASTA_LOCAL:
        caminho = Path(config.PASTA_LOCAL) / nome
        if not caminho.exists():
            raise FileNotFoundError(f"{caminho} não encontrado (CFEM_PASTA_LOCAL={config.PASTA_LOCAL})")
        st = caminho.stat()
        return ArquivoFonte(nome, str(caminho), "local", None, st.st_size, sha256_arquivo(caminho),
                            datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"), None, None)

    pasta = config.PASTA_CACHE / "brutos"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome
    arq_meta = pasta / f"{nome}.meta.json"
    meta = json.loads(arq_meta.read_text()) if arq_meta.exists() and destino.exists() else {}
    if destino.exists() and not meta.get("sha256"):
        meta["sha256"] = sha256_arquivo(destino)
    url = urljoin(config.URL_BASE, nome)

    def _resultado(origem, mudou=None):
        return ArquivoFonte(nome, str(destino), origem, url, destino.stat().st_size, meta["sha256"],
                            meta.get("last_modified"), meta.get("etag"), meta.get("baixado_em"), mudou)

    # Período encerrado com cópia recente: não baixa de novo
    dias = config.REBAIXAR_HISTORICOS_A_CADA_DIAS
    if dias > 0 and destino.exists() and eh_historico(nome) and meta.get("baixado_em"):
        idade = datetime.now(timezone.utc) - datetime.fromisoformat(meta["baixado_em"])
        if idade.total_seconds() < dias * 86400:
            return _resultado("cache_historico", False)

    cabecalhos = {"Accept-Encoding": "identity", "User-Agent": "cfem-carajas-api/1.1"}
    if destino.exists():
        if meta.get("etag"):
            cabecalhos["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            cabecalhos["If-Modified-Since"] = meta["last_modified"]

    try:
        timeout = httpx.Timeout(config.TIMEOUT_DOWNLOAD, connect=30)
        with httpx.stream("GET", url, headers=cabecalhos, timeout=timeout, follow_redirects=True) as resp:
            if resp.status_code == 304:
                log.info("%s: portal respondeu 304 (sem alterações)", nome)
                return _resultado("cache", False)
            resp.raise_for_status()
            parcial = destino.with_name(destino.name + ".parcial")
            h = hashlib.sha256()
            with open(parcial, "wb") as f:
                for bloco in resp.iter_bytes(1 << 20):   # descomprime se o servidor mandar gzip
                    f.write(bloco)
                    h.update(bloco)
            esperado = resp.headers.get("content-length")
            recebido = parcial.stat().st_size
            if esperado and not resp.headers.get("content-encoding") and int(esperado) != recebido:
                parcial.unlink(missing_ok=True)
                raise IOError(f"download incompleto de {nome}: {recebido}/{esperado} bytes")
            novo_sha = h.hexdigest()
            mudou = None if not meta.get("sha256") else novo_sha != meta["sha256"]
            os.replace(parcial, destino)
            meta = {"etag": resp.headers.get("etag"), "last_modified": resp.headers.get("last-modified"),
                    "baixado_em": _agora(), "url": url, "sha256": novo_sha}
            arq_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
            log.info("%s baixado (%.1f MB)%s", nome, recebido / 1e6,
                     "" if mudou is None else (" — conteúdo novo" if mudou else " — conteúdo idêntico ao anterior"))
            return _resultado("anm", mudou)
    except (httpx.HTTPError, OSError) as erro:
        if destino.exists():
            log.warning("Falha ao baixar %s (%s). Usando a cópia local.", nome, erro)
            return _resultado("cache_falha_download", False)
        raise


def versao_conjunto(fontes: list[ArquivoFonte]) -> str:
    """Identificador da combinação de arquivos. Depende só do conteúdo (SHA-256) e da versão da lógica."""
    base = "\n".join(sorted(f.assinatura() for f in fontes)) + "\nlogica=v1"
    return hashlib.sha1(base.encode()).hexdigest()[:12]

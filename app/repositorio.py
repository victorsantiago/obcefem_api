"""Carga dos dados em memória, com cache processado em parquet e troca atômica na atualização."""
from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from app import config
from app.fonte import ArquivoFonte, obter_arquivo, versao_conjunto
from app.leitura import preparar_arrecadacao, preparar_autuacao

log = logging.getLogger("cfem.repositorio")


@dataclass
class Dados:
    versao: str
    regiao: dict[str, pd.DataFrame]      # por base: linhas dos 12 municípios
    nacional: dict[str, pd.DataFrame]    # por base: agregado do Brasil inteiro
    cobertura: dict
    fontes: list[dict]
    carregado_em: str
    substancias: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # base -> {"agrupadas"|"originais": [...]}

    @property
    def bases(self) -> list[str]:
        return list(self.regiao)


class DadosIndisponiveis(RuntimeError):
    pass


class Repositorio:
    def __init__(self):
        self._dados: Dados | None = None
        self._trava = threading.Lock()
        self.estado = "iniciando"
        self.ultimo_erro: str | None = None
        self.ultima_verificacao: str | None = None
        self.proxima_atualizacao: str | None = None
        self.ultimo_resultado: dict | None = None

    # ------------------------------------------------------------------ acesso
    @property
    def dados(self) -> Dados:
        if self._dados is None:
            raise DadosIndisponiveis(self.ultimo_erro or "Dados ainda estão sendo carregados.")
        return self._dados

    @property
    def pronto(self) -> bool:
        return self._dados is not None

    # ------------------------------------------------------------------ carga / atualização
    def atualizar(self, forcar: bool = False) -> dict:
        """Verifica o portal, baixa o que mudou e reprocessa se necessário. Retorna um resumo."""
        if not self._trava.acquire(blocking=False):
            return {"status": "ja_em_andamento"}
        try:
            resultado = self._atualizar(forcar)
        finally:
            self._trava.release()
        self.ultimo_resultado = {**resultado, "em": _agora()}
        return resultado

    def _atualizar(self, forcar: bool) -> dict:
        try:
            self.estado = "atualizando" if self._dados else "carregando"
            self.ultima_verificacao = _agora()
            nomes = list(config.ARQUIVOS_ARRECADACAO) + ([config.ARQUIVO_AUTUACAO] if config.ARQUIVO_AUTUACAO else [])
            fontes = [obter_arquivo(n) for n in nomes]
            versao = versao_conjunto(fontes)
            resumo = {"arquivos": {f.nome: {"origem": f.origem, "conteudo_mudou": f.conteudo_mudou} for f in fontes},
                      "falhas_download": [f.nome for f in fontes if f.origem == "cache_falha_download"]}
            if not forcar and self._dados is not None and self._dados.versao == versao:
                self.estado = "pronto"
                return {"status": "sem_mudancas", "versao": versao, **resumo}

            novo = None if forcar else self._ler_processado(versao, fontes)
            if novo is None:
                novo = self._processar(versao, fontes)
                self._salvar_processado(novo)
            self._dados = novo                      # troca atômica
            self.estado, self.ultimo_erro = "pronto", None
            log.info("Dados prontos (versão %s)", versao)
            return {"status": "atualizado", "versao": versao, **resumo}
        except Exception as erro:  # noqa: BLE001
            log.exception("Falha ao carregar os dados")
            self.ultimo_erro = f"{type(erro).__name__}: {erro}"
            self.estado = "pronto" if self._dados else "erro"
            return {"status": "erro", "erro": self.ultimo_erro}

    def _processar(self, versao: str, fontes: list[ArquivoFonte]) -> Dados:
        arr_fontes = [f for f in fontes if f.nome in config.ARQUIVOS_ARRECADACAO]
        aut_fonte = next((f for f in fontes if f.nome == config.ARQUIVO_AUTUACAO), None)
        regiao, nacional = {}, {}
        nomes_por_doc: dict[str, str] = {}
        if aut_fonte:
            log.info("Processando %s", aut_fonte.nome)
            reg_aut, nac_aut, nomes_por_doc = preparar_autuacao(aut_fonte.caminho)
        log.info("Processando arrecadação (%d arquivo(s))", len(arr_fontes))
        regiao["arrecadacao"], nacional["arrecadacao"], cobertura = preparar_arrecadacao(
            [f.caminho for f in arr_fontes], nomes_por_doc)
        if aut_fonte:
            regiao["autuacao"], nacional["autuacao"] = reg_aut, nac_aut
        return self._montar(versao, regiao, nacional, cobertura, [f.como_dict() for f in fontes])

    @staticmethod
    def _montar(versao, regiao, nacional, cobertura, fontes) -> Dados:
        substancias = {}
        for base, df in regiao.items():
            substancias[base] = {
                "agrupadas": df.groupby("SubstanciaGrupo")["Valor"].sum().sort_values(ascending=False).index.tolist(),
                "originais": df.groupby("Substancia")["Valor"].sum().sort_values(ascending=False).index.tolist(),
            }
        return Dados(versao, regiao, nacional, cobertura, fontes, _agora(), substancias)

    # ------------------------------------------------------------------ cache processado (parquet)
    def _pasta(self, versao: str):
        return config.PASTA_CACHE / "processado" / versao

    def _salvar_processado(self, d: Dados) -> None:
        try:
            pasta = self._pasta(d.versao)
            pasta.mkdir(parents=True, exist_ok=True)
            for base in d.regiao:
                d.regiao[base].to_parquet(pasta / f"regiao_{base}.parquet", index=False)
                d.nacional[base].to_parquet(pasta / f"nacional_{base}.parquet", index=False)
            (pasta / "meta.json").write_text(json.dumps(
                {"bases": d.bases, "cobertura": d.cobertura, "fontes": d.fontes}, ensure_ascii=False, indent=2))
            for antiga in (config.PASTA_CACHE / "processado").iterdir():   # mantém só a versão atual
                if antiga.is_dir() and antiga.name != d.versao:
                    shutil.rmtree(antiga, ignore_errors=True)
        except Exception:  # noqa: BLE001 - cache é opcional
            log.exception("Não foi possível salvar o cache processado")

    def _ler_processado(self, versao: str, fontes: list[ArquivoFonte]) -> Dados | None:
        pasta = self._pasta(versao)
        if not (pasta / "meta.json").exists():
            return None
        try:
            meta = json.loads((pasta / "meta.json").read_text())
            regiao = {b: pd.read_parquet(pasta / f"regiao_{b}.parquet") for b in meta["bases"]}
            nacional = {b: pd.read_parquet(pasta / f"nacional_{b}.parquet") for b in meta["bases"]}
            log.info("Dados carregados do cache processado (versão %s)", versao)
            return self._montar(versao, regiao, nacional, meta["cobertura"], [f.como_dict() for f in fontes])
        except Exception:  # noqa: BLE001
            log.exception("Cache processado inválido; reprocessando")
            return None


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


repositorio = Repositorio()

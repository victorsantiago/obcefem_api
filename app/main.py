"""API REST da CFEM — Canaã dos Carajás e Parauapebas × Região de Carajás.

Rodar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
Docs:   http://localhost:8000/docs
"""
from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import agendador, config
from app.analises import Filtros, calcular, filtrar, metadados, notas
from app.dominio import MAPA_MUN, REGIAO_CARAJAS, norm
from app.leitura import grupo_substancia
from app.repositorio import Dados, DadosIndisponiveis, repositorio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("cfem.api")

_parar = threading.Event()


def _laco_atualizacao():
    agendador.laco(repositorio, _parar)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.MODO == "pre_processado":
        # Vercel/serverless: só lê dados_processados/ (menos de 1 s); a atualização é feita fora (GitHub Actions)
        repositorio.garantir()
    else:
        # Servidor: a carga roda em segundo plano; a API sobe na hora e responde 503 até os dados ficarem prontos
        threading.Thread(target=_laco_atualizacao, name="cfem-atualizacao", daemon=True).start()
    yield
    _parar.set()


app = FastAPI(
    title="API CFEM — Canaã dos Carajás e Parauapebas × Região de Carajás",
    description=("Dados abertos da ANM (https://dadosabertos.anm.gov.br/CFEM/) processados para o painel: "
                 "arrecadação e autuações dos 12 municípios da região de Carajás, com foco em Parauapebas e "
                 "Canaã dos Carajás, e médias por município do Pará e do Brasil."),
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGENS, allow_methods=["GET", "POST"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

api = APIRouter(prefix="/api/v1")


# ============================================================================ dependências
def obter_dados() -> Dados:
    repositorio.garantir()   # no modo pré-processado, carrega sob demanda (não depende do lifespan)
    try:
        return repositorio.dados
    except DadosIndisponiveis as e:
        raise HTTPException(503, detail=f"Dados indisponíveis no momento ({repositorio.estado}): {e}",
                            headers={"Retry-After": "30"})


def obter_filtros(
    dados: Dados = Depends(obter_dados),
    base: Literal["arrecadacao", "autuacao"] = Query("arrecadacao", description="Base de dados"),
    ano_inicio: int | None = Query(None, ge=1990, le=2100, description="Padrão: primeiro ano da base"),
    ano_fim: int | None = Query(None, ge=1990, le=2100, description="Padrão: último ano da base"),
    mes_inicio: int = Query(1, ge=1, le=12, description="Só para arrecadação"),
    mes_fim: int = Query(12, ge=1, le=12, description="Só para arrecadação"),
    substancias: list[str] = Query([], description="Repita o parâmetro para várias (?substancias=FERRO&substancias=COBRE). Vazio = todas"),
    agrupar_substancias: bool = Query(True, description="Somar 'MINÉRIO DE X' com 'X'"),
    tipo_titular: Literal["Todos", "PJ", "PF"] = Query("Todos"),
    municipios: list[str] = Query([], description="Municípios da região na comparação (com ou sem acento). Vazio = os 12"),
    denominador: Literal["com_registro", "todos"] = Query(
        "com_registro", description="Divisor das médias PA/BR: municípios com registro no período, ou todos (PA 144 · BR 5.570)"),
    excluir_foco_das_medias: bool = Query(False, description="Tirar Canaã e Parauapebas das médias PA/BR"),
    top_n: int = Query(10, ge=1, le=50, description="Itens em substâncias e titulares"),
) -> Filtros:
    if base not in dados.regiao:
        raise HTTPException(400, detail=f"Base '{base}' não carregada. Disponíveis: {dados.bases}")
    df = dados.regiao[base]
    a_ini = ano_inicio if ano_inicio is not None else int(df["Ano"].min())
    a_fim = ano_fim if ano_fim is not None else int(df["Ano"].max())
    if a_ini > a_fim:
        raise HTTPException(422, detail="ano_inicio maior que ano_fim")
    if mes_inicio > mes_fim:
        raise HTTPException(422, detail="mes_inicio maior que mes_fim")

    munis = []
    for m in municipios:
        canon = MAPA_MUN.get(norm(m))
        if canon is None:
            raise HTTPException(422, detail={"erro": f"Município fora da região: {m}", "validos": REGIAO_CARAJAS})
        munis.append(canon)
    munis = [m for m in REGIAO_CARAJAS if m in munis] or list(REGIAO_CARAJAS)

    validas = dados.substancias[base]["agrupadas" if agrupar_substancias else "originais"]
    mapa_subst = {norm(s): s for s in validas}
    subst = []
    for s in substancias:
        # com agrupamento, "minério de ferro" e "ferro" apontam para o mesmo grupo "FERRO"
        canon = mapa_subst.get(norm(grupo_substancia(s) if agrupar_substancias else s))
        if canon is None:
            raise HTTPException(422, detail={"erro": f"Substância inexistente na região: {s}", "validas": validas})
        subst.append(canon)

    return Filtros(base=base, ano_inicio=a_ini, ano_fim=a_fim, mes_inicio=mes_inicio, mes_fim=mes_fim,
                   substancias=tuple(sorted(set(subst))), agrupar_substancias=agrupar_substancias,
                   tipo_titular=tipo_titular, municipios=tuple(munis), denominador=denominador,
                   excluir_foco_das_medias=excluir_foco_das_medias, top_n=top_n)


def _resposta(nome: str, dados: Dados, f: Filtros) -> dict:
    try:
        resultado = calcular(nome, dados, f)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"filtros": f.como_dict(), "versao_dados": dados.versao, "notas": notas(dados, f), "dados": resultado}


# ============================================================================ rotas
@api.get("/saude", tags=["sistema"], summary="Estado da carga dos dados")
def saude():
    repositorio.garantir()
    d = repositorio._dados
    return {"estado": repositorio.estado, "pronto": repositorio.pronto, "modo": config.MODO,
            "versao_dados": d.versao if d else None,
            "carregado_em": d.carregado_em if d else None, "ultima_verificacao": repositorio.ultima_verificacao,
            "proxima_atualizacao": repositorio.proxima_atualizacao, "ultimo_resultado": repositorio.ultimo_resultado,
            "ultimo_erro": repositorio.ultimo_erro}


@api.get("/meta", tags=["sistema"], summary="Opções para montar os filtros no front (anos, substâncias, municípios, cores, cobertura)")
def meta(dados: Dados = Depends(obter_dados)):
    return metadados(dados)


@api.post("/admin/atualizar", tags=["sistema"], status_code=202,
          summary="Força a verificação/baixa dos CSVs na ANM (header X-Admin-Token)")
def admin_atualizar(tarefas: BackgroundTasks, forcar: bool = False,
                    x_admin_token: str | None = Header(None)):
    if config.MODO == "pre_processado":
        raise HTTPException(409, detail="Nesta hospedagem os dados são atualizados pelo GitHub Actions "
                                        "(workflow 'Atualizar dados da ANM'). Rode-o pela aba Actions do repositório.")
    if not config.TOKEN_ADMIN:
        raise HTTPException(403, detail="Defina CFEM_TOKEN_ADMIN para habilitar esta rota.")
    if x_admin_token != config.TOKEN_ADMIN:
        raise HTTPException(401, detail="Token inválido.")
    tarefas.add_task(repositorio.atualizar, forcar)
    return {"status": "agendado", "forcar": forcar, "acompanhe_em": "/api/v1/saude"}


def _rota(nome: str, resumo: str):
    def handler(dados: Dados = Depends(obter_dados), f: Filtros = Depends(obter_filtros)):
        return _resposta(nome, dados, f)
    handler.__name__ = nome
    caminho = "/" + nome.replace("_", "-")
    api.add_api_route(caminho, handler, methods=["GET"], tags=["visualizações"], summary=resumo)


_rota("indicadores", "Cartões: total da região, Parauapebas, Canaã, soma e médias PA/BR")
_rota("evolucao_anual", "Valor por ano: Parauapebas, Canaã e demais municípios da região")
_rota("comparacao_medias", "Parauapebas e Canaã × média por município do Pará e do Brasil (por ano e no período)")
_rota("participacao", "Participação (%) de Parauapebas, Canaã e da soma no total da região, por ano")
_rota("ranking", "Ranking dos municípios da região + médias PA/BR do período")
_rota("serie_mensal", "Série mensal (só arrecadação), com o mês a partir do qual os dados estão incompletos")
_rota("substancias", "Top N substâncias por valor, separadas em Parauapebas, Canaã e demais")
_rota("mapa_calor", "Matriz município × ano")
_rota("titulares", "Maiores titulares em Parauapebas e Canaã")
_rota("tabela_resumo", "Tabela município × ano + total da região + linhas de média PA/BR")
_rota("painel", "Todas as visualizações numa chamada só")


@api.get("/exportar.csv", tags=["exportação"], summary="Linhas filtradas da região em CSV (; e vírgula decimal)")
def exportar_csv(dados: Dados = Depends(obter_dados), f: Filtros = Depends(obter_filtros)):
    d = filtrar(dados, f).drop(columns=["SubstanciaExib"])
    buf = io.StringIO()
    d.to_csv(buf, sep=";", decimal=",", index=False)
    nome = f"cfem_{f.base}_carajas_{f.ano_inicio}_{f.ano_fim}.csv"
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


app.include_router(api)

# Front (painel web) servido na raiz. Para hospedar o front em outro lugar, basta copiar a pasta
# front/ e abrir index.html?api=https://seu-servidor/api/v1
PASTA_FRONT = Path(__file__).resolve().parent.parent / "front"
if PASTA_FRONT.exists():
    app.mount("/", StaticFiles(directory=PASTA_FRONT, html=True), name="front")

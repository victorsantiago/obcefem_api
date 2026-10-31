"""Agenda da atualização automática.

Padrão: todo dia às 07:30 (America/Belem), depois da publicação diária da ANM (~6h).
Se o download falhar (portal fora do ar) ou a carga der erro, tenta de novo a cada
CFEM_NOVA_TENTATIVA_MINUTOS até o próximo horário agendado.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import config

log = logging.getLogger("cfem.agendador")


def proxima_execucao(agora: datetime) -> datetime | None:
    """Próximo horário agendado (em UTC), ou None se a atualização automática estiver desativada."""
    if config.HORARIO_ATUALIZACAO:
        hora, minuto = (int(x) for x in config.HORARIO_ATUALIZACAO.split(":"))
        fuso = ZoneInfo(config.FUSO_HORARIO)
        local = agora.astimezone(fuso)
        alvo = local.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if alvo <= local:
            alvo += timedelta(days=1)
        return alvo.astimezone(timezone.utc)
    if config.ATUALIZAR_A_CADA_HORAS > 0:
        return agora + timedelta(hours=config.ATUALIZAR_A_CADA_HORAS)
    return None


def precisa_nova_tentativa(resultado: dict) -> bool:
    return resultado.get("status") == "erro" or bool(resultado.get("falhas_download"))


def laco(repositorio, parar: threading.Event) -> None:
    resultado = repositorio.atualizar()
    while True:
        agora = datetime.now(timezone.utc)
        prox = proxima_execucao(agora)
        if precisa_nova_tentativa(resultado) and config.NOVA_TENTATIVA_MINUTOS > 0:
            retry = agora + timedelta(minutes=config.NOVA_TENTATIVA_MINUTOS)
            prox = min(prox, retry) if prox else retry
            log.warning("Atualização incompleta (%s); nova tentativa às %s UTC",
                        resultado.get("erro") or resultado.get("falhas_download"), retry.strftime("%H:%M"))
        repositorio.proxima_atualizacao = prox.isoformat(timespec="seconds") if prox else None
        if prox is None:
            return
        if parar.wait(max(0.0, (prox - agora).total_seconds())):
            return
        log.info("Verificando o portal da ANM…")
        resultado = repositorio.atualizar()
        log.info("Resultado da atualização: %s", {k: v for k, v in resultado.items() if k != "arquivos"})

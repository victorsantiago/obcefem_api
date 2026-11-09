"""Verificação TLS do portal da ANM, tolerante a cadeia de certificados incompleta.

É comum servidores do governo mandarem só o certificado do site, sem a AC intermediária. Navegadores
completam a cadeia sozinhos (baixando a intermediária pelo endereço "CA Issuers" que vem no próprio
certificado, a extensão AIA), mas o Python não: dá "CERTIFICATE_VERIFY_FAILED: unable to get local
issuer certificate".

Aqui fazemos o mesmo que o navegador, sem abrir mão da verificação:
- 1ª tentativa: verificação normal (raízes do certifi + PEMs extras da pasta certificados/);
- se falhar por cadeia, baixa as intermediárias pela AIA e tenta de novo. Só entram certificados que
  NÃO são autoassinados, e a verificação parcial fica desligada: a cadeia continua tendo que terminar
  numa raiz confiável do certifi (ou da pasta certificados/). Uma "raiz" servida por terceiros nunca
  passa a ser confiável.

Se a ANM passar a usar uma AC raiz que não está no certifi, ponha o PEM dela em certificados/.
"""
from __future__ import annotations

import logging
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import httpx
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

log = logging.getLogger("cfem.tls")

PASTA_CERTIFICADOS = Path(__file__).resolve().parent.parent / "certificados"
MAX_NIVEIS = 5

_contextos: dict[str, ssl.SSLContext] = {}
_completados: set[str] = set()
_resumos: dict[str, str] = {}


def ja_completado(url: str) -> bool:
    return (urlsplit(url).hostname or "") in _completados


def eh_erro_de_cadeia(erro: BaseException) -> bool:
    """True se a falha foi de verificação do certificado (e não rede fora do ar, timeout etc.)."""
    while erro is not None:
        if isinstance(erro, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(erro):
            return True
        erro = erro.__cause__ or erro.__context__
    return False


def _pems_extras() -> str:
    if not PASTA_CERTIFICADOS.is_dir():
        return ""
    return "\n".join(p.read_text() for p in sorted(PASTA_CERTIFICADOS.glob("*.pem")))


def contexto_base(cafile: str | None = None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=cafile or certifi.where())
    # sem verificação parcial: certificado intermediário nunca vira âncora de confiança
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    extras = _pems_extras()
    if extras.strip():
        ctx.load_verify_locations(cadata=extras)
    return ctx


def _carregar_certificados(dados: bytes) -> list[x509.Certificate]:
    """O endereço CA Issuers pode devolver DER, PEM ou PKCS#7 (.p7c)."""
    for carregar in (lambda d: [x509.load_der_x509_certificate(d)], x509.load_pem_x509_certificates,
                     pkcs7.load_der_pkcs7_certificates, pkcs7.load_pem_pkcs7_certificates):
        try:
            certs = carregar(dados)
            if certs:
                return list(certs)
        except Exception:
            continue
    return []


def _url_emissor(cert: x509.Certificate) -> list[str]:
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in aia
            if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS and d.access_location.value.startswith("http")]


def _autoassinado(cert: x509.Certificate) -> bool:
    return cert.issuer == cert.subject


def certificado_do_servidor(host: str, porta: int = 443, timeout: float = 30) -> x509.Certificate:
    """Lê o certificado que o servidor apresenta. Só para ler a AIA: não confia nele por isso."""
    pem = ssl.get_server_certificate((host, porta), timeout=timeout)
    return x509.load_pem_x509_certificate(pem.encode())


def intermediarias_via_aia(folha: x509.Certificate, timeout: float = 30) -> list[x509.Certificate]:
    cadeia, atual = [], folha
    for _ in range(MAX_NIVEIS):
        urls = _url_emissor(atual)
        if not urls:
            break
        proximo = None
        for url in urls:
            try:
                r = httpx.get(url, timeout=timeout, follow_redirects=True)
                r.raise_for_status()
            except httpx.HTTPError as erro:
                log.warning("AIA: falha ao baixar %s (%s)", url, erro)
                continue
            certs = [c for c in _carregar_certificados(r.content) if c.subject == atual.issuer]
            if certs:
                proximo = certs[0]
                break
        if proximo is None or _autoassinado(proximo):
            break       # raiz: tem que vir do certifi / certificados/, nunca da internet
        cadeia.append(proximo)
        atual = proximo
    return cadeia


def descrever(cert: x509.Certificate) -> str:
    return (f"emitido para {cert.subject.rfc4514_string()} por {cert.issuer.rfc4514_string()}, "
            f"válido de {cert.not_valid_before_utc:%d/%m/%Y} a {cert.not_valid_after_utc:%d/%m/%Y}"
            + (f", AIA {', '.join(_url_emissor(cert))}" if _url_emissor(cert) else ", sem AIA"))


def contexto_com_cadeia(host: str, porta: int = 443, cafile: str | None = None) -> tuple[ssl.SSLContext, str]:
    """Contexto com as intermediárias do host completadas pela AIA. Devolve também uma descrição para o log."""
    folha = certificado_do_servidor(host, porta)
    inter = intermediarias_via_aia(folha)
    ctx = contexto_base(cafile)
    if inter:
        ctx.load_verify_locations(cadata="\n".join(c.public_bytes(Encoding.PEM).decode() for c in inter))
    resumo = f"certificado de {host}: {descrever(folha)}; intermediárias obtidas pela AIA: {len(inter)}"
    return ctx, resumo


def verificacao_para(url: str) -> ssl.SSLContext:
    """Contexto já completado para o host (se uma tentativa anterior precisou), ou o contexto base."""
    host = urlsplit(url).hostname or ""
    if host not in _contextos:
        _contextos[host] = contexto_base()
    return _contextos[host]


def completar_cadeia(url: str) -> str:
    """Chamado depois de uma falha de cadeia: prepara o contexto do host para a próxima tentativa."""
    partes = urlsplit(url)
    ctx, resumo = contexto_com_cadeia(partes.hostname, partes.port or 443)
    _contextos[partes.hostname] = ctx
    _completados.add(partes.hostname)
    _resumos[partes.hostname] = resumo
    log.warning("Cadeia de certificados incompleta; completada pela AIA. %s", resumo)
    return resumo


def diagnostico(url: str) -> str:
    """Texto para o log/resumo quando nem a cadeia completada passou: ajuda a saber qual AC falta."""
    resumo = _resumos.get(urlsplit(url).hostname or "", "")
    return (f"Nem completando a cadeia pela AIA a verificação passou ({resumo}). Provavelmente a AC raiz não está "
            "no certifi: coloque o PEM dela na pasta certificados/.") if resumo else ""

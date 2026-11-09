"""Cadeia de certificados incompleta (servidor sem a AC intermediária), como passou a acontecer no portal da ANM.

Monta uma PKI local: raiz -> intermediária -> certificado do servidor (127.0.0.1). O servidor HTTPS manda só o
próprio certificado; a intermediária fica num servidor HTTP, no endereço da AIA."""
import datetime as dt
import http.server
import ipaddress
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from app import tls


def _nome(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(cn, chave, emissor_nome, emissor_chave, ca, aia=None, ip=None):
    agora = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(_nome(cn)).issuer_name(emissor_nome).public_key(chave.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(days=1))
         .not_valid_after(agora + dt.timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(emissor_chave.public_key()), critical=False))
    if ca:
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    else:
        b = b.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    if aia:
        b = b.add_extension(x509.AuthorityInformationAccess(
            [x509.AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(aia))]),
            critical=False)
    if ip:
        b = b.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
    return b.sign(emissor_chave, hashes.SHA256())


def _pem(c):
    return c.public_bytes(serialization.Encoding.PEM)


class _Arquivos(http.server.BaseHTTPRequestHandler):
    conteudo: dict = {}

    def do_GET(self):
        corpo = self.conteudo.get(self.path)
        self.send_response(200 if corpo is not None else 404)
        self.end_headers()
        if corpo is not None:
            self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def _servidor(handler, ctx=None):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if ctx:
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def pki(tmp_path, monkeypatch):
    aia = _servidor(type("AIA", (_Arquivos,), {"conteudo": {}}))
    base_aia = f"http://127.0.0.1:{aia.server_address[1]}"
    k_raiz, k_int, k_srv = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    raiz = _cert("Raiz Teste", k_raiz, _nome("Raiz Teste"), k_raiz, True)
    inter = _cert("Intermediaria Teste", k_int, raiz.subject, k_raiz, True, aia=f"{base_aia}/raiz.cer")
    folha = _cert("127.0.0.1", k_srv, inter.subject, k_int, False, aia=f"{base_aia}/inter.cer", ip="127.0.0.1")
    aia.RequestHandlerClass.conteudo.update({"/inter.cer": inter.public_bytes(serialization.Encoding.DER),
                                             "/raiz.cer": raiz.public_bytes(serialization.Encoding.DER)})
    raiz_pem = tmp_path / "raiz.pem"
    raiz_pem.write_bytes(_pem(raiz))
    # servidor HTTPS que manda só o próprio certificado (sem a intermediária)
    (tmp_path / "srv.pem").write_bytes(_pem(folha))
    (tmp_path / "srv.key").write_bytes(k_srv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    ctx_srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx_srv.load_cert_chain(tmp_path / "srv.pem", tmp_path / "srv.key")
    arquivos = type("ANM", (_Arquivos,), {"conteudo": {"/CFEM/teste.csv": b"Ano;Valor\n2026;1\n"}})
    https = _servidor(arquivos, ctx_srv)
    monkeypatch.setattr(tls.certifi, "where", lambda: str(raiz_pem))
    monkeypatch.setattr(tls, "PASTA_CERTIFICADOS", tmp_path / "sem_certificados")
    tls._contextos.clear(); tls._completados.clear(); tls._resumos.clear()
    yield {"url": f"https://127.0.0.1:{https.server_address[1]}/CFEM/", "raiz": raiz_pem, "aia": aia,
           "k_int": k_int, "inter": inter, "base_aia": base_aia, "tmp": tmp_path}
    https.shutdown(); aia.shutdown()


def test_cadeia_incompleta_falha_sem_aia_e_passa_com_aia(pki):
    with pytest.raises(httpx.ConnectError) as e:
        httpx.get(pki["url"] + "teste.csv", verify=tls.contexto_base())
    assert tls.eh_erro_de_cadeia(e.value)
    ctx, resumo = tls.contexto_com_cadeia("127.0.0.1", int(pki["url"].split(":")[2].split("/")[0]))
    assert "intermediárias obtidas pela AIA: 1" in resumo
    assert httpx.get(pki["url"] + "teste.csv", verify=ctx).text.startswith("Ano;Valor")


def test_raiz_vinda_da_internet_nao_vira_confiavel(pki):
    # A AIA aponta para uma "raiz" autoassinada que não está no certifi: não pode ser aceita.
    k_falsa = ec.generate_private_key(ec.SECP256R1())
    falsa = _cert("Raiz Falsa", k_falsa, _nome("Raiz Falsa"), k_falsa, True)
    pki["aia"].RequestHandlerClass.conteudo["/inter.cer"] = falsa.public_bytes(serialization.Encoding.DER)
    porta = int(pki["url"].split(":")[2].split("/")[0])
    ctx, resumo = tls.contexto_com_cadeia("127.0.0.1", porta)
    assert "intermediárias obtidas pela AIA: 0" in resumo
    with pytest.raises(httpx.ConnectError):
        httpx.get(pki["url"] + "teste.csv", verify=ctx)


def test_download_da_anm_completa_a_cadeia_sozinho(pki, monkeypatch, tmp_path):
    from app import config, fonte
    monkeypatch.setattr(config, "PASTA_LOCAL", None)
    monkeypatch.setattr(config, "PASTA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(config, "URL_BASE", pki["url"])
    arq = fonte.obter_arquivo("teste.csv")
    assert arq.origem == "anm" and arq.tamanho_bytes > 0
    assert tls.ja_completado(pki["url"])

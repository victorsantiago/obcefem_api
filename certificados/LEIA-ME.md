# Certificados extras

Certificados de AC (em formato PEM, extensão `.pem`) que a API passa a aceitar, além das raízes do `certifi`,
ao baixar os CSVs do portal da ANM. Veja `app/tls.py`.

Normalmente esta pasta fica vazia: quando o portal manda a cadeia incompleta, a API completa sozinha as ACs
intermediárias pelo endereço "CA Issuers" (AIA) do certificado. Só é preciso pôr um arquivo aqui se a ANM
passar a usar uma AC **raiz** que não está no `certifi`. Nesse caso, o resumo da execução no GitHub Actions
mostra qual é o emissor do certificado.

# API CFEM — Canaã dos Carajás e Parauapebas × Região de Carajás

Backend em Python (FastAPI) que baixa os CSVs de **https://dadosabertos.anm.gov.br/CFEM/**, aplica a mesma lógica do painel do Colab e entrega os dados prontos para o front montar os gráficos.

- **Foco:** Parauapebas e Canaã dos Carajás.
- **Comparação:** os 12 municípios da região de Carajás e a **média por município do Pará e do Brasil**.
- **Bases:** arrecadação (`CFEM_Arrecadacao_*.csv`) e autuações (`CFEM_Autuacao.csv`).

## Painel web

A pasta `front/` traz o painel pronto (HTML, CSS e JavaScript puro, sem etapa de build). Ele é servido pela própria API na raiz: depois de subir o servidor, abra **http://localhost:8000/**.

- **Filtros na lateral:** base, período, meses, substâncias (com busca), titular, municípios da comparação, forma de calcular as médias, escala logarítmica e itens nos rankings. No celular, os filtros ficam numa gaveta.
- **Manchete:** uma frase que se reescreve a cada filtro, seguida de seis indicadores e nove seções: evolução anual, comparação com as médias do Pará e do Brasil (gráfico e tabela), participação, substâncias, ranking com as linhas de média, mês a mês (com os meses incompletos sombreados), mapa de calor, maiores titulares e tabela resumo.
- **Uma chamada por seção:** cada seção chama o seu endpoint, em paralelo, e mostra o próprio estado de carregamento ou erro.
- **Demais endpoints:** `/meta` monta os filtros, `/saude` mostra quando os dados foram processados e quando é a próxima verificação. Os botões usam `/exportar.csv` e `/painel` (JSON), e "Atualizar agora" chama `/admin/atualizar` com o token.
- **Link compartilhável:** os filtros ficam na URL, então o link reabre o painel no mesmo estado.
- **Atualização sem recarregar:** a cada 10 min o painel confere se há dados novos (atualização diária) e se recarrega sozinho.
- **Tema:** claro ou escuro, conforme o sistema.
- **Gráficos:** Plotly incluído em `front/vendor/`, sem depender de CDN. Cada gráfico baixa como PNG em alta resolução pelo menu do próprio gráfico.

Para hospedar o front em outro servidor, copie a pasta `front/` e abra `index.html?api=https://seu-servidor/api/v1`, ou defina `window.CFEM_API` antes de carregar `app.js`. Se for em outro domínio, libere esse domínio em `CFEM_CORS_ORIGENS`.

## Rodando

```bash
pip install -r requirements.txt
cp .env.example .env            # ajuste se quiser
uvicorn app.main:app --env-file .env --port 8000
```

- Painel: http://localhost:8000/
- Documentação interativa: http://localhost:8000/docs
- A API sobe na hora e baixa/processa os CSVs em segundo plano. Até terminar, as rotas de dados respondem **503** com `Retry-After`. Acompanhe em `/api/v1/saude`.
- Tempos medidos com o arquivo 2022–2026 (100 MB): ~5 s de processamento e ~400 MB de memória no pico. Na reinicialização, os dados processados saem do cache em parquet em menos de 1 s.

Com Docker:

```bash
docker build -t cfem-api .
docker run -p 8000:8000 -v cfem_dados:/data --env-file .env cfem-api
```

## Atualização diária

A ANM regrava **todos** os arquivos de `/CFEM/` todo dia por volta das 6h (horário de Brasília), inclusive os de períodos encerrados. A data de modificação muda todo dia, mesmo quando o conteúdo é igual. A API lida com isso assim:

1. **Horário fixo.** Todo dia às **07:30 (America/Belem)** a API consulta o portal (`CFEM_HORARIO_ATUALIZACAO`, `CFEM_FUSO_HORARIO`). A próxima execução aparece em `/api/v1/saude` → `proxima_atualizacao`.
2. **Recarga completa, não incremental.** A API não acrescenta só as linhas novas: baixa o arquivo do período atual inteiro e reprocessa. Isso é intencional. A ANM também altera meses passados (guias que chegam com atraso preenchem meses que estavam incompletos), e só acrescentar linhas deixaria essas correções de fora. Com o arquivo 2022–2026, a recarga leva cerca de 5 s.
3. **Versão pelo conteúdo.** Cada arquivo baixado recebe um SHA-256. Se o conteúdo for idêntico ao do dia anterior, nada é reprocessado (`status = "sem_mudancas"`). A "versão dos dados" só muda quando o conteúdo muda.
4. **Arquivos históricos.** `..._2002_2006` a `..._2017_2021` só são baixados de novo se a cópia local tiver mais de 7 dias (`CFEM_REBAIXAR_HISTORICOS_A_CADA_DIAS`). Isso evita ~225 MB de download por dia de arquivos que não mudam.
5. **Falhas.** Se o portal estiver fora do ar, a API continua servindo a última versão e tenta de novo a cada 60 min (`CFEM_NOVA_TENTATIVA_MINUTOS`) até o próximo horário agendado.
6. **Troca sem interrupção.** Os dados novos substituem os antigos de uma vez só. Requisições em andamento não são afetadas, e o cache de respostas é renovado automaticamente (a versão faz parte da chave).
7. **Reinício.** O resultado processado fica em `CFEM_PASTA_CACHE/processado/<versão>/*.parquet`. Ao reiniciar no mesmo dia, carrega em menos de 1 s.
8. **Forçar agora:** `POST /api/v1/admin/atualizar?forcar=true` com o header `X-Admin-Token` (defina `CFEM_TOKEN_ADMIN`).

`GET /api/v1/saude` mostra o resultado da última verificação: para cada arquivo, a origem (`anm`, `cache_historico`, `cache_falha_download`…) e se o conteúdo mudou.

> **Implantação:** rode **um único processo** (`--workers 1`). Cada worker teria sua própria cópia dos dados e seu próprio agendamento. Para escalar horizontalmente, separe a atualização num job (ex.: cron chamando `/admin/atualizar`) e desligue o agendamento interno com `CFEM_HORARIO_ATUALIZACAO=` vazio.

Para carregar a **série histórica completa** (2002 em diante), liste os arquivos por período em `CFEM_ARQUIVOS_ARRECADACAO`. Veja `.env.example`.

## Filtros (query string, iguais em todas as rotas de visualização)

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `base` | `arrecadacao` | `arrecadacao` ou `autuacao` |
| `ano_inicio`, `ano_fim` | faixa da base | Para autuação, o ano é o do processo de cobrança |
| `mes_inicio`, `mes_fim` | 1, 12 | Só na arrecadação. Use `mes_fim=6` para comparar 2026 (parcial) com anos completos |
| `substancias` | todas | Repita o parâmetro: `?substancias=FERRO&substancias=COBRE`. Aceita com ou sem acento |
| `agrupar_substancias` | `true` | Soma "MINÉRIO DE FERRO" com "FERRO" |
| `tipo_titular` | `Todos` | `Todos`, `PJ` ou `PF` |
| `municipios` | os 12 | Municípios da região na comparação (repita o parâmetro) |
| `denominador` | `com_registro` | Divisor das médias PA/BR: `com_registro` (municípios com registro no período) ou `todos` (PA 144 · BR 5.570, IBGE) |
| `excluir_foco_das_medias` | `false` | Tira Canaã e Parauapebas das médias PA/BR |
| `top_n` | 10 | Itens em substâncias e titulares (1–50) |

Valores inválidos (município fora da região, substância inexistente, anos invertidos) retornam **422**, com a lista de opções válidas.

## Rotas (`/api/v1`)

| Rota | Para que serve no front |
|---|---|
| `GET /saude` | Estado da carga (`pronto`, `versao_dados`, `ultimo_erro`) |
| `GET /meta` | Monta os filtros: anos por base, substâncias (ordenadas por valor), municípios, cores, cobertura do último ano, fontes |
| `GET /indicadores` | Cartões: total da região, Parauapebas, Canaã, soma, média PA e BR (com "quantas vezes") |
| `GET /evolucao-anual` | Barras empilhadas por ano: Parauapebas, Canaã, demais municípios + totais |
| `GET /comparacao-medias` | Parauapebas e Canaã × média por município do PA e do BR, por ano e no período |
| `GET /participacao` | % de Parauapebas, Canaã e da soma no total da região, por ano |
| `GET /ranking` | Municípios da região ordenados por valor + médias PA/BR do período (linhas de referência) |
| `GET /serie-mensal` | Série mensal (só arrecadação) + `incompleto_a_partir_de` para sombrear meses incompletos |
| `GET /substancias` | Top N substâncias, separadas em Parauapebas, Canaã e demais |
| `GET /mapa-calor` | Matriz município × ano |
| `GET /titulares` | Maiores titulares em Parauapebas e Canaã |
| `GET /tabela-resumo` | Município × ano + total da região + linhas de média PA/BR |
| `GET /painel` | Todas as anteriores numa chamada só |
| `GET /exportar.csv` | Linhas filtradas da região em CSV (`;` e vírgula decimal, abre direto no Excel) |
| `POST /admin/atualizar` | Força a verificação do portal (header `X-Admin-Token`) |

### Formato das respostas

Todas as rotas de visualização devolvem:

```json
{
  "filtros": { "...filtros efetivamente aplicados..." },
  "versao_dados": "dc9b04c1c74c",
  "notas": ["2026 é parcial: o volume de registros só é completo até jun. ..."],
  "dados": { "...específico de cada rota..." }
}
```

- Valores em **R$ como número** (sem formatação). Percentuais de 0 a 100. `null` onde não há valor.
- Os anos vêm como `{"ano": 2026, "rotulo": "2026 (parcial)", "parcial": true}`, para o front marcar o ano incompleto.
- Cada série traz uma `cor` sugerida, a mesma do painel do Colab.

A pasta `exemplos/` tem respostas reais (`meta.json`, `indicadores.json`, `comparacao_medias.json`, `ranking_ferro_jan_jun.json`, `painel.json`) e o `openapi.json`, que serve para gerar um cliente tipado (ex.: `openapi-typescript`).

### Exemplo no front (JavaScript)

```js
const API = "http://localhost:8000/api/v1";
const params = new URLSearchParams({ mes_fim: 6, excluir_foco_das_medias: true });
["FERRO", "COBRE"].forEach(s => params.append("substancias", s));

const r = await fetch(`${API}/comparacao-medias?${params}`);
if (r.status === 503) { /* dados carregando: tente de novo em alguns segundos */ }
const { dados, notas } = await r.json();

// Plotly: barras agrupadas por ano (escala log)
const x = dados.anos.map(a => a.rotulo);
const traces = [
  ...dados.municipios.map(m => ({ type: "bar", name: m.nome, x, y: m.valores, marker: { color: m.cor } })),
  ...dados.medias.map(m => ({ type: "bar", name: m.nome, x, y: m.valor_medio, marker: { color: m.cor } })),
];
Plotly.newPlot("grafico", traces, { barmode: "group", yaxis: { type: "log" }, separators: ",." });
```

## Testes

```bash
# pasta com CFEM_Arrecadacao_2022_2026.csv e CFEM_Autuacao.csv
CFEM_TESTE_DADOS=./dados_teste pytest -q
```

Os testes conferem os totais com somas feitas direto no CSV, os filtros, as validações, o ano parcial, a exportação e o download com cache. A atualização diária é testada contra um servidor local que imita o portal: arquivo regravado com o mesmo conteúdo (não reprocessa), linha nova (reprocessa e o valor muda), portal fora do ar, arquivo histórico e horário agendado.

## Observações sobre os dados

- **Arrecadação** é o valor pago pelas mineradoras referente à produção do município, não o repasse à prefeitura (a cota do município produtor é 60%, Lei 13.540/2017). O repasse está em `CFEM_Distribuicao.csv`, que pode ser incluído com a mesma estrutura.
- **Autuação** é o valor inicial do auto de cobrança, não valor pago.
- O último ano da arrecadação é parcial. A API detecta o último mês completo comparando o volume de registros com a mediana dos anos anteriores (ver `cobertura_arrecadacao` em `/meta`).
- As **médias PA/BR** usam o país inteiro (todas as UFs do CSV), com os mesmos filtros de período, substância e titular. Linhas sem município nem UF ficam de fora (no arquivo 2022–2026, 51 linhas, cerca de R$ 0,9 mi).
- São Domingos do Araguaia não tem registros nas bases atuais.
- Os valores são nominais (sem correção monetária).

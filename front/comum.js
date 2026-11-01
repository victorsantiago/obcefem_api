/* Observatório da CFEM — código comum às páginas (filtros, URL, carga das seções, tema dos gráficos).
 * Cada página carrega este arquivo e, depois, o seu (app.js = arrecadação, distribuicao.js = distribuição),
 * que define window.PAGINA com as seções e as rotas.
 * Consome a API em /api/v1 (mesma origem por padrão; para outra, use ?api=https://servidor/api/v1
 * ou defina window.CFEM_API antes deste script).
 */
"use strict";

// ============================================================================ configuração
const URL_INICIAL = new URLSearchParams(location.search);
const API = (URL_INICIAL.get("api") || window.CFEM_API || new URL("api/v1", document.baseURI).href).replace(/\/$/, "");

const FOCO = ["Parauapebas", "Canaã dos Carajás"];
const DEMAIS = "Demais municípios da região";
const SOMA = "Canaã + Parauapebas";
const REF_PA = "Média dos municípios do Pará";
const REF_BR = "Média dos municípios do Brasil";
const REF_RC = "Média dos municípios da região de Carajás";
const ESCOPOS = [["RC", "Região"], ["PA", "PA"], ["BR", "BR"]];   // médias de referência, da mais próxima à mais ampla
const COR_VAR = {
  "Parauapebas": "--c-parauapebas", "Canaã dos Carajás": "--c-canaa", [DEMAIS]: "--c-demais",
  [SOMA]: "--c-soma", [REF_RC]: "--c-media-rc", [REF_PA]: "--c-media-pa", [REF_BR]: "--c-media-br",
};
// Ano em que o painel abre selecionado (o usuário pode escolher desde o início da série).
// Se a base não tiver esse ano, usa o mais próximo disponível.
const ANO_INICIAL_PADRAO = 2022;
const anoInicialPadrao = (b) => Math.min(Math.max(ANO_INICIAL_PADRAO, b.ano_min), b.ano_max);

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const CAMPOS_LISTA = ["substancias", "municipios"];

const estado = {
  meta: null,
  versao: null,
  respostas: {},          // última resposta de cada rota (para redesenhar sem refazer a chamada)
  controlador: null,
  temporizador: null,
};

// ============================================================================ utilitários
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];
const css = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const corSerie = (nome) => css(COR_VAR[nome] || "--c-contexto");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const nf = (casas) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const NF2 = nf(2), NF1 = nf(1), NF0 = nf(0);

function brl(v, compacto = true) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (compacto) {
    const a = Math.abs(v);
    if (a >= 1e9) return `R$ ${NF2.format(v / 1e9)} bi`;
    if (a >= 1e6) return `R$ ${NF2.format(v / 1e6)} mi`;
    if (a >= 1e3) return `R$ ${NF2.format(v / 1e3)} mil`;
  }
  return `R$ ${NF2.format(v)}`;
}
const pct = (v) => (v === null || v === undefined ? "–" : v > 0 && v < 0.1 ? "<0,1%" : `${NF1.format(v)}%`);
const vezes = (v) => (v === null || v === undefined ? "–" : v >= 10 ? `${NF0.format(v)}×` : `${NF1.format(v)}×`);
const vezesTexto = (v) => (v === null || v === undefined ? "–" : v >= 10 ? NF0.format(v) : NF1.format(v));
const frase = (s) => { const t = String(s).toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
const rotuloEixo = (r) => r.replace(" (", "<br>(");
const dataHora = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "–");

async function chamar(rota, qs = "", opcoes = {}) {
  const resp = await fetch(`${API}/${rota}${qs ? `?${qs}` : ""}`, opcoes);
  if (!resp.ok) {
    let msg = resp.statusText;
    try {
      const j = await resp.json();
      msg = typeof j.detail === "string" ? j.detail : (j.detail && (j.detail.erro || JSON.stringify(j.detail))) || msg;
    } catch (_) { /* sem corpo JSON */ }
    const erro = new Error(msg);
    erro.status = resp.status;
    throw erro;
  }
  return resp.json();
}

// ============================================================================ filtros <-> formulário <-> URL
const form = () => $("#filtros");
const pagina = () => window.PAGINA;
// A página de distribuição não tem o seletor de base: trabalha sempre sobre a arrecadação
const baseAtual = () => (form().base ? form().base.value : "arrecadacao");

function lerFiltros() {
  const f = form();
  const marcados = (id) => $$(`#${id} input:checked`).map((i) => i.value);
  // Substâncias: todas marcadas = sem filtro (lista vazia para a API); nenhuma marcada = esperar o usuário escolher
  const subst = marcados("lista-substancias");
  const totalSubst = $$("#lista-substancias input").length;
  return {
    base: baseAtual(),
    ano_inicio: f.ano_inicio.value,
    ano_fim: f.ano_fim.value,
    mes_inicio: f.mes_inicio.value,
    mes_fim: f.mes_fim.value,
    substancias: subst.length === totalSubst ? [] : subst,
    semSubstancia: totalSubst > 0 && subst.length === 0,
    agrupar_substancias: f.agrupar_substancias.checked,
    tipo_titular: f.tipo_titular ? f.tipo_titular.value : undefined,
    municipios: marcados("lista-municipios"),
    denominador: f.denominador.value,
    excluir_foco_das_medias: f.excluir_foco_das_medias.checked,
    top_n: f.top_n ? f.top_n.value : undefined,
    regra: f.regra ? f.regra.value : undefined,
    escala: f.escala.checked ? "log" : "linear",
  };
}

function paramsAPI(fl) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(fl)) {
    if (k === "escala" || k === "semSubstancia" || v === undefined) continue;
    if (k === "base" && !form().base) continue;
    if (CAMPOS_LISTA.includes(k)) {
      if (k === "municipios" && v.length === estado.meta.regiao_carajas.length) continue;
      v.forEach((x) => p.append(k, x));
    } else if (fl.base === "autuacao" && (k === "mes_inicio" || k === "mes_fim")) {
      continue;
    } else {
      p.append(k, v);
    }
  }
  return p;
}

function paramsURL(fl) {
  const p = paramsAPI(fl);
  // tira da URL o que está no padrão, para o link compartilhado ficar curto
  const b = estado.meta.bases[fl.base];
  const padrao = { base: "arrecadacao", ano_inicio: String(anoInicialPadrao(b)), ano_fim: String(b.ano_max), mes_inicio: "1", mes_fim: "12",
    agrupar_substancias: "true", tipo_titular: "Todos", denominador: "com_registro", excluir_foco_das_medias: "false", top_n: "10", regra: "vigente" };
  for (const [k, v] of Object.entries(padrao)) if (p.get(k) === v) p.delete(k);
  if (fl.escala === "log") p.set("escala", "log");
  if (URL_INICIAL.get("api")) p.set("api", URL_INICIAL.get("api"));
  return p;
}

function opcoes(select, itens, valor) {
  select.innerHTML = itens.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
  if (valor !== undefined && itens.some(([v]) => String(v) === String(valor))) select.value = valor;
}

// selecionadas vazio ou ausente = todas marcadas (padrão)
function montarSubstancias(selecionadas) {
  const f = form();
  const b = estado.meta.bases[baseAtual()];
  const lista = f.agrupar_substancias.checked ? b.substancias_agrupadas : b.substancias_originais;
  const todas = !selecionadas || selecionadas.length === 0;
  const sel = new Set((selecionadas || []).map((s) => s.toUpperCase()));
  $("#lista-substancias").innerHTML = lista.map((s) =>
    `<label class="marcar" data-busca="${esc(s.toLowerCase())}"><input type="checkbox" value="${esc(s)}" ${todas || sel.has(s.toUpperCase()) ? "checked" : ""}> ${esc(frase(s))}</label>`).join("")
    + '<p class="sem-resultado" hidden>Nenhuma substância com esse nome.</p>';
  filtrarListaSubstancias();
}

const semAcento = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

function filtrarListaSubstancias() {
  const termo = semAcento($("#busca-substancia").value.trim().toLowerCase());
  let visiveis = 0;
  $$("#lista-substancias label").forEach((l) => {
    l.hidden = Boolean(termo) && !semAcento(l.dataset.busca).includes(termo);
    if (!l.hidden) visiveis += 1;
  });
  const aviso = $("#lista-substancias .sem-resultado");
  if (aviso) aviso.hidden = visiveis > 0;
}

// Enter na busca: se só sobrou uma substância na lista, marca ela
function enterNaBusca(e) {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const visiveis = $$("#lista-substancias label").filter((l) => !l.hidden);
  if (visiveis.length !== 1) return;
  const caixa = $("input", visiveis[0]);
  if (!caixa.checked) {
    caixa.checked = true;
    caixa.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function montarMunicipios(selecionados) {
  const b = estado.meta.bases[baseAtual()];
  const sem = new Set(b.municipios_sem_registro);
  const sel = new Set(selecionados && selecionados.length ? selecionados : estado.meta.regiao_carajas);
  $("#lista-municipios").innerHTML = estado.meta.regiao_carajas.map((m) => {
    const cor = FOCO.includes(m) ? `style="background:var(${COR_VAR[m]})"` : "";
    return `<label class="marcar"><input type="checkbox" value="${esc(m)}" ${sel.has(m) ? "checked" : ""}>
      <span class="amostra" ${cor}></span>${esc(m)}${sem.has(m) ? ' <span class="valor">sem registros</span>' : ""}</label>`;
  }).join("");
}

function montarPeriodo(valores = {}) {
  const f = form();
  const b = estado.meta.bases[baseAtual()];
  const anos = [];
  for (let a = b.ano_min; a <= b.ano_max; a++) anos.push([a, a]);
  opcoes(f.ano_inicio, anos, valores.ano_inicio ?? anoInicialPadrao(b));
  opcoes(f.ano_fim, anos, valores.ano_fim ?? b.ano_max);
  const meses = MESES.map((m, i) => [i + 1, m]);
  opcoes(f.mes_inicio, meses, valores.mes_inicio ?? 1);
  opcoes(f.mes_fim, meses, valores.mes_fim ?? 12);
  const temMes = b.tem_mes;
  $("#grupo-meses").hidden = !temMes;
  if ($("#dica-base")) $("#dica-base").textContent = baseAtual() === "arrecadacao"
    ? "Valor pago pelas mineradoras sobre a produção do município. Não é o repasse que chega à prefeitura."
    : "Valor inicial dos autos de cobrança, não valor pago. O ano é o do processo de cobrança.";
}

function aplicarNoFormulario(p) {
  const f = form();
  const base = p.get("base");
  if (f.base && base && estado.meta.bases[base]) f.base.value = base;
  montarPeriodo({ ano_inicio: p.get("ano_inicio") ?? undefined, ano_fim: p.get("ano_fim") ?? undefined,
    mes_inicio: p.get("mes_inicio") ?? undefined, mes_fim: p.get("mes_fim") ?? undefined });
  f.agrupar_substancias.checked = p.get("agrupar_substancias") !== "false";
  montarSubstancias(p.getAll("substancias"));   // sem o parâmetro na URL = todas marcadas
  montarMunicipios(p.getAll("municipios"));
  if (f.tipo_titular) f.tipo_titular.value = p.get("tipo_titular") || "Todos";
  f.denominador.value = p.get("denominador") === "todos" ? "todos" : "com_registro";
  f.excluir_foco_das_medias.checked = p.get("excluir_foco_das_medias") === "true";
  if (f.top_n) f.top_n.value = p.get("top_n") || "10";
  if (f.regra) f.regra.value = p.get("regra") === "atual" ? "atual" : "vigente";
  f.escala.checked = p.get("escala") === "log";
}

function atualizarResumos(fl) {
  const ns = fl.substancias.length;
  const totalSubst = $$("#lista-substancias input").length;
  $("#resumo-substancias").textContent = fl.semSubstancia ? "Nenhuma marcada"
    : ns === 0 ? `Todas (${totalSubst})` : ns === 1 ? frase(fl.substancias[0]) : `${ns} de ${totalSubst}`;
  $("#dica-substancias").hidden = !fl.semSubstancia;
  const nm = fl.municipios.length, total = estado.meta.regiao_carajas.length;
  $("#resumo-municipios").textContent = nm === 0 || nm === total ? `Os ${total} municípios` : `${nm} de ${total}`;
  const base = pagina().rotulo ? pagina().rotulo(fl) : fl.base === "arrecadacao" ? "Arrecadação" : "Autuações";
  $("#resumo-movel").textContent = `${base}, ${fl.ano_inicio} a ${fl.ano_fim}${ns ? `, ${$("#resumo-substancias").textContent.toLowerCase()}` : ""}`;

  // aviso de ano parcial
  const cob = estado.meta.cobertura_arrecadacao;
  const aviso = $("#aviso-parcial");
  const mostrar = fl.base === "arrecadacao" && cob.ano_parcial && Number(fl.ano_fim) >= cob.ultimo_ano
    && Number(fl.mes_fim) > cob.ultimo_mes_completo;
  aviso.hidden = !mostrar;
  if (mostrar) {
    const m = Math.max(cob.ultimo_mes_completo, 1);
    $("p", aviso).textContent = `${cob.ultimo_ano} só está completo até ${MESES_LONGOS[m - 1]}.`;
    $("button", aviso).textContent = `Comparar todos os anos de janeiro a ${MESES_LONGOS[m - 1]}`;
  }
}

// ============================================================================ carga dos dados

function agendarCarga() {
  clearTimeout(estado.temporizador);
  estado.temporizador = setTimeout(carregarTudo, 250);
}

function carregarTudo() {
  const fl = lerFiltros();
  if (fl.semSubstancia) {               // aguardando o usuário marcar ao menos uma substância
    if (estado.controlador) estado.controlador.abort();
    atualizarResumos(fl);
    return;
  }
  const qs = paramsAPI(fl).toString();
  const qsURL = paramsURL(fl).toString();
  history.replaceState(null, "", qsURL ? `${location.pathname}?${qsURL}` : location.pathname);
  const pre = pagina().prefixo || "";
  $("#link-csv").href = `${API}/${pre}exportar.csv?${qs}`;
  $("#link-json").href = `${API}/${pre}painel?${qs}`;
  atualizarNavegacao(qsURL);
  atualizarResumos(fl);

  if (estado.controlador) estado.controlador.abort();
  const ctrl = (estado.controlador = new AbortController());

  for (const [rota, idSecao, desenhar] of pagina().secoes) {
    const secao = document.getElementById(idSecao);
    if (pagina().pular && pagina().pular(rota, fl)) {
      estado.respostas[rota] = null;
      secao.dataset.estado = "pronto";
      desenhar(null, fl);
      continue;
    }
    secao.dataset.estado = "carregando";
    chamar(pre + rota, qs, { signal: ctrl.signal })
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        estado.respostas[rota] = resp;
        if (resp.versao_dados) estado.versao = resp.versao_dados;
        secao.dataset.estado = "pronto";
        limparErro(secao);
        desenhar(resp, fl);
        if (rota === (pagina().secaoNotas || "indicadores")) desenharNotas(resp.notas);
      })
      .catch((erro) => {
        if (erro.name === "AbortError") return;
        secao.dataset.estado = "erro";
        if (erro.status === 503) {
          mostrarErro(secao, "Os dados ainda estão sendo carregados no servidor. O painel tenta de novo sozinho.");
          setTimeout(agendarCarga, 8000);
        } else {
          mostrarErro(secao, erro.status === 422 || erro.status === 400
            ? `Filtro não aceito: ${erro.message}`
            : `Não foi possível carregar esta seção (${erro.message}). Verifique se a API está no ar em ${API}.`);
        }
      });
  }
}

// Links entre as páginas levam os filtros em comum (período, substâncias, municípios, médias)
function atualizarNavegacao(qsURL) {
  $$("[data-pagina]").forEach((a) => {
    const p = new URLSearchParams(qsURL);
    if (a.dataset.pagina !== "arrecadacao") p.delete("base");
    if (a.dataset.pagina !== "distribuicao") p.delete("regra");
    const q = p.toString();
    a.href = `${a.dataset.arquivo}${q ? `?${q}` : ""}`;
  });
}

function mostrarErro(secao, texto) {
  limparErro(secao);
  const div = document.createElement("div");
  div.className = "erro-secao";
  div.textContent = texto;
  secao.appendChild(div);
}
function limparErro(secao) { $$(".erro-secao", secao).forEach((e) => e.remove()); }

function redesenhar() {
  const fl = lerFiltros();
  for (const [rota, , desenhar] of pagina().secoes) {
    const resp = estado.respostas[rota];
    if (resp !== undefined) desenhar(resp, fl);
  }
}

// ============================================================================ Plotly: tema e utilitários
const CONFIG = {
  displaylogo: false, responsive: true, locale: "pt-BR",
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
  toImageButtonOptions: { format: "png", scale: 3, filename: "cfem_carajas" },
};

function layout(extra = {}) {
  const fonte = css("--fonte");
  const eixo = { gridcolor: css("--grid"), linecolor: css("--rule"), zeroline: false, tickfont: { color: css("--muted") },
    title: { font: { size: 12, color: css("--muted") } }, automargin: true };
  const base = {
    font: { family: fonte, size: 12.5, color: css("--ink-2") },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", separators: ",.",
    margin: { l: 8, r: 16, t: 34, b: 8 },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--rule"), font: { family: fonte, color: css("--ink"), size: 12.5 } },
    legend: { orientation: "h", x: 0, y: 1.0, yanchor: "bottom", font: { color: css("--ink-2") }, traceorder: "normal" },
    xaxis: { ...eixo }, yaxis: { ...eixo }, bargap: 0.28, bargroupgap: 0.06,
  };
  const juntar = (a, b) => {
    for (const [k, v] of Object.entries(b)) a[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" ? juntar({ ...a[k] }, v) : v;
    return a;
  };
  return juntar(base, extra);
}

const eixoValor = (log, titulo = "R$ milhões") => (log
  ? { type: "log", dtick: 1, tickformat: ",~g", title: { text: titulo } }
  : { type: "linear", tickformat: ",~g", title: { text: titulo }, rangemode: "tozero" });

let localeRegistrado = false;
function registrarLocale() {
  if (localeRegistrado || !window.Plotly) return;
  Plotly.register({
    moduleType: "locale", name: "pt-BR",
    dictionary: { "Download plot as a png": "Baixar como PNG", "Zoom in": "Aproximar", "Zoom out": "Afastar",
      "Reset axes": "Restaurar eixos", "Pan": "Mover", "Zoom": "Zoom" },
    format: {
      days: ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"],
      shortDays: ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"],
      months: MESES_LONGOS, shortMonths: MESES,
      date: "%d/%m/%Y", decimal: ",", thousands: ".",
    },
  });
  localeRegistrado = true;
}

function plotar(id, traces, lay) {
  const el = document.getElementById(id);
  registrarLocale();
  if (!window.Plotly) { el.innerHTML = '<div class="erro-secao">A biblioteca de gráficos não carregou (vendor/plotly.min.js).</div>'; return; }
  if (!traces.length) { Plotly.purge(el); el.innerHTML = '<div class="vazio">Nenhum registro com estes filtros.</div>'; return; }
  if (el.querySelector(".vazio, .erro-secao")) el.innerHTML = "";
  el.style.height = `${lay.height || 380}px`;
  Plotly.react(el, traces, lay, CONFIG);
}

const tudoZero = (arrs) => arrs.every((a) => a.every((v) => !v));

// ============================================================================ seções
function desenharNotas(notas) {
  $("#notas").innerHTML = (notas || []).map((n) => `<li${/parcial/.test(n) ? ' class="alerta"' : ""}>${esc(n)}</li>`).join("");
}

function textoPeriodo(fl) {
  const anos = fl.ano_inicio === fl.ano_fim ? `Em ${fl.ano_inicio}` : `De ${fl.ano_inicio} a ${fl.ano_fim}`;
  if (fl.base === "arrecadacao" && (fl.mes_inicio !== "1" || fl.mes_fim !== "12")) {
    return `${anos}, considerando ${MESES[fl.mes_inicio - 1]} a ${MESES[fl.mes_fim - 1]} de cada ano`;
  }
  return anos;
}

function desenharMedias(resp, fl) {
  const d = resp.dados;
  const x = d.anos.map((a) => rotuloEixo(a.rotulo));
  const maxBR = Math.max(...d.periodo.municipios.map((m) => m.vezes_media_br || 0));
  $("#sub-medias").textContent = `${frase(d.descricao_media)}. Escala logarítmica${maxBR > 20 ? `, porque a diferença chega a ${vezesTexto(maxBR)} vezes` : ""}.`;
  const traces = [
    ...d.municipios.map((m) => ({
      type: "bar", name: m.nome, x, y: m.valores.map((v) => (v ? v / 1e6 : null)),
      marker: { color: corSerie(m.nome), line: { color: css("--surface"), width: 1 } },
      customdata: m.valores.map((v, i) => [brl(v, false), vezes(m.vezes_media_rc[i]), vezes(m.vezes_media_pa[i]), vezes(m.vezes_media_br[i])]),
      hovertemplate: `<b>${m.nome}</b>, %{x}<br>%{customdata[0]}<br>%{customdata[1]} a média da região<br>%{customdata[2]} a média do Pará<br>%{customdata[3]} a média do Brasil<extra></extra>`,
    })),
    ...d.medias.map((m) => ({
      type: "bar", name: m.nome, x, y: m.valor_medio.map((v) => (v ? v / 1e6 : null)),
      marker: { color: corSerie(m.nome), line: { color: css("--surface"), width: 1 } },
      customdata: m.valor_medio.map((v, i) => [brl(v, false), NF0.format(m.municipios[i]), brl(m.total[i])]),
      hovertemplate: `<b>${m.nome}</b>, %{x}<br>%{customdata[0]} por município<br>%{customdata[2]} ÷ %{customdata[1]} municípios<extra></extra>`,
    })),
  ];
  const vazio = tudoZero(traces.map((t) => t.y.map((v) => v || 0)));
  plotar("g-medias", vazio ? [] : traces, layout({ height: 400, barmode: "group", bargap: 0.22, yaxis: eixoValor(true), xaxis: { type: "category" } }));

  // tabela
  const P = "Parauapebas", C = "Canaã dos Carajás";
  const mP = d.municipios.find((m) => m.nome === P), mC = d.municipios.find((m) => m.nome === C);
  const med = Object.fromEntries(d.medias.map((m) => [m.escopo, m]));
  const per = d.periodo, pP = per.municipios.find((m) => m.nome === P), pC = per.municipios.find((m) => m.nome === C);
  const pmed = Object.fromEntries(per.medias.map((m) => [m.escopo, m]));
  const chave = (e) => `vezes_media_${e.toLowerCase()}`;
  const celulas = (vals) => vals.map((v) => `<td>${v}</td>`).join("");
  let linhas = d.anos.map((a, i) => `<tr><td>${esc(a.rotulo)}</td>${celulas([
    brl(mP.valores[i]), brl(mC.valores[i]),
    ...ESCOPOS.map(([e]) => brl(med[e].valor_medio[i])),
    ...ESCOPOS.map(([e]) => vezes(mP[chave(e)][i])),
    ...ESCOPOS.map(([e]) => vezes(mC[chave(e)][i])),
    ...ESCOPOS.map(([e]) => NF0.format(med[e].municipios[i])),
  ])}</tr>`).join("");
  linhas += `<tr class="total"><td>${esc(per.rotulo)}</td>${celulas([
    brl(pP.valor), brl(pC.valor),
    ...ESCOPOS.map(([e]) => brl(pmed[e].valor_medio)),
    ...ESCOPOS.map(([e]) => vezes(pP[chave(e)])),
    ...ESCOPOS.map(([e]) => vezes(pC[chave(e)])),
    ...ESCOPOS.map(([e]) => NF0.format(pmed[e].municipios)),
  ])}</tr>`;
  const sub = ESCOPOS.map(([, r]) => `<th>${r}</th>`).join("");
  $("#t-medias").innerHTML = `<thead>
    <tr class="grupo"><th rowspan="2">Ano</th><th colspan="5">Valor</th><th colspan="3">Parauapebas ÷ média</th><th colspan="3">Canaã ÷ média</th><th colspan="3">Municípios na média</th></tr>
    <tr><th>Parauapebas</th><th>Canaã</th>${ESCOPOS.map(([, r]) => `<th>Média ${r === "Região" ? "região" : r}</th>`).join("")}${sub}${sub}${sub}</tr>
    </thead><tbody>${linhas}</tbody>`;
}

function desenharRanking(resp, fl) {
  const d = resp.dados, log = fl.escala === "log";
  $("#sub-ranking").textContent = `Linhas tracejadas: médias por município no período (${d.descricao_media.replace(/^média = /, "")}).`;
  const itens = [...d.itens].reverse();
  const nomes = itens.map((i) => (i.sem_registros ? `${i.municipio} (sem registros)` : i.municipio));
  const traces = d.total ? [{
    type: "bar", orientation: "h", x: itens.map((i) => i.valor / 1e6), y: nomes, showlegend: false,
    marker: { color: itens.map((i) => (i.foco ? corSerie(i.municipio) : css("--c-contexto"))) },
    text: itens.map((i) => (i.valor > 0 ? `${brl(i.valor)}  ${pct(i.participacao_pct)}` : "")),
    textposition: "outside", cliponaxis: false, textfont: { color: css("--ink-2"), size: 11.5 },
    customdata: itens.map((i) => [brl(i.valor, false), pct(i.participacao_pct)]),
    hovertemplate: "<b>%{y}</b><br>%{customdata[0]}<br>%{customdata[1]} da região<extra></extra>",
  }] : [];
  const valores = itens.filter((i) => i.valor > 0).map((i) => i.valor / 1e6);
  if (traces.length) {
    for (const m of d.medias_periodo) {
      if (!m.valor_medio) continue;
      valores.push(m.valor_medio / 1e6);
      traces.push({ type: "scatter", mode: "lines", name: `${m.nome}: ${brl(m.valor_medio)}`,
        x: [m.valor_medio / 1e6, m.valor_medio / 1e6], y: [nomes[0], nomes[nomes.length - 1]],
        line: { color: corSerie(m.nome), width: 2, dash: "dash" },
        hovertemplate: `${m.nome}<br>${brl(m.valor_medio, false)}<extra></extra>` });
    }
  }
  const max = Math.max(...valores), min = Math.min(...valores);
  const xaxis = log ? { ...eixoValor(true), range: [Math.log10(min) - 0.3, Math.log10(max) + 1.2] } : { ...eixoValor(false), range: [0, max * 1.3] };
  plotar("g-ranking", traces, layout({ height: Math.max(360, 30 * nomes.length + 110), xaxis, yaxis: { type: "category", gridcolor: "rgba(0,0,0,0)", title: { text: "" } } }));
}

function desenharResumo(resp, fl) {
  const d = resp.dados;
  $("#sub-resumo").textContent = `Linhas em itálico: ${d.descricao_media}. ${d.observacao}`;
  const cab = d.anos.map((a) => `<th>${esc(a.rotulo)}</th>`).join("");
  const corpo = d.linhas.map((l) => {
    const cls = l.tipo === "total" ? ' class="total"' : l.tipo === "media" ? ' class="media"' : "";
    const tag = l.foco ? `<span class="tag" style="background:var(${COR_VAR[l.nome]})"></span>`
      : l.tipo === "media" ? `<span class="tag" style="background:var(${COR_VAR[l.nome]})"></span>` : "";
    return `<tr${cls}><td>${tag}${esc(l.nome)}</td>${l.valores.map((v) => `<td>${brl(v, false)}</td>`).join("")}<td>${brl(l.total, false)}</td><td>${pct(l.participacao_pct)}</td></tr>`;
  }).join("");
  $("#t-resumo").innerHTML = `<thead><tr><th>Município</th>${cab}<th>Total</th><th>Parte da região</th></tr></thead><tbody>${corpo}</tbody>`;
}

// ============================================================================ estado dos dados / administração
async function atualizarEstado() {
  try {
    const s = await chamar("saude");
    const t = $("#texto-estado");
    if (!s.pronto) {
      t.textContent = s.ultimo_erro ? `O servidor não conseguiu carregar os dados: ${s.ultimo_erro}` : "O servidor está baixando e processando os dados da ANM…";
      return s;
    }
    const prox = s.proxima_atualizacao ? ` Próxima verificação: ${dataHora(s.proxima_atualizacao)}.` : "";
    t.textContent = `Dados processados em ${dataHora(s.carregado_em)}.${prox}`;
    return s;
  } catch (e) {
    $("#texto-estado").textContent = `Sem resposta da API em ${API}.`;
    return null;
  }
}

async function esperarDados() {
  for (;;) {
    const s = await atualizarEstado();
    if (s && s.pronto) return s;
    let texto, espera = 4000;
    if (!s) {
      texto = `Não foi possível falar com a API em ${API}. Verifique se ela está rodando.`;
      espera = 15000;
    } else if (s.ultimo_erro) {
      texto = "O servidor não conseguiu carregar os dados. Veja o motivo no rodapé dos filtros.";
      espera = 30000;
    } else {
      texto = "O servidor está preparando os dados da ANM. Isso leva alguns segundos na primeira vez.";
    }
    $("#manchete").textContent = texto;
    await new Promise((r) => setTimeout(r, espera));
  }
}

async function recarregarMeta() {
  estado.meta = await chamar("meta");
  estado.versao = estado.meta.versao_dados;
}

async function verificarNovaVersao() {
  const s = await atualizarEstado();
  if (s && s.pronto && s.versao_dados && s.versao_dados !== estado.versao) {
    const fl = lerFiltros();
    await recarregarMeta();
    aplicarNoFormulario(paramsURL(fl));
    carregarTudo();
  }
}

async function enviarAdmin(ev) {
  ev.preventDefault();
  const f = ev.target, msg = $("#msg-admin");
  msg.textContent = "Enviando…";
  try {
    const r = await fetch(`${API}/admin/atualizar?forcar=${f.forcar.checked}`, { method: "POST", headers: { "X-Admin-Token": f.token.value } });
    if (r.status === 202) {
      msg.textContent = "Verificação iniciada. O painel recarrega sozinho se houver dados novos.";
      let n = 0;
      const t = setInterval(async () => { n += 1; await verificarNovaVersao(); if (n > 24) clearInterval(t); }, 5000);
    } else if (r.status === 401) msg.textContent = "Token incorreto.";
    else if (r.status === 403) msg.textContent = "A atualização manual está desligada no servidor. Defina CFEM_TOKEN_ADMIN para ligá-la.";
    else if (r.status === 409) msg.textContent = (await r.json()).detail;
    else msg.textContent = `O servidor respondeu ${r.status}.`;
  } catch (e) {
    msg.textContent = `Sem resposta da API (${e.message}).`;
  }
}

// ============================================================================ eventos
function ligarEventos() {
  const f = form();
  f.addEventListener("submit", (e) => e.preventDefault());
  f.addEventListener("change", (e) => {
    const alvo = e.target;
    if (alvo.name === "escala") { redesenhar(); history.replaceState(null, "", `${location.pathname}?${paramsURL(lerFiltros())}`); return; }
    if (alvo.name === "base") {
      const atual = lerFiltros();
      montarPeriodo();
      montarSubstancias(atual.substancias);
      montarMunicipios(atual.municipios);
    } else if (alvo.name === "agrupar_substancias") {
      montarSubstancias(null);
    } else if (alvo.name === "ano_inicio" && Number(f.ano_inicio.value) > Number(f.ano_fim.value)) {
      f.ano_fim.value = f.ano_inicio.value;
    } else if (alvo.name === "ano_fim" && Number(f.ano_fim.value) < Number(f.ano_inicio.value)) {
      f.ano_inicio.value = f.ano_fim.value;
    } else if (alvo.name === "mes_inicio" && Number(f.mes_inicio.value) > Number(f.mes_fim.value)) {
      f.mes_fim.value = f.mes_inicio.value;
    } else if (alvo.name === "mes_fim" && Number(f.mes_fim.value) < Number(f.mes_inicio.value)) {
      f.mes_inicio.value = f.mes_fim.value;
    }
    agendarCarga();
  });
  $("#busca-substancia").addEventListener("input", filtrarListaSubstancias);
  $("#busca-substancia").addEventListener("keydown", enterNaBusca);

  document.addEventListener("click", (e) => {
    const acao = e.target.closest("[data-acao]")?.dataset.acao;
    if (!acao) return;
    if (acao === "limpar-substancias") {
      $$("#lista-substancias input").forEach((i) => (i.checked = false));
      atualizarResumos(lerFiltros());
      $("#busca-substancia").focus();
    }
    if (acao === "marcar-substancias") {
      $("#busca-substancia").value = "";
      filtrarListaSubstancias();
      $$("#lista-substancias input").forEach((i) => (i.checked = true));
      agendarCarga();
    }
    if (acao === "todos-municipios") { $$("#lista-municipios input").forEach((i) => (i.checked = true)); agendarCarga(); }
    if (acao === "meses-completos") {
      f.mes_inicio.value = "1"; f.mes_fim.value = String(Math.max(estado.meta.cobertura_arrecadacao.ultimo_mes_completo, 1)); agendarCarga();
    }
    if (acao === "restaurar") { $("#busca-substancia").value = ""; aplicarNoFormulario(new URLSearchParams()); agendarCarga(); }
    if (acao === "abrir-filtros") { document.body.classList.add("filtros-abertos"); $(".veu").hidden = false; $("#lateral").focus?.(); }
    if (acao === "fechar-filtros") { document.body.classList.remove("filtros-abertos"); $(".veu").hidden = true; }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("filtros-abertos")) {
      document.body.classList.remove("filtros-abertos"); $(".veu").hidden = true;
    }
  });
  $("#form-admin").addEventListener("submit", enviarAdmin);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redesenhar);
}

// ============================================================================ início
async function iniciar() {
  ligarEventos();
  await esperarDados();
  try {
    await recarregarMeta();
  } catch (e) {
    $("#manchete").textContent = `Não foi possível ler as opções da API (${e.message}).`;
    return;
  }
  aplicarNoFormulario(URL_INICIAL);
  if (pagina().aoIniciar) await pagina().aoIniciar();
  carregarTudo();
  setInterval(verificarNovaVersao, 10 * 60 * 1000);   // pega a atualização diária sem recarregar a página
}

document.addEventListener("DOMContentLoaded", iniciar);

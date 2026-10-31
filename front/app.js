/* CFEM Carajás — front do painel.
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
const COR_VAR = {
  "Parauapebas": "--c-parauapebas", "Canaã dos Carajás": "--c-canaa", [DEMAIS]: "--c-demais",
  [SOMA]: "--c-soma", [REF_PA]: "--c-media-pa", [REF_BR]: "--c-media-br",
};
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
const rotuloEixo = (r) => r.replace(" (parcial)", "<br>(parcial)");
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

function lerFiltros() {
  const f = form();
  const marcados = (id) => $$(`#${id} input:checked`).map((i) => i.value);
  // Substâncias: todas marcadas = sem filtro (lista vazia para a API); nenhuma marcada = esperar o usuário escolher
  const subst = marcados("lista-substancias");
  const totalSubst = $$("#lista-substancias input").length;
  return {
    base: f.base.value,
    ano_inicio: f.ano_inicio.value,
    ano_fim: f.ano_fim.value,
    mes_inicio: f.mes_inicio.value,
    mes_fim: f.mes_fim.value,
    substancias: subst.length === totalSubst ? [] : subst,
    semSubstancia: totalSubst > 0 && subst.length === 0,
    agrupar_substancias: f.agrupar_substancias.checked,
    tipo_titular: f.tipo_titular.value,
    municipios: marcados("lista-municipios"),
    denominador: f.denominador.value,
    excluir_foco_das_medias: f.excluir_foco_das_medias.checked,
    top_n: f.top_n.value,
    escala: f.escala.checked ? "log" : "linear",
  };
}

function paramsAPI(fl) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(fl)) {
    if (k === "escala" || k === "semSubstancia") continue;
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
  const padrao = { base: "arrecadacao", ano_inicio: String(b.ano_min), ano_fim: String(b.ano_max), mes_inicio: "1", mes_fim: "12",
    agrupar_substancias: "true", tipo_titular: "Todos", denominador: "com_registro", excluir_foco_das_medias: "false", top_n: "10" };
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
  const b = estado.meta.bases[f.base.value];
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
  const b = estado.meta.bases[form().base.value];
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
  const b = estado.meta.bases[f.base.value];
  const anos = [];
  for (let a = b.ano_min; a <= b.ano_max; a++) anos.push([a, a]);
  opcoes(f.ano_inicio, anos, valores.ano_inicio ?? b.ano_min);
  opcoes(f.ano_fim, anos, valores.ano_fim ?? b.ano_max);
  const meses = MESES.map((m, i) => [i + 1, m]);
  opcoes(f.mes_inicio, meses, valores.mes_inicio ?? 1);
  opcoes(f.mes_fim, meses, valores.mes_fim ?? 12);
  const temMes = b.tem_mes;
  $("#grupo-meses").hidden = !temMes;
  $("#dica-base").textContent = f.base.value === "arrecadacao"
    ? "Valor pago pelas mineradoras sobre a produção do município. Não é o repasse que chega à prefeitura."
    : "Valor inicial dos autos de cobrança, não valor pago. O ano é o do processo de cobrança.";
}

function aplicarNoFormulario(p) {
  const f = form();
  const base = p.get("base");
  if (base && estado.meta.bases[base]) f.base.value = base;
  montarPeriodo({ ano_inicio: p.get("ano_inicio") ?? undefined, ano_fim: p.get("ano_fim") ?? undefined,
    mes_inicio: p.get("mes_inicio") ?? undefined, mes_fim: p.get("mes_fim") ?? undefined });
  f.agrupar_substancias.checked = p.get("agrupar_substancias") !== "false";
  montarSubstancias(p.getAll("substancias"));   // sem o parâmetro na URL = todas marcadas
  montarMunicipios(p.getAll("municipios"));
  if (p.get("tipo_titular")) f.tipo_titular.value = p.get("tipo_titular");
  f.denominador.value = p.get("denominador") === "todos" ? "todos" : "com_registro";
  f.excluir_foco_das_medias.checked = p.get("excluir_foco_das_medias") === "true";
  if (p.get("top_n")) f.top_n.value = p.get("top_n");
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
  const base = fl.base === "arrecadacao" ? "Arrecadação" : "Autuações";
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
const SECOES = [
  ["indicadores", "sec-indicadores", desenharIndicadores],
  ["evolucao-anual", "sec-evolucao", desenharEvolucao],
  ["comparacao-medias", "sec-medias", desenharMedias],
  ["participacao", "sec-participacao", desenharParticipacao],
  ["ranking", "sec-ranking", desenharRanking],
  ["serie-mensal", "sec-mensal", desenharMensal],
  ["substancias", "sec-substancias", desenharSubstancias],
  ["mapa-calor", "sec-calor", desenharCalor],
  ["titulares", "sec-titulares", desenharTitulares],
  ["tabela-resumo", "sec-resumo", desenharResumo],
];

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
  $("#link-csv").href = `${API}/exportar.csv?${qs}`;
  $("#link-json").href = `${API}/painel?${qs}`;
  atualizarResumos(fl);

  if (estado.controlador) estado.controlador.abort();
  const ctrl = (estado.controlador = new AbortController());

  for (const [rota, idSecao, desenhar] of SECOES) {
    const secao = document.getElementById(idSecao);
    if (rota === "serie-mensal" && fl.base !== "arrecadacao") {
      estado.respostas[rota] = null;
      secao.dataset.estado = "pronto";
      desenhar(null, fl);
      continue;
    }
    secao.dataset.estado = "carregando";
    chamar(rota, qs, { signal: ctrl.signal })
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        estado.respostas[rota] = resp;
        if (resp.versao_dados) estado.versao = resp.versao_dados;
        secao.dataset.estado = "pronto";
        limparErro(secao);
        desenhar(resp, fl);
        if (rota === "indicadores") desenharNotas(resp.notas);
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
  for (const [rota, , desenhar] of SECOES) {
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

function desenharIndicadores(resp, fl) {
  const d = resp.dados;
  const foco = Object.fromEntries(d.foco.map((x) => [x.municipio, x]));
  const medias = Object.fromEntries(d.medias.map((m) => [m.escopo, m]));
  const P = foco["Parauapebas"], C = foco["Canaã dos Carajás"];

  // manchete
  const mun = (nome, cls) => `<span class="mun ${cls}">${esc(nome)}</span>`;
  const subst = fl.substancias.length ? ` com ${fl.substancias.length === 1 ? frase(fl.substancias[0]).toLowerCase() : "as substâncias escolhidas"}` : "";
  let html;
  if (!d.total_regiao) {
    html = "Nenhum registro na região com estes filtros. Amplie o período ou as substâncias.";
  } else if (!d.foco_soma.valor) {
    html = `${esc(textoPeriodo(fl))}, ${mun("Parauapebas", "p")} e ${mun("Canaã dos Carajás", "c")} não têm registros com estes filtros. A região somou <b>${brl(d.total_regiao)}</b>.`;
  } else {
    const vp = medias.PA.vezes["Parauapebas"], vc = medias.PA.vezes["Canaã dos Carajás"];
    const verbo = fl.base === "arrecadacao" ? "recolheram" : "receberam autos que somam";
    const comparacao = vezesTexto(vp) === vezesTexto(vc)
      ? `Cada um ${fl.base === "arrecadacao" ? "recolheu" : "soma"} <b>${vezesTexto(vp)} vezes</b> a média de um município ${mun("do Pará", "m")}.`
      : `${mun("Parauapebas", "p")} ${fl.base === "arrecadacao" ? "recolheu" : "soma"} <b>${vezesTexto(vp)} vezes</b> e ${mun("Canaã", "c")} <b>${vezesTexto(vc)} vezes</b> a média de um município ${mun("do Pará", "m")}.`;
    html = `${esc(textoPeriodo(fl))}, ${mun("Parauapebas", "p")} e ${mun("Canaã dos Carajás", "c")} ${verbo} <b>${brl(d.foco_soma.valor)}</b> de CFEM${esc(subst)}, `
      + `<b>${pct(d.foco_soma.participacao_regiao_pct)}</b> do total da região de Carajás. ${comparacao}`;
  }
  $("#manchete").innerHTML = html;

  // faixa de cifras
  const cifra = (rotulo, valor, extra, corVar) =>
    `<div class="cifra" style="--cor:var(${corVar})"><div class="rotulo">${esc(rotulo)}</div><div class="valor">${valor}</div><div class="extra">${extra}</div></div>`;
  const nm = d.municipios_selecionados;
  $("#cifras").innerHTML = [
    cifra("Total da região", brl(d.total_regiao), `${nm} ${nm === 1 ? "município" : "municípios"}`, "--ink"),
    cifra("Parauapebas", brl(P.valor), `${pct(P.participacao_regiao_pct)} da região`, "--c-parauapebas"),
    cifra("Canaã dos Carajás", brl(C.valor), `${pct(C.participacao_regiao_pct)} da região`, "--c-canaa"),
    cifra("As duas somadas", brl(d.foco_soma.valor), `${pct(d.foco_soma.participacao_regiao_pct)} da região`, "--c-soma"),
    cifra("Média por município do Pará", brl(medias.PA.valor_medio),
      `Parauapebas ${vezes(medias.PA.vezes["Parauapebas"])}, Canaã ${vezes(medias.PA.vezes["Canaã dos Carajás"])}<br>${NF0.format(medias.PA.municipios)} municípios na média`, "--c-media-pa"),
    cifra("Média por município do Brasil", brl(medias.BR.valor_medio),
      `Parauapebas ${vezes(medias.BR.vezes["Parauapebas"])}, Canaã ${vezes(medias.BR.vezes["Canaã dos Carajás"])}<br>${NF0.format(medias.BR.municipios)} municípios na média`, "--c-media-br"),
  ].join("");
}

function desenharEvolucao(resp, fl) {
  const d = resp.dados, log = fl.escala === "log";
  const x = d.anos.map((a) => rotuloEixo(a.rotulo));
  const traces = tudoZero(d.series.map((s) => s.valores)) ? [] : d.series.filter((s) => s.valores.some((v) => v)).map((s) => ({
    type: "bar", name: s.nome, x, y: s.valores.map((v) => v / 1e6),
    marker: { color: corSerie(s.nome), line: { color: css("--surface"), width: 1.5 } },
    customdata: s.valores.map((v, i) => [brl(v, false), pct(s.participacao_pct[i])]),
    hovertemplate: `<b>${s.nome}</b>, %{x}<br>%{customdata[0]}<br>%{customdata[1]} da região<extra></extra>`,
  }));
  if (traces.length && !log && d.anos.length <= 8) {
    traces.push({ type: "scatter", mode: "text", x, y: d.totais.map((t) => t / 1e6), text: d.totais.map((t) => (t ? brl(t) : "")),
      textposition: "top center", textfont: { color: css("--ink-2"), size: 12 }, hoverinfo: "skip", showlegend: false, cliponaxis: false });
  }
  plotar("g-evolucao", traces, layout({ height: 400, barmode: log ? "group" : "stack", yaxis: eixoValor(log), xaxis: { type: "category" } }));
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
      customdata: m.valores.map((v, i) => [brl(v, false), vezes(m.vezes_media_pa[i]), vezes(m.vezes_media_br[i])]),
      hovertemplate: `<b>${m.nome}</b>, %{x}<br>%{customdata[0]}<br>%{customdata[1]} a média do Pará<br>%{customdata[2]} a média do Brasil<extra></extra>`,
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
  const [pa, br] = d.medias;
  let linhas = d.anos.map((a, i) => `<tr><td>${esc(a.rotulo)}</td><td>${brl(mP.valores[i])}</td><td>${brl(mC.valores[i])}</td>
    <td>${brl(pa.valor_medio[i])}</td><td>${brl(br.valor_medio[i])}</td>
    <td>${vezes(mP.vezes_media_pa[i])}</td><td>${vezes(mP.vezes_media_br[i])}</td><td>${vezes(mC.vezes_media_pa[i])}</td><td>${vezes(mC.vezes_media_br[i])}</td>
    <td>${NF0.format(pa.municipios[i])}</td><td>${NF0.format(br.municipios[i])}</td></tr>`).join("");
  const per = d.periodo, pP = per.municipios.find((m) => m.nome === P), pC = per.municipios.find((m) => m.nome === C);
  const [ppa, pbr] = per.medias;
  linhas += `<tr class="total"><td>${esc(per.rotulo)}</td><td>${brl(pP.valor)}</td><td>${brl(pC.valor)}</td><td>${brl(ppa.valor_medio)}</td><td>${brl(pbr.valor_medio)}</td>
    <td>${vezes(pP.vezes_media_pa)}</td><td>${vezes(pP.vezes_media_br)}</td><td>${vezes(pC.vezes_media_pa)}</td><td>${vezes(pC.vezes_media_br)}</td>
    <td>${NF0.format(ppa.municipios)}</td><td>${NF0.format(pbr.municipios)}</td></tr>`;
  $("#t-medias").innerHTML = `<thead>
    <tr class="grupo"><th rowspan="2">Ano</th><th colspan="4">Valor</th><th colspan="2">Parauapebas ÷ média</th><th colspan="2">Canaã ÷ média</th><th colspan="2">Municípios na média</th></tr>
    <tr><th>Parauapebas</th><th>Canaã</th><th>Média PA</th><th>Média BR</th><th>PA</th><th>BR</th><th>PA</th><th>BR</th><th>PA</th><th>BR</th></tr>
    </thead><tbody>${linhas}</tbody>`;
}

function desenharParticipacao(resp, fl) {
  const d = resp.dados;
  const x = d.anos.map((a) => rotuloEixo(a.rotulo));
  const traces = tudoZero([d.totais_regiao]) ? [] : d.series.map((s) => ({
    type: "scatter", mode: "lines+markers", name: s.nome, x, y: s.participacao_pct,
    line: { color: corSerie(s.nome), width: 2, dash: s.nome === SOMA ? "dot" : "solid" },
    marker: { size: 8, color: corSerie(s.nome), line: { color: css("--surface"), width: 2 } },
    customdata: s.valores.map((v) => brl(v, false)),
    hovertemplate: `<b>${s.nome}</b>, %{x}<br>%{y:.1f}% da região<br>%{customdata}<extra></extra>`,
  }));
  plotar("g-participacao", traces, layout({ height: 380, yaxis: { range: [0, 104], ticksuffix: "%", title: { text: "" } }, xaxis: { type: "category" } }));
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

function desenharMensal(resp, fl) {
  const el = $("#g-mensal");
  if (!resp) {
    if (window.Plotly) Plotly.purge(el);
    el.style.height = "auto";
    el.innerHTML = '<div class="vazio">A base de autuações não tem mês de referência. Escolha a arrecadação para ver a série mensal.</div>';
    $("#sub-mensal").textContent = "";
    return;
  }
  const d = resp.dados, log = fl.escala === "log";
  $("#sub-mensal").textContent = d.incompleto_a_partir_de ? "A faixa cinza marca os meses que a ANM ainda não publicou por completo." : "";
  const x = d.meses.map((m) => `${m}-01`);
  const traces = tudoZero(d.series.map((s) => s.valores)) ? [] : d.series.map((s) => ({
    type: "scatter", mode: "lines", name: s.nome, x, y: s.valores.map((v) => (log && !v ? null : v / 1e6)),
    line: { color: corSerie(s.nome), width: 2 },
    customdata: s.valores.map((v) => brl(v, false)),
    hovertemplate: `${s.nome}: %{customdata}<extra></extra>`,
  }));
  const shapes = [];
  if (d.incompleto_a_partir_de && x.length) {
    const ini = new Date(`${d.incompleto_a_partir_de}-01T00:00:00`); ini.setDate(ini.getDate() - 15);
    const fim = new Date(`${x[x.length - 1]}T00:00:00`); fim.setDate(fim.getDate() + 15);
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: ini.toISOString().slice(0, 10), x1: fim.toISOString().slice(0, 10),
      y0: 0, y1: 1, fillcolor: css("--c-incompleto"), line: { width: 0 }, layer: "below" });
  }
  plotar("g-mensal", traces, layout({ height: 380, hovermode: "x unified", shapes,
    xaxis: { type: "date", tickformat: "%b<br>%Y", dtick: "M3", hoverformat: "%b/%Y" }, yaxis: eixoValor(log) }));
}

function desenharSubstancias(resp, fl) {
  const d = resp.dados, log = fl.escala === "log";
  const cats = [...d.categorias].reverse().map(frase);
  const traces = d.categorias.length ? d.series.filter((s) => s.valores.some((v) => v)).map((s) => ({
    type: "bar", orientation: "h", name: s.nome, y: cats, x: [...s.valores].reverse().map((v) => (log && !v ? null : v / 1e6)),
    marker: { color: corSerie(s.nome), line: { color: css("--surface"), width: 1 } },
    customdata: [...s.valores].reverse().map((v) => brl(v, false)),
    hovertemplate: `<b>%{y}</b>, ${s.nome}<br>%{customdata}<extra></extra>`,
  })) : [];
  plotar("g-substancias", traces, layout({ height: Math.max(380, 44 * cats.length + 110), barmode: "group", bargap: 0.3,
    xaxis: eixoValor(log), yaxis: { type: "category", gridcolor: "rgba(0,0,0,0)", title: { text: "" } } }));
}

function desenharCalor(resp, fl) {
  const d = resp.dados;
  if (!d.maximo) { plotar("g-calor", [], {}); return; }
  const z = d.valores.map((l) => l.map((v) => (v > 0 ? Math.log10(v) : null)));
  const zmin = Math.floor(Math.log10(d.minimo_positivo)), zmax = Math.ceil(Math.log10(d.maximo));
  const ticks = []; for (let t = zmin; t <= zmax; t++) ticks.push(t);
  const escala = [1, 2, 3, 4, 5, 6, 7].map((i, k, a) => [k / (a.length - 1), css(`--seq-${i}`)]);
  const mostrarTexto = d.anos.length <= 8 && $("#g-calor").clientWidth > 560;   // em tela estreita, só no toque/hover
  const municipios = [...d.municipios].reverse(), valores = [...d.valores].reverse(), zz = [...z].reverse();
  plotar("g-calor", [{
    type: "heatmap", x: d.anos.map((a) => rotuloEixo(a.rotulo)), y: municipios, z: zz, zmin, zmax, xgap: 2, ygap: 2,
    colorscale: escala, hoverongaps: false,
    text: valores.map((l) => l.map((v) => (v > 0 ? brl(v) : ""))), texttemplate: mostrarTexto ? "%{text}" : "",
    textfont: { size: 10.5 },
    customdata: valores.map((l) => l.map((v) => brl(v, false))),
    hovertemplate: "<b>%{y}</b>, %{x}<br>%{customdata}<extra></extra>",
    colorbar: { thickness: 10, outlinewidth: 0, tickvals: ticks, ticktext: ticks.map((t) => brl(10 ** t)), tickfont: { color: css("--muted"), size: 11 } },
  }], layout({ height: Math.max(380, 34 * municipios.length + 90), margin: { t: 8 },
    xaxis: { type: "category", side: "top", gridcolor: "rgba(0,0,0,0)", linecolor: "rgba(0,0,0,0)" },
    yaxis: { type: "category", gridcolor: "rgba(0,0,0,0)", title: { text: "" } } }));
}

function desenharTitulares(resp, fl) {
  const d = resp.dados;
  $("#sub-titulares").textContent = d.observacao || "";
  if (!d.itens.length) { $("#t-titulares").innerHTML = '<tbody><tr><td class="vazio">Nenhum registro de Parauapebas ou Canaã com estes filtros.</td></tr></tbody>'; return; }
  $("#t-titulares").innerHTML = `<thead><tr><th>Titular</th><th>Parauapebas</th><th>Canaã dos Carajás</th><th>Total</th><th>Parte das duas cidades</th></tr></thead><tbody>${
    d.itens.map((i) => `<tr><td>${esc(i.titular)}</td><td>${brl(i.valores["Parauapebas"], false)}</td><td>${brl(i.valores["Canaã dos Carajás"], false)}</td>
      <td>${brl(i.total, false)}</td><td class="barra"><i style="width:${Math.max(0, Math.min(100, i.participacao_foco_pct || 0)) * 0.9}px"></i><span>${pct(i.participacao_foco_pct)}</span></td></tr>`).join("")}</tbody>`;
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
  carregarTudo();
  setInterval(verificarNovaVersao, 10 * 60 * 1000);   // pega a atualização diária sem recarregar a página
}

document.addEventListener("DOMContentLoaded", iniciar);

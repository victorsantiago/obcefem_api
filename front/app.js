/* Observatório da CFEM — página "Análise da arrecadação" (index.html).
 * O código comum (filtros, carga, tema dos gráficos) está em comum.js.
 */
"use strict";

window.PAGINA = {
  id: "arrecadacao",
  prefixo: "",                       // rotas em /api/v1/...
  secaoNotas: "indicadores",
  // a série mensal não existe para autuações
  pular: (rota, fl) => rota === "serie-mensal" && fl.base !== "arrecadacao",
  get secoes() {
    return [
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
  },
};

// ============================================================================ seções da arrecadação
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
    const verbo = fl.base === "arrecadacao" ? "recolheram" : "receberam autos que somam";
    const par = (esc) => [vezesTexto(medias[esc].vezes["Parauapebas"]), vezesTexto(medias[esc].vezes["Canaã dos Carajás"])];
    const [rp, rc] = par("RC"), [pp, pc] = par("PA");
    const regiao = mun("da região de Carajás", "r"), para = mun("do Pará", "m");
    const txt = (a, b) => (a === b ? a : `${a} e ${b}`);
    const iguais = rp === rc && pp === pc;
    const sujeito = iguais ? `Cada um ${fl.base === "arrecadacao" ? "recolheu" : "soma"}`
      : `Parauapebas e Canaã ${fl.base === "arrecadacao" ? "recolheram" : "somam"}, respectivamente,`;
    const comparacao = `${sujeito} <b>${txt(rp, rc)} vezes</b> a média de um município ${regiao} e <b>${txt(pp, pc)} vezes</b> a de um município ${para}.`;
    html = `${esc(textoPeriodo(fl))}, ${mun("Parauapebas", "p")} e ${mun("Canaã dos Carajás", "c")} ${verbo} <b>${brl(d.foco_soma.valor)}</b> de CFEM${esc(subst)}, `
      + `<b>${pct(d.foco_soma.participacao_regiao_pct)}</b> do total da região de Carajás. ${comparacao}`;
  }
  $("#manchete").innerHTML = html;

  // faixa de cifras
  const cifra = (rotulo, valor, extra, corVar, classe = "") =>
    `<div class="cifra ${classe}" style="--cor:var(${corVar})"><div class="rotulo">${esc(rotulo)}</div><div class="valor">${valor}</div><div class="extra">${extra}</div></div>`;
  const nm = d.municipios_selecionados;
  $("#cifras").innerHTML = [
    cifra("Total da região", brl(d.total_regiao), `${nm} ${nm === 1 ? "município" : "municípios"}`, "--ink"),
    cifra("Parauapebas", brl(P.valor), `${pct(P.participacao_regiao_pct)} da região`, "--c-parauapebas"),
    cifra("Canaã dos Carajás", brl(C.valor), `${pct(C.participacao_regiao_pct)} da região`, "--c-canaa"),
    cifra("As duas somadas", brl(d.foco_soma.valor), `${pct(d.foco_soma.participacao_regiao_pct)} da região`, "--c-soma"),
    ...[["RC", "Média por município da região", "--c-media-rc"], ["PA", "Média por município do Pará", "--c-media-pa"],
      ["BR", "Média por município do Brasil", "--c-media-br"]].map(([e, rotulo, cor]) => cifra(rotulo, brl(medias[e].valor_medio),
      `Parauapebas ${vezes(medias[e].vezes["Parauapebas"])}, Canaã ${vezes(medias[e].vezes["Canaã dos Carajás"])}<br>${NF0.format(medias[e].municipios)} ${medias[e].municipios === 1 ? "município" : "municípios"} na média`, cor, "media")),
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
    xaxis: { type: "date", tickformat: x.length > 48 ? "%Y" : "%b<br>%Y", dtick: x.length > 48 ? "M12" : "M3", hoverformat: "%b/%Y" },
    yaxis: eixoValor(log) }));
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


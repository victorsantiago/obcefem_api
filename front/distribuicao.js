/* Observatório da CFEM — página "Análise da distribuição" (distribuicao.html).
 * Para onde vai a CFEM arrecadada: município produtor, estado, municípios afetados e União.
 * Valores estimados pela regra da ANM (rotas /api/v1/distribuicao/...). Código comum em comum.js.
 */
"use strict";

const DEST = ["municipio", "estado", "afetados", "uniao"];
const DEST_VAR = { municipio: "--c-dest-municipio", estado: "--c-dest-estado", afetados: "--c-dest-afetados", uniao: "--c-dest-uniao" };
// nomes como aparecem nos textos da página (o Estado da região é sempre o Pará)
const DEST_NOME = { municipio: "Município produtor", estado: "Governo do Pará", afetados: "Municípios afetados", uniao: "União" };
const corDest = (id) => css(DEST_VAR[id]);
const estadoDist = { regras: null, origem: "soma" };

window.PAGINA = {
  id: "distribuicao",
  prefixo: "distribuicao/",
  secaoNotas: "indicadores",
  rotulo: (fl) => (fl.regra === "atual" ? "Distribuição (regra atual)" : "Distribuição"),
  aoIniciar: carregarRegras,
  get secoes() {
    return [
      ["indicadores", "sec-indicadores", desenharIndicadoresDist],
      ["fluxo", "sec-fluxo", desenharFluxo],
      ["destinos-anual", "sec-destinos", desenharDestinosAnual],
      ["comparacao-medias", "sec-medias", desenharMedias],
      ["peso-nos-repasses", "sec-peso", desenharPeso],
      ["ranking", "sec-ranking", desenharRanking],
      ["tabela-destinos", "sec-tabela-destinos", desenharTabelaDestinos],
      ["tabela-resumo", "sec-resumo", desenharResumo],
    ];
  },
};

const pctInteiro = (v) => (v === null || v === undefined ? "–" : Math.abs(v - Math.round(v)) < 0.05 ? `${NF0.format(Math.round(v))}%` : pct(v));

// ============================================================================ regras (quadro fixo)
async function carregarRegras() {
  try {
    estadoDist.regras = await chamar("distribuicao/regras");
  } catch (e) {
    $("#regras").innerHTML = `<div class="erro-secao">Não foi possível ler as regras de distribuição (${esc(e.message)}).</div>`;
    return;
  }
  desenharRegras();
}

function desenharRegras(fl) {
  const r = estadoDist.regras;
  if (!r) return;
  const usadas = new Set(estadoDist.regrasNoPeriodo || []);
  const periodo = (x) => (x.de && x.ate ? `${x.de} a ${x.ate}` : x.de ? `Desde ${x.de}` : `Até ${x.ate}`);
  const nomesUniao = Object.fromEntries(r.parcelas_uniao.map((p) => [p.id, p.nome]));
  const linhas = [...r.regras].reverse().map((x) => {
    const segmentos = DEST.filter((d) => x.destinos[d] > 0).map((d) =>
      `<span class="seg" style="flex-basis:${x.destinos[d]}%;background:var(${DEST_VAR[d]})" title="${esc(DEST_NOME[d])}: ${pctInteiro(x.destinos[d])}">${pctInteiro(x.destinos[d])}</span>`).join("");
    const uniao = Object.entries(x.uniao).filter(([, v]) => v > 0).map(([k, v]) => `${nomesUniao[k]} ${pctInteiro(v)}`).join(" · ");
    return `<div class="regra${usadas.size && !usadas.has(x.id) ? " fora" : ""}">
      <div class="regra-cab"><b>${esc(periodo(x))}</b> <span>${esc(x.nome)}</span>${usadas.has(x.id) && usadas.size ? '<em class="selo">no período</em>' : ""}</div>
      <div class="barra-regra" role="img" aria-label="${esc(DEST.map((d) => `${DEST_NOME[d]} ${pctInteiro(x.destinos[d])}`).join(", "))}">${segmentos}</div>
      <p class="dica">União: ${esc(uniao)}. ${esc(x.observacao || "")}</p>
    </div>`;
  }).join("");
  const legenda = DEST.map((d) => `<span><i style="background:var(${DEST_VAR[d]})"></i>${esc(DEST_NOME[d] === "Governo do Pará" ? "Estado" : DEST_NOME[d])}</span>`).join("");
  $("#regras").innerHTML = `<div class="legenda-dest">${legenda}</div>${linhas}`;
  $("#uso-recursos").innerHTML = `<p>“${esc(r.uso_dos_recursos)}”</p><cite>Agência Nacional de Mineração</cite>`;
}

// ============================================================================ indicadores + manchete
function desenharIndicadoresDist(resp, fl) {
  const d = resp.dados;
  estadoDist.regrasNoPeriodo = d.regras_no_periodo;
  desenharRegras(fl);
  const S = d.foco_soma, foco = Object.fromEntries(d.foco.map((x) => [x.municipio, x]));
  const P = foco["Parauapebas"], C = foco["Canaã dos Carajás"];
  const medias = Object.fromEntries(d.medias_cota_municipal.map((m) => [m.escopo, m]));
  const mun = (nome, cls) => `<span class="mun ${cls}">${esc(nome)}</span>`;
  const dest = (id, texto) => `<span class="dest" style="--cor:var(${DEST_VAR[id]})">${esc(texto)}</span>`;
  const p = (id) => (d.regra_mista ? `${pctInteiro(S.percentuais[id])} no período` : pctInteiro(S.percentuais[id]));
  const subst = fl.substancias.length ? ` com ${fl.substancias.length === 1 ? frase(fl.substancias[0]).toLowerCase() : "as substâncias escolhidas"}` : "";

  let html;
  if (!S.gerado) {
    html = `${esc(textoPeriodo(fl))}, ${mun("Parauapebas", "p")} e ${mun("Canaã dos Carajás", "c")} não têm arrecadação com estes filtros, então não há CFEM a distribuir.`;
  } else {
    const vp = vezesTexto(medias.RC.vezes["Parauapebas"]), vc = vezesTexto(medias.RC.vezes["Canaã dos Carajás"]);
    const vezesTxt = vp === vc ? `${vp} vezes` : `${vp} e ${vc} vezes`;
    const quem = vp === vc ? "A cota de cada prefeitura equivale a" : "As cotas das prefeituras equivalem, respectivamente, a";
    const afet = S.destinos.afetados > 0 ? `, <b>${brl(S.destinos.afetados)}</b> (${p("afetados")}) a ${dest("afetados", "municípios afetados")}` : "";
    html = `${esc(textoPeriodo(fl))}, a mineração em ${mun("Parauapebas", "p")} e ${mun("Canaã dos Carajás", "c")} gerou <b>${brl(S.gerado)}</b> de CFEM${esc(subst)}. `
      + `${fl.regra === "atual" && Number(fl.ano_inicio) <= 2017 ? "Aplicando a regra atual a todos os anos" : "Pela regra da ANM"}, <b>${brl(S.destinos.municipio)}</b> (${p("municipio")}) ficam com as ${dest("municipio", "duas prefeituras")}, `
      + `<b>${brl(S.destinos.estado)}</b> (${p("estado")}) vão para o ${dest("estado", "Governo do Pará")}${afet} `
      + `e <b>${brl(S.destinos.uniao)}</b> (${p("uniao")}) para a ${dest("uniao", "União")}. `
      + `${quem} <b>${vezesTxt}</b> a de um município médio ${mun("da região de Carajás", "r")}.`;
  }
  $("#manchete").innerHTML = html;

  const cifra = (rotulo, valor, extra, corVar, classe = "") =>
    `<div class="cifra ${classe}" style="--cor:var(${corVar})"><div class="rotulo">${rotulo}</div><div class="valor">${valor}</div><div class="extra">${extra}</div></div>`;
  const u = S.uniao;
  $("#cifras").innerHTML = [
    cifra("Arrecadado em Parauapebas e Canaã", brl(S.gerado), `Parauapebas ${brl(P.gerado)}<br>Canaã ${brl(C.gerado)}`, "--ink", "origem"),
    cifra(`Município produtor <span class="pp">${p("municipio")}</span>`, brl(S.destinos.municipio),
      `Parauapebas ${brl(P.destinos.municipio)}<br>Canaã ${brl(C.destinos.municipio)}`, DEST_VAR.municipio),
    cifra(`Governo do Pará <span class="pp">${p("estado")}</span>`, brl(S.destinos.estado), "Cota do estado onde a substância foi extraída", DEST_VAR.estado),
    cifra(`Municípios afetados <span class="pp">${p("afetados")}</span>`, brl(S.destinos.afetados),
      S.destinos.afetados > 0 ? "Repartida pela ANM entre municípios afetados de todo o país" : "Sem cota para afetados no período", DEST_VAR.afetados),
    cifra(`União <span class="pp">${p("uniao")}</span>`, brl(S.destinos.uniao),
      `ANM ${brl(u.anm)} · FNDCT ${brl(u.fndct)}<br>CETEM ${brl(u.cetem)} · IBAMA ${brl(u.ibama)}`, DEST_VAR.uniao),
  ].join("");
}

// ============================================================================ fluxo (Sankey)
// "(2022 a 2026)", "(2024)" ou "(2022 a 2026, jan a jun)" para os títulos
function intervalo(fl) {
  const anos = fl.ano_inicio === fl.ano_fim ? fl.ano_inicio : `${fl.ano_inicio} a ${fl.ano_fim}`;
  const meses = fl.mes_inicio !== "1" || fl.mes_fim !== "12" ? `, ${MESES[fl.mes_inicio - 1]} a ${MESES[fl.mes_fim - 1]}` : "";
  return `(${anos}${meses})`;
}

function desenharFluxo(resp, fl) {
  $("#titulo-fluxo").textContent = `Para onde vai a CFEM arrecadada no Pará ${intervalo(fl)}`;
  const d = resp.dados;
  const origens = d.origens.filter((o) => o.gerado > 0);
  if (!origens.length) { plotar("g-fluxo", [], {}); return; }
  const totalRC = estado.meta.regiao_carajas.length, nm = fl.municipios.length;
  $("#sub-fluxo").textContent = "Cada faixa sai de onde a CFEM foi arrecadada e chega ao destino da repartição legal; a largura é proporcional ao valor."
    + (nm && nm < totalRC ? ` Região de Carajás: só os ${nm} de ${totalRC} municípios selecionados no filtro.` : "")
    + " Passe o mouse ou toque para ver os números.";
  const nomesUniao = Object.fromEntries(d.parcelas_uniao.map((p) => [p.id, p.nome]));
  const tot = d.total;
  const estreito = $("#g-fluxo").clientWidth < 640;
  // nome de cada origem nos rótulos (curto) e nas dicas (por extenso)
  const curto = (o) => ({ [DEMAIS]: "Demais da RI Carajás", [DEMAIS_PA]: "Demais do Pará", "Canaã dos Carajás": estreito ? "Canaã" : "Canaã dos Carajás" }[o.nome] || o.nome);
  const extenso = (o) => ({ [DEMAIS]: "demais municípios da Região de Integração do Carajás", [DEMAIS_PA]: "demais municípios do Pará (fora da RI Carajás)" }[o.nome] || o.nome);
  // Colunas, da esquerda para a direita:
  //   1. onde foi arrecadado: Parauapebas, Canaã, demais da RI Carajás e demais do Pará (sem sobreposição)
  //   2. a cota do município produtor, que fica com cada prefeitura
  //   3. o restante: Governo do Pará, municípios afetados e União
  //   4. as parcelas da União (ANM, FNDCT, CETEM, IBAMA) — só em tela larga
  const outros = ["estado", "afetados", "uniao"].filter((k) => tot.destinos[k] > 0);
  const comParcelas = outros.includes("uniao") && !estreito;
  const X = comParcelas ? [0.001, 0.33, 0.64, 0.999] : [0.001, 0.5, 0.999];
  const nos = { label: [], color: [], x: [], y: [], customdata: [] };
  const links = { source: [], target: [], value: [], color: [], customdata: [] };
  const no = (rotulo, cor, x, y, dica) => {
    nos.label.push(rotulo); nos.color.push(cor); nos.x.push(x); nos.y.push(Math.min(Math.max(y, 0.001), 0.999));
    nos.customdata.push(dica); return nos.label.length - 1;
  };
  const liga = (de, para, v, cor, dica) => {
    if (!(v > 0)) return;
    links.source.push(de); links.target.push(para); links.value.push(v / 1e6); links.color.push(cor); links.customdata.push(dica);
  };
  const translucida = (hex, a) => {
    const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  // posições verticais proporcionais ao valor, com um vão entre os nós de uma coluna
  const vao = 0.035;
  const empilhar = (valores) => {
    const util = 1 - vao * (valores.length - 1);
    let acum = 0;
    return valores.map((v, i) => { const y = ((acum + v / 2) / tot.gerado) * util + vao * i; acum += v; return y; });
  };
  const yOrig = empilhar(origens.map((o) => o.gerado));
  // colunas 2 e 3 na mesma escala: prefeituras em cima, demais destinos embaixo
  const ys = empilhar([...origens.map((o) => o.destinos.municipio), ...outros.map((k) => tot.destinos[k])]);

  const iOrig = origens.map((o, i) => no(`${curto(o)}<br>${brl(o.gerado)}`, corSerie(o.nome), X[0], yOrig[i],
    `<b>Arrecadado em ${extenso(o)}</b><br>${brl(o.gerado, false)}<br>${pct((o.gerado / tot.gerado) * 100)} do arrecadado no Pará`));
  origens.forEach((o, i) => {
    const v = o.destinos.municipio;
    if (!(v > 0)) return;
    const multi = o.nome === DEMAIS || o.nome === DEMAIS_PA;
    const alvo = no(`${curto(o)}<br>${brl(v)}`, corSerie(o.nome), X[1], ys[i],
      `<b>Prefeitura${multi ? `s dos ${extenso(o)}` : ` de ${o.nome}`}</b><br>${brl(v, false)}<br>${pct(o.percentuais.municipio)} do que foi arrecadado ${multi ? "nesses municípios" : "no município"}`);
    liga(iOrig[i], alvo, v, translucida(corSerie(o.nome), 0.4), `${curto(o)} → cota do município produtor<br>${brl(v, false)}`);
  });
  const iOutro = {};
  outros.forEach((k, j) => {
    const v = tot.destinos[k];
    iOutro[k] = no(`${DEST_NOME[k]}<br>${brl(v)} (${pct(tot.percentuais[k])})`, corDest(k), X[2], ys[origens.length + j],
      `<b>${DEST_NOME[k]}</b><br>${brl(v, false)}<br>${pct(tot.percentuais[k])} do arrecadado`
      + (k === "uniao" ? `<br>${Object.entries(tot.uniao).filter(([, x]) => x > 0).map(([p, x]) => `${nomesUniao[p]} ${brl(x)}`).join(" · ")}` : "")
      + `<br>${origens.map((o) => `${curto(o)}: ${brl(o.destinos[k])}`).join("<br>")}`);
    origens.forEach((o, i) => liga(iOrig[i], iOutro[k], o.destinos[k], translucida(corSerie(o.nome), 0.3),
      `${curto(o)} → ${DEST_NOME[k]}<br>${brl(o.destinos[k], false)} (${pct(o.percentuais[k])} do arrecadado ${o.nome === DEMAIS || o.nome === DEMAIS_PA ? "nesses municípios" : "no município"})`));
  });
  if (comParcelas) {
    const parcelas = Object.entries(tot.uniao).filter(([, v]) => v > 0);
    const yU = nos.y[iOutro.uniao], passo = 0.075;
    let yp = parcelas.map((_, j) => yU + (j - (parcelas.length - 1) / 2) * passo);
    const excesso = Math.max(...yp) - 0.97;
    if (excesso > 0) yp = yp.map((y) => y - excesso);
    parcelas.forEach(([k, v], j) => {
      const alvo = no(`${nomesUniao[k]} ${brl(v)}`, corDest("uniao"), X[3], yp[j],
        `<b>União: ${nomesUniao[k]}</b><br>${brl(v, false)}<br>${pct((v / tot.gerado) * 100)} do arrecadado`);
      liga(iOutro.uniao, alvo, v, translucida(corDest("uniao"), 0.3), `União → ${nomesUniao[k]}<br>${brl(v, false)}`);
    });
  }
  // títulos das colunas
  const pMun = pct(tot.percentuais.municipio), pResto = pct(100 - (tot.percentuais.municipio || 0));
  const titulos = comParcelas
    ? [[`Arrecadado no Pará: ${brl(tot.gerado)}`, X[0], "left"], [`Município produtor (${pMun})`, X[1], "center"], [`Estado, afetados e União (${pResto})`, X[2], "center"], ["Parcelas da União", X[3], "right"]]
    : [[`Arrecadado<br>${brl(tot.gerado)}`, X[0], "left"], [`Prefeituras (${pMun})`, X[1], "center"], [`Demais (${pResto})`, X[2], "right"]];
  const annotations = titulos.map(([t, x, al]) => ({ text: `<b>${t}</b>`, x, y: 1, xref: "paper", yref: "paper", yanchor: "bottom",
    xanchor: al, showarrow: false, font: { size: estreito ? 10.5 : 12, color: css("--muted") } }));
  plotar("g-fluxo", [{
    type: "sankey", arrangement: "snap", valueformat: ",.1f", valuesuffix: " mi",
    node: { ...nos, pad: estreito ? 10 : 14, thickness: estreito ? 12 : 16, line: { width: 0 },
      hovertemplate: "%{customdata}<extra></extra>" },
    link: { ...links, hovertemplate: "%{customdata}<extra></extra>" },
    textfont: { family: css("--fonte"), size: estreito ? 10.5 : 12.5, color: css("--ink") },
  }], layout({ height: estreito ? 560 : 520, margin: { l: 4, r: 4, t: estreito ? 40 : 30, b: 10 }, annotations }));
}

// ============================================================================ destinos por ano
function desenharDestinosAnual(resp, fl) {
  const d = resp.dados, log = fl.escala === "log";
  const o = d.origens.find((x) => x.id === estadoDist.origem) || d.origens[0];
  const x = d.anos.map((a) => rotuloEixo(a.rotulo));
  const mudanca = d.regra_por_ano.findIndex((r, i) => i > 0 && r !== d.regra_por_ano[i - 1]);
  const total = estado.meta.regiao_carajas.length, nm = fl.municipios.length;
  const recorte = o.id === "regiao" && nm && nm < total ? ` (${nm} de ${total} municípios selecionados)` : "";
  $("#sub-destinos").textContent = `${o.nome}${recorte}: a pilha inteira é o total arrecadado. `
    + (mudanca > 0 ? `Em ${d.anos[mudanca].ano} entra a regra atual, com a cota dos municípios afetados.` : "Cada cor é um destino.");
  const traces = tudoZero([o.gerado]) ? [] : DEST.filter((k) => o.destinos[k].some((v) => v)).map((k) => ({
    type: "bar", name: DEST_NOME[k], x, y: o.destinos[k].map((v) => (log && !v ? null : v / 1e6)),
    marker: { color: corDest(k), line: { color: css("--surface"), width: 1.5 } },
    customdata: o.destinos[k].map((v, i) => [brl(v, false), pct(o.gerado[i] ? (v / o.gerado[i]) * 100 : null)]),
    hovertemplate: `<b>${DEST_NOME[k]}</b>, %{x}<br>%{customdata[0]}<br>%{customdata[1]} do arrecadado<extra></extra>`,
  }));
  if (traces.length && !log && d.anos.length <= 8) {
    traces.push({ type: "scatter", mode: "text", x, y: o.gerado.map((t) => t / 1e6), text: o.gerado.map((t) => (t ? brl(t) : "")),
      textposition: "top center", textfont: { color: css("--ink-2"), size: 12 }, hoverinfo: "skip", showlegend: false, cliponaxis: false });
  }
  plotar("g-destinos", traces, layout({ height: 400, barmode: log ? "group" : "stack", yaxis: eixoValor(log), xaxis: { type: "category" } }));
}

// ============================================================================ peso nos repasses
function desenharPeso(resp, fl) {
  const d = resp.dados;
  const x = d.anos.map((a) => rotuloEixo(a.rotulo));
  const soma = d.series.find((s) => s.nome === SOMA);
  const pe = soma.periodo.pct_cota_estadual_pa, pa = soma.periodo.pct_afetados_br;
  $("#sub-peso").textContent = `No período, a CFEM gerada nas duas cidades formou ${pct(pe)} da cota do Governo do Pará`
    + (pa !== null ? ` e ${pct(pa)} de todo o fundo dos municípios afetados do país (o mesmo vale para a parcela da União).` : ". A cota dos afetados só existe a partir de 2018.");
  const linhas = (chave, valores) => d.series.map((s) => ({
    type: "scatter", mode: "lines+markers", name: s.nome, x, y: s[chave],
    line: { color: corSerie(s.nome), width: 2, dash: s.nome === SOMA ? "dot" : "solid" },
    marker: { size: 8, color: corSerie(s.nome), line: { color: css("--surface"), width: 2 } },
    customdata: s[valores].map((v) => brl(v, false)), connectgaps: false,
    hovertemplate: `<b>${s.nome}</b>, %{x}<br>%{y:.1f}%<br>%{customdata}<extra></extra>`,
  }));
  const lay = () => layout({ height: 340, yaxis: { range: [0, 104], ticksuffix: "%", title: { text: "" } }, xaxis: { type: "category" } });
  plotar("g-peso-estado", tudoZero([d.totais.cota_estadual_pa]) ? [] : linhas("pct_cota_estadual_pa", "cota_estadual"), lay());
  const semAfetados = d.totais.afetados_br.every((v) => !v);
  if (semAfetados) {
    const el = $("#g-peso-afetados");
    if (window.Plotly) Plotly.purge(el);
    el.style.height = "auto";
    el.innerHTML = '<div class="vazio">Não havia cota para municípios afetados no período escolhido (só existe a partir de 2018).</div>';
  } else {
    plotar("g-peso-afetados", linhas("pct_afetados_br", "afetados"), lay());
  }
}

// ============================================================================ tabela município × destino
function desenharTabelaDestinos(resp, fl) {
  const d = resp.dados;
  $("#sub-tabela-destinos").textContent = `Valores do período inteiro. Linhas em itálico: ${d.descricao_media}.`;
  const usados = DEST.filter((k) => d.linhas.some((l) => l.destinos[k]));
  const cab = usados.map((k) => `<th><span class="tag" style="background:var(${DEST_VAR[k]})"></span>${esc(DEST_NOME[k] === "Governo do Pará" ? "Estado" : DEST_NOME[k])}</th>`).join("");
  const corpo = d.linhas.map((l) => {
    const cls = l.tipo === "total" ? ' class="total"' : l.tipo === "media" ? ' class="media"' : "";
    const tag = l.foco || l.tipo === "media" ? `<span class="tag" style="background:var(${COR_VAR[l.nome]})"></span>` : "";
    return `<tr${cls}><td>${tag}${esc(l.nome)}</td><td>${brl(l.gerado)}</td>${usados.map((k) => `<td>${brl(l.destinos[k])}</td>`).join("")}</tr>`;
  }).join("");
  $("#t-destinos").innerHTML = `<thead><tr><th>Município</th><th>Arrecadado</th>${cab}</tr></thead><tbody>${corpo}</tbody>`;
}

// ============================================================================ eventos próprios da página
document.addEventListener("change", (e) => {
  if (e.target.name !== "origem") return;
  estadoDist.origem = e.target.value;
  const resp = estado.respostas["destinos-anual"];
  if (resp) desenharDestinosAnual(resp, lerFiltros());
});

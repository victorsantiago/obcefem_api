/* Observatório da CFEM — exportação nas páginas de arrecadação/autuação e de distribuição:
 * - CSV e PNG de cada gráfico, e CSV de cada tabela (botões no rodapé de cada bloco);
 * - PDF da página inteira (botão "Download" nos filtros), com indicadores, gráficos, tabelas e fontes.
 * Carregado depois de comum.js e do script da página; usa as funções globais de comum.js
 * ($, $$, esc, lerFiltros, textoPeriodo, baseAtual). O jsPDF (vendor/jspdf.umd.min.js) só é carregado ao gerar o PDF.
 */
"use strict";
(() => {
  const pagina = () => (window.PAGINA ? window.PAGINA.id : "arrecadacao");
  const prefixo = () => (pagina() === "distribuicao" ? "distribuicao" : baseAtual());
  const nomePagina = () => (pagina() === "distribuicao" ? "Análise da distribuição" : baseAtual() === "autuacao" ? "Análise das autuações" : "Análise da arrecadação");
  const fonte = () => (pagina() === "distribuicao"
    ? "ANM, dados abertos da CFEM (arrecadação); distribuição estimada pela regra da Lei 13.540/2017"
    : baseAtual() === "autuacao" ? "ANM, dados abertos da CFEM (autuações)" : "ANM, dados abertos da CFEM (arrecadação)");
  const slug = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
  const semTags = (t) => String(t ?? "").replace(/<br\s*\/?>/gi, " ").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
  const numero = (v) => (typeof v === "number" ? new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6, useGrouping: false }).format(v) : v ?? "");
  const cel = (v) => { const s = String(v ?? ""); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csvTexto = (linhas) => "﻿" + linhas.map((l) => l.map(cel).join(";")).join("\r\n");
  const periodo = () => { try { return textoPeriodo(lerFiltros()); } catch (e) { return ""; } };

  // Imagens chegam como data:URL; viram Blob, que o navegador baixa de forma mais confiável que URLs longas
  function blobDeDataURL(u) {
    const [cab, dados] = u.split(",");
    const bin = atob(dados), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: cab.slice(5).split(";")[0] });
  }
  function baixar(nome, conteudo, tipo) {
    const blob = typeof conteudo === "string" && conteudo.startsWith("data:") ? blobDeDataURL(conteudo) : new Blob([conteudo], { type: tipo });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: nome });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
  function avisar(msg) {
    const p = $("#manchete");
    const aviso = Object.assign(document.createElement("p"), { className: "erro-secao", textContent: msg, role: "alert" });
    p.after(aviso); setTimeout(() => aviso.remove(), 8000);
  }

  // ============================================================================ títulos de cada gráfico
  function titulos(el) {
    const sec = el.closest("section");
    const h2 = sec.querySelector("h2") ? sec.querySelector("h2").textContent.trim() : "";
    const h3 = el.parentElement.querySelector("h3");
    const varios = sec.querySelectorAll(".grafico").length > 1;
    const sub = sec.querySelector(".sub") ? sec.querySelector(".sub").textContent.trim() : "";
    return { titulo: varios && h3 ? `${h2}: ${h3.textContent.trim()}` : h2, sub, curto: varios && h3 ? h3.textContent.trim() : "" };
  }

  // ============================================================================ CSV a partir do que o gráfico mostra
  const brlParaNumero = (s) => { const m = String(s).replace(/R\$\s?/, "").replace(/\./g, "").replace(",", "."); const n = Number(m); return Number.isFinite(n) ? n : null; };
  function linhasDoGrafico(gd) {
    const lay = gd.layout || {};
    const unY = semTags(lay.yaxis && lay.yaxis.title ? lay.yaxis.title.text || "" : ""), unX = semTags(lay.xaxis && lay.xaxis.title ? lay.xaxis.title.text || "" : "");
    const linhas = [];
    for (const t of gd.data || []) {
      if (t.visible === false || t.hoverinfo === "skip") continue;
      const nome = semTags(t.name || "");
      if (t.type === "sankey") {
        const rot = t.node.label.map(semTags);
        t.link.source.forEach((s, i) => linhas.push([rot[s], rot[t.link.target[i]], t.link.value[i], "R$ milhões"]));
        continue;
      }
      if (t.type === "heatmap") {
        t.y.forEach((yy, i) => t.x.forEach((xx, j) => {
          const bruto = t.customdata && t.customdata[i] ? brlParaNumero(t.customdata[i][j]) : null;
          const v = bruto !== null ? bruto : t.z[i][j];
          if (v !== null && v !== undefined && !Number.isNaN(v)) linhas.push([semTags(yy), semTags(xx), v, bruto !== null ? "R$" : ""]);
        }));
        continue;
      }
      const h = t.orientation === "h";
      const cats = h ? t.y : t.x, vals = h ? t.x : t.y;
      if (!cats || !vals) continue;
      cats.forEach((c, i) => {
        if (vals[i] === null || vals[i] === undefined) return;
        linhas.push([nome || "valor", semTags(c), vals[i], h ? unX : unY]);
      });
    }
    return linhas;
  }
  function csvGrafico(el) {
    const { titulo } = titulos(el);
    const extra = [periodo(), fonte()];
    const corpo = linhasDoGrafico(el).map(([s, c, v, u]) => [s, c, numero(v), u, ...extra]);
    const cab = el.data && el.data[0] && el.data[0].type === "sankey" ? ["origem", "destino", "valor", "unidade", "periodo", "fonte"] : ["serie", "categoria", "valor", "unidade", "periodo", "fonte"];
    baixar(`observatorio-cfem_${prefixo()}_${slug(titulo)}.csv`, csvTexto([cab, ...corpo]), "text/csv;charset=utf-8");
  }
  const celulasTabela = (tab) => [...tab.rows].map((r) => [...r.cells].flatMap((c) => [c.textContent.replace(/\s+/g, " ").trim(), ...Array(Math.max(0, (c.colSpan || 1) - 1)).fill("")]));
  function csvTabela(tab) {
    const sec = tab.closest("section");
    const titulo = sec.querySelector("h2") ? sec.querySelector("h2").textContent.trim() : "tabela";
    const linhas = celulasTabela(tab);
    linhas.push([], [`Período: ${periodo()}`], [`Fonte: ${fonte()}`]);
    baixar(`observatorio-cfem_${prefixo()}_${slug(titulo)}_tabela.csv`, csvTexto(linhas), "text/csv;charset=utf-8");
  }

  // ============================================================================ PNG com título, subtítulo e fonte
  function figuraBranca(gd, comTitulo) {
    const lay = JSON.parse(JSON.stringify(gd.layout || {}));
    const alt = (gd._fullLayout && gd._fullLayout.height) || gd.clientHeight || 380;
    const m = lay.margin || {};
    lay.paper_bgcolor = "#ffffff"; lay.plot_bgcolor = "#ffffff";
    lay.width = 1200;
    if (comTitulo) {
      const { titulo, sub } = titulos(gd);
      lay.title = {
        text: `<b>${esc(titulo)}</b>${sub ? `<br><span style="font-size:12px;color:#69707a">${esc(sub)}</span>` : ""}<br><span style="font-size:11px;color:#69707a">${esc(periodo())} · Fonte: ${esc(fonte())} · Observatório da CFEM</span>`,
        xref: "container", x: 0, xanchor: "left", yref: "container", y: 1, yanchor: "top", pad: { t: 18, l: 16 }, font: { size: 16, color: "#1c1e21" },
      };
      lay.margin = { ...m, t: (m.t || 30) + 100, l: Math.max(m.l || 8, 16), r: Math.max(m.r || 16, 16) };
      lay.height = alt + 100;
    } else {
      lay.margin = { ...m, l: Math.max(m.l || 8, 16), r: Math.max(m.r || 16, 16) };
      lay.height = alt;
    }
    return { data: gd.data, layout: lay };
  }
  async function pngGrafico(el) {
    const f = figuraBranca(el, true);
    const url = await Plotly.toImage(f, { format: "png", width: f.layout.width, height: f.layout.height, scale: 2 });
    baixar(`observatorio-cfem_${prefixo()}_${slug(titulos(el).titulo)}.png`, url);
  }

  // ============================================================================ rodapé de cada bloco
  function montarRodapes() {
    $$("main section.bloco").forEach((sec) => {
      if (sec.querySelector(".rodape-bloco")) return;
      const graficos = [...sec.querySelectorAll(".grafico")];
      const tabelas = [...sec.querySelectorAll("table.tabela")];
      if (!graficos.length && !tabelas.length) return;
      const botoes = [];
      graficos.forEach((g) => {
        const h3 = graficos.length > 1 && g.parentElement.querySelector("h3");
        const rot = h3 ? ` · ${h3.textContent.trim()}` : "";
        botoes.push(`<button type="button" class="botao-mini" data-exportar="csv" data-alvo="${g.id}" title="Baixar os dados deste gráfico em CSV">CSV${esc(rot)}</button>`);
        botoes.push(`<button type="button" class="botao-mini" data-exportar="png" data-alvo="${g.id}" title="Baixar este gráfico como imagem PNG">PNG${esc(rot)}</button>`);
      });
      tabelas.forEach((t) => botoes.push(`<button type="button" class="botao-mini" data-exportar="tabela" data-alvo="${t.id}" title="Baixar esta tabela em CSV">${graficos.length ? "Tabela (CSV)" : "CSV"}</button>`));
      sec.insertAdjacentHTML("beforeend", `<div class="rodape-bloco"><span class="fonte-bloco">Fonte: ${esc(fonte())}</span><span class="acoes-bloco">${botoes.join("")}</span></div>`);
    });
  }
  const atualizarFontes = () => $$(".fonte-bloco").forEach((s) => { s.textContent = `Fonte: ${fonte()}`; });

  // ============================================================================ PDF da página inteira
  const carregar = (src) => new Promise((ok, erro) => {
    if (window.jspdf) return ok();
    const s = Object.assign(document.createElement("script"), { src, onload: ok, onerror: () => erro(new Error(`não carregou ${src}`)) });
    document.head.appendChild(s);
  });
  const pdfTexto = (t) => String(t ?? "").replace(/[–—]/g, "-").replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/…/g, "...")
    .replace(/→/g, "->").replace(/›/g, ">").replace(/×/g, "x").replace(/[  ]/g, " ").replace(/[^\u0000-ÿ]/g, "");

  async function gerarPDF(botao) {
    const rotulo = botao.textContent;
    botao.disabled = true;
    try {
      await carregar("vendor/jspdf.umd.min.js");
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ unit: "mm", format: "a4", compress: true });
      const M = 15;
      let W = 180, BASE = 282, y = M, deitada = false;
      const novaPagina = (paisagem = false) => {
        doc.addPage("a4", paisagem ? "landscape" : "portrait"); deitada = paisagem;
        W = paisagem ? 267 : 180; BASE = paisagem ? 195 : 282; y = M;
      };
      const texto = (t, { tam = 9.5, cor = [28, 30, 33], negrito = false, entre = 1.5 } = {}) => {
        doc.setFont("helvetica", negrito ? "bold" : "normal"); doc.setFontSize(tam); doc.setTextColor(...cor);
        const linhas = doc.splitTextToSize(pdfTexto(t), W);
        const alt = linhas.length * tam * 0.3528 * 1.25;
        if (y + alt > BASE) novaPagina(deitada);
        doc.text(linhas, M, y + tam * 0.3528); y += alt + entre;
      };
      // capa
      texto("Observatório da CFEM", { tam: 11, cor: [35, 122, 90], negrito: true });
      texto(nomePagina(), { tam: 22, negrito: true, entre: 3 });
      texto($("#manchete").textContent, { tam: 11, cor: [70, 75, 82], entre: 3 });
      const fl = lerFiltros();
      texto(`Período: ${periodo()}.`, { tam: 9.5, cor: [70, 75, 82] });
      texto(`Municípios na comparação: ${fl.municipios.length ? fl.municipios.join(", ") : "todos os 12"}.`, { tam: 9.5, cor: [70, 75, 82] });
      if (pagina() !== "distribuicao" || fl.substancias.length) texto(`Substâncias: ${fl.substancias.length ? fl.substancias.join(", ") : "todas"}.`, { tam: 9.5, cor: [70, 75, 82] });
      texto(`Gerado em ${new Date().toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "short" })} a partir de ${location.href}`, { tam: 8.5, cor: [105, 112, 122], entre: 3 });
      $$("#notas li").forEach((li) => texto(`• ${li.textContent}`, { tam: 8.5, cor: [105, 112, 122], entre: 1 }));
      y += 3;
      // indicadores (cifras)
      const cifras = $$(".cifra");
      if (cifras.length) {
        texto("Indicadores", { tam: 13, negrito: true, entre: 2 });
        cifras.forEach((c) => {
          const rot = c.querySelector(".rotulo"), val = c.querySelector(".valor"), ex = c.querySelector(".extra");
          texto(`${rot ? rot.textContent.trim() : ""}: ${val ? val.textContent.trim() : ""}${ex && ex.textContent.trim() ? ` (${ex.textContent.trim()})` : ""}`, { tam: 9.5, entre: 1 });
        });
        y += 4;
      }
      // blocos
      const blocos = $$("main section.bloco").filter((s) => !s.hidden && s.offsetParent !== null);
      let n = 0;
      for (const sec of blocos) {
        n += 1; botao.textContent = `Gerando PDF… ${n}/${blocos.length}`;
        const h2 = sec.querySelector("h2"), sub = sec.querySelector(".sub");
        const larga = (t) => Math.max(0, ...celulasTabela(t).map((l) => l.length)) > 6;
        const soTabelaLarga = !sec.querySelector(".js-plotly-plot") && [...sec.querySelectorAll("table.tabela")].some(larga);
        if (soTabelaLarga) novaPagina(true);
        else if (deitada || y + 40 > BASE) novaPagina(false);
        texto(h2 ? h2.textContent : "", { tam: 13, negrito: true, entre: 1 });
        if (sub && sub.textContent.trim()) texto(sub.textContent, { tam: 9, cor: [105, 112, 122], entre: 2 });
        for (const gd of sec.querySelectorAll(".js-plotly-plot")) {
          const h3 = gd.parentElement.querySelector("h3");
          if (h3 && sec.querySelectorAll(".js-plotly-plot").length > 1) texto(h3.textContent, { tam: 10, negrito: true, entre: 1 });
          const f = figuraBranca(gd, false);
          const img = await Plotly.toImage(f, { format: "jpeg", width: f.layout.width, height: f.layout.height, scale: 1.5 });
          const alt = (W * f.layout.height) / f.layout.width;
          if (y + alt > BASE) novaPagina(false);
          doc.addImage(img, "JPEG", M, y, W, alt, undefined, "FAST"); y += alt + 3;
        }
        for (const tab of sec.querySelectorAll("table.tabela")) {
          const linhas = celulasTabela(tab).filter((l) => l.some((c) => c));
          if (!linhas.length) continue;
          const nc = Math.max(...linhas.map((l) => l.length));
          if (nc > 6 && !deitada) { novaPagina(true); texto(`${h2 ? h2.textContent : ""} (tabela)`, { tam: 12, negrito: true, entre: 2 }); }
          const tam = nc > 14 ? 5.8 : nc > 6 ? 6.8 : 7.5, lh = tam * 0.3528 * 1.6;
          const c0 = Math.min(nc > 6 ? 62 : 55, W * 0.3), cw = nc > 1 ? (W - c0) / (nc - 1) : W;
          const cabecalho = tab.tHead ? tab.tHead.rows.length : 1;
          linhas.forEach((l, i) => {
            if (y + lh > BASE) novaPagina(deitada);
            doc.setFont("helvetica", i < cabecalho ? "bold" : "normal"); doc.setFontSize(tam); doc.setTextColor(28, 30, 33);
            l.forEach((c, j) => {
              const largura = j === 0 ? c0 - 1 : cw - 1.5;
              let t = pdfTexto(c), fs = tam;
              doc.setFontSize(fs);
              while (fs > 4.6 && doc.getTextWidth(t) > largura) { fs -= 0.3; doc.setFontSize(fs); }   // números: diminui a letra em vez de cortar
              if (doc.getTextWidth(t) > largura) t = doc.splitTextToSize(t, largura)[0] || "";
              if (j === 0) doc.text(t, M, y + tam * 0.3528);
              else doc.text(t, M + c0 + cw * j - 1, y + tam * 0.3528, { align: "right" });
              doc.setFontSize(tam);
            });
            if (i === cabecalho - 1) { doc.setDrawColor(214, 217, 213); doc.line(M, y + lh - 0.6, M + W, y + lh - 0.6); }
            y += lh;
          });
          y += 3;
        }
        texto(`Fonte: ${fonte()}`, { tam: 8.5, cor: [70, 75, 82], entre: 6 });
      }
      const total = doc.getNumberOfPages();
      for (let p = 1; p <= total; p++) {
        doc.setPage(p);
        const larg = doc.internal.pageSize.getWidth(), altura = doc.internal.pageSize.getHeight();
        doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(105, 112, 122);
        doc.text(pdfTexto(`Observatório da CFEM · ${nomePagina()}`), M, altura - 6);
        doc.text(`${p} / ${total}`, larg - M, altura - 6, { align: "right" });
      }
      doc.save(`observatorio-cfem_${pagina() === "distribuicao" ? "distribuicao" : baseAtual()}.pdf`);
    } catch (e) {
      avisar(`Não foi possível gerar o PDF: ${e.message}`);
    } finally {
      botao.disabled = false; botao.textContent = rotulo;
    }
  }

  // ============================================================================ eventos
  function iniciar() {
    montarRodapes();
    document.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-exportar]");
      if (b) {
        const alvo = document.getElementById(b.dataset.alvo);
        try {
          if (b.dataset.exportar === "tabela") csvTabela(alvo);
          else if (!alvo || !alvo.data) avisar("O gráfico ainda está carregando. Tente de novo em instantes.");
          else if (b.dataset.exportar === "csv") csvGrafico(alvo);
          else await pngGrafico(alvo);
        } catch (erro) { avisar(`Não foi possível baixar: ${erro.message}`); }
        return;
      }
      const pdf = e.target.closest("[data-acao='baixar-pdf']");
      if (pdf) gerarPDF(pdf);
    });
    const f = $("#filtros");
    if (f) f.addEventListener("change", atualizarFontes);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();

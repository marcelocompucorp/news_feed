"""Lê os feeds de feeds.txt, pede ao Gemini para separar o que interessa
segundo perfil.md e publica docs/feed.xml (aprovadas) e docs/barrados.xml
(descartadas, com o motivo, para conferir o filtro).

Uso:
    GEMINI_API_KEY=... python filtro.py           # execução normal
    python filtro.py --sem-ia                     # testa sem IA (aprova tudo)
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

import requests

RAIZ = Path(__file__).parent
ESTADO = RAIZ / "estado.json"
SAIDA = RAIZ / "docs"
URL_PUBLICA = "https://marcelocompucorp.github.io/news_feed/"

# WebSub: o feed anuncia este hub, e o workflow avisar.yml o notifica a cada
# publicação. Assim o Feedly recebe as matérias na hora em vez de esperar a
# próxima visita dele, que num feed com um assinante pode levar muitas horas.
HUB = "https://pubsubhubbub.appspot.com/"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM)

# Tenta na ordem; se o Google estiver sobrecarregado num modelo, passa ao seguinte.
MODELOS = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest,gemini-flash-latest").split(",")
ERROS_PASSAGEIROS = (429, 500, 502, 503, 504)
URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

DIAS_NO_ESTADO = 30   # depois disso a matéria sai do estado.json
ITENS_NO_FEED = 100   # quantas matérias o feed publicado mantém

INSTRUCAO = """Você filtra matérias de um site de tecnologia para um leitor.
Abaixo está o perfil de interesse dele. Para cada matéria recebida, decida se
ela deve ir para o feed dele (manter=true) ou não (manter=false), e dê um
motivo curto em português (até 12 palavras).

Responda com uma entrada para cada matéria, usando o mesmo id.

PERFIL:
{perfil}"""


def ler_feeds():
    linhas = (RAIZ / "feeds.txt").read_text().splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.startswith("#")]


def baixar_itens(url):
    resposta = requests.get(url, timeout=30, headers={"User-Agent": "news_feed-filtro/1.0"})
    resposta.raise_for_status()
    canal = ET.fromstring(resposta.content).find("channel")
    fonte = canal.findtext("title", url)
    itens = []
    for item in canal.findall("item"):
        link = item.findtext("link", "").strip()
        itens.append({
            "guid": item.findtext("guid", link).strip(),
            "titulo": item.findtext("title", "").strip(),
            "link": link,
            "resumo": item.findtext("description", "").strip(),
            "categorias": [c.text.strip() for c in item.findall("category") if c.text],
            "data": item.findtext("pubDate", ""),
            "fonte": fonte,
        })
    return itens


def classificar(itens, perfil):
    """Devolve {guid: (manter, motivo)} numa única chamada ao Gemini."""
    chave = os.environ["GEMINI_API_KEY"]
    materias = [
        {"id": str(i), "titulo": it["titulo"], "resumo": it["resumo"][:500],
         "categorias": it["categorias"]}
        for i, it in enumerate(itens)
    ]
    corpo = {
        "systemInstruction": {"parts": [{"text": INSTRUCAO.format(perfil=perfil)}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(materias, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "STRING"},
                        "manter": {"type": "BOOLEAN"},
                        "motivo": {"type": "STRING"},
                    },
                    "required": ["id", "manter", "motivo"],
                },
            },
        },
    }
    resposta = None
    for modelo in MODELOS:
        for tentativa in range(2):
            try:
                resposta = requests.post(URL_GEMINI.format(modelo.strip()), json=corpo, timeout=120,
                                         headers={"x-goog-api-key": chave})
            except requests.RequestException as erro:
                print(f"{modelo}: falha de rede ({erro})")
                resposta = None
            if resposta is not None and resposta.status_code not in ERROS_PASSAGEIROS:
                break
            time.sleep(15)
        if resposta is not None and resposta.status_code not in ERROS_PASSAGEIROS:
            break
        print(f"{modelo}: indisponível ({resposta.status_code if resposta is not None else 'rede'})")
    else:
        # Problema passageiro do lado do Google: as matérias não entram no
        # estado e são avaliadas de novo na próxima execução, sem falhar o job.
        print("::warning::Gemini indisponível; as matérias ficam para a próxima execução")
        return {}
    resposta.raise_for_status()  # erro de verdade (chave inválida, modelo extinto): falha o job

    partes = resposta.json()["candidates"][0]["content"]["parts"]
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
    decisoes = {d["id"]: (d["manter"], d["motivo"]) for d in json.loads(texto)}
    return {it["guid"]: decisoes[str(i)] for i, it in enumerate(itens) if str(i) in decisoes}


def gravar_feed(arquivo, titulo, descricao, itens):
    rss = ET.Element("rss", version="2.0")
    canal = ET.SubElement(rss, "channel")
    ET.SubElement(canal, "title").text = titulo
    ET.SubElement(canal, "link").text = "https://github.com/marcelocompucorp/news_feed"
    ET.SubElement(canal, "description").text = descricao
    ET.SubElement(canal, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(canal, f"{{{ATOM}}}link", rel="self", href=URL_PUBLICA + arquivo.name,
                  type="application/rss+xml")
    ET.SubElement(canal, f"{{{ATOM}}}link", rel="hub", href=HUB)
    for it in itens:
        item = ET.SubElement(canal, "item")
        ET.SubElement(item, "title").text = it["titulo"]
        ET.SubElement(item, "link").text = it["link"]
        ET.SubElement(item, "guid", isPermaLink="false").text = it["guid"]
        ET.SubElement(item, "pubDate").text = it["data"]
        ET.SubElement(item, "description").text = f'{it["resumo"]}\n\n[Filtro: {it["motivo"]}]'
        for categoria in it["categorias"]:
            ET.SubElement(item, "category").text = categoria
    ET.indent(rss)
    arquivo.write_bytes(ET.tostring(rss, encoding="utf-8", xml_declaration=True))


def data_do_item(it):
    try:
        return parsedate_to_datetime(it["data"])
    except (TypeError, ValueError):
        return datetime.fromisoformat(it["avaliado_em"])


def main():
    sem_ia = "--sem-ia" in sys.argv
    estado = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    perfil = (RAIZ / "perfil.md").read_text()
    agora = datetime.now(timezone.utc)

    novos = []
    for url in ler_feeds():
        try:
            novos += [it for it in baixar_itens(url) if it["guid"] not in estado]
        except (requests.RequestException, ET.ParseError) as erro:
            print(f"Falha ao ler {url}: {erro}")
    novos = list({it["guid"]: it for it in novos}.values())
    print(f"{len(novos)} matérias novas")

    if novos:
        if sem_ia:
            decisoes = {it["guid"]: (True, "teste sem IA") for it in novos}
        else:
            decisoes = classificar(novos, perfil)
        for it in novos:
            if it["guid"] not in decisoes:
                continue  # sem resposta para esta: tenta de novo na próxima execução
            it["manter"], it["motivo"] = decisoes[it["guid"]]
            it["avaliado_em"] = agora.isoformat()
            estado[it["guid"]] = it
            print(f'{"✓" if it["manter"] else "✗"} {it["titulo"]}  ({it["motivo"]})')

    limite = agora - timedelta(days=DIAS_NO_ESTADO)
    estado = {g: it for g, it in estado.items() if datetime.fromisoformat(it["avaliado_em"]) > limite}
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1))

    if sem_ia:
        return  # não publica feed de teste

    ordenados = sorted(estado.values(), key=data_do_item, reverse=True)
    SAIDA.mkdir(exist_ok=True)
    gravar_feed(SAIDA / "feed.xml", "Engadget filtrado",
                "Matérias que passaram no filtro de perfil.md",
                [it for it in ordenados if it["manter"]][:ITENS_NO_FEED])
    gravar_feed(SAIDA / "barrados.xml", "Engadget filtrado: barrados",
                "Matérias descartadas pelo filtro, com o motivo",
                [it for it in ordenados if not it["manter"]][:ITENS_NO_FEED])


if __name__ == "__main__":
    main()

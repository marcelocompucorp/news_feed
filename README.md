# news_feed

Filtra feeds RSS de tecnologia com IA (Gemini) e publica um feed só com o que
interessa, para assinar no Feedly.

- `feeds.txt`: feeds de origem (hoje só o Engadget).
- `perfil.md`: o que quero e o que não quero ver. É o único arquivo a editar
  para afinar o filtro.
- `filtro.py`: baixa os feeds, manda as matérias novas ao Gemini e grava
  `docs/feed.xml` (aprovadas) e `docs/barrados.xml` (descartadas, com motivo).
- `estado.json`: matérias já avaliadas nos últimos 30 dias, para não pagar
  duas vezes pela mesma.
- `.github/workflows/filtro.yml`: roda tudo de hora em hora no GitHub Actions.

## Feeds publicados

- Aprovadas: https://marcelocompucorp.github.io/news_feed/feed.xml
- Barradas: https://marcelocompucorp.github.io/news_feed/barrados.xml

## Configuração (uma vez)

1. Gerar uma chave em https://aistudio.google.com/apikey.
2. Settings → Secrets and variables → Actions → New repository secret,
   nome `GEMINI_API_KEY`.
3. Settings → Pages → Deploy from a branch → `main`, pasta `/docs`.
4. Actions → Filtrar feeds → Run workflow, para a primeira execução.

## Rodar localmente

```bash
GEMINI_API_KEY=... python3 filtro.py
```

`python3 filtro.py --sem-ia` testa a leitura dos feeds sem chamar a IA.
Os dois comandos alteram o `estado.json`.

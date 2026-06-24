# Réviseur RAG

Un assistant de révision qui lit tes cours en PDF et te fait réviser dessus. Trois usages : poser une question et obtenir une réponse sourcée, générer une fiche de synthèse, ou se faire interroger en répétition espacée — le système pose les questions, corrige tes réponses et reprogramme chaque carte selon ce que tu retiens.

L'idée n'est pas seulement de retrouver l'information (ça, un chatbot le fait déjà) mais de la mémoriser : les questions sont générées automatiquement depuis tes propres documents, tes réponses libres sont corrigées, et la révision suit un planning type Anki.

## Fonctionnalités

- **Q&A** — question en langage naturel, réponse construite à partir des passages les plus proches, avec citation des sources (fichier + page).
- **Fiche** — synthèse structurée d'un document : idées clés, définitions, à retenir, questions d'auto-test.
- **Interroge-moi** — le système génère des cartes question/réponse, t'interroge, note ta réponse de 0 à 5 (correction par l'IA) et la replanifie avec l'algorithme SM-2.
- **QCM** — questions à choix multiples générées depuis tes cours, avec une ou plusieurs bonnes réponses (cases à cocher, correction tout-ou-rien) et une explication systématique (pourquoi la bonne est correcte, pourquoi les autres sont fausses). Bonne réponse → carte espacée, mauvaise → carte revue dès le lendemain (même planning SM-2).
- **Flashcards** — révision en autonomie du même jeu de cartes que « Interroge-moi » : on révèle la réponse et on s'auto-note (Raté / Difficile / Bien / Facile), sans appel à l'IA. La note alimente le SM-2.
- **Tableau de bord** — statistiques de révision : maturité des cartes (nouvelles → maîtrisées), activité par jour, répartition par document, et une heatmap des échéances à venir. Filtrable par document.

## Comment ça marche

Le pipeline RAG (Retrieval-Augmented Generation) :

1. **Découpage** — chaque PDF est lu avec `pypdf` et coupé en passages d'environ 800 mots, avec un recouvrement de 150 mots pour ne pas perdre le fil entre deux passages.
2. **Indexation** — chaque passage est encodé en vecteur avec le modèle `all-MiniLM-L6-v2` (sentence-transformers). L'index est mis en cache dans `index_cache.pkl` : seuls les fichiers modifiés sont réencodés.
3. **Recherche** — la question est encodée puis comparée aux passages par similarité cosinus ; les 4 plus proches forment le contexte.
4. **Génération** — ce contexte est envoyé à un modèle Groq (`llama-3.3-70b`) qui rédige la réponse en français et cite les sources.

Pour la répétition espacée, chaque carte garde son état SM-2 (facilité, intervalle, prochaine échéance) dans une base SQLite. La note 0–5 met à jour cet état : bonne réponse → l'intervalle s'allonge, mauvaise → la carte revient dès le lendemain. Seules les cartes arrivées à échéance sont proposées à la révision. Chaque révision est aussi journalisée (table `reviews`), ce qui alimente la courbe d'activité du tableau de bord. Les graphes sont rendus côté client avec Chart.js, la heatmap d'échéances en CSS pur.

## Installation

Python 3.10+.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copie `.env.example` en `.env` et renseigne ta clé Groq (gratuite sur console.groq.com) :

```
GROQ_API_KEY=ta_cle_ici
```

## Lancement

```bash
python app.py
```

L'interface est sur http://127.0.0.1:5000. Au premier démarrage, le modèle d'embeddings (~80 Mo) est téléchargé. Ajoute tes PDF via le bouton « Ajouter un PDF », ou place-les directement dans le dossier `docs/`.

Une version ligne de commande existe aussi :

```bash
python chatbot.py
```

### Avec Docker

```bash
docker build -t reviseur-rag .
docker run -p 5000:5000 -e GROQ_API_KEY=ta_cle_ici reviseur-rag
```

Le modèle d'embeddings est téléchargé pendant le build, donc le conteneur démarre vite. Pour conserver tes PDF et tes cartes entre deux lancements, monte le dossier `docs/` et la base SQLite (crée d'abord le fichier vide, sinon Docker monterait un dossier à sa place) :

```bash
touch revision.db
docker run -p 5000:5000 -e GROQ_API_KEY=ta_cle_ici \
  -v "$(pwd)/docs:/app/docs" \
  -v "$(pwd)/revision.db:/app/revision.db" \
  reviseur-rag
```

## Tests

```bash
pytest
```

Les tests couvrent l'algorithme SM-2 : calcul des intervalles, réinitialisation après un échec, plancher du facteur de facilité, validation des notes.

## Structure

- `app.py` — serveur Flask, endpoints JSON
- `rag_engine.py` — moteur RAG : index, recherche, orchestration des trois modes
- `chatbot.py` — lecture PDF, embeddings, appels au modèle, et version ligne de commande
- `scheduler.py` — algorithme de répétition espacée SM-2 (fonction pure, testée)
- `store.py` — persistance SQLite des cartes et de leur planning
- `templates/index.html` — interface web

## Limites connues

- La recherche se fait en mémoire avec numpy : largement suffisant pour quelques documents, mais à remplacer par un index vectoriel dédié (FAISS) si le corpus grossit.
- Pas d'authentification ni de comptes : le projet est pensé pour un usage local.

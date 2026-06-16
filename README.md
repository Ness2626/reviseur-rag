# Réviseur RAG

Un assistant de révision qui lit tes cours en PDF et te fait réviser dessus. Trois usages : poser une question et obtenir une réponse sourcée, générer une fiche de synthèse, ou se faire interroger en répétition espacée — le système pose les questions, corrige tes réponses et reprogramme chaque carte selon ce que tu retiens.

L'idée n'est pas seulement de retrouver l'information (ça, un chatbot le fait déjà) mais de la mémoriser : les questions sont générées automatiquement depuis tes propres documents, tes réponses libres sont corrigées, et la révision suit un planning type Anki.

## Fonctionnalités

- **Q&A** — question en langage naturel, réponse construite à partir des passages les plus proches, avec citation des sources (fichier + page).
- **Fiche** — synthèse structurée d'un document : idées clés, définitions, à retenir, questions d'auto-test.
- **Interroge-moi** — le système génère des cartes question/réponse, t'interroge, note ta réponse de 0 à 5 et la replanifie avec l'algorithme SM-2.

## Comment ça marche

Le pipeline RAG (Retrieval-Augmented Generation) :

1. **Découpage** — chaque PDF est lu avec `pypdf` et coupé en passages d'environ 800 mots, avec un recouvrement de 150 mots pour ne pas perdre le fil entre deux passages.
2. **Indexation** — chaque passage est encodé en vecteur avec le modèle `all-MiniLM-L6-v2` (sentence-transformers). L'index est mis en cache dans `index_cache.pkl` : seuls les fichiers modifiés sont réencodés.
3. **Recherche** — la question est encodée puis comparée aux passages par similarité cosinus ; les 4 plus proches forment le contexte.
4. **Génération** — ce contexte est envoyé à un modèle Groq (`llama-3.3-70b`) qui rédige la réponse en français et cite les sources.

Pour la répétition espacée, chaque carte garde son état SM-2 (facilité, intervalle, prochaine échéance) dans une base SQLite. La note 0–5 met à jour cet état : bonne réponse → l'intervalle s'allonge, mauvaise → la carte revient dès le lendemain. Seules les cartes arrivées à échéance sont proposées à la révision.

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

- Les modes QCM et Flashcards sont prévus dans l'interface mais pas encore actifs.
- La recherche se fait en mémoire avec numpy : largement suffisant pour quelques documents, mais à remplacer par un index vectoriel dédié (FAISS) si le corpus grossit.
- Pas d'authentification ni de comptes : le projet est pensé pour un usage local.

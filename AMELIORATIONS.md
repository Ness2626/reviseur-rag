# Améliorations — fiche de route

Les évolutions envisagées pour le Réviseur, avec les décisions de conception déjà
tranchées pour chacune. Rien n'est urgent : l'ordre conseillé est en bas, et c'est
l'usage réel qui départage.

---

## 1. Recherche hybride BM25 + vecteurs — ½ journée

**Pourquoi.** MiniLM rate les termes exacts et les sigles (PSS, OAEP, X.509) ; BM25
les attrape. C'est un problème de *qualité* de retrieval, pas de vitesse (le retrieval
actuel prend quelques millisecondes, le goulot est l'appel LLM).

**Décisions prises.**
- Lib : `rank-bm25` (BM25Okapi), épinglée dans requirements.txt.
- Fusion : Reciprocal Rank Fusion sur les **rangs** (k=60), jamais sur les scores
  bruts — cosinus et BM25 ont des échelles incomparables. `score(doc) = Σ 1/(60+rang)`.
- `top_k=4` conservé après fusion.
- Tokenisation : lowercase + découpe sur les non-alphanumériques. Pas de stemming
  français (YAGNI).
- Index BM25 construit dans `RagEngine.rebuild()` à côté des embeddings. Pas de cache
  disque : la construction est rapide, on ne complexifie pas le cache HMAC existant.
- Le filtre par document s'applique **avant** la fusion (comme pour les vecteurs).

**Fichiers.** `rag_engine.py` (`_retrieve`), `requirements.txt`, `test_rag_engine.py`.
**Test clé.** Avec le FakeEmbedder existant (vocab rsa/tcp/aes) : une requête contenant
un terme hors vocab mais présent mot pour mot dans un chunk doit remonter ce chunk —
c'est exactement le cas que les vecteurs seuls ratent.

## 2. Chunking par sections — 1 journée (le plus incertain)

**Pourquoi.** Couper à 800 mots tranche au milieu des notions ; le titre de section
porte le contexte que le chunk perd.

**Décisions prises.**
- Détection **heuristique** des titres (ligne courte, numérotation `1.2.3`, majuscules)
  plutôt que l'outline pypdf : les PDF de cours n'en ont presque jamais.
- Préfixer chaque chunk par son titre : `[Section : RSA — signatures] <texte>`.
  Le préfixe entre dans l'embedding ET dans le contexte envoyé au LLM.
- Fallback : si aucune section détectée dans un PDF, garder le découpage 800/150 actuel.
- Cache : ajouter une constante `CHUNKER_VERSION` intégrée à `file_signature` pour
  invalider proprement les caches existants.

**Piège.** Valider l'heuristique sur les vrais PDF de cours **avant** d'écrire les
tests — c'est le point le plus dépendant des données réelles de toute la liste.

**Fait (validé sur les PDF réels).** La validation a écarté deux décisions initiales :
- La règle « ligne courte / majuscules » sortait 112 faux positifs sur un deck de slides
  (fragments de schémas : `LA`, `s=d(m,LA)`, `(m,s)`). **Abandonnée** au profit des seuls
  titres numérotés `N.`/`N.N`, numéro à 1–2 chiffres (élimine les années type `2017 (…)`)
  et ≤ 9 mots / 65 caractères (élimine les items de liste). Précision ~100 % sur les docs
  rédigés (CARNET, certif) ; slides et PDF sans texte → fallback 800/150, zéro régression.
- `CHUNKER_VERSION` **n'est pas** intégré à `file_signature` : celui-ci est comparé à un
  SHA-256 brut dans la détection de doublons (point 14), le mélanger casserait ce contrôle.
  Une fonction `cache_signature` distincte (`"{VERSION}:{sha256}"`) porte la version pour le
  cache uniquement. `CHUNKER_VERSION = 2` a invalidé et réencodé l'index une fois.
- Le préfixe `[Section : …] <texte>` entre dans l'embedding, dans le contexte LLM et
  s'affiche dans la citation (l'utilisateur voit de quelle section vient l'extrait).
  Titre carry-over d'une page à l'autre pour les sections à cheval, numéros de page
  préservés (citations intactes). Tests : `test_chatbot.py`.

## 3. Streaming SSE des réponses — ½ à 1 journée

**Pourquoi.** 5-10 s d'attente sans feedback sur les réponses longues.

**Décisions prises.**
- Groq `stream=True` ; côté Flask, `Response(generator, mimetype="text/event-stream")`.
- Côté client : **accumuler** le texte et re-render le tout (marked + DOMPurify) avec
  un throttle ~100 ms. Ne jamais insérer les deltas bruts dans le DOM — ça
  contournerait la correction XSS du point 2 de SECURITY.md.
- CSP inchangée (`connect-src 'self'` couvre EventSource/fetch stream).
- Seul `/api/ask` streame. Cartes/quiz/exercices restent en JSON (le client attend un
  objet complet à valider).
- Gunicorn : les threads suffisent, `--timeout 120` déjà en place.

## 4. Page de connexion — 1 journée (seulement si démo déployée)

**Pourquoi.** En local elle n'apporte rien (voir SECURITY.md, choix assumé). Elle
devient **obligatoire** le jour où une démo part sur Render/Railway pour le CV. Bien
faite, c'est le point qui vaut le plus en entretien sécu ; mal faite, le plus cher.

**Décisions prises.**
- Mono-utilisateur : pas de table users, pas d'inscription. Un mot de passe, point.
- Hash : `argon2-cffi` (ou `hashlib.scrypt` stdlib si on refuse la dépendance), hash
  stocké dans `.env` (`APP_PASSWORD_HASH`) — jamais le mot de passe en clair.
- Session Flask signée : `SECRET_KEY` généré (`secrets.token_hex`), dans `.env`,
  jamais en dur dans le code.
- `@login_required` sur **toutes** les routes `/api/*` et `/` ; seule `/login` est
  publique.
- Rate limiting sur `/login` (flask-limiter, ~5/min) — sans ça, la page de login est
  le nouveau point d'attaque et l'ajout est contre-productif.
- Cookie : `Secure` + `HttpOnly` + `SameSite=Lax`.
- Mettre à jour SECURITY.md (le paragraphe « pas d'authentification » saute).

## 5. Mode examen blanc — 1 journée

**Décisions prises.**
- `/api/exam/new` : N questions (défaut 10) mélangeant quiz + questions ouvertes +
  un ou deux exercices de calcul, tirées sur tous les documents (ou un seul si filtré).
- Chrono côté client uniquement (affichage), durée envoyée à la fin pour l'historique.
- Correction en réutilisant `submit_answer` / `submit_quiz` / `grade` existants —
  aucun nouveau code de notation.
- Les réponses **comptent** dans SM-2 et la table `reviews` : un examen est une
  révision comme une autre.
- Note finale sur 20, stockée pour affichage dans le dashboard.

## 6. Export Anki / CSV — 2-3 h

**Décisions prises.** CSV d'abord (`question;réponse;source`, séparateur `;`, UTF-8
BOM pour Excel), bouton dans le dashboard, endpoint `GET /api/export/csv`.
`genanki` (.apkg natif) seulement si le CSV s'avère insuffisant à l'usage — ne pas
commencer par là.

## 7. Stats par notion — ½ journée

**Décisions prises.**
- Colonne `topic TEXT` sur `cards` (migration `ALTER TABLE`, tolérer NULL sur
  l'existant).
- Remplie **à la génération** : un champ de plus dans le JSON demandé au LLM — il lit
  déjà le contenu, le taguer ne coûte rien. Pas de re-classification a posteriori.
- Dashboard : un graphe groupé par topic (les cartes NULL groupées en « non classé »).

## 8. Historique Feynman — 2-3 h

**Décisions prises.** Table `feynman_history(id, concept, explanation, feedback,
created_at)`, insertion dans le endpoint existant, liste dans l'onglet Feynman
(les N derniers, dépliables). Rien de plus.

## 9. OCR fallback — 1 journée (seulement si besoin réel)

**Pourquoi.** PDF scannés → texte vide → rien d'indexé. À faire uniquement si le cas
se présente vraiment dans les cours.

**Décisions prises.**
- Détection : page dont `extract_text()` rend vide/quasi-vide → OCR de cette page.
- `pytesseract` + `pdf2image` en **extra optionnel** (pas dans requirements de base :
  dépendances système poppler + tesseract, pénibles surtout en Docker).
  `try/except ImportError` avec message clair « installez l'extra OCR ».
- `CHUNKER_VERSION` (point 2) sert aussi ici pour invalider le cache.

## 11. Rouvrir un PDF indexé — ½ heure

**Pourquoi.** Une fois un document ajouté, on ne peut plus le consulter. Manque
visible dès qu'on teste l'appli, et utile pour vérifier une source citée par le RAG.

**Décisions prises.**
- Route `GET /docs/<nom>` servant le fichier depuis `chatbot.DOCS_DIR` via
  `flask.send_from_directory` — jamais de concaténation de chemin à la main
  (`send_from_directory` bloque déjà le path traversal, cohérent avec l'upload).
- Valider que le nom se termine par `.pdf` avant de servir ; 404 sinon.
- Côté UI : le nom de chaque document dans la liste devient un lien
  `target="_blank"` vers `/docs/<nom>`. Le PDF s'ouvre dans le viewer natif du
  navigateur, aucun code de rendu à écrire.
- CSP : `object-src 'none'` reste ; on ouvre dans un onglet, on n'embarque pas.

**Fichiers.** `app.py` (nouvelle route), `templates/index.html` + `static/app.js`
(le lien), `test_app.py`.
**Test clé.** `GET /docs/cours.pdf` après upload → 200 + `Content-Type` PDF ;
`GET /docs/../app.py` → 404 (le path traversal reste neutralisé).

## 12. Séparer par matière — 1 journée

**Pourquoi.** Aujourd'hui tout est indexé par nom de fichier ; rien ne regroupe
« crypto » et « réseaux ». Pour réviser une matière sans mélanger les cartes des
autres, il faut une notion au-dessus du document.

**Décisions prises.**
- Une matière = un simple tag texte porté par le **document**, pas par la carte
  (une carte hérite de la matière de son PDF). Table `documents(name TEXT PRIMARY
  KEY, subject TEXT)`, `subject` NULL toléré (« non classé »).
- Assignée à l'upload : un champ texte libre à côté du bouton d'ajout (défaut
  vide). Pas de liste fermée de matières (YAGNI) — l'autocomplétion sur les
  matières déjà utilisées suffira plus tard si besoin.
- Le filtre existant (par document) gagne un cran au-dessus : filtrer par matière
  = filtrer sur tous les documents de cette matière. Réutiliser le paramètre
  `document` partout où c'est possible en résolvant matière → liste de documents
  côté `store`, pour ne pas propager un deuxième paramètre dans toutes les routes.
- Recoupe le point 7 (stats par notion) : `topic` = grain fin *dans* un PDF,
  `subject` = grain gros *au-dessus*. Les deux coexistent, ne pas les confondre.

**Piège.** Le filtre `document` traverse déjà `rag_engine`, `store` et l'UI —
lister tous ses points de passage **avant** de coder, sinon le filtre matière ne
s'appliquera qu'à moitié.
**Fichiers.** `store.py`, `rag_engine.py`, `app.py`, `templates/index.html`,
`static/app.js`, `test_store.py`, `test_app.py`.

## 13. Supprimer un document indexé — ½ journée

**Pourquoi.** Aucun moyen de retirer un cours depuis l'UI ; il fallait effacer le
fichier à la main dans `docs/` puis relancer.

**Décisions prises.**
- `DELETE /api/documents/<name>` : `secure_filename` sur le nom (le converter
  `<name>` rejette déjà les slashes), 404 si le fichier n'est pas dans `docs/`.
- Supprimer **le fichier + les cartes du document + son historique de reviews +
  son tag matière**, puis réindexer. Garder des cartes orphelines fausserait les
  stats. `store.delete_document` fait le ménage en une transaction.
- Confirmation navigateur avant suppression (irréversible).
- Bouton ✕ par document dans la liste latérale ; handler délégué sur `#doc-links`.

**Fichiers.** `store.py`, `app.py`, `templates/index.html`, `static/app.js`,
`test_store.py`, `test_app.py`.

## 14. Refus des doublons par contenu — 2-3 h

**Pourquoi.** Le refus de doublon ne portait que sur le **nom** de fichier : un
même PDF sous deux noms différents était indexé deux fois.

**Décisions prises.**
- SHA-256 du contenu uploadé, comparé aux `file_signature` des PDF déjà présents
  (réutilise le hash que le cache calcule déjà — pas de nouvelle logique de hash).
- 409 avec le nom du document identique déjà indexé.
- Le refus par nom (409 « existe déjà ») est conservé et testé en premier.

**Fichiers.** `app.py`, `test_app.py`.

## 15. Re-ranker cross-encoder — ½ journée

**Pourquoi.** La fusion RRF mélange les classements BM25 et vecteurs mais personne ne
*relit* les passages : un chunk peut être bien classé par les deux voies sans vraiment
répondre à la question. Un cross-encoder lit la paire (question, passage) en entier et
la note — bien plus précis qu'une comparaison de vecteurs calculés séparément. C'est le
« fused re-ranking » des moteurs RAG sérieux (RAGFlow), et ça bénéficie directement aux
citations ancrées : meilleurs passages en entrée, meilleures citations en sortie.

**Décisions prises.**
- Modèle : `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingue, gère le
  français ; via la classe `CrossEncoder` de sentence-transformers — aucune nouvelle
  dépendance). Chargé au démarrage comme l'embedder.
- Pipeline : RRF garde les **20** premiers candidats (au lieu de 4), le cross-encoder
  note les 20 paires, on garde les 4 meilleures. Latence CPU ~centaines de ms,
  négligeable devant l'appel LLM.
- Le re-ranking s'applique à `_retrieve` (Q&A et Feynman en profitent), pas aux
  générations de cartes/fiches (elles échantillonnent le corpus, pas une requête).
- Poids du modèle (~500 Mo) : à télécharger dans le build Docker comme l'embedder,
  sinon premier démarrage lent.

**Fichiers.** `rag_engine.py` (`_retrieve`), `chatbot.py` (chargement), `Dockerfile`,
`test_rag_engine.py`.
**Test clé.** Avec un faux cross-encoder qui note par recouvrement de mots : un chunk
classé 10e par RRF mais qui répond mot pour mot à la question doit finir dans le top 4.

## 10. LLM local Ollama — 1-2 journées (gros morceau, en dernier)

**Décisions prises.**
- Extraire une interface `LLMClient` (les appels `chat.completions.create` passent
  déjà tous par `RagEngine` — l'abstraction est presque gratuite) avec deux
  implémentations : Groq (défaut) et Ollama, choisies par variable d'env
  `LLM_PROVIDER`.
- Argument CV : « les cours ne quittent plus la machine » (répond directement à la
  limite « les cours partent chez un tiers » de SECURITY.md).
- Réalisme : sur CPU, un 7B quantisé (qwen2.5:7b-instruct-q4) est **lent** et plus
  faible que gpt-oss-120b — c'est une option de confidentialité, pas une amélioration
  de qualité. Le dire tel quel dans le README.
- Les prompts JSON (cartes/quiz) devront probablement être re-testés : les petits
  modèles respectent moins bien le format. Prévoir une validation plus tolérante ou
  un retry.

---

## Ordre conseillé

Déjà faits : **point 1** (recherche hybride BM25), **point 2** (chunking par sections),
**point 3** (streaming SSE), **point 6** (export CSV), **point 11** (rouvrir un PDF),
**point 12** (séparer par matière), **point 13** (supprimer un document), **point 14**
(refus des doublons par contenu), **point 15** (re-ranking cross-encoder), plus les
**citations ancrées** du Q&A (hors liste, inspirées de l'analyse de RAGFlow).

1. **Utiliser l'outil pour réviser** (0 min de dev) — c'est l'usage réel qui départage
   la suite : PDF scannés → point 9.
2. Manques visibles au premier test, rapides : **point 11** (rouvrir un PDF, ½ h)
   puis **point 12** (séparer par matière) — le point 12 est aussi le plus utile pour
   réviser une matière à la fois.
3. Démo déployée pour le CV → point 4 obligatoire d'abord.
4. Confort, dans l'ordre du meilleur ratio valeur/effort : 8, 7, 5.
5. Point 10 en dernier, quand tout le reste est stable.

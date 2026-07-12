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

1. **Utiliser l'outil pour réviser** (0 min de dev) — c'est l'usage réel qui départage
   la suite : retrieval qui rate des sigles → point 1 ; chunks incohérents → point 2 ;
   attente pénible → point 3 ; PDF scannés → point 9.
2. Démo déployée pour le CV → point 4 obligatoire d'abord.
3. Confort, dans l'ordre du meilleur ratio valeur/effort : 6, 8, 7, 5.
4. Point 10 en dernier, quand tout le reste est stable.

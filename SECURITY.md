# Sécurité — Réviseur RAG

Ce document décrit le modèle de menace du projet, les vulnérabilités identifiées lors d'une
revue de sécurité du code (juillet 2026), et les limites volontairement assumées.
Il est tenu à jour au fil des corrections : chaque vulnérabilité indique son statut.

## Contexte et périmètre

Réviseur RAG est une application **locale et mono-utilisateur** : un serveur Flask lancé sur
la machine de l'utilisateur (`127.0.0.1:5000` par défaut), qui indexe des PDF de cours et
interroge un LLM distant (API Groq). Il n'y a ni comptes, ni données d'autres utilisateurs,
ni exposition réseau prévue.

Ce contexte cadre l'analyse : les menaces pertinentes ne sont pas celles d'un service web
public (pas de scénario multi-tenant), mais celles d'une application de bureau qui traite
des **fichiers non fiables** (PDF venus de tiers), exécute du **contenu généré par un LLM**
dans un navigateur, et dépend d'une **chaîne d'approvisionnement** (PyPI, CDN, image Docker).

## Modèle de menace

### Actifs à protéger

| Actif | Localisation | Enjeu principal |
|---|---|---|
| Clé d'API Groq | `.env` | Confidentialité (usage frauduleux, quota) |
| Machine de l'utilisateur | hôte / conteneur | Intégrité (exécution de code arbitraire) |
| Session navigateur de l'utilisateur | front `templates/index.html` | Intégrité (XSS) |
| Contenu des cours (PDF) | `docs/` | Confidentialité (envoyés à un tiers, voir Limites) |
| Données de révision (cartes, historique) | `revision.db` | Intégrité / disponibilité |
| Cache d'index | `index_cache.json` / `.npz` / `.hmac` | Intégrité (authentifié par HMAC, voir V1) |

### Surfaces d'attaque et acteurs

1. **PDF non fiables** — l'utilisateur ajoute des documents dont il n'est pas l'auteur
   (cours partagés, fichiers téléchargés). Un PDF peut être malformé (attaque du parseur)
   ou contenir du texte adversarial destiné au LLM (injection de prompt indirecte).
2. **Sortie du LLM** — par construction non fiable : elle dérive du contenu des PDF et
   d'un modèle distant. Elle est affichée dans le navigateur de l'utilisateur.
3. **Fichiers locaux de l'application** — un processus ou un utilisateur local capable
   d'écrire dans le dossier du projet peut altérer le cache d'index ou `revision.db`.
4. **Chaîne d'approvisionnement** — dépendances PyPI non épinglées, bibliothèque JS
   chargée depuis un CDN, image de base Docker.
5. **Réseau local** — si l'application est lancée avec `HOST=0.0.0.0` (cas Docker),
   toute machine du réseau peut atteindre l'API sans authentification.

### Menaces et mitigations (synthèse)

| Menace | Vecteur | Mitigation en place | Mitigation prévue |
|---|---|---|---|
| Exécution de code via le cache d'index | fichier de cache altéré | Format inerte (JSON + npz) signé HMAC-SHA256, rejet si signature invalide (V1) | — |
| XSS via la réponse du LLM | PDF adversarial → injection de prompt → HTML dans la sortie | Sanitisation DOMPurify (SRI) + échappement systématique (V2) | — |
| Fuite de la clé d'API | commit accidentel, image Docker | `.env` exclu de git et de `.dockerignore` | — |
| Upload abusif (DoS, écrasement) | endpoint `/api/upload` | `secure_filename`, extension `.pdf`, taille max 50 Mo, magic bytes `%PDF`, refus des collisions (V3) | — |
| Compromission d'une dépendance | PyPI, CDN | Côté CDN : versions épinglées + SRI (V5) | V4 : versions PyPI épinglées, audit |
| Corrigé d'exercice erroné | hallucination du LLM | Les exercices crypto sont **calculés en Python**, jamais corrigés par le LLM (`exercises.py`) | — |
| Réponses pédagogiques trompeuses | hallucination du LLM | Réponses sourcées (fichier + page), avertissement IA dans l'interface | — |
| Accès réseau non authentifié | `HOST=0.0.0.0` | Bind sur `127.0.0.1` par défaut | Limite assumée (voir plus bas) |

## Vulnérabilités identifiées

Classement par priorité, issue d'une revue de code. Statut : ⏳ à corriger · ✅ corrigé.

### Priorité haute

**V1 — Désérialisation non sûre du cache d'index** · ✅ corrigé (juillet 2026) · CWE-502
`chatbot.py` utilisait `pickle.load()` sur `index_cache.pkl`. Le format `pickle` permet
l'exécution de code arbitraire à la désérialisation : quiconque pouvait écrire ce fichier
(autre processus, archive de projet partagée, volume Docker) obtenait une exécution de code
au prochain démarrage. C'était la vulnérabilité la plus grave du projet car elle transformait
un fichier de cache anodin en vecteur d'exécution.
*Correction : le cache est stocké en formats inertes — `index_cache.json` (chunks et
signatures des PDF) et `index_cache.npz` chargé avec `allow_pickle=False` (embeddings) —
et authentifié par un HMAC-SHA256 stocké dans `index_cache.hmac`. La clé (32 octets,
`secrets.token_bytes`) vit hors du cache dans `.cache_key` (mode 600, non versionné,
exclu de l'image Docker). Au chargement, le HMAC est recalculé et comparé en temps
constant (`hmac.compare_digest`) **avant** tout parsing ; en cas d'écart le cache est
rejeté et reconstruit depuis les PDF sources. On protège ici l'**intégrité**, pas la
confidentialité, le contenu n'étant pas secret.*

**V2 — XSS via la sortie du LLM (injection de prompt indirecte)** · ✅ corrigé (juillet 2026) · CWE-79, OWASP LLM01
`templates/index.html` — les réponses du LLM étaient converties en HTML par
`marked.parse()` puis insérées via `innerHTML` sans sanitisation. Or le LLM reçoit en
contexte le texte brut des PDF : un document piégé pouvait lui faire produire du HTML actif
(`<img onerror=…>`), exécuté dans le navigateur de l'utilisateur. Chaîne complète :
*PDF adversarial → injection de prompt indirecte → sortie HTML → XSS*.
*Correction : toute conversion Markdown passe par un helper `md()` qui sanitise la sortie
de `marked.parse()` avec DOMPurify 3.4.11 (chargé via CDN avec version épinglée et
attribut `integrity` SRI sha384 — le problème V5 ne s'applique donc pas à cette
bibliothèque). Le helper est fail-closed : si DOMPurify n'est pas chargé, le texte est
échappé au lieu d'être interprété. Les insertions de contenu LLM hors Markdown (question
de carte, feedback et réponse de référence de la correction, libellés de sources) passent
désormais toutes par `esc()`. La sortie d'un LLM est traitée comme une entrée utilisateur.*

### Priorité moyenne

**V3 — Durcissement insuffisant de l'upload PDF** · ✅ corrigé (juillet 2026) · CWE-400, CWE-434
`app.py` — trois manques :
- pas de `MAX_CONTENT_LENGTH` : un upload arbitrairement volumineux était accepté
  (épuisement disque/mémoire) ;
- seule l'extension était vérifiée, pas les magic bytes `%PDF` : n'importe quel fichier
  renommé passait, puis était parsé par `pypdf` ;
- un fichier existant du même nom était écrasé silencieusement.
*Correction : `MAX_CONTENT_LENGTH` fixé à 50 Mo (handler 413 avec message JSON clair),
vérification des magic bytes `%PDF` avant acceptation, et refus explicite (HTTP 409) si
un fichier du même nom existe déjà — le refus a été préféré au renommage automatique car
les cartes de révision sont rattachées au nom du document : un renommage silencieux
fragmenterait la progression entre deux noms pour un même cours.*

**V4 — Dépendances non épinglées** · ⏳ · CWE-1104
`requirements.txt` ne fixe aucune version. Le build n'est pas reproductible et chaque
installation récupère la dernière version publiée, sans contrôle (exposition supply chain).
*Correction prévue : versions épinglées, audit automatisé (`pip-audit`) en CI.*

**V5 — Bibliothèque JS chargée d'un CDN sans intégrité** · ✅ corrigé (juillet 2026) · CWE-829
`templates/index.html` — `marked` était chargé depuis jsdelivr sans version épinglée ni
attribut `integrity`, et Chart.js sans `integrity` : une compromission du CDN ou du paquet
npm aurait injecté du JS arbitraire dans l'application (et pu neutraliser DOMPurify, V2).
*Correction : les trois bibliothèques (marked 18.0.5, DOMPurify 3.4.11, Chart.js 4.4.1)
sont épinglées à une version exacte et portent un attribut `integrity` sha384 calculé
depuis les fichiers réellement servis, plus `crossorigin="anonymous"`. Chart.js référence
l'artefact publié `dist/chart.umd.js` plutôt que la variante `.min.js` re-générée à la
volée par jsdelivr, pour garantir la stabilité du hash. Le navigateur refuse tout script
dont le contenu ne correspond plus au hash.*

### Priorité basse

**V6 — Serveur de développement Flask en production Docker** · ⏳
`app.py:223` — `app.run()` lance le serveur de développement Werkzeug, mono-thread et
non durci, y compris dans le conteneur. *Correction prévue : gunicorn dans l'image Docker.*

**V7 — Conteneur exécuté en root** · ⏳ · CWE-250
`Dockerfile` — aucune instruction `USER` : le processus tourne en root dans le conteneur,
ce qui aggrave l'impact de toute compromission (V1 notamment, via le volume monté).
*Correction prévue : utilisateur non privilégié dédié.*

**V8 — MD5 pour la signature des fichiers** · ⏳ · CWE-328
`chatbot.py:72` — MD5 sert à détecter les modifications de PDF pour invalider le cache.
Ce n'est **pas exploitable ici** : aucun adversaire ne gagne quoi que ce soit à produire
une collision (au pire, un cache réutilisé à tort). On le remplace néanmoins par SHA-256 :
hygiène, cohérence avec V1, et silence des analyseurs statiques. Distinguer les usages
sécuritaires et non sécuritaires d'une fonction de hachage fait partie de l'analyse.

## Limites assumées

Choix délibérés, cohérents avec un usage local mono-utilisateur — documentés pour être
honnêtes sur ce que le projet ne protège **pas** :

- **Pas d'authentification ni de gestion de comptes.** L'application est conçue pour
  tourner sur `127.0.0.1`. Quiconque peut atteindre le port peut tout faire (uploader,
  interroger, consommer le quota d'API). En Docker (`HOST=0.0.0.0`), ne pas exposer le
  port au-delà de la machine hôte.
- **Le contenu des cours est envoyé à un tiers.** Chaque question transmet des extraits
  des PDF à l'API Groq. Ne pas indexer de documents confidentiels ou soumis à restriction
  de diffusion. Une alternative locale (Ollama) éliminerait cette dépendance.
- **Pas de chiffrement au repos.** `revision.db` et le cache d'index sont en clair sur
  le disque : le contenu (extraits de cours, statistiques de révision) ne justifie pas de
  chiffrement, et la clé d'API — la seule vraie donnée sensible — reste dans `.env`.
  Le HMAC du cache (V1) garantit son intégrité, pas sa confidentialité.
- **Pas de rate limiting.** Sans exposition réseau, le seul consommateur du quota Groq
  est l'utilisateur lui-même.
- **Le LLM peut se tromper.** Les réponses Q&A, fiches, corrections de réponses libres et
  QCM sont générés par un modèle et peuvent contenir des erreurs malgré l'ancrage dans les
  documents. Seuls les **exercices de calcul** ont un corrigé garanti (calculé en Python).
  L'interface l'indique ; ce n'est pas une vulnérabilité mais une propriété du système à
  garder en tête.

## Signaler un problème

Ce projet est un projet étudiant maintenu par une seule personne. Pour signaler une
vulnérabilité, ouvrez une issue GitHub (ou un contact privé via le profil
[@Ness2626](https://github.com/Ness2626) si le sujet est sensible).

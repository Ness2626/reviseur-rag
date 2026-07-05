# Sécurité — Réviseur RAG

Ce que j'ai vérifié et corrigé côté sécurité (revue en juillet 2026, 8 points, tous
corrigés), et ce que je ne protège volontairement pas.

## Le contexte

L'appli tourne en local, sur ma machine, pour moi seule. Les vrais risques ne sont donc
pas ceux d'un site web public. Ils viennent de trois endroits : les PDF que j'indexe
(je n'en suis pas toujours l'auteure), les réponses du LLM affichées dans mon navigateur
(elles dérivent de ces PDF, donc pas fiables par construction), et les dépendances
(paquets Python, bibliothèques JS, image Docker). À protéger : ma clé d'API, ma machine
et mon navigateur.

## Les 8 points corrigés

**1 — Cache d'index.** J'utilisais pickle pour sauvegarder le cache, mais ce format
peut exécuter du code au chargement : si quelqu'un modifiait ce fichier, il prenait le
contrôle de ma machine au démarrage suivant. Je suis passée à des formats qui ne
peuvent rien exécuter (JSON + tableaux numpy), et j'ai ajouté une signature HMAC-SHA256
pour vérifier que le fichier n'a pas été touché. La clé de signature est stockée à part
du cache : si elle y était aussi, un attaquant qui modifie le cache pourrait aussi
re-signer son fichier piégé, et ma vérification ne servirait à rien. Si la signature ne
correspond plus, je rejette le cache et je le reconstruis depuis les PDF.

**2 — XSS via le LLM.** Les réponses du LLM étaient converties en HTML et insérées
telles quelles dans la page. Or le LLM lit mes PDF : un document piégé pouvait lui
faire produire du HTML malveillant qui s'exécutait dans mon navigateur. Je nettoie
maintenant tout le Markdown généré avec DOMPurify avant affichage, et j'échappe les
autres contenus qui viennent du LLM (questions de cartes, corrections, sources). La
règle que j'en retiens : la sortie d'un LLM se traite comme une entrée utilisateur.

**3 — Upload trop permissif.** J'acceptais n'importe quelle taille, je ne vérifiais que
l'extension `.pdf` (pas le contenu réel), et un fichier du même nom écrasait l'ancien
sans prévenir. Maintenant : 50 Mo max, lecture des premiers octets pour vérifier que
c'est vraiment un PDF (magic bytes `%PDF`), et refus clair si le nom existe déjà. J'ai
préféré refuser plutôt que renommer automatiquement : mes cartes de révision sont liées
au nom du document, un renommage silencieux aurait coupé la progression en deux.

**4 — Dépendances non figées.** Mon `requirements.txt` ne fixait aucune version :
chaque installation récupérait les dernières versions publiées, sans contrôle. J'ai
tout épinglé à des versions précises et je passe `pip-audit` pour repérer les
vulnérabilités connues — le premier audit a d'ailleurs trouvé une vraie faille dans la
bibliothèque qui lit les PDF, corrigée en changeant de version. Une GitHub Action
relance l'audit chaque lundi (et à chaque modification des dépendances) : le job échoue
si une faille apparaît, ça me suffit comme alerte.

**5 — Bibliothèques JS non vérifiées.** Mes libs (marked, Chart.js) arrivaient d'un CDN
sans version fixe ni vérification : si le CDN ou le paquet était compromis, le code
injecté s'exécutait chez moi — et pouvait même désactiver DOMPurify, donc annuler ma
correction du point 2. J'ai d'abord épinglé chaque lib à une version exacte avec une
empreinte SRI (le navigateur refuse le fichier si son hash ne correspond plus), puis je
suis allée au bout de la logique : les trois libs sont maintenant servies en copie
locale (`static/vendor/`, fichiers vérifiés par leur empreinte avant d'être copiés).
Plus aucun CDN dans la boucle, et l'appli fonctionne hors ligne.

**6 — Serveur de dev en Docker.** Le conteneur lançait le serveur de développement de
Flask, mono-thread et pas fait pour tourner en continu. Je l'ai remplacé par gunicorn,
avec un seul worker parce que mon index et le modèle d'embeddings vivent en mémoire —
plusieurs workers en auraient chacun une copie divergente. En local, je garde le
lancement Flask classique pour développer.

**7 — Docker en root.** Rien ne changeait d'utilisateur dans le conteneur, donc tout
tournait en administrateur : la moindre compromission (le point 1 par exemple, via un
volume monté) avait les pleins pouvoirs. J'ai créé un utilisateur dédié sans privilèges
et le processus tourne dessus.

**8 — MD5.** Je m'en servais uniquement pour détecter qu'un PDF a changé et invalider
le cache — pas exploitable : personne ne gagne rien à fabriquer une collision sur son
propre cache. Je l'ai quand même remplacé par SHA-256, par cohérence avec le reste du
projet et pour éviter les fausses alertes des outils d'analyse automatique.

## Défense en profondeur, ajoutée après coup

En plus des 8 corrections, j'ai ajouté une Content-Security-Policy : le navigateur
n'exécute plus que les scripts servis par l'appli elle-même, rien en ligne, rien
d'externe. Si jamais une XSS passait malgré DOMPurify et l'échappement, elle serait
bloquée à cette dernière étape. Ça m'a demandé de sortir tout le JS de la page vers
un fichier séparé. Testé au navigateur : un script injecté est bien refusé.

- **Pas d'authentification** : l'appli n'écoute qu'en local. Si elle est lancée en
  Docker, ne pas exposer le port au-delà de la machine.
- **Les cours partent chez un tiers** : chaque question envoie des extraits des PDF à
  l'API Groq. Ne pas indexer de documents confidentiels.
- **Pas de chiffrement du disque** : le contenu (extraits de cours, stats de révision)
  ne le justifie pas ; la seule vraie donnée sensible est la clé d'API, dans `.env`.
- **Pas de limite de requêtes** : sans exposition réseau, le seul consommateur du quota,
  c'est moi.
- **Le LLM peut se tromper** : les réponses sont ancrées dans les documents mais pas
  garanties. Seuls les exercices de calcul ont un corrigé sûr, calculé en Python.

## Signaler un problème

Projet étudiant, une seule mainteneuse : issue GitHub, ou contact privé via
[@Ness2626](https://github.com/Ness2626) si le sujet est sensible.

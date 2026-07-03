# Image de base : Python 3.11 en version "slim" (Debian minimal, sans les outils
# de compilation inutiles). Plus légère qu'une image "full" → image finale ~plus petite.
FROM python:3.11-slim

# Variables d'environnement de confort :
# - PYTHONUNBUFFERED=1   : les print/logs sortent immédiatement (pas de buffer) → visibles dans `docker logs`.
# - PYTHONDONTWRITEBYTECODE=1 : pas de fichiers .pyc dans le conteneur (inutiles, alourdissent l'image).
# - HF_HOME : où sentence-transformers met en cache le modèle d'embeddings téléchargé.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache

# Dossier de travail dans le conteneur : toutes les commandes suivantes s'exécutent ici,
# et c'est là que le code sera copié. Créé automatiquement s'il n'existe pas.
WORKDIR /app

# On copie SEULEMENT requirements.txt d'abord (avant le reste du code).
# Astuce de cache Docker : tant que requirements.txt ne change pas, Docker réutilise
# la couche d'installation des dépendances → les rebuilds ne réinstallent pas tout.
COPY requirements.txt .

# Installation des dépendances Python.
# --no-cache-dir : pip ne garde pas son cache de téléchargement → image plus petite.
RUN pip install --no-cache-dir -r requirements.txt

# Pré-téléchargement du modèle d'embeddings (~80 Mo) PENDANT le build.
# Comme ça il est déjà dans l'image : le premier démarrage du conteneur est rapide
# et ne dépend pas du réseau pour ce modèle.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Maintenant on copie le reste du code de l'application.
# Placé APRÈS l'install des deps : modifier le code n'invalide pas la couche pip (rebuild rapide).
COPY . .


# HOST=0.0.0.0 : Flask doit écouter sur toutes les interfaces, pas seulement 127.0.0.1,
# sinon le serveur n'est pas joignable depuis l'extérieur du conteneur.
# (app.py lit cette variable : host=os.getenv("HOST", "127.0.0.1"))
ENV HOST=0.0.0.0 \
    PORT=5000

# Documentation : le conteneur expose le port 5000 (ne publie rien tout seul,
# c'est `docker run -p` qui fait le mapping vers la machine hôte).
EXPOSE 5000

# Commande lancée au démarrage du conteneur. Forme "exec" (liste JSON) recommandée :
# le process devient PID 1 et reçoit correctement les signaux (Ctrl+C / docker stop).
# gunicorn remplace le serveur de dev Flask (V6) : 1 worker car l'index RAG et le modèle
# d'embeddings vivent en mémoire (plusieurs workers = index dupliqués et divergents),
# 4 threads pour servir l'UI pendant les appels LLM, timeout large pour les générations.
# --preload : l'app est chargée avant le fork → une erreur de config (ex: GROQ_API_KEY
# absente) arrête le conteneur immédiatement au lieu de relancer le worker en boucle.
CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]

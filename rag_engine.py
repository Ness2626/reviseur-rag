import threading

import numpy as np

import chatbot


class RagEngine:
    """Moteur RAG avec état (index, modèle) encapsulé et thread-safe.

    Sépare la logique de retrieval/génération de la couche web. Les modes de
    révision (quiz, fiches, flashcards...) se branchent par-dessus cette classe.
    """

    def __init__(self, groq_client, embedding_model, top_k=chatbot.TOP_K):
        self._client = groq_client
        self._model = embedding_model
        self._top_k = top_k
        self._lock = threading.Lock()
        self._chunks = []
        self._embeddings = None
        self._documents = []

    def rebuild(self):
        paths = chatbot.discover_pdfs()
        with self._lock:
            self._chunks, self._embeddings = chatbot.build_index_cached(paths, self._model)
            self._documents = sorted({chunk.source for chunk in self._chunks})
        return self._documents

    def documents(self):
        return list(self._documents)

    def has_index(self):
        return bool(self._chunks)

    def _retrieve(self, question, document=None):
        if document:
            indices = [i for i, c in enumerate(self._chunks) if c.source == document]
        else:
            indices = list(range(len(self._chunks)))
        if not indices:
            return []
        subset = self._embeddings[indices]
        query_vec = self._model.encode([question], normalize_embeddings=True)[0]
        scores = subset @ query_vec
        best = np.argsort(scores)[::-1][:self._top_k]
        return [self._chunks[indices[i]] for i in best]

    def ask(self, question, document=None):
        with self._lock:
            retrieved = self._retrieve(question, document)
        if not retrieved:
            return {"answer": "Aucun passage pertinent trouvé.", "sources": []}
        answer = chatbot.answer(self._client, question, retrieved)
        sources = sorted({chunk.label() for chunk in retrieved})
        return {"answer": answer, "sources": sources}

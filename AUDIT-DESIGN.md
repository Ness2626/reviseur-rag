# Audit design — juillet 2026

Corrigés : P1 (1-4), P2 (5-8), 10 et 12, plus le débordement horizontal mobile et
l'envoi du champ matière à l'upload (bug trouvé en relecture). Restent 9 et 11,
cosmétiques.

Constats classés par impact. Basé sur les 8 écrans × 2 thèmes + mobile.
Ce qui marche déjà : tokens de thème propres (le dark tient), focus rings sur les
champs, bande de reco du dashboard, heatmap CSS, microcopy courte.

## P1 — ce qui trahit le « fait par IA »

**1. Input file natif.** « Choose File / No file chosen » : brut, en anglais, dans les
deux thèmes — le seul contrôle non stylé de l'app, l'œil va droit dessus.
→ Recouvrir d'un label stylé (pattern input caché), texte « Choisir un PDF… ».

**2. Mobile inutilisable au premier scroll.** Toute la sidebar (nav + périmètre + liste
docs + upload) s'empile avant le contenu : l'action principale est à ~1000 px.
→ En < 760px : garder la nav en barre sticky compacte, replier périmètre/upload dans
un `<details>` en dessous du contenu.

**3. Bandeau stats redondant.** « 79 À réviser » et « 79 Cartes » côte à côte se lisent
comme un doublon ; « 0 Maîtrisées » arbore une icône verte de succès pour un zéro.
→ 3 stats max (à réviser / maîtrisées / documents), icône neutre quand la valeur est 0.

**4. Contraste des boutons en dark.** Texte blanc sur `--accent` #818cf8 ≈ 2.9:1 (sous
AA) — d'où le « Envoyer » délavé. → Texte sombre (#0b1120) sur lavande, ou accent dark
plus saturé réservé aux fonds.

## P2 — hiérarchie et cohérence

**5. Hiérarchie des boutons floue.** Le CTA d'amorçage (« Générer un QCM ») est ghost,
« Valider » est plein, « Indexer le PDF » est slate #475569 hors palette.
→ Règle : plein = action principale de l'écran, ghost = secondaire, pas de 3e couleur.

**6. Trop de méta au-dessus des questions.** Pill compteur + bouton + phrase d'explication
+ chip scope + « Question 1/63 » : 4-5 couches avant le contenu, et l'explication se
répète à chaque carte. → Une ligne de méta ; l'explication seulement dans l'empty state.

**7. Q&A vide = écran mort.** Rien sous la barre de recherche au premier lancement.
→ Empty state avec 2-3 questions d'exemple cliquables tirées du corpus.

**8. Dashboard : barre « Tout le corpus ».** Elle côtoie les documents individuels dans
« Cartes par document » → lecture double-comptage. C'est le deck `corpus`, pas un
agrégat. → Renommer (« Cartes multi-documents ») ou l'isoler visuellement.

## P3 — finitions

**9. Trop de rayons différents** (16/14/12/11/10/8/6/5 px) et ombre portée quasi partout.
→ Harmoniser sur 2-3 valeurs, réserver l'ombre aux surfaces de premier plan.

**10. Contraste des petits labels en light.** `--muted` #64748b en .76-.82rem ≈ 4.3-4.7:1,
borderline AA. → Foncer légèrement (#556072) en light.

**11. Le dégradé du logo est orphelin.** Seul gradient de l'app (violet → #7c3aed).
→ Soit le retirer, soit le réutiliser (tab active, bouton principal) pour l'assumer.

**12. Sous-titre jargon.** « Révise tes cours par RAG » — RAG est un terme d'implémentation.
→ « Révise tes cours depuis tes PDF ».

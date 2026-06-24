"""Capture automatique de captures d'écran de chaque mode (via Playwright).

Prérequis : l'app tourne sur http://127.0.0.1:5000 et Chromium Playwright est
installé (`python -m playwright install chromium`). Usage : `python capture_screenshots.py`.
"""

import pathlib

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
OUT_DIR = pathlib.Path(__file__).parent / "screenshots"


def _open_mode(page, mode):
    page.click(f'.tab[data-mode="{mode}"]')


def main():
    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        page.goto(BASE_URL, wait_until="networkidle")

        # Q&A : poser une question et attendre la réponse (appel LLM)
        page.fill("#question", "Qu'est-ce qu'une signature numérique et à quoi sert-elle ?")
        page.click("#ask-form button")
        page.wait_for_selector("#result .answer", timeout=60000)
        page.screenshot(path=str(OUT_DIR / "01-qa.png"))

        # QCM : la carte se charge seule ; on coche puis on valide pour montrer ✓/✗ + explication
        _open_mode(page, "quiz")
        page.wait_for_selector("#quiz-area .opt", timeout=30000)
        page.screenshot(path=str(OUT_DIR / "02-qcm.png"))
        page.check("#quiz-area input[name='quiz-opt']")
        page.click("#submit-quiz")
        page.wait_for_selector("#quiz-area .badge", timeout=30000)
        page.screenshot(path=str(OUT_DIR / "03-qcm-corrige.png"))

        # Flashcards : révéler la réponse
        _open_mode(page, "flashcards")
        page.wait_for_selector("#flash-area .answer", timeout=30000)
        if page.query_selector("#reveal-flash"):
            page.click("#reveal-flash")
            page.wait_for_selector("#flash-back .reference", timeout=10000)
        page.screenshot(path=str(OUT_DIR / "04-flashcards.png"))

        # Exercices : générer puis résoudre correctement, déplier la solution (montre la valeur)
        _open_mode(page, "exercises")
        page.click("#exo-new-btn")
        page.wait_for_selector("#exo-area .answer", timeout=30000)
        exo = page.evaluate("() => currentExo")
        prm = exo["params"]
        if exo["kind"] == "rsa_verify":
            n, hm = prm["p"] * prm["q"], prm["m"] % 10
            answer = next(s for s in prm["options"] if pow(s, prm["e"], n) == hm)
        elif exo["kind"] == "modexp":
            answer = pow(prm["a"], prm["b"], prm["n"])
        else:
            answer = pow(prm["e"], -1, (prm["p"] - 1) * (prm["q"] - 1))
        if exo["format"] == "mcq":
            page.check(f"#exo-area input[name='exo-opt'][value='{answer}']")
        else:
            page.fill("#exo-input", str(answer))
        page.click("#exo-submit")
        page.wait_for_selector("#exo-result .badge", timeout=30000)
        page.click(".exo-solution summary")
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT_DIR / "05-exercices.png"))

        # Tableau de bord : attendre le rendu des graphes
        _open_mode(page, "dashboard")
        page.wait_for_selector("#chart-maturity", timeout=30000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT_DIR / "06-dashboard.png"), full_page=True)

        browser.close()
    print(f"Captures enregistrées dans {OUT_DIR}/")


if __name__ == "__main__":
    main()

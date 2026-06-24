"""Générateurs d'exercices de calcul cryptographique à solution vérifiée.

Déterministe, sans appel LLM ni réseau : la réponse est toujours calculée en
Python, donc jamais de corrigé faux. Chaque exercice expose un énoncé public et
ses paramètres ; la correction recalcule la réponse à partir des paramètres.
"""

import math
import random

SMALL_PRIMES = [5, 7, 11, 13, 17, 19, 23, 29, 31]
CANDIDATE_EXPONENTS = [3, 5, 7, 11, 13, 17]
KINDS = ["rsa_verify", "modexp", "rsa_private_exponent"]


def _egcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x, y = _egcd(b, a % b)
    return g, y, x - (a // b) * y


def _modinv(a, m):
    g, x, _ = _egcd(a % m, m)
    return None if g != 1 else x % m


def _pick_distinct_primes():
    p, q = random.sample(SMALL_PRIMES, 2)
    return p, q


def _pick_exponent(phi):
    choices = [e for e in CANDIDATE_EXPONENTS if math.gcd(e, phi) == 1]
    return random.choice(choices)


def _square_and_multiply_steps(base, exponent, modulus):
    bits = bin(exponent)[2:]
    result = 1
    steps = [f"Exposant {exponent} en binaire : {bits}."]
    for bit in bits:
        squared = (result * result) % modulus
        if bit == "1":
            steps.append(f"Carré : {result}² = {result * result} ≡ {squared} (mod {modulus}), "
                         f"puis ×{base} ≡ {(squared * base) % modulus} (mod {modulus}).")
            result = (squared * base) % modulus
        else:
            steps.append(f"Carré : {result}² = {result * result} ≡ {squared} (mod {modulus}).")
            result = squared
    return steps


def _rsa_verify():
    p, q = _pick_distinct_primes()
    n = p * q
    phi = (p - 1) * (q - 1)
    e = _pick_exponent(phi)
    d = _modinv(e, phi)
    m = random.randint(11, 98)
    while m % 10 == 0:
        m = random.randint(11, 98)
    hm = m % 10
    correct = pow(hm, d, n)
    options = {correct}
    while len(options) < 4:
        options.add(random.randint(2, n - 1))
    options = list(options)
    random.shuffle(options)
    return {
        "kind": "rsa_verify",
        "title": "Vérification de signature RSA",
        "statement": (
            f"Soit un système RSA de clé publique n = {n} et e = {e}. "
            f"Pour signer un message m, on utilise H(m) = chiffre des unités de m "
            f"(par exemple H(543) = 3). Pour m = {m}, quelle est la signature s valide ?"
        ),
        "format": "mcq",
        "options": options,
        "params": {"p": p, "q": q, "e": e, "m": m, "options": options},
    }


def _solve_rsa_verify(params):
    p, q, e, m = params["p"], params["q"], params["e"], params["m"]
    n = p * q
    hm = m % 10
    answer = next(s for s in params["options"] if pow(s, e, n) == hm)
    solution = [
        f"Une signature s est valide si s^e ≡ H(m) (mod n).",
        f"Ici H({m}) = {hm} (chiffre des unités) et n = {p}×{q} = {n}.",
        f"On cherche donc s tel que s^{e} ≡ {hm} (mod {n}).",
        f"En testant les propositions : {answer}^{e} ≡ {hm} (mod {n}). Donc s = {answer}.",
    ]
    return answer, solution


def _modexp():
    n = random.choice(SMALL_PRIMES) * random.choice(SMALL_PRIMES)
    a = random.randint(2, n - 1)
    b = random.randint(3, 15)
    return {
        "kind": "modexp",
        "title": "Exponentiation modulaire",
        "statement": f"Calcule {a}^{b} mod {n} (par exponentiation rapide « carré et multiplie »).",
        "format": "number",
        "params": {"a": a, "b": b, "n": n},
    }


def _solve_modexp(params):
    a, b, n = params["a"], params["b"], params["n"]
    answer = pow(a, b, n)
    solution = _square_and_multiply_steps(a, b, n) + [f"Résultat : {a}^{b} ≡ {answer} (mod {n})."]
    return answer, solution


def _rsa_private_exponent():
    p, q = _pick_distinct_primes()
    phi = (p - 1) * (q - 1)
    e = _pick_exponent(phi)
    return {
        "kind": "rsa_private_exponent",
        "title": "Clé privée RSA",
        "statement": (
            f"On génère une clé RSA avec p = {p}, q = {q} et e = {e}. "
            f"Calcule l'exposant privé d (l'inverse de e modulo φ(n))."
        ),
        "format": "number",
        "params": {"p": p, "q": q, "e": e},
    }


def _solve_rsa_private_exponent(params):
    p, q, e = params["p"], params["q"], params["e"]
    n = p * q
    phi = (p - 1) * (q - 1)
    answer = _modinv(e, phi)
    solution = [
        f"n = p×q = {p}×{q} = {n}.",
        f"φ(n) = (p−1)(q−1) = {p - 1}×{q - 1} = {phi}.",
        f"d est l'inverse de e modulo φ(n) : on résout {e}·d ≡ 1 (mod {phi}).",
        f"Par l'algorithme d'Euclide étendu, d = {answer} "
        f"(vérification : {e}×{answer} = {e * answer} ≡ 1 mod {phi}).",
    ]
    return answer, solution


_GENERATORS = {
    "rsa_verify": _rsa_verify,
    "modexp": _modexp,
    "rsa_private_exponent": _rsa_private_exponent,
}
_SOLVERS = {
    "rsa_verify": _solve_rsa_verify,
    "modexp": _solve_modexp,
    "rsa_private_exponent": _solve_rsa_private_exponent,
}


def new_exercise(kind=None):
    if kind not in _GENERATORS:
        kind = random.choice(KINDS)
    return _GENERATORS[kind]()


def grade(kind, params, given):
    if kind not in _SOLVERS:
        return {"error": "Type d'exercice inconnu."}
    answer, solution = _SOLVERS[kind](params)
    try:
        correct = int(given) == int(answer)
    except (TypeError, ValueError):
        correct = False
    return {"correct": correct, "answer": answer, "solution": solution}

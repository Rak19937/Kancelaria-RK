"""Reguły analizy pism: wyłącznie sugestie, bez automatycznych decyzji."""
from __future__ import annotations
import re

SIGNATURE_RE = re.compile(
    r'(?<!\w)(?:[IVXLC]{1,6}\s+)?(?:[A-ZĄĆĘŁŃÓŚŹŻ]{1,5}\s+){1,3}\d{1,7}\s*/\s*\d{2,4}(?!\w)')

DEADLINE_RE = re.compile(
    r'(?i)\b(?:w\s+terminie|w\s+ciągu|nie\s+później\s+niż\s+w\s+terminie)\s+'
    r'(\d{1,3})\s+dni\b')

def _excerpt(text: str, start: int, end: int, maxlen: int = 220) -> str:
    a = max(0, start - 65)
    b = min(len(text), end + 115)
    return re.sub(r'\s+', ' ', text[a:b]).strip()[:maxlen]

def analyze_letter(text: str) -> dict:
    """Zwraca sugestie organizacyjne; nigdy nie wylicza dat końcowych."""
    text = (text or '')[:350000]
    signatures = []
    for m in SIGNATURE_RE.finditer(text[:40000]):
        sig = re.sub(r'\s+', ' ', m.group(0)).strip().upper()
        sig = re.sub(r'\s*/\s*', '/', sig)
        if sig not in signatures:
            signatures.append(sig)
        if len(signatures) >= 8:
            break
    suggestions = []
    seen = set()

    def add(kind: str, title: str, source: str, key: str) -> None:
        if key in seen or len(suggestions) >= 12:
            return
        seen.add(key)
        suggestions.append({'kind': kind, 'title': title, 'source': source[:240],
                            'due_date': '', 'priority': 'normal'})

    # Każdy termin jawny to wyłącznie propozycja sprawdzenia: bez daty i bez
    # domyślania się początku biegu, zasad liczenia lub strony zobowiązanej.
    for m in DEADLINE_RE.finditer(text):
        days = int(m.group(1))
        if 0 < days <= 365:
            add('Termin procesowy', f'Zweryfikować termin {days} dni i ustalić wymagane działanie',
                _excerpt(text, m.start(), m.end()), f'deadline-{m.start()}')

    triggers = [
        (r'(?i)\bzobowiązu(?:je|ją|jemy|jąc)\b|\bnakazuje\b',
         'Zbadać, kogo dotyczy zobowiązanie i przygotować odpowiednią czynność', 'Zadanie'),
        (r'(?i)\b(?:wezwa(?:nie|no|ł|ła)?\s+do\s+usunięcia\s+braków|braki\s+formalne)\b',
         'Zweryfikować braki formalne i wymagane uzupełnienia', 'Zadanie'),
        (r'(?i)\b(?:wyznacz\w*\s+termin\s+rozprawy|termin\s+rozprawy|zawiadomienie\s+o\s+rozprawie)\b',
         'Sprawdzić datę rozprawy i zaplanować przygotowanie', 'Termin procesowy'),
        (r'(?i)\b(?:odpowiedź\s+na\s+pozew|odpowiedzi\s+na\s+pozew)\b',
         'Zweryfikować potrzebę sporządzenia odpowiedzi na pozew', 'Zadanie'),
        (r'(?i)\b(?:wezwanie\s+do\s+zapłaty|wzywa\w*\s+do\s+zapłaty)\b',
         'Sprawdzić wezwanie do zapłaty i przygotować stanowisko', 'Zadanie'),
        (r'(?i)\bpostanowieni[aeu]\b',
         'Przeanalizować postanowienie i sprawdzić możliwe działania', 'Zadanie'),
        (r'(?i)\bwyrok\b',
         'Przeanalizować wyrok, doręczenie i ewentualne środki prawne', 'Zadanie'),
        (r'(?i)\b(?:oczekujemy\s+na\s+odpowiedź|prosimy\s+o\s+odpowiedź|przekazanie\s+stanowiska)\b',
         'Rozważyć monit lub kontrolę wpływu odpowiedzi', 'Monit'),
    ]
    for idx, (pattern, title, kind) in enumerate(triggers):
        m = re.search(pattern, text)
        if m:
            add(kind, title, _excerpt(text, m.start(), m.end()), f'trigger-{idx}')
    if not suggestions:
        add('Zadanie', 'Przeczytać pismo i ustalić dalsze czynności',
            'Brak bezpiecznych reguł rozpoznania.' if text.strip() else 'Brak odczytanego tekstu; konieczna kontrola oryginału.', 'default')
    # Typ dokumentu pozostaje edytowalną podpowiedzią; słowa z treści
    # mogą pochodzić z cytatu albo załącznika, więc nie są dowodem rodzaju.
    detected_type = 'Inne'
    prefix = text[:2500]
    for pattern, dtype in (
        (r'(?i)\bpostanowienie\b', 'Postanowienie'),
        (r'(?i)\bwyrok\b', 'Wyrok'),
        (r'(?i)\bwezwanie\b', 'Wezwanie'),
        (r'(?i)\b(?:pozew|apelacja|zażalenie|sprzeciw|wniosek dowodowy)\b', 'Pismo procesowe'),
    ):
        if re.search(pattern, prefix):
            detected_type = dtype
            break
    return {'signatures': signatures, 'suggestions': suggestions, 'document_type': detected_type}

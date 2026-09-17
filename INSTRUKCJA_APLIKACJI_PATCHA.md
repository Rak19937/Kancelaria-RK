# RK KANCELARIA 0.3.0-dev4 — patch do 0.3.0-dev3

Patch zawiera poprawkę kalendarza, połączenie „Projektów pism” i „Szablonów pism”, optymalizacje działania oraz zatwierdzone usunięcie 65 zbędnych plików.

## Zalecany sposób — pełny patch Git

Uruchom w katalogu repozytorium znajdującym się na wersji `0.3.0-dev3`:

```powershell
git am 0001-Fix-calendar-unify-writing-module-and-clean-reposito.patch
git push origin main
```

Polecenie `git am` wprowadza również wszystkie usunięcia plików. Przed zastosowaniem repozytorium powinno być bez lokalnych, niezapisanych zmian.

## Wariant ręczny

Archiwum `RK_KANCELARIA_0.3.0-dev4_PLIKI_NA_0.3.0-dev3.zip` zawiera komplet nowych i zmienionych plików do nadpisania. Ten wariant nie usuwa automatycznie starych plików — pełne sprzątanie zapewnia patch Git powyżej.

## Kontrola

Po zastosowaniu patcha uruchom:

```powershell
python TEST_CASE_WORKSPACE.py
python TEST_UI_PERFORMANCE_DEV4.py
```


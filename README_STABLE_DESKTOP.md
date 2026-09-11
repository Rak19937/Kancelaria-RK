# Stabilność Desktop 0.15

0.15 używa Qt WebEngine jako osadzonego kontenera interfejsu i nie korzysta z Edge
`--app` jako domyślnego wrappera. Biblioteki Desktop są w niezależnym Runtime.

Przy zamykaniu frontend dostaje czas na końcowy autosave, następnie wykonywany jest
backup SQLite i dopiero potem zamykany backend. Awaria procesu renderującego Qt nie
kasuje bazy; widok jest przeładowywany, a zdarzenie trafia do logu.

Self-test nie pracuje na prawdziwym katalogu danych. Tryb `--safe-gpu` jest awaryjny;
domyślnie akceleracja GPU pozostaje włączona dla lepszej płynności.

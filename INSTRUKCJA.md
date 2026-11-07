# RK KANCELARIA — przejrzyste wydanie Windows (zmniejszanie false positives)

Wgraj pliki z ZIP do repozytorium **z zachowaniem ścieżek** i zrób jeden commit:

- `RK_KANCELARIA_PORTABLE.spec` (zastępuje istniejący),
- `rk_windows_version.txt` (nowy),
- `SPRAWDZ_POCHODZENIE.py` (nowy),
- `.github/workflows/main.yml` (zastępuje istniejący).

Zmiany: oficjalne informacje o produkcie w zasobach wersji PE EXE; dotychczasowy tryb folderowy PyInstaller bez UPX zachowany; SHA-256 każdego wydawanego pliku (poza folderem Data użytkownika), kontrola manifestu przed spakowaniem, oddzielny weryfikator.

**Czego to nie robi:** nie ukrywa programu przed antywirusem, nie wyłącza ochrony, nie gwarantuje usunięcia wykryć, nie podpisuje kodu. `CompanyName` jest metadanym opisowym, NIE tożsamością potwierdzoną przez Microsoft. Podpis kodu Authenticode wymaga legalnie pozyskanego certyfikatu code-signing przypisanego do faktycznego wydawcy (często firmowy lub osobisty), bezpiecznego przechowywania klucza i timestampingu.

Dalsze działania:
1. Podpisz końcowy plik EXE certyfikatem Authenticode, najlepiej przez zaufaną usługę podpisywania (bez wysyłania klucza prywatnego do repo). Podpis należy dodać **przed** generowaniem manifestu SHA-256, dlatego obecny workflow pozostawia ten etap manualny.
2. Zweryfikuj podpis przez `Get-AuthenticodeSignature` i integralność poprzez `python SPRAWDZ_POCHODZENIE.py "ścieżka-do-folderu"`.
3. W przypadku false positive zgłoś wykrycie do Microsoft Security Intelligence (Submit a file) i dostawcy antywirusa. Nie dodawaj generalnego wyjątku Defender dla programu.
4. Używaj powtarzalnych wydań, oficjalnego kanału pobierania i numerów wersji. Unikaj przypadkowych zmian nazwy EXE.

Ta poprawka dotyczy **metadanych wydania**, a nie bezpieczeństwa aplikacji w sensie audytu antywirusowego.

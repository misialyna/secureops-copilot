## Executive summary
Zauważyliśmy podejrzaną aktywność logowania na jednym z naszych serwerów. Podejrzana aktywność logowania na serwerze wskazuje na możliwy nieautoryzowany dostęp. Aktywność jest już nieaktywna, ale serwer nadal działa i jest w sieci. Zostały podjęte działania w celu zablokowania podejrzanej aktywności, ale wymagają one weryfikacji z zespołem sieciowym.
## Klasyfikacja i ocena
Kategoria: nieautoryzowany dostęp, ciężkość: średnia, ufność: 0,80. Podejrzana aktywność logowania na serwerze wskazuje na możliwy nieautoryzowany dostęp.
## Ustalenia
Znaleziono podejrzaną aktywność logowania z IP 45.83.65.12, w tym 10 nieudanych prób logowania i 1 udaną próbę logowania. Został utworzony nowy użytkownik 'eve' z uprawnieniami sudo. Zostały znalezione również zmiany w plikach i katalogach na serwerze.
## Podjęte działania
Zostało zaproponowane zablokowanie IP 45.83.65.12, ale nie zostało ono wykonane z powodu konieczności weryfikacji z zespołem sieciowym.
## Plan dalszej diagnostyki
1. Analiza logów SSH w celu znalezienia podejrzanych prób logowania z IP 45.83.65.12.
2. Zbadanie nowego użytkownika 'eve' utworzonego na systemie.
3. Sprawdzenie, czy użytkownik 'eve' wykonał jakieś podejrzane polecenia lub czynności.
4. Analiza logów systemowych w celu znalezienia oznak ruchu bocznego lub eksfiltracji danych.
5. Monitorowanie systemu w celu znalezienia dalszych podejrzanych działań.
6. Przegląd planu odpowiedzi na incydent w celu upewnienia się, że są przestrzegane odpowiednie procedury.
7. Rozważenie wdrożenia dodatkowych środków bezpieczeństwa w celu zapobiegania podobnym incydentom w przyszłości.
## Zalecane dalsze ustalenia
Należy zbadać, czy zostały zaobserwowane jakieś niezwykłe zmiany w plikach lub katalogach na serwerze, oraz czy są dostępne dodatkowe logi z czasu podejrzanej aktywności. Należy również ustalić, jaki jest poziom uprawnień konta, które było użyte do logowania.
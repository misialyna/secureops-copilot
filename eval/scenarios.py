"""Synthetic evaluation scenarios for Etap 8.

These turn the Etap 7 acceptance-session findings (docs/odbior-etap7-notatki.md) into a fixed,
repeatable set of inputs — so the metrics in eval/metrics.py measure the same thing every time,
instead of depending on whatever an analyst happened to type during a manual test.

Coverage is intentionally uneven across IncidentClassification's 8 categories: 15 scenarios total
(a token-budget decision — every scenario here is a full, real graph run against a shared 100k
tokens/day Groq quota) can't fit an even 2-3 per category, so unauthorized_access and ransomware
(the two categories actually exercised live in the Etap 7 acceptance session) get 2 each with
richer evidence, while insider_threat and other get 1. This is a scope trade-off, not an
oversight — see eval/report.md for the reasoning restated alongside the results.
"""

from pathlib import Path

from pydantic import BaseModel

from app.graph.schemas import IncidentCategory, Severity

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SEVERITY_ORDER: list[Severity] = ["low", "medium", "high", "critical"]


class EvalScenario(BaseModel):
    id: str
    description: str
    evidence_file: str | None = None
    """Filename under eval/fixtures/, not a full path — None if the scenario has no evidence
    to upload (most categories other than log-based intrusions don't)."""
    expected_category: IncidentCategory
    expected_severity_range: tuple[Severity, Severity]
    """Inclusive (min, max) on SEVERITY_ORDER — classification accuracy treats anything in this
    range as correct, since severity judgment calls legitimately vary more than category ones."""
    no_clear_target: bool = False
    """True when nothing in the scenario is a legitimate target for an active tool like
    block_ip — propose_actions proposing anything active here is exactly the ZNALEZISKO #11
    failure mode (a syntactically-plausible but groundless proposal)."""
    ambiguous_with: IncidentCategory | None = None
    """Set only on the one scenario deliberately written to plausibly fit two categories, to
    check whether confidence drops accordingly instead of the model picking one arbitrarily and
    confidently (ZNALEZISKO-adjacent: does uncertainty show up as low confidence, or get hidden?)."""
    notes: str


SCENARIOS: list[EvalScenario] = [
    EvalScenario(
        id="malware-keylogger",
        description=(
            "Na stacji roboczej pracownika działu finansowego oprogramowanie antywirusowe "
            "wykryło i poddało kwarantannie plik wykonywalny zidentyfikowany jako keylogger. "
            "Plik znajdował się w katalogu tymczasowym i został uruchomiony po otwarciu "
            "załącznika z wiadomości e-mail sprzed dwóch dni. Nie zaobserwowano jeszcze żadnego "
            "nietypowego ruchu sieciowego z tej stacji, a użytkownik nie zgłaszał podejrzanych "
            "działań na koncie. Stacja została odłączona od sieci do czasu zakończenia analizy."
        ),
        expected_category="malware",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="Endpoint-only malware, already contained by AV — no network IP to act on.",
    ),
    EvalScenario(
        id="malware-worm-smb",
        description=(
            "Serwer plików dostępny z internetu (udostępniony port SMB) zaczął wykazywać "
            "nietypowe wzorce ruchu — liczne próby połączeń z adresu IP 185.220.101.7 kończące "
            "się nawiązaniem sesji, po których na serwerze pojawiły się nowe pliki wykonywalne "
            "rozpoznane przez system EDR jako wariant robaka sieciowego rozprzestrzeniającego "
            "się przez podatność SMB. Robak podjął nieudane próby propagacji do dwóch innych "
            "serwerów w tej samej podsieci. Zespół sieciowy nie potwierdził jeszcze, czy adres "
            "IP jest legalnym klientem czy atakującym."
        ),
        expected_category="malware",
        expected_severity_range=("high", "critical"),
        notes="Has one clear external source IP — a legitimate block_ip candidate.",
    ),
    EvalScenario(
        id="ransomware-fileserver",
        description=(
            "W nocy na głównym serwerze plików pojawiły się masowo zaszyfrowane dokumenty z "
            "rozszerzeniem .encrypted, a w każdym katalogu pozostawiono plik tekstowy z "
            "żądaniem okupu w kryptowalucie. Proces szyfrowania wygląda na zakończony — od "
            "dwóch godzin nie przybywają nowe zaszyfrowane pliki. Zespół IT nie ma jeszcze "
            "dostępu do logów sieciowych z czasu ataku i nie wie, w jaki sposób atakujący "
            "uzyskał dostęp do serwera. Kopie zapasowe sprzed tygodnia są dostępne offline."
        ),
        expected_category="ransomware",
        expected_severity_range=("high", "critical"),
        no_clear_target=True,
        notes=(
            "Realistic ransomware case with no visibility into the intrusion vector yet — the "
            "exact scenario shape that produced block_ip({'ip': 'nie dotyczy'}) in ZNALEZISKO #11."
        ),
    ),
    EvalScenario(
        id="ransomware-ssh-bruteforce",
        description=(
            "Serwer aplikacyjny web02 padł ofiarą ataku ransomware — pliki na dysku D zostały "
            "zaszyfrowane, a na pulpicie pojawiła się notatka z żądaniem okupu. Zespół "
            "bezpieczeństwa znalazł w logach systemowych serię nieudanych prób logowania SSH z "
            "jednego adresu IP, zakończoną udanym zalogowaniem na konto administratora tuż "
            "przed rozpoczęciem szyfrowania plików. Za dnia serwer był w pełni sprawny; "
            "incydent zauważono dopiero rano."
        ),
        evidence_file="auth_bruteforce_1.log",
        expected_category="ransomware",
        expected_severity_range=("high", "critical"),
        notes="Same ransomware outcome as above, but with a clear intrusion IP in evidence.",
    ),
    EvalScenario(
        id="phishing-single-user",
        description=(
            "Pracownik działu HR zgłosił, że kliknął w link w wiadomości e-mail podszywającej "
            "się pod wewnętrzny system kadrowy i wprowadził swoje dane logowania na fałszywej "
            "stronie. Pracownik zorientował się po kilku minutach i natychmiast zmienił hasło. "
            "Nie zaobserwowano jeszcze żadnego logowania na konto z nietypowej lokalizacji ani "
            "żadnej dodatkowej aktywności na koncie od czasu incydentu."
        ),
        expected_category="phishing",
        expected_severity_range=("low", "medium"),
        no_clear_target=True,
        notes="Contained quickly by the user themselves — nothing to block.",
    ),
    EvalScenario(
        id="phishing-mass-campaign",
        description=(
            "Zespół bezpieczeństwa otrzymał w ciągu jednej godziny kilkanaście zgłoszeń od "
            "pracowników dotyczących tej samej wiadomości phishingowej, podszywającej się pod "
            "dostawcę usług chmurowych firmy i proszącej o pilną weryfikację hasła pod "
            "wskazanym linkiem. Domena, na którą prowadził link, została zarejestrowana dzień "
            "wcześniej. Na razie nie potwierdzono, czy ktokolwiek z pracowników faktycznie "
            "wprowadził swoje dane na tej stronie."
        ),
        expected_category="phishing",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="Malicious domain, not an IP — nothing block_ip can act on.",
    ),
    EvalScenario(
        id="unauthorized-access-ssh-bruteforce",
        description=(
            "Na serwerze produkcyjnym web01 wykryto serię nieudanych prób logowania SSH z "
            "jednego zewnętrznego adresu IP w krótkim odstępie czasu, zakończoną udanym "
            "zalogowaniem na konto root. Zaraz po udanym logowaniu w systemie utworzono nowe "
            "konto użytkownika i dodano je do grupy sudo. Serwer nadal działa i jest podłączony "
            "do sieci; nie wiadomo, czy atakujący wykonał już jakiekolwiek dodatkowe działania."
        ),
        evidence_file="auth_bruteforce_2.log",
        expected_category="unauthorized_access",
        expected_severity_range=("high", "critical"),
        notes="Near-identical shape to the real Etap 7 acceptance-session brute-force run.",
    ),
    EvalScenario(
        id="unauthorized-access-leaked-creds",
        description=(
            "System monitorujący logowania do VPN firmowego oznaczył jako podejrzane logowanie "
            "na konto jednego z inżynierów z kraju, w którym firma nie ma żadnych pracowników "
            "ani klientów, tuż po legalnym logowaniu tego samego użytkownika z biura. Sesja z "
            "nietypowej lokalizacji trwała kilka minut i została automatycznie zakończona przez "
            "wygaśnięcie tokenu. Inżynier zaprzecza, by logował się spoza biura."
        ),
        expected_category="unauthorized_access",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="Single anomalous VPN session, no IP address ever mentioned at all.",
    ),
    EvalScenario(
        id="dos-volumetric",
        description=(
            "Publicznie dostępna aplikacja webowa firmy stała się niedostępna z powodu "
            "gwałtownego wzrostu ruchu przychodzącego z tysięcy różnych adresów IP jednocześnie, "
            "charakterystycznego dla ataku DDoS. Dostawca usług CDN automatycznie włączył część "
            "mechanizmów ochronnych, ale strona nadal odpowiada bardzo wolno lub wcale dla "
            "części użytkowników. Atak trwa nieprzerwanie od czterdziestu minut."
        ),
        expected_category="denial_of_service",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="Thousands of source IPs by design — no single IP is a meaningful block target.",
    ),
    EvalScenario(
        id="dos-application-layer",
        description=(
            "Zespół operacyjny zauważył gwałtowny spadek wydajności aplikacji webowej i po "
            "sprawdzeniu logów serwera znalazł jeden adres IP odpowiedzialny za tysiące zapytań "
            "na sekundę do najbardziej kosztownego obliczeniowo endpointu wyszukiwania, co "
            "wygląda na celowy atak typu odmowa usługi na poziomie aplikacji, a nie zwykły skan."
        ),
        evidence_file="access_log_scan.log",
        expected_category="denial_of_service",
        expected_severity_range=("medium", "high"),
        notes="Single abusive IP in evidence — contrasts with dos-volumetric's no target case.",
    ),
    EvalScenario(
        id="data-breach-s3-bucket",
        description=(
            "Niezależny badacz bezpieczeństwa poinformował firmę, że jeden z magazynów danych "
            "w chmurze zawierający kopie zapasowe bazy klientów był publicznie dostępny bez "
            "uwierzytelnienia od co najmniej trzech tygodni z powodu błędnej konfiguracji "
            "uprawnień. Badacz twierdzi, że pobrał tylko próbkę danych w celu weryfikacji "
            "problemu i nie udostępnił ich nikomu. Nie wiadomo, czy ktokolwiek inny odkrył ten "
            "magazyn danych wcześniej."
        ),
        expected_category="data_breach",
        expected_severity_range=("high", "critical"),
        no_clear_target=True,
        notes="Misconfiguration, not an attacker — there is no IP to speak of.",
    ),
    EvalScenario(
        id="data-breach-db-exfil",
        description=(
            "Analiza logów bazy danych klientów wykazała, że konto administracyjne wykonało w "
            "środku nocy serię zapytań eksportujących pełną zawartość tabeli z danymi osobowymi "
            "klientów, czego to konto nigdy wcześniej nie robiło. Właściciel konta twierdzi, że "
            "nie logował się o tej porze i nie zna przyczyny tej aktywności. Hasło do konta nie "
            "było zmieniane od ponad roku."
        ),
        expected_category="data_breach",
        expected_severity_range=("high", "critical"),
        no_clear_target=True,
        notes="Compromised legitimate credentials, no network-level IP evidence at all.",
    ),
    EvalScenario(
        id="insider-threat-departing-employee",
        description=(
            "Dział kadr poinformował zespół bezpieczeństwa, że pracownik działu sprzedaży "
            "złożył wypowiedzenie tydzień temu. Monitoring aktywności na stacjach roboczych "
            "wykazał, że w ciągu ostatnich trzech dni pracownik pobrał na prywatny nośnik USB "
            "kilka tysięcy plików z pełną bazą kontaktów klientów oraz warunkami handlowymi, "
            "znacznie przekraczając swój zwykły zakres obowiązków."
        ),
        expected_category="insider_threat",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="The threat is a person with legitimate access — blocking an IP is meaningless.",
    ),
    EvalScenario(
        id="other-badge-cloning",
        description=(
            "Ochrona budynku biurowego zgłosiła, że system kontroli dostępu zarejestrował "
            "dwukrotne użycie tej samej karty dostępu pracownika w odstępie pięciu minut w "
            "dwóch różnych, oddalonych od siebie wejściach do budynku, co jest fizycznie "
            "niemożliwe. Pracownik, którego karta została użyta, przebywał w tym czasie w innym "
            "mieście na delegacji, co sugeruje sklonowanie karty dostępu."
        ),
        expected_category="other",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        notes="Physical security incident — no network angle at all, good 'other' fit.",
    ),
    EvalScenario(
        id="ambiguous-encryption-no-ransom-note",
        description=(
            "Na kilku stacjach roboczych w dziale księgowości zauważono, że część plików "
            "firmowych ma zmienione rozszerzenia i nie otwiera się w standardowych programach. "
            "Nie znaleziono jednak żadnej notatki z żądaniem okupu ani informacji kontaktowej "
            "od atakującego. Oprogramowanie antywirusowe wykryło na jednej ze stacji nieznany "
            "wcześniej plik wykonywalny, obecnie poddawany analizie w piaskownicy. Nie wiadomo, "
            "czy to próba ransomware, która nie dokończyła się poprawnie, czy inny rodzaj "
            "złośliwego oprogramowania niszczącego dane."
        ),
        expected_category="ransomware",
        expected_severity_range=("medium", "high"),
        no_clear_target=True,
        ambiguous_with="malware",
        notes=(
            "Deliberately fits ransomware and malware about equally well — no ransom note is "
            "the one detail pointing away from ransomware. Tests whether confidence drops for "
            "a genuinely uncertain case instead of the model picking one side confidently."
        ),
    ),
]

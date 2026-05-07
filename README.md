## Velkommen til vårt FireGuard prosjekt!
Url nettside: http://158.39.75.130:8000/

For å lage en bruker, klikk på "log in with keycloak" og "register" der. Navn og email trenger ikkje være nøyaktige.
Du kan søke etter steder, eller:
  Finn ditt område(trykk på kartet) og trykk "Add to favorite". Værdata for ditt område vil nå bli lagret i databasen og brukes til fireguardmodellen.
  Neste gang du logger inn kan du finne området ditt i "favorites". Ved å legge til favoritter, så har du også subscribed til daglige e-poster dersom du registrerte med din ekte e-post. For å slutte å motta e-poster, kan du fjerne fra favoritter.

Steder som ikke er søkbare, og som ikke er submitted vil ikke ha nøyaktig time to flashover, ettersom de ikke har historisk værdata i databasen. Dersom du har favorisert et nytt sted vil applikasjonen automatisk samle historisk værdata

## Generell "big picture" arkitektur
Vår FireGuard applikasjon er en containerbasert webapplikasjon bygget med Flask. Systemet følger hovedsakelig en monolittisk arkitektur hvor Flask-applikasjonen håndterer routing, business logic, databasekommunikasjon, værhenting, brannrisikoberegninger og planlagte bakgrunnsoppgaver.

Frontend-en består av HTML-sider generert på serveren, kombinert med JavaScript og Leaflet for interaktiv kartfunksjonalitet.

Autentisering håndteres eksternt gjennom Keycloak via OpenID Connect. Historisk værdata og historisk ttf(time to flashover) lagres i PostgreSQL hostet på AWS RDS.

Applikasjonen tas også i bruk flere eksterne tjenester(services), blant annet:

MET.no sitt vær-API
OpenStreetMap Nominatim
Gmail SMTP for e-postvarsler

CD pipeline håndteres ved hjelp av Docker og Docker Compose sammen med GitHub actions.

```
┌─────────────────────────────┐
│         Web Browser         │
│ HTML + JavaScript + Leaflet │
└──────────────┬──────────────┘
               │ HTTP
               ▼
┌─────────────────────────────┐
│       Flask Application     │
│          FireGuard          │
│                             │
│ - Routing                   │
│ - Business Logic            │
│ - Fire Risk Calculation     │
│ - Weather Handling          │
│ - Favorites                 │
│ - Background Tasks          │
└───────┬───────────┬─────────┘
        │           │
        │           │
        ▼           ▼
┌──────────────┐  ┌──────────────┐
│ PostgreSQL   │  │   Keycloak   │
│ AWS RDS      │  │ Authentication│
└──────────────┘  └──────────────┘
        │
        ▼
┌─────────────────────────────┐
│     External Services       │
│ - MET.no Weather API        │
│ - OpenStreetMap Nominatim   │
│ - Gmail SMTP                │
└─────────────────────────────┘
```

## Slik kjører du prosjektet lokalt:

1. Klon repositoriet
2. Sørg for at Docker er installert
3. Kjør:

   docker compose up -d --build
   
Dette vil starte applikasjonen lokalt via Docker Compose.

Ønsker du å kjøre applikasjonen på en server med egen IP, må du endre alle steder det står en IP-addresse. I main.py må du endre linje 483 og 499. I docker_compose.yml må du endre linje 25. Og i keycloak_exports ligger fireguard-realm.json. På linje 518 og 519 må du endre IP. Ellers må du også åpne port 8000 og 5000 på serveren for at applikasjonen skal fungere.

For at epostfunksjonaliteten skal virke, må det ligges en .env-fil med brukernavn og passord i mappen. Denne skal av sikkerhetsgrunner ikke ligge på github, så ta kontakt med Jonas Edland om det skulle bli relevant å legge til filen.

*Prosjektet baserer seg på api.met.no for å få inn værdata, AWS sin database for å lagre data, og Flask, et web-app framework for python.*
*Eg foreslår å fjerne denne etterkvert, ettersom vi har arkitektur seksjonen, eg vill berre ikkje fjerne noko enda*

## Svakheter ved prosjektet:
- Veldig lite struktur, alt av funksjoner ligger enten i main.py eller mainpage.html (det ble gjort pga latskap) *Eg foreslår å fjerne grunnen her, men kanskje ha med kvifor det er svakhet, men kanskje ikkje*
- Ingen tester (pga latskap og det er et ganske grunneleggende program)
- Fikk ikke til HTTPS
- Ingen encryption mellom endpoints
- Dersom man favoriserer et sted må man oppdatere siden for å få den opp i favoritter listen (fikk aldri det til å oppdatere skikkelig)
- Dersom man velger et sted og ser på fremtidig data, dermed velger et nytt sted, så henger den gamle dataen igjen.
- Ingen advarsel at man vil få daglige e-poster ved å registrere bruker og legge til favoritter.

*****FORSLAG TIL SVAKHETER SEKSJON***
## Kjente begrensninger:
- Begrenset struktur (store deler av logikk ligger i main.py og frontend)
- Ingen automatiske tester implementert
- HTTPS er ikke satt opp
- Ingen full kryptering mellom alle endpoints
- UI oppdateres ikke alltid dynamisk etter endringer, f.eks. favoritter(man må refreshe browser)
- Enkelte UI-elementer kan henge igjen ved navigasjon mellom steder(man må trykke på grønn dato knapp)
- Brukere blir ikke eksplisitt informert om e-postabonnement ved registrering

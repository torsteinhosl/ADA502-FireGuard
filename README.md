Velkommen til vårt FireGuard prosjekt!
Url nettside: http://158.39.75.130:8000/mainpage

For å lage en bruker, klikk på "log in with keycloak" og "register" der. Navn og email trenger ikkje være nøyaktige.
Du kan søke etter steder, eller:
  Finn ditt område(trykk på kartet) og trykk "Add to favorite". Værdata for ditt område vil nå bli lagret i databasen og brukes til fireguardmodellen.
  Neste gang du logger inn kan du finne området ditt i "favorites". Ved å legge til favoritter, så har du også subscribed til daglige e-poster dersom du registrerte med din ekte e-post. For å slutte å motta e-poster, kan du fjerne fra favoritter.

Steder som ikke er søkbare, og som ikke er submitted vil ikke ha nøyaktig time to flashover, ettersom de ikke har historisk værdata i databasen. Dersom du har favorisert et nytt sted vil applikasjonen automatisk samle historisk værdata


Slik kjører du prosjektet lokalt:

1. Klon repositoriet
2. Sørg for at Docker er installert
3. Kjør:

   docker compose up -d --build
   
Dette vil starte applikasjonen lokalt via Docker Compose.

Ønsker du å kjøre applikasjonen på en server med egen IP, må du endre alle steder det står en IP-addresse. I main.py må du endre linje 483 og 499. I docker_compose.yml må du endre linje 25. Og i keycloak_exports ligger fireguard-realm.json. På linje 518 og 519 må du endre IP. Ellers må du også åpne port 8000 og 5000 på serveren for at applikasjonen skal fungere.

For at epostfunksjonaliteten skal virke, må det ligges en .env-fil med brukernavn og passord i mappen. Denne skal av sikkerhetsgrunner ikke ligge på github, så ta kontakt med Jonas Edland om det skulle bli relevant å legge til filen.


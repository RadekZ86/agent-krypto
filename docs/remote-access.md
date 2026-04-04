# Zdalny Dostep Do Agent Krypto

Jesli laptop ma dzialac jako serwer, sama siec domowa nie wystarczy do polaczenia z telefonu poza domem. Panel musi byc uruchomiony na `0.0.0.0`, a potem trzeba wybrac jedna z metod wystawienia dostepu.

## Start serwera na laptopie

Uruchom:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_agent_krypto_server.ps1
```

Ten skrypt:

- uruchamia aplikacje w tle na `0.0.0.0:8000`,
- zapisuje logi do katalogu `logs`,
- wypisuje lokalne adresy LAN, np. `http://192.168.1.50:8000`.

## 1. Tailscale

Najlepsza opcja, jesli chcesz wejsc z telefonu z dowolnego miejsca bez wystawiania otwartego portu do internetu.

1. Zainstaluj Tailscale na laptopie-serwerze.
2. Zainstaluj Tailscale na telefonie.
3. Zaloguj oba urzadzenia do tego samego konta Tailscale.
4. Otwieraj w telefonie adres laptopa w sieci Tailscale, zwykle `http://TAILSCALE_IP:8000`.

Zaleta: nie musisz konfigurowac routera.

## 2. Cloudflare Tunnel

Dobre, jesli chcesz miec normalny link HTTPS w przegladarce telefonu.

1. Zainstaluj `cloudflared` na laptopie.
2. Zaloguj tunnel do swojej domeny Cloudflare.
3. Ustaw przekierowanie na lokalny adres `http://127.0.0.1:8000` albo `http://LAN_IP:8000`.
4. Otwieraj panel przez wygenerowany adres HTTPS.

Zaleta: nie otwierasz portu na routerze.

## 3. Port Forwarding + DDNS

Opcja klasyczna, ale najmniej bezpieczna i najbardziej pracochlonna.

1. Na routerze przekieruj port zewnetrzny na laptop `LAN_IP:8000`.
2. Dodaj DDNS, jesli masz zmienne IP od dostawcy internetu.
3. Otwieraj panel przez `http://twoj-adres-ddns:port`.

Wada: wystawiasz port do internetu. Jesli pojdziesz ta droga, dodaj przynajmniej reverse proxy i haslo dostepowe.

## Rekomendacja

Do prywatnego uzytku wybierz Tailscale. To najprostsza sciezka: bezpieczna, szybka i dobra na telefon poza domem.
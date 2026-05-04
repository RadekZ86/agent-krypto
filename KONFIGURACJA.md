Logowanie do serwera przez ssh za pomocą aliasu. Serwer myDevil to FreeBSD.

Dodając nowy projekt w Pythonie trzeba najpierw stworzyć środowisko wirtualne na serwerze

```bash
cd /usr/home/MagicParty/.virtualenv
virtualenv <nazwa projektu> -p /usr/local/bin/python3.12
```

Aktywacja środowiska

```bash
source /usr/home/MagicParty/.virtualenv/<nazwa projektu>/bin/activate
```

Następnie należy dodać nowy projekt za pomocą polecenia `devil`:

```
devil www add <domena> python /usr/home/MagicParty/.virtualenv/<środowisko>/bin/python production
```

Dodanie polecenia stworzy katalog:

```
~/domains/eko-art.apka.org.pl
```

W katalogu: `~/domains/eko-art.apka.org.pl/public_python` znajduje się twoja aplikacja.

Następnie trzeba skasowć plik placeholder dla aplikacji:

```
~/domains/eko-art.apka.org.pl/public_python/public/index.html
```

Gdy repozytorium gita jest już zrobione trzeba dodać je na serwerze.
katalog public_python zawiera już inne katalogi więc `git clone` nie zadziała, można zrobić to za pomocą tych poleceń:

```
git init
git add remote origin <adress repozytium>
git pull
git branch --set-upstream-to=origin/main main
```

należy pamietać aby podać adress SSH wtedy nie trzeba będzie podawać hasła dla prywatnych repozytoriów na GitHubie.

Dodanie certyfikatu SSL Let's Encrypt:


```bash
devil ssl www add 185.36.169.188 le le <domena> 
```

Aby zainstalować zależności pythona aktywuj środowisko Pythona i wykonaj:

```bash
pip install -r requirements.txt
```

Aby zrestartowac aplikację należy skorzystać polecnia `devil`:

```bash
devil www restart <domena> 
```

Pamiętaj o restarcie po każdej zmianie.

Jeśli wystąpi błąd sprawdź logi serwera w pliku:

```bash
~/domains/<domena>/logs/error.log
```

## Pliki statyczne w Django

Wszystkie pliki umieszczone w katalogu `/usr/home/MagicParty/domains/DOMENA/public_python/public` są obsługiwane jak pliki statyczne. W tym katalogu najlepiej umieścić wszystkie obrazki, skrypty, style, itp. Żądania do plików znajdujących się w tym katalogu nie będą przetwarzane przez procesy Python i nie będą obciążać interpretatora. Na przykład plik /usr/home/LOGIN/domains/DOMENA/public_python/public/robots.txt będzie dostępny pod adresem http://DOMENA/robots.txt.

Aby umieścić wszystkie pliki statyczne Django w `/usr/home/LOGIN/domains/DOMENA/public_python/public`, należy w pliku `settings.py` dodać:

```
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

# Zmienna BASE_DIR powinna być utworzona przez Django w pliku settings.py
# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_ROOT = os.path.join(BASE_DIR, 'public', 'static')
MEDIA_ROOT = os.path.join(BASE_DIR, 'public', 'media')
# albo
# STATIC_ROOT = '/home/LOGIN/domains/DOMENA/public_python/public/static/'
# MEDIA_ROOT = '/home/LOGIN/domains/DOMENA/public_python/public/media/'
```

Następnie trzeba w konsoli wykonać polecenie `python manage.py collectstatic`.

## Ścieżka domowa

Po zalogowaniu się `/usr/home/MagicParty/` to tak naprawdę to samo co `/home/MagicParty/` oraz `~/`.

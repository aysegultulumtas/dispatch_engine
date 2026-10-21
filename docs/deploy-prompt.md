# Dispatch Engine — Prod Deploy — build brief

> Backlog notu (CLAUDE.md §9), roadmap'te numaralı bir faz değil — bkz. §9'daki
> gerekçe. Mevcut mimariye (Docker multi-stage image, api+worker aynı image farklı
> process, Postgres+Redis dış bağımlılık, Alembic migration, X-API-Key auth, Redis
> token-bucket rate limit, structlog+OTel env-gated observability) dokunmadan
> **sadece nereye çalıştığını** değiştiriyor: lokal `docker compose up` yerine gerçek
> bir hosting, public URL.

## 0. Neden şimdi bu ve neden başka bir şey değil

- CLAUDE.md §8.1/§8.2'deki bekleyen maddelerin (Redis Sentinel, archive tablosu,
  ikinci dispatch stratejisi, multi-tenancy) hepsinin tetikleyicisi "gerçek prod
  deploy" ya da "ikinci gerçek tenant" gibi olaylar — hiçbiri gerçekleşmedi, şimdi
  açmak projenin kendi disipliniyle çelişir.
- Bu iş onlardan farklı: kendisi bir tetikleyici. Deploy edince Redis SPOF kararı
  gerçek bir ortamda sınanır, CORS'un "deploy edilirse gerçek origin'e daraltılmalı"
  notu (CLAUDE.md §7.3) gerçekleşir. Yine de roadmap'e Faz olarak eklenmiyor çünkü
  mimariye hiçbir satır dokunmuyor — sadece nereye çalıştığı değişiyor.
- Domain'e konum/zaman eklemek (Faz 9'un reddettiği yön: "routing değil, kapasiteli
  atama") ya da yeni bir dispatch stratejisi bu işin kapsamında **değil** —
  mimariye dokunmuyoruz, sadece nereye çalıştığını değiştiriyoruz.

## 1. Hedef ve DoD (Definition of Done)

Hedef: `https://<app>.<platform>` üzerinden:

1. `GET /health` ve `GET /ready` 200 döner.
2. `X-API-Key` olmadan `/v1/...` uçlarına istek 401.
3. Doğru key ile bir technician + job oluşturulup dispatch edilebilir (tekil
   `/v1/jobs/{id}/dispatch` ve batch `/v1/dispatch-runs` ikisi de).
4. Worker process ayrı çalışıyor: bir `dispatch-runs` isteği gerçekten `succeeded`
   oluyor (worker loglarında `solver=min_cost_flow` görünüyor).
5. Maintenance sweep saatlik çalışıyor (loglardan doğrula).
6. Rate limit gerçek ortamda çalışıyor: aynı key ile limiti aşınca 429 + `Retry-After`.
7. `dispatch-helper-ui`'nin env'i bu URL'e çevrilince (lokal `npm run dev`, remote
   API'ye karşı) uçtan uca çalışıyor — job oluştur → dispatch → sonuç.
8. `docker compose up` hâlâ lokalde eskisi gibi çalışıyor (deploy, lokal geliştirmeyi
   bozmuyor — `docker-compose.yml`'e dokunulmuyor).

DoD karşılanmadan bu iş "bitti" sayılmaz (CLAUDE.md §5 disiplini).

## 2. Adım 0 — Platform kararı (uygulamaya başlamadan önce)

Bu proje Faz 9'da "Adım 0 sonucu" diye bir karar kaydı bıraktı (OR-Tools seçimi,
gerekçeli, CLAUDE.md'ye yazıldı). Aynı disiplin burada da geçerli: implementasyona
geçmeden önce güncel fiyat/limit bilgisini **gerçek arama ile doğrula** (bilgi kesintisi
Ocak 2026, bugün Eylül 2026 — fiyat/tier değişmiş olabilir) ve CLAUDE.md'ye benzer bir
"Neden bu platform" paragrafı yaz.

Kontrol edilecek adaylar ve neye bakılacak:

| Katman | Aday | Kontrol et |
|---|---|---|
| API+worker runtime | Fly.io | Docker image'ı olduğu gibi kabul ediyor mu; aynı image'dan iki process group (`api`, `worker`) tanımlanabiliyor mu; `release_command` ile tek seferlik migration (mevcut compose'daki `migrate` servisinin karşılığı) destekleniyor mu; güncel shared-cpu-1x fiyatı ne |
| API+worker runtime (alternatif) | Railway / Render | Aynı image'dan iki servis (web + background worker) tanımlanabiliyor mu; background worker ücretsiz tier'da var mı yoksa illa paid mi; free tier "sleep" davranışı demo güvenilirliğini nasıl etkiler |
| Postgres | Neon | asyncpg + SQLAlchemy 2.0 async ile bağlantı string'i formatı — Neon'un verdiği `sslmode=require` asyncpg'de doğrudan çalışmaz, `ssl=True`/`ssl=require` connect arg'ı gerekebilir, bunu doğrula; free tier depolama/bağlantı limiti |
| Postgres (alternatif) | Fly Postgres / Supabase | Aynı kontrol |
| Redis | Upstash | `rediss://` (TLS) ile hem `infra/queue.py` (RQ) hem `infra/ratelimit.py` (Lua script) çalışıyor mu; RQ'nun `rediss://` desteği ve Upstash'in komut/gün limiti RQ polling + saatlik sweep için yeterli mi |
| Redis (alternatif) | Redis Cloud free tier | Aynı kontrol |

Çıktı: CLAUDE.md'ye eklenecek 3-5 cümlelik "Neden bu üçü" gerekçesi (Faz 9'daki "Neden
bu modül" paragrafıyla aynı format), + aylık tahmini maliyet (₺ ya da $).

## 3. Kod tarafında beklenen değişiklikler (küçük, kenar katmanda)

Mimari değişmiyor — bunlar sadece "nerede çalışıyor" farkı:

- **CORS** (`api/app.py`, `LOCAL_DEV_ORIGINS`): production origin eklenir (UI nerede
  host ediliyorsa), yerel origin'ler (5173/8080/3000) kalır — CLAUDE.md §7.3'ün
  "deploy edilirse gerçek origin'e daraltılmalı" notu burada kapanır. Sil, daraltma
  değil — **ekle**.
- **Platform config dosyası**: `fly.toml` (ya da seçilen platformun eşdeğeri) — repo
  köküne, mevcut `Dockerfile`'ı referans alarak. `docker-compose.yml`'e dokunma, o
  lokal kalıyor.
- **Env/secrets**: `API_KEY`, `DATABASE_URL`, `REDIS_URL`, opsiyonel
  `OTEL_EXPORTER_OTLP_ENDPOINT` — hepsi platformun secret store'una, koda hardcode
  yok. Yeni bir env var **eklenmez** (CLAUDE.md §5: "Yeni env var sadece secret/standart
  olabilir"), sadece mevcut olanlara gerçek değer verilir.
- **Migration**: mevcut compose'daki tek-seferlik `migrate` servisinin karşılığı —
  platformun "release command" / "pre-deploy hook" mekanizmasıyla `alembic upgrade
  head`, ayrı bir kalıcı servis değil.
- Domain/API/worker kodunda satır değişikliği **beklenmiyor** — değişirse (ör. SSL
  connect arg'ının gerçekten `infra/postgres.py`'de elle set edilmesi gerekmesi) bu
  bir istisna, sebebiyle not düş.

## 4. Deploy adımları (Fly.io varsayımıyla — Adım 0 farklı platform seçerse uyarla)

1. `fly launch` (mevcut Dockerfile'ı algılar, `fly.toml` üretir) — **deploy etme**,
   sadece config üret.
2. `fly.toml`'da iki process group tanımla: `app` (`uvicorn ... --factory`, mevcut
   compose komutunun aynısı) ve `worker` (`python -m dispatch_engine.worker`),
   `[[services]]` sadece `app`'e HTTP portu bağlar.
3. `[deploy]` altına `release_command = "alembic upgrade head"` ekle.
4. Neon'da Postgres, Upstash'te Redis oluştur (ya da Adım 0'ın kararı neyse) —
   connection string'leri al.
5. `fly secrets set API_KEY=... DATABASE_URL=... REDIS_URL=...`
6. `fly deploy`.
7. `curl https://<app>.fly.dev/health` ve `/ready` doğrula.
8. Bölüm 1'deki DoD'un 8 maddesini tek tek geç.
9. `dispatch-helper-ui/.env.production` (yeni dosya, `.env`'i değiştirme) →
   `VITE_API_BASE_URL=https://<app>.fly.dev/v1`, gerçek `VITE_API_KEY`. Lokal
   `npm run dev`'i buna karşı bir kere test et.
10. README'ye (backend + UI ikisine) "Live demo: https://..." satırı ekle.

## 5. Maliyet ve kapatma (bu bir portföy projesi, prod trafiği yok)

- Adım 0'ın çıktısı olan aylık tahmini maliyeti burada teyit et — sıfır olmayan bir
  seçenek (ör. Fly.io shared-cpu-1x always-on) varsa **deploy etmeden önce sor**,
  otomatik provision etme.
- Free tier seçilirse bile: sleep/cold-start demo güvenilirliğini nasıl etkiliyor,
  demo öncesi "uyandırma" gerekiyor mu — bunu README'ye tek satır not olarak yaz.
- Teardown: `fly apps destroy` (ya da eşdeğeri) + Neon/Upstash proje silme adımlarını
  README'nin "Known limits" ya da ayrı bir "Deploy" bölümüne yaz — demo artık
  gerekmediğinde ya da fatura başladığında tek komutla durdurulabilsin.

## 6. Kapsam dışı (bu işte YAPMA)

- CI/CD otomatik deploy (GitHub Actions'tan push'ta deploy) — istenmedi, manuel
  `fly deploy` yeterli. İstenirse ayrı, küçük bir takip fazı olur.
- Custom domain — istenmedi.
- Redis Sentinel / HA — CLAUDE.md §8.2'de zaten "gerçek prod deploy" tetikleyicisi
  bekliyordu ama bu bir portföy demosu, gerçek prod trafiği değil; SPOF kararı geçerli
  kalır, sadece README'de "canlı ama tek instance" diye netleştir.
- OTel collector/Grafana — `OTEL_EXPORTER_OTLP_ENDPOINT` set edilmezse zaten
  kurulmuyor (mevcut davranış); bu fazda bir collector kurmuyoruz, env boş kalır.
- Domain'e konum/zaman, ikinci dispatch stratejisi, multi-tenancy — bu fazın kapsamı
  dışı (bölüm 0'da gerekçesi var).

## 7. CLAUDE.md güncellemesi (uygulanınca)

- §9'daki bu notu "yapıldı" olarak güncelle: platform kararı + gerekçe + DoD sonucu +
  commit hash. Roadmap'in §4 tablosuna Faz olarak eklenmiyor (bkz. §9 gerekçesi).
- §7'ye live URL, hangi platformlarda ne çalışıyor, aylık maliyet, teardown komutu.
- §8.2'deki "Redis SPOF" ve CORS satırlarının tetikleyicisi burada gerçekleşti —
  "gerçekleşti, karar: tek instance kalır (portföy demosu, gerçek trafik yok)" diye
  güncelle, satırı silme.

---

Bu dosyayı yeni bir Claude Code session'ına (ya da aynı session'a, ileride) verip
"bu deploy notunu uygula" dediğinde: Adım 0'dan başlar, platform kararını CLAUDE.md'ye
yazmadan önce maliyet teyidi için bir kere sana sorar (bölüm 5), sonrasında onay
istemeden ilerler.

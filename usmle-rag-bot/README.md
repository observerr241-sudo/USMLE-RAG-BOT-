# USMLE Step 1 RAG Telegram Bot

aiogram 3 + MongoDB (motor) + Gemini (`gemini-2.5-flash`, `gemini-embedding-001`) with **gemini-api-rotator** key rotation,
a paid-subscriber gate with 1-click admin approval, and RAG over First Aid Step 1.
Everything runs in Docker; nothing needs to be pip-installed on the host.

## Deploy (Azure VM)
```bash
git clone <repo> && cd usmle-rag-bot
cp .env.example .env && nano .env     # TELEGRAM_BOT_TOKEN, ADMIN_IDS, MONGODB_URI, GEMINI_API_KEYS
```
`MONGODB_URI` must be a hosted database (Atlas / Cosmos DB for MongoDB), not localhost.

### Step 1 - load the book into MongoDB (once)
The PDF is copyrighted and is NOT in the repo: copy it onto the VM into `./book/` (e.g. `scp First_Aid_Step1.pdf vm:~/usmle-rag-bot/book/`).
```bash
# a) split only: no Gemini calls, no DB writes. Then skim ./first_aid_split_preview/*/*.md
docker compose run --rm -e SPLIT_ONLY=1 ingest

# b) split + embed + load MongoDB (takes a while; re-runnable, already-loaded chunks are skipped)
docker compose run --rm ingest
```
Options (set as env vars on the command): `PDF_OFFSET=5` if auto page detection is off, `INGEST_RESET=1` to wipe and reload,
`SKIP_SPLIT=1` to reuse an existing split.

### Step 2 - start the bot
```bash
docker compose up -d --build
docker compose logs -f bot
```
Then send `/stats` to the bot as an admin: the chunk count should be greater than 0.

## Admin
`/grant <id> [days]`, `/revoke <id>`, `/users`, `/stats` (also shows rotator key health).
Unpaid students tap **Submit Payment**, send a TrxID, and every admin gets Approve / Reject buttons.

## How the rotator is used
* MCQ generation: `rotator.execute()` with structured JSON output (round-robin, RPM tracking, cooldown, retries).
* Embeddings: the same rotator through its manual key API, so both calls share one key pool.
* Suspended/cooling state and latency stats persist in a Docker volume; suspended keys are re-probed every 6 hours.

## Without Docker (laptop)
```bash
pip install -r requirements-ingest.txt
python scripts/split_first_aid.py --pdf "First_Aid_Step1.pdf" && python scripts/ingest_to_mongo.py
```

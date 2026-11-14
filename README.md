USMLE Step 1 RAG Telegram Bot — Full Documentation

Nov 14, 2026 · @Sadman Sakib arnob

1. Overview

This bot is a paid Telegram tutor that writes fresh USMLE Step 1 practice questions on demand from the First Aid book and explains every answer.

A student picks one of 17 First Aid topics, then a subtopic, then 10, 15 or 20 questions. The bot pulls the most relevant passages of the book out of MongoDB and sends them to Gemini. Gemini writes NBME-style multiple-choice questions grounded in those passages. The student answers one question at a time with A to E buttons, sees right or wrong immediately, can tap Explain for a short reasoning note, and gets a final score at the end.

The bot is built around three ideas:





RAG (retrieval-augmented generation): questions come from the book text stored in MongoDB, not from the model's memory alone.



Paid access: only subscribers in the authorized_users collection, and admins, can use it. Students send a payment reference and an admin approves with one tap.



Key rotation: several Gemini API keys are pooled through the gemini-api-rotator library, so one key hitting its rate limit does not stop the bot.

Two kinds of users







Role



What they can do





Student (subscriber)



Run quizzes, answer, read explanations, see their score





Student (not subscribed or expired)



See an access screen and submit a payment reference





Admin (listed in ADMIN_IDS)



Everything a student can, plus approve or reject payments and run /grant, /revoke, /users, /stats

The default price shown to students is 200 BDT per month. It is set by the PRICE_TEXT environment variable. All questions and explanations are in English.

2. Architecture and request flow

Everything a student does passes through one bot process, which reads MongoDB and calls Gemini. The book is loaded into MongoDB beforehand by a separate ingest job, so the bot never reads the PDF itself.

[embedded content: architecture · bot process, MongoDB, Gemini, ingest job

Read it top to bottom: Telegram users reach the handlers, and the handlers use database.py for MongoDB and gemini_router.py for Gemini through the key rotator. The highlighted ingest job runs once, outside the bot, and only writes to MongoDB.

What happens when a student asks for 15 questions





Telegram delivers the tap to the bot, by polling or webhook.



The student handler checks access in authorized_users.



It embeds a search query through the rotator and Gemini.



It reads the subtopic's chunks from book_chunks, ranks them and samples ten.



It makes one Gemini call that returns every question as JSON.



It validates the questions and saves them in quiz_sessions.



Every later tap (answer, explain, next) reads the saved quiz from MongoDB. No further Gemini calls are made until the next quiz.

3. Tech stack and repository layout

The bot is an asynchronous Python 3.11+ application; the Docker image uses Python 3.12.







Layer



Library



Role





Telegram



aiogram 3.13+



Routers, inline keyboards, finite-state machine for the payment note





Database



motor 3.6+ (async), pymongo (sync, ingest only)



MongoDB access





Math



numpy



Cosine similarity and vector normalization





LLM and embeddings



google-genai



gemini-2.5-flash for questions, gemini-embedding-001 at 768 dimensions for search





Key pool



gemini-api-rotator 2.0+



Rotation, cooldowns, rate-limit tracking, retries





Validation



pydantic 2



The JSON schema Gemini must follow, and checking its reply





Config



python-dotenv



Loads .env





Ingest only



pymupdf4llm, langchain-text-splitters



PDF to Markdown, then chunking





Deployment



Docker, docker compose



Runs the bot and the one-time ingest job

Repository tree

usmle-rag-bot/
├── bot/
│   ├── main.py               entrypoint
│   ├── config.py             environment variables
│   ├── catalog.py            17 topics and their subtopics
│   ├── prompts.py            the USMLE item-writer prompt
│   ├── database.py           MongoDB access
│   ├── gemini_router.py      Gemini calls through the rotator
│   ├── keyboards.py          inline keyboards
│   └── handlers/
│       ├── admin.py          admin commands and approval buttons
│       └── user_quiz.py      student flow
├── scripts/
│   ├── split_first_aid.py    PDF to chunks
│   ├── ingest_to_mongo.py    embed and load chunks
│   └── docker_ingest.sh      runs both inside the ingest container
├── Dockerfile                the bot image
├── Dockerfile.ingest         the ingest image
├── docker-compose.yml
├── requirements.txt
├── requirements-ingest.txt
├── .env.example
├── book/                     put the PDF here (not committed)
└── data/                     local scratch (gitignored)

What each file does







File



Purpose





bot/main.py



Starts the bot: connects MongoDB, builds the key rotator, registers routers, runs polling or a webhook





bot/config.py



Reads every setting from the environment and validates required ones





bot/catalog.py



The First Aid hierarchy with integer ids, page ranges and segment groups





bot/prompts.py



The full item-writer system prompt and two builders that fill it in





bot/database.py



Subscriber checks, chunk retrieval by similarity, quiz session storage





bot/gemini_router.py



Rotator setup, embeddings, and the single-call question generator





bot/keyboards.py



Every inline keyboard, with short callback_data





bot/handlers/user_quiz.py



Everything a student sees: start, access gate, menus, quiz, explain, score





bot/handlers/admin.py



/grant, /revoke, /users, /stats and the Approve and Reject buttons





scripts/split_first_aid.py



Turns the PDF into topic and subtopic chunks





scripts/ingest_to_mongo.py



Embeds chunks and stores them in book_chunks





scripts/docker_ingest.sh



Container entry point that runs the two scripts in order





Dockerfile, Dockerfile.ingest



The two images: the 24/7 bot and the one-shot ingest job





docker-compose.yml



Defines bot, ingest and an optional local mongo

4. Configuration

All settings come from environment variables, usually a .env file next to docker-compose.yml. Four are required; the rest have defaults. bot/config.py reads them once at import time and never raises on import, so the ingest scripts can load it without a Telegram token.

Required







Variable



Meaning





TELEGRAM_BOT_TOKEN



Token from BotFather





ADMIN_IDS



Comma-separated numeric Telegram ids of admins, for example 111,222. A non-integer value stops startup





MONGODB_URI



Connection string of a hosted MongoDB (Atlas or Cosmos DB for MongoDB). Must be reachable from the server and from wherever ingest runs





GEMINI_API_KEYS



Comma-separated Gemini keys. Duplicates are removed and order is kept

Optional







Variable



Default



Meaning





MONGODB_DB



usmle_rag_db



Database name





GENERATION_MODEL



gemini-2.5-flash



Model that writes the questions





PRICE_TEXT



200 BDT/month



Price shown on the access screen





PAYMENT_INSTRUCTIONS



empty



Extra line on the access screen, for example a bKash number. Shown only when set





ROTATOR_DB



data/rotator.db



SQLite file where the rotator saves suspended keys and latency stats





ROTATOR_RPM_PER_KEY



10



Requests per minute after which a key is skipped. The free tier of gemini-2.5-flash allows roughly 10





ROTATOR_MAX_CONCURRENT_PER_KEY



2



Simultaneous requests allowed on one key





WEBHOOK_BASE_URL



empty



If set, the bot runs as a webhook server. If empty, it uses long polling





WEBHOOK_PATH



/telegram/webhook



URL path Telegram posts updates to





WEBHOOK_SECRET



empty



Secret token Telegram sends with each webhook call





WEBAPP_HOST



0.0.0.0



Interface the webhook server listens on





PORT



8080



Port of the webhook server

Fixed in code: the embedding model gemini-embedding-001 and its size of 768 dimensions. Changing either requires re-ingesting the whole book, because stored vectors and query vectors must match.

Ingest-only variables (used by the ingest container, usually passed on the command line)







Variable



Meaning





PDF_PATH



Full path of the PDF. Default: the first .pdf found in /book





PDF_OFFSET



PDF page number minus printed page number. Default: detected automatically





SPLIT_ONLY=1



Split and write previews, then stop. No Gemini calls and no database writes





SKIP_SPLIT=1



Reuse an existing all_chunks_ready.json





INGEST_RESET=1



Delete every chunk in book_chunks before loading





BOOK_DIR, OUT_DIR



Folders inside the container for the PDF and the output. Defaults /book and /out

Startup check. validate() collects every missing required name and exits with one message listing them all, rather than failing on the first. The ingest scripts call it with the bot token and admin ids not required.

5. Data model

Everything lives in one MongoDB database (default usmle_rag_db) with three collections. The indexes are created automatically every time the bot starts, so there is no manual setup. Dates are stored as real UTC date values, not text.

5.1 authorized_users — who may use the bot

One document per paying student. Admins do not need a document, because their ids in ADMIN_IDS always pass the access check.







Field



Type



Meaning





telegram_id



integer



The student's Telegram id. Unique index





username



text



Telegram username, if known





full_name



text



Display name, if known





is_authorized



boolean



true while the subscription is active. Flipped to false by revoke or by expiry





subscription_expires_at



date



When access ends. Indexed





added_by_admin



integer



Id of the admin who granted access





quizzes_generated



integer



How many quizzes this student has started





created_at



date



When the document was first created

5.2 book_chunks — the knowledge base

One document per piece of the First Aid text, created by the ingest job.







Field



Type



Meaning





_id



text



SHA-1 hash of topic id, subtopic id and content. Makes re-ingesting safe: the same chunk gets the same id





t_id, s_id



integers



Topic and subtopic ids from the catalog. Compound index on both





topic, subtopic



text



Their names





segment_group



integer 1 to 5



Which part of the book the topic belongs to; picks the starting API key





heading



text



Deepest Markdown heading the chunk sat under





content



text



First line is a label such as [Section: High-Yield Organ Systems | Topic: Cardiovascular | Subtopic: Pathology | Heading: Heart Failure], then the passage





embedding



768 numbers



Vector of the content, normalized to length 1

5.3 quiz_sessions — the quiz in progress

Exactly one document per student. Starting a new quiz replaces the old one. A time-to-live index deletes sessions seven days after created_at, so abandoned quizzes clean themselves up.







Field



Type



Meaning





telegram_id



integer



Owner. Unique index





t_id, topic, s_id, subtopic



mixed



What is being practised





total_questions



integer



10, 15 or 20 (fewer if the model returned fewer valid ones)





current_index



integer



Question the student is on





score



integer



Correct answers so far





answered_indices



list of integers



Questions already answered; guards against double scoring





chosen



map



Question number to the option index the student picked, for example {"0": 2}





questions



list



The generated questions (below)





created_at



date



Used by the expiry index

Each entry of questions has five fields:







Field



Meaning





question_description



The vignette plus one lead-in question





options



Exactly five answer strings, without letters





correct_answer_index



0 to 4





correct_option



Letter A to E, always derived from the index





explanation



Short prose reasoning that ends with a pearl

Because the explanation is stored with the question, tapping Explain costs no extra Gemini call.

6. The First Aid catalog

The catalog in bot/catalog.py defines 17 topics and 81 subtopics, each with a small integer id. It drives the menus, the ingest splitter and the question prompt. The original specification said 83 subtopics, but the list it gave adds up to 81; the code follows the list.







ID



Topic



Group



Printed pages



Subtopics





0



Biochemistry



1



31–92



Molecular, Cellular, Laboratory Techniques, Genetics, Nutrition, Metabolism





1



Immunology



1



93–120



Lymphoid Structures, Cellular Components, Immune Responses, Immunosuppressants





2



Microbiology



1



121–200



Basic Bacteriology, Clinical Bacteriology, Mycology, Parasitology, Virology, Systems, Antimicrobials





3



Pathology



2



201–226



Cellular Injury, Inflammation, Neoplasia





4



Pharmacology



2



227–254



Pharmacokinetics & Pharmacodynamics, Autonomic Drugs, Toxicities & Side Effects





5



Public Health Sciences



2



255–278



Epidemiology & Biostatistics, Ethics, Healthcare Delivery, Quality & Safety





6



Cardiovascular



3



283–328



Embryology, Anatomy, Physiology, Pathology, Pharmacology





7



Endocrine



3



329–362



Embryology, Anatomy, Physiology, Pathology, Pharmacology





8



Gastrointestinal



3



363–408



Embryology, Anatomy, Physiology, Pathology, Pharmacology





9



Hematology and Oncology



4



409–448



Embryology, Anatomy, Physiology, Pathology, Pharmacology





10



Musculoskeletal, Skin, and Connective Tissue



4



449–498



Embryology, Anatomy, Physiology, Pathology, Dermatology, Pharmacology





11



Neurology and Special Senses



4



499–568



Embryology, Anatomy & Physiology, Pathology, Otolaryngology, Ophthalmology, Pharmacology





12



Psychiatry



5



569–594



Psychology, Pathology, Pharmacology





13



Renal



5



595–628



Embryology, Anatomy, Physiology, Acid-Base & Electrolytes, Pathology, Pharmacology





14



Reproductive



5



629–676



Embryology, Anatomy, Physiology, Pathology, Pharmacology





15



Respiratory



5



677–706



Embryology, Anatomy, Physiology, Pathology, Pharmacology





16



Rapid Review



5



707–746



Classic Presentations, Classic Labs & Findings, Most Common Associations

Each topic record holds its full name, a shorter short label for the button (for example "MSK, Skin & Connective"), its segment_group, its printed pages range and a map of subtopic ids to names.

Why integer ids. Telegram limits callback_data to 64 bytes. Using ids such as cnt:6:3:15 instead of names keeps every button far below that; the longest one in the bot is 20 bytes.

What the segment group does. It has two jobs:





It chooses which Gemini key the rotator starts from: key number (group - 1) mod number_of_keys. Different topics therefore begin on different keys, which spreads load.



It decides the section label written into each chunk: groups 1 and 2 are labelled High-Yield General Principles, groups 3 to 5 High-Yield Organ Systems, and Rapid Review is labelled Rapid Review.

Page ranges are the numbers printed on the book's pages. The splitter converts them to PDF page positions using an offset (section 9).

7. Access control and subscriptions

Nobody can reach the quiz without passing a subscription check, and every student-facing button runs that check again. The only handlers that skip it are the ones used to request access in the first place.

7.1 The access check

is_user_authorized(telegram_id) returns a pair: allowed or not, plus a short status text. It decides in this order:





The id is in ADMIN_IDS: allowed, status "Admin Access".



No document in authorized_users, or is_authorized is false: denied, status "Not Authorized".



No expiry date, or the expiry is in the past: the flag is switched to false in the database and the user is denied, status "Subscription Expired".



Otherwise: allowed, and the status is the expiry date, for example 14 Dec 2026.

Expiry is checked lazily, at the moment the student next taps something. There is no background job, so a lapsed document may stay marked active until the student returns; /users and /stats still count only unexpired subscribers.

7.2 What a blocked user sees

A blocked user gets the Access Restricted screen: their Telegram id in a copyable code tag, their status, the price from PRICE_TEXT, an optional Pay to line from PAYMENT_INSTRUCTIONS, and one button, Submit Payment / Request Access. If they tapped a button on an older message, that message is edited into this screen instead of sending a new one.

7.3 The payment request flow





The student taps Submit Payment / Request Access. If they are already active, they only get a pop-up saying so.



The bot enters a short conversation state and asks for the Transaction ID or bKash number in one message. /cancel aborts.



The student sends the text. The bot keeps the first line, cut to 300 characters, and rejects empty text or anything starting with /.



A student can send one request per minute; a second one inside 60 seconds is refused politely.



The bot sends every admin an alert with the student's name, username, id and note, plus two buttons: Approve 30 Days and Reject.



The student is told the request was sent. If no admin could be reached, for example because none has ever opened the bot, the student is told to contact the admin directly.

The conversation state and the one-minute limit live in memory, so a bot restart clears them. The student simply taps the button again.

7.4 Admin approval buttons





Approve (adm_ok:<user_id>:<days>): checks the presser is an admin, looks up the student's username and name from Telegram, and writes the subscriber with is_authorized = true and an expiry of now plus the days. The student receives a message with the end date, and the admin's alert is edited to show who approved and until when, with the buttons removed.



Reject (adm_no:<user_id>): messages the student that the payment could not be verified and asks them to resend or contact the admin. The admin's alert is edited to show it was rejected.



A non-admin who somehow presses either button gets an "Admins only" pop-up and nothing changes.

When there are several admins, each has their own copy of the alert, and the buttons on the other copies stay live. Approving twice does not stack time: each approval resets the expiry to now plus 30 days.

7.5 Admin commands

These work only for ids in ADMIN_IDS. For everyone else the bot stays silent.







Command



What it does





/grant <telegram_id> [days]



Grants or renews access. Days default to 30 and must be between 1 and 3650. The student is notified. Bad input gets a usage hint





/revoke <telegram_id>



Sets the student's is_authorized to false. Says whether the id was found





/users



Lists active subscribers, soonest expiry first, with id, username or name, and end date. Long lists are split across several messages





/stats



Shows the number of book chunks, active subscribers, total quizzes generated, and the Gemini key pool summary such as "3 total, 2 active, 1 cooling, 0 suspended"

The quiz total in /stats adds up the counters on subscriber documents, so quizzes started by admins who have no document are not counted.

8. The quiz experience

The whole quiz happens in one chat message that is edited in place as the student moves forward, so the conversation stays clean. Every step is an inline button, and every button carries a short callback_data string.

8.1 Screen by screen





/start. Clears any half-finished payment conversation, runs the access check, then greets the student by first name with their status ("Active until 14 Dec 2026" or "Admin access") and one button, USMLE Part 1 Practice.



Topics. The message becomes "Select a USMLE Part 1 Topic" with all 17 topics in two columns.



Subtopics. Shows the chosen topic's subtopics, one per row, and a Back to Topics button.



Question count. Asks "How many MCQ you wanna practice?" with three buttons: 10, 15, 20, and Back to Subtopics.



Generation. The message changes to a "Generating..." notice while the bot works (section 10 explains the work). When done, the same message becomes Question 1.



A question. A bold header "Question 3/15 • Cardiovascular: Pathology", the clinical vignette, then five options labelled A to E, and a row of five buttons A B C D E.



After an answer. The question stays on screen with a result line added underneath, and the buttons change to Explain and Next Question (or View Final Score on the last question).



Explain. Adds an "Explanation" paragraph under the result and removes the Explain button.



Final score. Shows the score out of the total, the percentage, and a medal: a trophy at 80% or more, a thumbs-up at 60% or more, a book otherwise. A button offers another subtopic.

8.2 Button reference







callback_data



Meaning





menu:topics



Show the 17 topics





top:<t>



Show subtopics of topic t





sub:<t>:<s>



Show the 10, 15, 20 choice for that subtopic





cnt:<t>:<s>:<n>



Generate n questions (n must be 10, 15 or 20)





ans:<i>:<c>



Answer question i with option index c (0 to 4)





exp:<i>



Show the explanation of question i





nxt:<i>



Go to question i





finish



Show the final score





req_access



Start the payment request





adm_ok:<user>:<days>, adm_no:<user>



Admin approve and reject

Ids that do not exist in the catalog, or a count other than 10, 15 or 20, produce an "Invalid selection" pop-up and nothing else.

8.3 How answers are scored

When a student taps A to E, the bot loads their session and compares the chosen index with correct_answer_index. The first answer to a question is recorded with one atomic database update that only succeeds if that question number is not yet in answered_indices. That update adds the question to the answered list, adds one to the score when correct, and stores the choice. Because the check and the write are one operation, two quick taps cannot score the same question twice. A later tap on an already answered question simply re-shows the stored result.

The result line reads either "Correct! (B)" or "Incorrect. You chose A | Correct Answer: B (option text)".

8.4 How Explain works

The explanation was written by Gemini together with the question and is stored in the session, so Explain reads it from MongoDB and makes no Gemini call. It works only after the question has been answered; before that the student gets a pop-up asking them to answer first. If the question, result and explanation together would pass 4,000 characters, the explanation is sent as a separate message instead of being appended, because Telegram caps a message at 4,096.

8.5 Safeguards in the flow





One generation at a time per student. While a quiz is being built, a second tap on a count button shows "Already generating your quiz". The marker is kept in memory.



Escaped text. All model-written text is HTML-escaped before display, so a vignette containing something like "<5 mm" cannot break the formatting.



Safe editing. If Telegram rejects an edit as "not modified" the bot ignores it; if it rejects the HTML, the bot retries as plain text cut to 4,000 characters.



Failures are friendly. If generation fails for any reason, the student sees "Couldn't generate the quiz right now" with the count buttons to try again; the real error goes to the log.



Expired quiz. If the session no longer exists, the student is told the quiz has expired and offered a fresh start.

9. RAG ingestion: from PDF to searchable chunks

Before the bot can write a single question, the First Aid PDF must be cut into pieces, embedded as vectors and stored in book_chunks. This is a one-time job, run separately from the bot. It has two stages, and the ingest container runs both in order.

9.1 Stage one: splitting (split_first_aid.py)

Finding the page offset. The topic page ranges in the catalog are the numbers printed on the book's pages, but the PDF counts from its first cover page, and the front matter uses roman numerals. The script scans PDF pages 21 to 140 and looks at the first three and last three non-empty lines of each. A line that is a plain number from 1 to 800 casts a vote for PDF page number − printed number. The most common value wins. Roman numerals never vote, because only digits count. If nothing votes, the script stops and asks for --offset; the same flag overrides detection.

Cutting out each topic. For every topic, the printed range is converted to PDF positions with the offset, and only those pages are converted to Markdown with pymupdf4llm. A topic whose range falls outside the PDF is skipped with a warning.

Chunking. The Markdown is first split at headings (levels 1 to 4), keeping each heading with its text. Each section is then cut into pieces of about 1,800 characters with 200 characters of overlap, so a fact on a boundary appears whole in at least one piece. Pieces under 80 characters are dropped.

Assigning subtopics. The PDF has no subtopic markers, so the script reads the headings:





It keeps a running "current subtopic", starting at the first one of the topic.



Each heading is lowercased, with "&" turned into "and" and punctuation removed. It is compared with the subtopic names and their parts: "Anatomy & Physiology" matches on "anatomy and physiology", "anatomy" or "physiology"; singular and plural forms count too.



A heading of 60 characters or fewer that contains a match as a whole word switches the current subtopic. It stays until another match.



Text before the first matching heading belongs to the first subtopic.

This is a heuristic, and it works well for chapters laid out as Embryology, Anatomy, Physiology, Pathology, Pharmacology. It is the least certain part of the pipeline, which is why a preview step exists.

Each chunk record carries t_id, topic, s_id, subtopic, segment_group, heading (the deepest heading above it, or the topic name) and content, whose first line is the label [Section: … | Topic: … | Subtopic: … | Heading: …]. That label travels to Gemini with the text, so the model always knows what it is reading.

Outputs. One Markdown file per subtopic in first_aid_split_preview/NN_Topic/NN_Subtopic.md, for a human to skim, plus all_chunks_ready.json with every chunk. The console lists the chunk count of each subtopic and names any that came out empty. An empty subtopic is not fatal: at question time the bot falls back to the whole topic.

9.2 Stage two: embedding and loading (ingest_to_mongo.py)





Reads the JSON and gives each chunk a stable _id: the SHA-1 of its topic id, subtopic id and text.



Connects to MongoDB, makes sure the (t_id, s_id) index exists, and with --reset deletes all existing chunks first.



Asks the database which chunk ids already have an embedding and skips those, so the job can be stopped and rerun without redoing work or creating duplicates.



Embeds the rest in batches of 40 with gemini-embedding-001 at 768 dimensions, using the retrieval-document task type. Calls go through the key rotator, so a rate-limited key is rotated out automatically.



Normalizes every vector to length 1 and writes the batch with an unordered bulk upsert. It prints the running total and the seconds per batch.



Finishes by printing the collection size and the key pool summary.

The duration depends on how many chunks the book produces and on the rate limits of your keys.

9.3 Running it in Docker (docker_ingest.sh)

The ingest service mounts the host folder ./book read-only at /book, and ./first_aid_split_preview at /out. The script finds the first PDF in /book, splits into /out, then ingests. The recommended order is a split-only run first, so the previews can be checked before any Gemini quota is spent, then the full run:

docker compose run --rm -e SPLIT_ONLY=1 ingest   # split, no Gemini calls, no database writes
docker compose run --rm ingest                    # split, embed and load MongoDB

It stops with a clear message if no PDF is found, or if SKIP_SPLIT=1 is set but no split file exists. The other switches are PDF_OFFSET, SKIP_SPLIT and INGEST_RESET (section 4).

10. Retrieval and question generation

When a student picks a count, the bot finds the best passages of the book for that subtopic and has Gemini write all the questions in a single request.

10.1 The pipeline





Embed a query. The bot builds a fixed sentence for the chosen subtopic, "High-yield USMLE Step 1 testable facts, mechanisms and clinical associations: Cardiovascular — Pathology", and embeds it with the query task type. If embedding fails, the bot carries on without ranking.



Fetch candidate chunks. It loads every chunk stored for that topic and subtopic. If fewer than three exist, it loads the whole topic instead. If there are none at all, the student is told no content has been ingested yet.



Rank by cosine similarity. The similarity between the query vector and each chunk vector is computed in Python with numpy. This needs no special database feature, so it runs on any MongoDB, including ones without vector search.



Pick ten. To avoid giving the same questions every time a subtopic is repeated, the bot takes the 20 best-ranked chunks and randomly samples 10 of them. If 10 or fewer are available, it uses all. Without a query vector it samples 10 at random.



Build the prompt. The system message is the item-writer prompt with topic, subtopic and count filled in. The user message holds the ten excerpts, separated by dividers, and asks for exactly the requested number of questions.



One Gemini call. Model gemini-2.5-flash, temperature 0.4, up to 32,768 output tokens, a small thinking budget of 1,024 tokens, JSON output forced to follow the USMLEQuizResponse schema, and a 240-second timeout.



Validate. The reply is parsed and checked (10.3).



Store and show. The questions are saved in the student's session, their quiz counter goes up, and Question 1 appears.

10.2 What the prompt asks Gemini to do

The prompt in bot/prompts.py is a long set of item-writing rules, in eight parts:





Style. Real USMLE items test application in two or three reasoning steps. The student must infer the diagnosis and then answer a question about it, such as the mechanism, the next step, the drug or the adverse effect.



Vignette structure. At least 80% of questions are clinical vignettes in a fixed order: patient, complaint, history, vitals, examination, labs or imaging, then one lead-in question. The diagnosis is never named. Up to 20% may be short basic-science stems.



Text only. No figures, tables or page references. Every image, ECG or smear is described in words, and lab values carry units.



Coverage. Anatomy, physiology, biochemistry, pathology, pharmacology, microbiology, immunology and biostatistics are each given their own expectations.



Lead-ins. A list of standard NBME phrasings to vary. One question only, and negative stems are avoided.



Options. Exactly five, all of the same kind, plausible distractors from the same differential or drug class, similar length, logical order, generic drug names, and never "all of the above". Correct answers should be spread across positions.



Accuracy and mix. Facts must be supported by the excerpts and current consensus. The difficulty target is about 30% easy, 50% moderate and 20% hard. US units, and plain Unicode symbols such as O₂, ↑ and ≥ instead of LaTeX.



Explanations. 400 to 600 characters of prose in two to four sentences: the reasoning, why the two strongest distractors are wrong, and a closing "Pearl:". No bullets and no references to option letters.

10.3 Checking what comes back

Gemini's structured output enforces the shape of the JSON but not rules such as "exactly five options", so the code checks them itself. A question is kept only if:





it has exactly five non-empty options, all different when compared without case;



correct_answer_index is between 0 and 4;



the vignette and explanation are not empty;



its vignette is not a duplicate of an earlier one in the same reply.

The letter shown to the student is always recomputed from the index, so the two can never disagree. Valid questions are then trimmed to the requested count.

10.4 Retries and partial results

The generator makes up to three attempts. It succeeds immediately when it has the full count. After three attempts it accepts the best set it saw if that set holds at least 70% of the requested questions, for example 7 of 10, and the student simply gets that smaller quiz. Below 70% it gives up and the student sees the friendly failure message. Separately from these three attempts, the rotator retries on its own for rate limits and server errors (section 11).

11. Gemini key rotation with gemini-api-rotator

The free Gemini tier limits how many requests each key can make per minute and per day. The bot pools several keys through the gemini-api-rotator library (version 2.0.0), so a key that hits its limit is set aside while others carry on.

11.1 What the library does

The rotator hands out keys round-robin. It skips a key that is suspended, cooling down after a rate-limit error, at its per-minute ceiling, or at its limit of simultaneous requests. A rate-limited key cools down for 60 seconds, and repeated hits lengthen the wait up to 30 minutes. It also records per-key success rates and latency, can save its state in SQLite, and can call hooks when a key is suspended or recovers.

It classifies each failure by the text of the error:







Error contains



Treated as



Action





429, RESOURCEEXHAUSTED, QUOTA



Rate limit



Key cools down with growing delay; another key is tried





CONSUMERSUSPENDED, PERMISSIONDENIED, APIKEYINVALID, DISABLED



Suspended key



Key is blacklisted until a recheck





500, 503, INTERNAL, UNAVAILABLE



Transient



Retried





Anything else



Unknown



Raised at once, not retried

11.2 How the bot sets it up

get_rotator() in bot/gemini_router.py builds one rotator for the whole process the first time it is needed:





The keys come from GEMINI_API_KEYS.



State is saved in a SQLite file at ROTATOR_DB, so suspended keys and latency statistics survive restarts. If the file cannot be opened, the bot logs a warning and keeps going without persistence.



Requests per minute per key come from ROTATOR_RPM_PER_KEY (default 10), and simultaneous requests per key from ROTATOR_MAX_CONCURRENT_PER_KEY (default 2).



The retry count is twice the number of keys, but never below 4 or above 10, with a 1.5-second base delay.



Hooks write a log line when a key is suspended or recovers, showing only the last six characters of the key.

11.3 Two ways the bot calls Gemini

Writing questions goes through the library's execute(). The bot passes the prompt, the model, the output limit, the temperature, the system instruction and extra settings for JSON output and thinking. execute() picks a key, tracks its use, times the call, classifies errors, backs off and retries, and records the outcome. The blocking SDK call runs in a worker thread so the bot's event loop never freezes.

Embeddings cannot use execute(), which only wraps text generation. The bot's helper call_with_rotation() therefore uses the rotator's manual calls, in this order: take the next working key, mark it in use, run the embedding call in a thread, report the outcome with its latency or its error, and release the key. On a rate limit, suspension or server error it waits a little (1.5 seconds times the attempt number, at most 8) and tries the next key; an unknown error is raised immediately. Both paths share one pool, so cooldowns and statistics are common to both.

11.4 Starting each topic on a different key

Before every generation attempt, the bot moves the rotator's cursor so the first pick is key number (segment_group - 1) mod number_of_keys. Topics from different parts of the book therefore start on different keys. The library has no public way to set this cursor, so the code writes its internal _last_index field under the rotator's own lock. It works with version 2.0.0; if a future version changes it, the failure is caught and the rotator simply continues in plain round-robin order.

11.5 Recovery and monitoring





Recheck loop. A background task wakes every six hours, probes suspended keys and returns healthy ones to the pool, then logs the pool summary.



/stats. An admin sees a line such as "3 total, 2 active, 1 cooling, 0 suspended".



Logs. Each failed attempt logs "Gemini call failed on attempt n of m; rotating key" with the error type.



Library CLI. The package also installs a gemini-rotator command (status, stats, latency, test). Per its README it reads keys from GEMINI_API_KEYS and the database path from GEMINI_ROTATOR_DB.

Practical note. Google applies free-tier limits per project, so keys created in the same project share one quota. Keys from separate projects give real extra capacity.

12. Function reference

Every function and class in the project, grouped by file. Names starting with an underscore are internal helpers.

12.1 bot/config.py







Name



What it does





_csv(name)



Reads a comma-separated variable into a list of trimmed, non-empty strings





_int_csv(name)



Same, but converts to integers and exits with a message on a bad value





validate(require_bot=True)



Exits with one message naming every missing required variable. With require_bot=False the bot token and admin ids are not required





Module constants



TELEGRAM_BOT_TOKEN, ADMIN_IDS, MONGODB_URI, GEMINI_API_KEYS, model names, rotator and webhook settings (section 4)

12.2 bot/catalog.py







Name



What it does





FIRST_AID_CATALOG



The dictionary of 17 topics, each with name, short label, segment group, page range and subtopics





_t(...)



Builds one topic record





get_topic(t_id)



The topic record, or nothing if the id is unknown





get_subtopic_name(t_id, s_id)



The subtopic name, or nothing





section_label(t_id)



"High-Yield General Principles", "High-Yield Organ Systems" or "Rapid Review"





topic_count(), subtopic_count()



17 and 81

12.3 bot/prompts.py







Name



What it does





USMLE_SYSTEM_PROMPT



The full item-writer instructions, with {topic}, {subtopic} and {count} placeholders





build_system_prompt(topic, subtopic, count)



Fills the placeholders





build_user_prompt(topic, subtopic, count, retrieved_chunks)



Wraps the excerpts and the request for exactly count questions

12.4 bot/database.py







Name



What it does





utcnow()



Current time in UTC with a time zone attached





_aware(dt)



Treats a date without a time zone as UTC





fmt_date(dt)



Formats a date as 14 Dec 2026





db(), users(), chunks(), sessions()



Handles to the database and its three collections. db() raises if init_db() has not run





init_db()



Connects with a 20-second server-selection timeout, pings, and creates every index





close_db()



Closes the connection at shutdown





is_user_authorized(telegram_id)



The access check of section 7.1; returns allowed and a status text





grant_user(telegram_id, days=30, admin_id=None, username="", full_name="")



Creates or updates a subscriber with expiry now plus days; returns the expiry





revoke_user(telegram_id)



Sets is_authorized to false; returns whether the user existed





list_active_users()



Unexpired subscribers, soonest expiry first





get_stats()



Chunk count, active subscriber count and total quizzes





increment_quizzes(telegram_id)



Adds one to a subscriber's counter; does nothing if there is no document





get_relevant_chunks(t_id, s_id, query_embedding, limit=10, diversify=True)



The retrieval of section 10.1; returns the chunks joined into one text, or an empty string





create_session(...)



Stores a new quiz, replacing any earlier one for that student





get_session(telegram_id)



The student's quiz, or nothing





record_answer(telegram_id, i, choice, correct)



Atomically records the first answer to question i; returns true only the first time





set_current_index(telegram_id, i)



Saves which question the student is on

12.5 bot/gemini_router.py







Name



What it does





USMLEQuestionItem



Pydantic model of one question: vignette, five options, correct index, letter, explanation





USMLEQuizResponse



Pydantic model of the reply: a list of questions. Also the schema sent to Gemini





get_rotator()



Builds the single key rotator on first use (section 11.2)





revalidate_loop(interval_seconds)



Endless background task that rechecks suspended keys every six hours





call_with_rotation(fn, model, max_attempts)



Runs any blocking Gemini call with a rotator-chosen key, rotating on retryable errors





_normalize(vecs)



Scales vectors to length 1





embed_texts(texts, task_type)



Embeds a list of texts at 768 dimensions and returns normalized vectors





embed_query(text)



Embeds one search query





_clean_questions(items)



Applies the checks of section 10.3 and returns plain dictionaries





generate_mcqs(topic, subtopic, count, chunks, segment_group)



The single-call generator with up to three attempts; returns the questions or raises an error

12.6 bot/keyboards.py







Name



What it builds





main_menu_kb()



The single USMLE Part 1 Practice button





access_request_kb()



The Submit Payment / Request Access button





topics_kb()



The 17 topics in two columns





subtopics_kb(t_id)



One row per subtopic plus Back to Topics





count_kb(t_id, s_id)



The 10, 15, 20 row and Back to Subtopics





question_kb(i)



The A to E answer row





after_answer_kb(i, total, show_explain=True)



Explain and Next Question, or View Final Score on the last question





final_kb()



Practice Another Subtopic





admin_decision_kb(user_id)



Approve 30 Days and Reject

12.7 bot/handlers/user_quiz.py







Name



What it does





PaymentFlow.waiting_for_payment_note



The conversation state used while waiting for the TrxID





_plain(text)



Strips HTML tags, for the plain-text fallback





safe_edit(cb, text, kb)



Edits the message, ignoring "not modified" and falling back to plain text on HTML errors





gate_text(telegram_id, reason)



Builds the Access Restricted text





deny(event, reason)



Shows the gate, as a new message or by editing the old one





check_auth(event)



Runs the access check and shows the gate when it fails





render_question(session, i)



Question text with options A to E





render_result(session, i)



The correct or incorrect line for a question already answered





render_explanation(session, i)



The explanation paragraph





cmd_start



Handles /start





cb_req_access



Starts the payment note conversation





cmd_cancel



Handles /cancel during that conversation





got_payment_note



Validates the note, applies the one-minute limit and alerts the admins





cb_topics, cb_topic, cb_subtopic



The three menu screens





_parse(data, n)



Splits callback_data into n integers, or returns nothing if malformed





cb_count



Runs the generation of section 10 and shows Question 1





_session_or_expired(cb)



Loads the session or tells the student the quiz expired





cb_answer, cb_explain, cb_next, cb_finish



Answer, explanation, next question and final score

12.8 bot/handlers/admin.py







Name



What it does





_is_admin(user_id)



True if the id is in ADMIN_IDS





_notify_active(bot, user_id, expires)



Messages a student that their subscription is active





cmd_grant, cmd_revoke, cmd_users, cmd_stats



The four admin commands (section 7.5)





cb_approve, cb_reject



The approval buttons (section 7.4)

12.9 bot/main.py







Name



What it does





build_dispatcher()



Creates the dispatcher with in-memory conversation storage and registers the admin router first, then the student router





on_startup(bot)



Connects MongoDB and creates indexes, builds the rotator, sets the /start command in Telegram's menu and launches the recheck loop





on_shutdown(bot)



Closes the database connection





main()



Validates settings, then runs long polling, or a webhook server when WEBHOOK_BASE_URL is set

12.10 Scripts







Name



What it does





split_first_aid.detect_offset(doc, ...)



Votes on the PDF-to-printed page offset (section 9.1)





split_first_aid._norm(s)



Lowercases and cleans a heading for matching





split_first_aid.subtopic_keys(name)



The match keywords for a subtopic name





split_first_aid.match_subtopic(header, key_map)



Returns the subtopic a heading names, or nothing





split_first_aid.split_topic(markdown, t_id)



Chunks one topic and assigns every chunk to a subtopic





split_first_aid.safe(name)



Makes a name safe to use as a file or folder name





split_first_aid.main()



Command-line driver: opens the PDF, loops over topics, writes previews and JSON





ingest_to_mongo.chunk_id(c)



The SHA-1 id of a chunk





ingest_to_mongo.main()



Command-line driver: embeds missing chunks in batches and upserts them





docker_ingest.sh



Container entry point that runs the two scripts with the switches in section 4

13. Deployment and operations

13.1 What you need first





A Linux server (an Azure VM, for example) with Docker and Docker Compose installed.



A hosted MongoDB, such as MongoDB Atlas or Azure Cosmos DB for MongoDB. Allow the server's IP address in its network settings, and the IP of any other machine that will run the ingest job.



A bot token from BotFather, the numeric Telegram ids of the admins, and the Gemini API keys.



The First Aid PDF, copied privately onto the server. It is not in the git repository.

13.2 First deployment

git clone <repo-url> && cd usmle-rag-bot
cp .env.example .env && nano .env      # fill the four required values
# copy the PDF into ./book/ (for example with scp)

docker compose run --rm -e SPLIT_ONLY=1 ingest   # split only; skim ./first_aid_split_preview/
docker compose run --rm ingest                    # embed and load MongoDB (once)

docker compose up -d --build                      # start the bot
docker compose logs -f bot                        # watch it come up

Then open the bot in Telegram as an admin and send /stats. A chunk count above zero confirms the bot sees the ingested book.

13.3 What Docker runs







Service



Image



Behaviour





bot



Dockerfile (Python 3.12, only the bot/ code)



Runs python -m bot.main as a non-root user. Restarts automatically unless you stop it. A named volume keeps the rotator's SQLite file across rebuilds





ingest



Dockerfile.ingest (adds PDF tools and the scripts/ folder)



Started only on request through the ingest profile. Mounts ./book read-only and ./first_aid_split_preview for output





mongo



mongo:7



Optional local database, started only with --profile localdb. Use it with MONGODB_URI=mongodb://mongo:27017

13.4 Polling or webhook

By default the bot uses long polling: it asks Telegram for updates, so it needs no public address and works behind any firewall. To use a webhook instead, set WEBHOOK_BASE_URL to a public HTTPS address, optionally WEBHOOK_SECRET, and uncomment the ports lines in docker-compose.yml. In webhook mode the bot registers the address with Telegram at startup and removes it at shutdown.

13.5 Everyday operations







Task



How





See logs



docker compose logs -f bot





Restart



docker compose restart bot





Deploy new code



git pull && docker compose up -d --build





Add or extend a subscriber



/grant <id> [days], or approve the student's alert





Remove access



/revoke <id>





Check health



/stats for chunks, subscribers, quizzes and key status





Reload the book



Run the ingest service again; add INGEST_RESET=1 to wipe and rebuild

13.6 Troubleshooting







Symptom



Likely cause



Fix





Bot exits at startup listing missing variables



.env incomplete



Fill the named variables





Startup fails connecting to MongoDB



Wrong URI, or the server's IP is not allowed



Check the URI and the database's network access list





"No textbook content has been ingested", or /stats shows 0 chunks



Ingest not run, or it wrote to a different MONGODB_DB



Run ingest against the same URI and database name as the bot





Student sees Access Restricted



Not subscribed, or expired



Approve or /grant them





Admin gets no payment alerts



The admin has never started the bot, and Telegram does not let bots message such users



Each admin sends /start to the bot once





"Couldn't generate the quiz right now"



All keys cooling or out of quota, or three bad model replies in a row



Check /stats and logs, wait a minute, add keys from other projects





Many subtopics show 0 chunks after splitting



Headings did not match the subtopic names, or pages are shifted



Skim the previews, try PDF_OFFSET; the bot still works through its topic fallback





Rotator state is lost on restart



The SQLite file is not writable



Check the log warning about persistence and the volume





Webhook mode receives nothing



URL is not public HTTPS, the path differs, or the secret does not match



Check WEBHOOK_BASE_URL, WEBHOOK_PATH and WEBHOOK_SECRET

14. Limitations, security and verification status

14.1 What has and has not been tested

The code was tested in a sandbox with stand-ins for the outside services. It has not yet run against the real ones.

Checked in the sandbox





Every Python file compiles, and all 18 Telegram handlers register.



The access check, including admin access, no subscription, active and expired, against an in-memory MongoDB substitute.



Chunk retrieval, its fallback to the whole topic, and the empty case.



Atomic answer recording: a second answer to the same question is refused.



Question generation against a fake Gemini client: a rate-limit error on the first key, then success on the next, with option letters corrected from indexes.



Embeddings arriving as 768 numbers of length 1.



PDF page-offset detection on a synthetic PDF, and subtopic assignment on sample Markdown.



The compose file validates, and the ingest script's error messages and split-only mode behave as described.

Not yet checked





A live Telegram bot, a real MongoDB server and real Gemini calls. This includes the quality and medical accuracy of real questions and the real rate-limit behaviour of your keys.



The real First Aid PDF: how well the headings match the subtopics, and whether the page offset is detected correctly.



Building the Docker images, because the sandbox had no running Docker daemon.



Webhook mode.

The first run on the server is therefore the real test. Splitting in preview mode first is the cheapest way to catch problems.

14.2 Known limitations





Questions are AI-generated and not fact-checked. The prompt demands accuracy and grounding in the excerpts, but nothing verifies the answers automatically. Students should treat questions as practice, and an expert should review a sample before launch.



Subtopic assignment is a heuristic based on headings (section 9.1). Wrong or empty subtopics are possible; the topic-wide fallback keeps the bot usable.



The "8–12 seconds" notice shown during generation comes from the original specification and was not measured. Fifteen or twenty questions in one call can take noticeably longer.



One active quiz per student. Starting a new quiz replaces the old one, and a button on an old quiz message will act on the newest quiz.



Some state lives in memory: the payment conversation, the one-minute request limit and the "already generating" marker. A restart clears them, and they are not shared between two running copies of the bot, so run a single instance.



Expiry is applied lazily, when the student next uses the bot.



Approvals reset the expiry to now plus the days; they do not add to remaining time.



Retrieval loads all candidate chunks into memory for each quiz. That is fine for one book; a much larger collection would call for a vector-search index.



Daily quota. Each quiz costs one embedding call and one generation call, plus retries. The free-tier daily limits of your keys cap how many quizzes the bot can serve per day.



The 81 subtopics follow the original list; the specification stated 83.



The key-cursor setting uses an internal field of the rotator library (section 11.4).



English only.

14.3 Security notes





Secrets. Keep .env out of git; the repository's .gitignore already excludes it. Share the token, Gemini keys and database URI through a private channel. The logs show only the last few characters of a key.



Admin rights are checked inside the handlers against ADMIN_IDS, not just by hiding buttons, so a forged button press from a non-admin is refused.



Escaping. Model text, student names and payment notes are HTML-escaped before they are shown, including in the admin alert.



Containers. The bot runs as a non-root user, and the PDF and .env are excluded from the images by .dockerignore.



Database. Use a dedicated MongoDB user with only the access the bot needs, and restrict network access to the known server addresses.



Webhook. If you use webhook mode, set WEBHOOK_SECRET so only Telegram can post updates.



Data kept. Per student: Telegram id, username, name, subscription dates, a quiz counter and the current quiz for up to seven days. The payment note is sent to the admins in Telegram and is not stored in the database. No card or wallet credentials are handled by the bot.



Copyright. The First Aid PDF is copyrighted. It is never committed, and chunks of it live only in your private database.


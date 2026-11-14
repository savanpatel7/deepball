# Deep Ball

Daily 8-bit sports trivia mining game. Seven prompts a day across the NFL, NBA, MLB, soccer, F1 and college sports; rarer correct answers dig deeper.

- `public/index.html` - the whole game
- `public/data/` - players (autocomplete), the daily prompts with answers and depth tiers, the calendar
- `src/worker.js` - API: /api/score (one score per player per day, returns the day's scores) and /api/report (player reports)
- `schema.sql` - the D1 tables
- `wrangler.jsonc` - Worker config; `database_id` must be the real D1 id of `deepball-scores`
- `tools/` - the bank builder and the Colab data scripts

Deploy command: `npx wrangler deploy`

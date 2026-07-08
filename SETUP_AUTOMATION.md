# One-time setup: fully automated daily updates + live published dashboard

No Python, no coding after this. GitHub's servers run everything on a schedule for free.

## Steps (~10 minutes, once)

1. **Create a GitHub account** (free) at github.com if you don't have one.
2. Click **New repository** → name it e.g. `swing-desk` → set it **Private**
   (or Public if you don't mind others seeing your signals) → Create.
3. On the new repo page click **uploading an existing file** and drag in **everything inside
   this folder** (including the hidden `.github` folder — on Mac press Cmd+Shift+. to see it;
   easiest is: upload the whole unzipped folder contents). Commit.
   - Skip `data/prices.csv` if the upload complains about size — the bot re-downloads it daily anyway.
4. Go to the repo's **Actions** tab → click **"I understand my workflows, enable them"**.
5. Go to **Settings → Actions → General → Workflow permissions** → select
   **"Read and write permissions"** → Save.
6. Test it: **Actions tab → Daily swing update → Run workflow**. Wait ~10 min, then check that
   `dashboard.html` shows a fresh commit.
7. (Optional, to view it as a website) **Settings → Pages** → Source: *Deploy from a branch* →
   Branch: `main`, folder `/ (root)` → Save. Your dashboard will be live at
   `https://<your-username>.github.io/swing-desk/dashboard.html` a few minutes after every update.
   - Note: with a **private** repo, GitHub Pages needs a paid plan — either make the repo public,
     or just open `dashboard.html` from the repo (click the file → ... → Download) when you want it.

## What happens automatically after that

- **Every trading day 7:15 pm IST**: fresh 2 years of Nifty 500 data → new dashboard + brief,
  committed to the repo (and the live page updates if Pages is on).
- **Fridays**: earnings dates refresh.
- **First Monday of each month**: re-tune with the overfit guard (only adopts params that pass validation).
- FII/DII flows + ASM/GSM lists can't refresh from GitHub's servers (NSE blocks them) — drop
  `data/flows.csv` / `data/asm_gsm.csv` manually if you want those, or ignore.

## Your trade log

- The log lives in your **browser's storage for the page you open** — the published Pages URL keeps
  the same address every day, so your log **survives every daily update** automatically.
- It does NOT sync between devices/browsers. Use the **Export JSON** button weekly as a backup;
  **Import** restores it anywhere.
- Anyone else opening your published page sees an empty log — trade logs never upload anywhere.

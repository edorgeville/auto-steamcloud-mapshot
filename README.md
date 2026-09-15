# factorio-mapshot-cloud

Renders your Factorio save into a zoomable web map and serves it, pulling the save straight from Steam Cloud. Nothing is installed on the machine you play on, so a Steam Deck needs no modification at all.

It pulls the newest cloud save on an interval, installs a matching Factorio client, syncs the save's mods, renders with [mapshot](https://github.com/Palats/mapshot) under a virtual X server, and serves the result over HTTP.

## 🤖 AI Disclosure

This is purely vibe-coded slop. It's good enough for me, as it automates something I couldn't be bothered with setting up myself. I spend enough time in front of a computer for work, I'd rather play Factorio on my Steam Deck and prompt Claude into building some automation while I wait for my shipment of batteries to arrive at Fulgora (no I do not plan anything)!
Published here to save the next guy a few tokens. Use at your own risk!

* **Tools Used:** Claude Opus 5 (1M context)
* **Scope of AI Assistance:** Commits contain an "Assisted-by" attribution when applicable. Spoiler: it's pretty much all of them.
* **Human Verification:** All AI-generated code has **not** been thoroughly reviewed, security-audited, and tested by the project maintainers to ensure correctness and adherence to project standards. Again, this is vibe-coded slop.


## The image ships no game files

There is no Factorio in this image, and no credentials. The client is downloaded at runtime from factorio.com with **your** account, and mods come from the Factorio mod portal with the same credentials. See [NOTICE](./NOTICE).

## Before you start

**You need a factorio.com account linked to your Factorio purchase.** If you bought the game on Steam, visit <https://factorio.com/profile> once after purchase: linking the accounts unlocks the DRM-free downloads, including Space Age. On that page you will find your **service username** and **service token** - those are what `FACTORIO_USERNAME` and `FACTORIO_TOKEN` want, not your website password. If you already have Factorio installed somewhere, the same two values are in `player-data.json` as `service-username` and `service-token`.

**The first render downloads several gigabytes.** The Space Age client is a 4.0 GB download that unpacks to about 4.6 GB in `/data`. It is fetched once per Factorio version, so only the first run and later game updates pay for it, and the log reports progress as it goes rather than going silent. `FACTORIO_KEEP_VERSIONS` defaults to `2`, so budget roughly **10 GB** for the client cache, plus the rendered map itself and the pulled saves.

**Renders are slow, and `MAPSHOT_TILEMIN` dominates the cost.** Factorio appears frozen while it works, which is normal. The same mid-game Space Age save, five surfaces, software rendering on a 6-core machine:

| `MAPSHOT_TILEMIN` | Time | Tiles | Size |
|---|---|---|---|
| mapshot default | ~3.5 min | 668 | 180 MB |
| `64` (what [`docker-compose.example.yml`](./docker-compose.example.yml) sets) | ~6 min | 2100 | 932 MB |

Lower means sharper and very much more expensive. Start with the default if you are not sure.

**The image is about 550 MB.** Nearly 200 MB of that is Mesa's software rasteriser (LLVM), which is unavoidable: Factorio has no headless rendering path, so a real OpenGL context is mandatory even with no GPU.

## Quick start

```yaml
# docker-compose.yml
services:
  mapshot:
    image: ghcr.io/edorgeville/auto-steamcloud-mapshot:latest
    restart: unless-stopped
    environment:
      FACTORIO_USERNAME: your-service-username
      FACTORIO_TOKEN: your-service-token
      STEAM_USERNAME: your-steam-account-name
    volumes:
      - ./config:/config
      - ./data:/data
      - ./output:/output
    ports:
      - "8080:8080"
    # Factorio needs longer than Docker's default 10s to flush its screenshots.
    stop_grace_period: 45s
```

Then:

```sh
docker compose run --rm -it mapshot login-steam   # one time, interactive
docker compose up -d
```

[`docker-compose.example.yml`](./docker-compose.example.yml) is the same thing with every tunable spelled out and commented.

`login-steam` asks for your Steam password and a Steam Guard code, and writes a password-free session to `./config`. The session lasts roughly a month from one IP address; when it expires the log says so and you run the command again.

Then open <http://localhost:8080>.

## Commands

| Command | Behaviour |
|---|---|
| `login-steam` | One-time interactive Steam login. Writes the session to `/config`. Needs `-it`. |
| `render` | One shot: pull, check, render, exit. |
| `serve` | Serve `/output` only, no rendering. |
| *(none)* | Serve continuously and render on an interval. This is the default. |

## Volumes

| Path | Contents |
|---|---|
| `/config` | Steam session and its database, the pulled save files, `player-data.json`, render state |
| `/data` | Factorio installs keyed by version, shared mods, render staging |
| `/output` | The rendered site. Bind-mount this if you want to serve it yourself. |

The pulled saves live in `/config/steam` rather than `/data` because the tool that fetches them keeps its session, its database and its downloads in a single directory, and `login-steam` has to work with only `/config` mounted.

**Steam hands over every Factorio file in your cloud, not just the one being rendered.** If you keep a lot of named saves, this adds up: a real account with 45 saves came to around 650 MB. `SCSD_ROTATION` defaults to `1` so only the current version of each file is kept, and you can set `STEAM_DIR=/data/steam` to move the whole lot onto the data volume instead. If you do, run `login-steam` with `/data` mounted as well, since that is where the session will then be written.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FACTORIO_USERNAME` | - | factorio.com service username (required) |
| `FACTORIO_TOKEN` | - | factorio.com service token (required) |
| `FACTORIO_BUILD` | `expansion` | `expansion` (with Space Age) or `alpha` (without). The `headless` build cannot render and is rejected. |
| `FACTORIO_VERSION` | `auto` | `auto`, an explicit version like `2.0.77`, or `stable` / `latest` |
| `FACTORIO_KEEP_VERSIONS` | `2` | How many installed clients to keep before pruning the least recently used |
| `FACTORIO_EXTRA_ARGS` | - | Extra arguments passed to Factorio, space separated |
| `STEAM_USERNAME` | - | Your Steam account name, for `login-steam` |
| `STEAM_2FA` | `mobile` | `mobile` or `mail`, matching how Steam sends your Guard code |
| `SCSD_ROTATION` | `1` | Versions of each cloud file kept. `1` keeps only the current one. |
| `STEAM_DIR` | `/config/steam` | Where the Steam session, its database and the pulled saves live |
| `SAVE_NAME` | *(newest)* | Which cloud save to render. Defaults to the most recently modified. |
| `RENDER_INTERVAL` | `3600` | Seconds between checks. Values below 900 are raised to 900. |
| `RENDER_TIMEOUT` | `14400` | Backstop in seconds. A render that overruns it is killed and reported as a failure; `/output` is left alone. |
| `MAPSHOT_AREA` | `player` | `player`, `entities` or `all` |
| `MAPSHOT_TILEMIN` | mapshot default | In-game units per tile at the most detailed zoom. Lower is sharper and far more expensive. |
| `MAPSHOT_TILEMAX` | mapshot default | In-game units per tile at the least detailed zoom |
| `MAPSHOT_RESOLUTION` | mapshot default | Pixel size of generated tiles |
| `MAPSHOT_JPGQUALITY` | mapshot default | JPEG quality |
| `MAPSHOT_MINJPGQUALITY` | mapshot default | JPEG quality for tiles with no player entities. `0` skips them entirely. |
| `MAPSHOT_SURFACE` | `_all_` | Which surface to render. `_all_` covers every Space Age planet and platform. |
| `SERVE_PORT` | `8080` | HTTP port |
| `PUID` / `PGID` | `1000` | Ownership of the files written to the volumes |

## How the sync actually behaves

**You are always one session behind.** Steam uploads Factorio saves to the cloud **when the game exits**, not continuously. So the map reflects the state at the end of your last session, and nothing you do in a running session shows up until you quit. This is how Steam Auto-Cloud works and is not something this tool can fix. Autosaves are synced too, so quitting is what matters, not saving.

**Very large saves silently stop syncing.** Steam Cloud enforces a per-file size limit for Factorio in the region of 256 to 400 MB. Past it, Steam quietly stops uploading that file: no error in game, the cloud copy simply stops moving. If the map has frozen at an old timestamp while the save on your Deck keeps growing, check the size of the save. Nothing here can work around it.

**Automated Steam Cloud pulling is not sanctioned by Valve.** The puller scrapes the [Steam cloud storage page](https://store.steampowered.com/account/remotestorage) rather than using an API, and throttles itself to stay well inside Steam's daily request budget, with randomised delays between requests. That throttling is deliberately left in place, and `RENDER_INTERVAL` has a hard floor of 900 seconds, so no configuration can hammer Steam's endpoints. Use at your own risk.

## What happens on each wake-up

Most wake-ups do nothing. The save is hashed after every pull and compared with the last render; if it is unchanged, the whole render is skipped and the log says `no change, skipping`. A restart of the container is therefore cheap: it will not re-download Factorio and will not re-render an unchanged save.

Renders are written to a staging directory on `/data` and moved into `/output` only when mapshot reports success. This matters more than it sounds: mapshot's mod writes its `mapshot.json` metadata *before* it generates a single tile, and the server treats any directory containing that file as a finished render. A render interrupted halfway would otherwise become the newest, broken, "latest" map. Staging makes that impossible - kill the container mid-render and the previous map keeps serving untouched.

If a pull or render fails, the previous render keeps being served, and the log distinguishes `steam pull failed`, `render failed` and `version mismatch, re-fetching`. Two renders can never overlap. On `SIGTERM` the whole process tree is stopped, Factorio included; it can take up to 20 seconds to flush its screenshot queue, which is why the compose example sets `stop_grace_period: 45s`. Cutting it shorter corrupts nothing, it just kills Factorio less politely.

## Version drift

Steam will update Factorio on your Deck, and the save will then need a newer client than the one cached here. With `FACTORIO_VERSION=auto` (the default), the render is attempted, the version Factorio reports in its own error is read back, that exact build is fetched, and the render is retried once. Each version is cached in `/data` keyed by version string, so a game update costs one download, not one per render.

The mismatch is caught during the mod sync, before any rendering work happens, so a Deck update costs a few seconds and one download rather than a wasted render.

Pin `FACTORIO_VERSION` to an explicit version to disable that. A pinned version that cannot load the save fails with a single line naming both versions and what to change:

```
ERROR  version mismatch: the save was made with Factorio 2.0.77 but the installed
       client is 2.0.60. FACTORIO_VERSION is pinned to 2.0.60, so no other version
       will be fetched. Set FACTORIO_VERSION=auto, or pin it to 2.0.77.
```

## Troubleshooting

**`no Steam session; run the login-steam command first`** - run `docker compose run --rm -it mapshot login-steam`.

**`could not parse Steam's save list`** or **`the Steam session could not be refreshed`** - the session expired, or your IP changed. Log in again.

**`factorio.com refused the download`** - `FACTORIO_USERNAME` / `FACTORIO_TOKEN` are wrong, or the account does not own the build you asked for. Check <https://factorio.com/profile>, and remember `FACTORIO_BUILD=expansion` requires Space Age.

**`no Factorio save found in Steam Cloud`** - play and quit once, then give Steam a moment to upload.

**The map is missing a mod's entities** - it should not be; mods are synced to the save's own mod list before every render. If it happens, check the sync step in the log for mod portal errors.

**Nothing is served at all** - `/output` is served even when no render has ever succeeded, so an empty listing means no render has completed yet. Watch the log for the render step.

## Not included

By design: no timelapses or snapshot history, no playable server, no uploading saves back to Steam Cloud, no arm64 (no arm64 Linux Factorio client exists), and nothing that runs on the Steam Deck.

## Credits

[mapshot](https://github.com/Palats/mapshot) by Palats does all the rendering and serving. [steamCloudSaveDownloader](https://github.com/pyscsd/steamCloudSaveDownloader) does the Steam Cloud pulling. See [NOTICE](NOTICE).
